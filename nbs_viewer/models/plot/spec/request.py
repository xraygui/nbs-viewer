"""
Immutable description of one plottable trace.

The upper of the view pipeline's two fixed layers. A :class:`PlotRequest` is
frozen and hashable so it can serve as the fingerprint of a fetch; what to
*read* for one is :mod:`plan` next door. Long-lived traces are identified by
:class:`TraceKey`, a subset of the request, so view / crop / transform
changes reuse the artist.
"""

from __future__ import annotations

import time as ttime
from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

import numpy as np
import xarray as xr

from ..plane.frame import PlotViewFrame
from ..plane.orientation import classify_render_mode, display_flips
from ..plane.roles import DimRole, MaskMode, SliceItem, SpatialReduce
from .axes import PlotAxes
from .bundle import PlotBundle
from .plan import FetchPlan, narrow
from .projection import Projection
from .region import RegionDefinition
from .stages import (
    apply_normalization,
    apply_transform,
    mask_to_profile,
    materialize_view,
    reduce_before_mask,
    reduce_to_plane,
)
from nbs_viewer.utils import print_debug


@dataclass(frozen=True)
class TraceKey:
    """
    Object identity for a :class:`Trace` and its artist.

    A :class:`PlotRequest` is the fingerprint of *what is plotted*. This key
    is the subset that names a long-lived object so crop, transform, and
    slice changes reuse the artist.

    Parameters
    ----------
    uid : str
        Run uid.
    xkey : str
        Primary X key.
    ykey : str
        Y data key.
    fan_out_index : int, optional
        Distinct cell when several slices of the same keys are shown at once
        (image grid). ``None`` for the main display.
    """

    uid: str
    xkey: str
    ykey: str
    fan_out_index: Optional[int] = None

    def as_tuple(self) -> Tuple[str, str, str]:
        """
        Return the legacy ``(xkey, ykey, uid)`` map key.

        Returns
        -------
        tuple of str
            Compatibility triple used by crop ``source_key`` and canvas
            connection tracking.
        """
        return (self.xkey, self.ykey, self.uid)


@dataclass(frozen=True)
class PlotRequest:
    """
    Complete description of one fetch / one trace.

    Parameters
    ----------
    uid : str
        Run uid the data is read from.
    xkeys : tuple of str
        Selected X key. When it is a coordinate along one of ``ykey``'s
        dimensions, that dimension is plotted against it and named after it.
    ykey : str
        Y data key.
    norm_keys : tuple of str
        Normalization keys. Empty means no normalization.
    view : Projection
        Rank-bound view of the plane that is loaded, including its optional
        crop. When ``region`` is set this is still the *parent* 2-D plane:
        the ROI reduces it afterwards, and the plane's identity is what the
        mask, the profile axis and the crop are all expressed against.
    dims : tuple of str
        Dimension name per storage axis of ``ykey`` under ``xkeys``. These
        are the names the projection was chosen against, so they travel with
        it: the fetch path used to ask the source for them again, and the
        read asked a third time. A function of ``(ykey, xkeys)``, so it adds
        nothing to the request's identity.
    region : RegionDefinition, optional
        ROI in data coordinates on the plot plane described by ``view``. When
        set, the output is a 1-D profile rather than the 2-D plane.
    mask_mode : str
        ``inside`` or ``outside`` when ``region`` is set.
    profile_axis : int, optional
        Storage axis the ROI profile runs along. Required when ``region`` is
        set. It is either one of the two plot-plane axes -- a profile across
        the image -- or an axis the projection holds at a single index, which
        the fetch then has to read in full.
    spatial_reduce : str
        ``sum`` or ``mean`` over the masked cells on the plot plane.
    transform : str
        Effective transform expression for this fetch. Empty string means no
        transform. The session may keep a separate enabled flag and full
        expression text; only the effective string enters the request so that
        toggling off does not change request identity relative to "no
        transform", while the expression itself is preserved on the session.
    """

    uid: str
    xkeys: Tuple[str, ...]
    ykey: str
    view: Projection
    dims: Tuple[str, ...]
    norm_keys: Tuple[str, ...] = ()
    region: Optional[RegionDefinition] = None
    mask_mode: MaskMode = "inside"
    profile_axis: Optional[int] = None
    spatial_reduce: SpatialReduce = "sum"
    transform: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "xkeys", tuple(self.xkeys))
        object.__setattr__(self, "dims", tuple(self.dims))
        object.__setattr__(self, "norm_keys", tuple(self.norm_keys or ()))
        if not self.uid:
            raise ValueError("uid must be non-empty")
        if not self.ykey:
            raise ValueError("ykey must be non-empty")
        if self.mask_mode not in ("inside", "outside"):
            raise ValueError(
                f"mask_mode must be 'inside' or 'outside', got {self.mask_mode!r}"
            )
        if self.spatial_reduce not in ("sum", "mean"):
            raise ValueError(
                f"spatial_reduce must be 'sum' or 'mean', got "
                f"{self.spatial_reduce!r}"
            )
        # Checked here, where the request is made, rather than wherever it is
        # first fetched: names that disagree with the view's rank, or repeat,
        # would give one axis another's role.
        PlotAxes.of(self.view, self.dims)
        if self.region is None:
            return
        # The projection is the plane the ROI is drawn on, not the profile it
        # reduces to. Requiring plot_ndim == 1 here was the other half of the
        # contradiction that made an ROI on a cropped plane unrepresentable.
        if self.view.plot_ndim != 2:
            raise ValueError(
                "ROI profile requests carry the parent plane, so they require "
                f"view.plot_ndim == 2, got {self.view.plot_ndim}"
            )
        if self.profile_axis is None:
            raise ValueError("ROI profile requests require a profile_axis")
        if not 0 <= self.profile_axis < self.view.ndim:
            raise ValueError(
                f"profile_axis {self.profile_axis} is out of range for ndim "
                f"{self.view.ndim}"
            )
        if (
            self.profile_axis not in self.plane_axes
            and self.view.roles[self.profile_axis] != DimRole.INDEX
        ):
            raise ValueError(
                f"profile_axis {self.profile_axis} must be a plot-plane axis "
                "or an indexed axis"
            )

    @property
    def plane_axes(self) -> Optional[Tuple[int, int]]:
        """
        Storage axes carrying plot Y and plot X, or None without a plane.

        Returns
        -------
        tuple of int or None
            ``(plot_y_axis, plot_x_axis)``.
        """
        if self.view.plot_ndim != 2:
            return None
        order = self.view.plot_axis_order()
        return (order[-2], order[-1])

    @property
    def axes(self) -> PlotAxes:
        """
        The projection by dimension name, for the stages after the load.

        Returns
        -------
        PlotAxes
            ``view`` named by ``dims``.
        """
        return PlotAxes.of(self.view, self.dims)

    @property
    def profile_axes(self) -> Optional[PlotAxes]:
        """
        The 1-D profile view the ROI reduces the plane to.

        Returns
        -------
        PlotAxes or None
            Named profile view, or None when there is no region.
        """
        if self.region is None:
            return None
        return self.axes.to_profile(self.profile_axis, self.spatial_reduce)

    @property
    def output_ndim(self) -> int:
        """
        Rank of what is drawn: 1 for an ROI profile, else the plane's rank.

        Returns
        -------
        int
            Plot dimensionality of the resulting bundle.
        """
        return 1 if self.region is not None else self.view.plot_ndim

    @property
    def plane_request(self) -> "PlotRequest":
        """
        The request for the plane this one reduces, without the ROI.

        An ROI profile *is* its parent plane plus four reduction parameters,
        so dropping them recovers the plane -- transform included, which is
        what makes masking the finished plane the same answer as the profile.

        Returns
        -------
        PlotRequest
            ``self`` when there is no region, else the parent plane request.
        """
        if self.region is None:
            return self
        return replace(
            self,
            region=None,
            mask_mode="inside",
            profile_axis=None,
            spatial_reduce="sum"
)

    def with_roi_profile(
        self,
        region: RegionDefinition,
        *,
        profile_axis,
        spatial_reduce: SpatialReduce = "sum",
        mask_mode: MaskMode = "inside",
        plane_frame: Optional[PlotViewFrame] = None,
        span_full: bool = False
) -> "PlotRequest":
        """
        Derive an ROI profile request from this plane request.

        This request already names the run, the keys, the projection and the
        crop, so a profile is that plus the four things a reduction adds: the
        region, the mask mode, the axis the profile runs along, and how the
        masked cells collapse.

        Parameters
        ----------
        region : RegionDefinition
            ROI in data coordinates on this plane.
        profile_axis : int or str
            Storage axis for the profile, or ``plot_x`` / ``plot_y``.
        spatial_reduce : str
            ``sum`` or ``mean`` within the ROI.
        mask_mode : str
            ``inside`` or ``outside`` the ROI.
        plane_frame : PlotViewFrame, optional
            Frame of the parent plane. Required for ``span_full``.
        span_full : bool
            Expand the ROI to the full plot extent along an in-plane profile
            axis. Ignored for shapes that are not separable along it.

        Returns
        -------
        PlotRequest
            Profile request for the fetch path.

        Raises
        ------
        ValueError
            If this request has no 2-D plane.
        """
        plane_axes = self.plane_axes
        if plane_axes is None:
            raise ValueError("an ROI profile needs a 2-D parent plane")
        if not isinstance(profile_axis, int):
            profile_axis = self.view.storage_axis_for(profile_axis)
        if (
            span_full
            and region.separable_for_profile
            and profile_axis in plane_axes
            and plane_frame is not None
        ):
            region = region.expand_for_profile(
                plane_frame,
                self.view.plot_axis_for(profile_axis)
)
        # The transform is inherited, not cleared. An ROI is drawn on what the
        # user sees, and what they see is f(y): clearing it here was why the same
        # ROI on a cube came back transformed along the two plane axes and
        # untransformed along the slider axis.
        return replace(
            self,
            region=region,
            mask_mode=mask_mode,
            profile_axis=int(profile_axis),
            spatial_reduce=spatial_reduce
)

    def trace_key(self, fan_out_index: Optional[int] = None) -> TraceKey:
        """
        Return the object-identity subset of this request.

        Parameters
        ----------
        fan_out_index : int, optional
            Image-grid cell index. Defaults to no fan-out.

        Returns
        -------
        TraceKey
            Key for the long-lived trace.
        """
        xkey = self.xkeys[0] if self.xkeys else ""
        return TraceKey(
            uid=self.uid,
            xkey=xkey,
            ykey=self.ykey,
            fan_out_index=fan_out_index
)

    def plot_bundle(
        self,
        reader,
        *,
        cached_plane: Optional[PlotBundle] = None,
        label: str = "",
    ) -> PlotBundle:
        """
        Load, normalize, reduce, transform, mask and pack this request.

        The end of the chain, and the only place the reader enters it. A
        request is the whole description -- the projection, the crop, and for
        an ROI the region, the profile axis and the spatial reduce -- so what
        the plot plane's coordinate frame is, and which storage indices to
        read, are both derived from it here rather than passed in.

        The stage order is the content of the pipeline:

        - Normalization happens first, on the whole block, so a norm key is
          divided in per element before anything is summed.
        - The transform runs on the finished plot plane, *before* the ROI
          mask. The user already sees ``f(y)`` on the image and draws the ROI
          on what they see, so summing the ROI must sum what they see.

        The load depends only on the fetch plan, so the reader holds the
        block as read: editing a transform, toggling a normalization already
        read, or moving an ROI inside a box already read re-runs only the
        arithmetic.

        Parameters
        ----------
        reader : object
            Whatever reads the run's keys. Three methods are used here --
            ``describe``, ``load_coords`` and ``block`` -- and in the
            application it is the ``RunSource`` the request names by ``uid``.
        cached_plane : PlotBundle, optional
            Plot plane already in memory for this request's ``view``. Used to
            skip rebuilding the plane an in-plane ROI profile reduces;
            ignored otherwise.
        label : str
            Optional display label for 1D ROI output.

        Returns
        -------
        PlotBundle
            Prepared plot payload for the view layer.
        """
        plane_axes = self.plane_axes

        # An ROI whose profile runs along an axis the plane already shows is
        # a reduction of the finished plane, so it is served by masking that
        # plane -- from memory when the caller has one, otherwise by building
        # it here. One implementation of masking a 2-D plane, and what it
        # masks is f(y), which is what the ROI was drawn on.
        if self.region is not None and self.profile_axis in (plane_axes or ()):
            plane = cached_plane
            if plane is None or plane.ndim != 2:
                plane = self.plane_request.plot_bundle(reader)
            return self.reduce_cached_plane(plane, label=label)

        # The plan comes back from planning rather than being re-derived: it
        # is not free to make -- an ROI plan compiles the region against the
        # parent plane -- and the mask stage needs the frame it produced.
        plan = self.plan(plane_frame=self._plane_frame(reader))
        data, norms = reader.block(plan)

        t0 = ttime.time()
        data = apply_normalization(data, norms)
        if self.region is None:
            axes = self.axes
            data = reduce_to_plane(data, axes)
            data = apply_transform(data, axes, self.transform)
        else:
            # Off-plane profile: the plane the user sees is one slice of the
            # block, so reduce to that stack, transform it, and only then
            # mask. The profile axis is read in full by the plan. The
            # transform sees the plane's own coordinates either way, so ``x``
            # means the same thing here as when the plane itself is drawn.
            profile = self.profile_axes
            data = reduce_before_mask(data, profile)
            data = apply_transform(data, profile, self.transform)
            data = mask_to_profile(
                data,
                profile,
                self.region,
                self.mask_mode,
                plan.region_frame,
            )
        t_tail = ttime.time() - t0

        print_debug(
            "PlotRequest.plot_bundle",
            f"{self.ykey} shape={data.shape} tail={t_tail:.4f}s",
            category="plots",
        )

        info = reader.describe(self.ykey)
        if info.synthetic and data.ndim == 1:
            data = data.rename({data.dims[0]: label or info.label})
        return PlotBundle.pack(
            data,
            is_roi_profile=self.region is not None,
            render_mode_hint=info.render_hint,
            label=label,
        )

    def _plane_frame(self, reader) -> Optional[PlotViewFrame]:
        """
        Derive the display frame of this request's full plot plane.

        An ROI is geometry in data coordinates, so something has to say which
        cell each coordinate falls in. That is a pure function of the plane's
        shape, its two coordinate arrays and the render mode, all of which are
        1-D and cheap to read, so the frame is derived here rather than passed
        in from whichever bundle the canvas happened to have drawn.

        Parameters
        ----------
        reader : object
            Whatever reads the run's keys; ``describe`` and ``load_coords``
            are used.

        Returns
        -------
        PlotViewFrame or None
            Frame of the uncropped plane, or None when there is no region to
            compile against it.
        """
        if self.region is None:
            return None
        plane_axes = self.plane_axes
        if plane_axes is None:
            raise ValueError("cannot resolve the plot plane for an ROI fetch")
        row_axis, col_axis = plane_axes
        names = self.dims
        coords = reader.load_coords(
            self.ykey, self.view.base_slice(), self.xkeys, dims=names
        )
        rows = np.atleast_1d(np.asarray(coords[names[row_axis]].values))
        cols = np.atleast_1d(np.asarray(coords[names[col_axis]].values))
        plane_shape = (int(rows.size), int(cols.size))
        render_mode = classify_render_mode(
            plane_shape,
            [rows, cols],
            render_mode_hint=reader.describe(self.ykey).render_hint,
        )
        row_reversed, col_reversed = display_flips(rows, cols, render_mode)
        return PlotBundle.from_2d(
            np.broadcast_to(np.float64(0.0), plane_shape),
            [
                rows[::-1] if row_reversed else rows,
                cols[::-1] if col_reversed else cols,
            ],
            [names[row_axis], names[col_axis]],
            render_mode_hint=render_mode,
            row_reversed=row_reversed,
            col_reversed=col_reversed,
        ).view_frame()

    def plan(
        self,
        *,
        plane_frame: Optional[PlotViewFrame] = None,
    ) -> FetchPlan:
        """
        Turn this plot description into the array indices that produce it.

        The one planner, and the next rung down the ladder: a request says
        what ends up on the plot, the :class:`FetchPlan` it returns says what
        to read. Crop and ROI both narrow the load, through :func:`narrow` and
        the same display-to-storage mapping, so the three narrowing paths this
        replaced cannot disagree about orientation again. A profile axis the
        projection holds at a single index widens the other way: it must be
        read in full, or the profile is one point long.

        Parameters
        ----------
        plane_frame : PlotViewFrame, optional
            Display frame of the full parent plot plane. Required when
            :attr:`region` is set, because the region is in data coordinates
            and has to be compiled against a frame.

        Returns
        -------
        FetchPlan
            Load slices plus the frames the loaded block lands in.

        Raises
        ------
        ValueError
            If a region is requested without a frame, covers no cells, or does
            not intersect the crop.
        """
        view = self.view
        items: List[SliceItem] = list(view.base_slice())
        plane_axes = self.plane_axes

        if self.region is not None and self.profile_axis not in plane_axes:
            items[self.profile_axis] = slice(None)

        crop = view.crop
        if crop is not None:
            r0, r1, c0, c1 = crop.storage_bbox
            items[crop.plot_y_axis] = narrow(items[crop.plot_y_axis], r0, r1)
            items[crop.plot_x_axis] = narrow(items[crop.plot_x_axis], c0, c1)

        if self.region is None:
            return FetchPlan(
                ykey=self.ykey,
                xkeys=self.xkeys,
                norm_keys=self.norm_keys,
                slice_info=tuple(items),
                dims=self.dims,
                plane_axes=plane_axes,
                plane_frame=plane_frame,
            )

        if plane_frame is None:
            raise ValueError("plan needs plane_frame when region is set")

        compiled = self.region.compile_masked(plane_frame, self.mask_mode)
        if compiled.pixel_count == 0:
            raise ValueError("ROI does not cover any cells")
        r0, r1, c0, c1 = plane_frame.storage_bbox(compiled.bbox)
        if r1 <= r0 or c1 <= c0:
            raise ValueError("ROI bounding box is empty")

        row_axis, col_axis = plane_axes
        items[row_axis] = narrow(items[row_axis], r0, r1)
        items[col_axis] = narrow(items[col_axis], c0, c1)

        # The block actually loaded is the ROI box intersected with the crop,
        # so derive the region frame from the narrowed slices rather than from
        # the ROI box, or the mask would not match the array it is applied to.
        loaded = (
            items[row_axis].start,
            items[row_axis].stop,
            items[col_axis].start,
            items[col_axis].stop,
        )
        region_frame = plane_frame.region_for_bbox(
            plane_frame.storage_bbox(loaded)
        )
        return FetchPlan(
            ykey=self.ykey,
            xkeys=self.xkeys,
            norm_keys=self.norm_keys,
            slice_info=tuple(items),
            dims=self.dims,
            plane_axes=plane_axes,
            plane_frame=plane_frame,
            region_frame=region_frame,
        )

    def reduce_cached_plane(
        self,
        plane: "PlotBundle",
        *,
        label: str = "",
    ) -> "PlotBundle":
        """
        Reduce an already-loaded display plane to an ROI profile.

        It took the request as its second argument while living beside the
        stages, which was the only thing tying that module to the chain above
        it. Everything it reads -- the plane axes, the profile axis, the spatial
        reduce, the region and the mask mode -- is this request's own.

        The one genuine optimisation in the fetch path: when the profile runs
        along an axis the plane already shows, the answer is in memory and no
        database read is needed. The plane is display-ordered and the masking
        stage works in the order the source stored the data, so the plane is
        turned back before it is masked.

        Parameters
        ----------
        plane : PlotBundle
            Cached 2-D bundle for this request's ``view`` plot plane.
        label : str
            Optional display label for the profile.

        Returns
        -------
        PlotBundle
            1-D profile payload.

        Raises
        ------
        ValueError
            If the plane is not 2-D, the profile axis is off it, or the ROI
            reduces to nothing.
        """
        if plane.ndim != 2:
            raise ValueError("cached_plane must be a 2-D bundle")
        plane_axes = self.plane_axes
        if plane_axes is None or self.profile_axis not in plane_axes:
            raise ValueError("cached_plane cannot serve an off-plane profile")

        frame = plane.view_frame()
        bundle_profile_axis = 0 if self.profile_axis == plane_axes[0] else 1
        plane_view = Projection(
            ndim=2,
            plot_ndim=2,
            roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
            indices=(0, 0),
        )
        arrays, names = plane.axis_arrays()
        values = np.asarray(plane.y)
        # ``mask_to_profile`` turns the display-ordered mask round to meet a
        # storage-ordered block, so the plane turns back first, coordinates with
        # it. Handed over as displayed, the mask was turned twice and an ROI drawn
        # low on a row-reversed image summed the mirror-image rows at the top.
        if frame.row_reversed:
            values = values[::-1, :]
            arrays[frame.plot_y_dim] = arrays[frame.plot_y_dim][::-1]
        if frame.col_reversed:
            values = values[:, ::-1]
            arrays[frame.plot_x_dim] = arrays[frame.plot_x_dim][::-1]
        data = xr.DataArray(
            values,
            dims=list(names),
            coords={name: array for name, array in zip(names, arrays)},
        )
        axes = PlotAxes.of(plane_view, names).to_profile(
            bundle_profile_axis, self.spatial_reduce
        )
        profile = materialize_view(
            data,
            axes,
            region=self.region,
            mask_mode=self.mask_mode,
            region_frame=frame,
        )
        if not np.isfinite(profile.values).any():
            raise ValueError("ROI profile is empty after reduction")
        profile_dim = profile.dims[0]
        return PlotBundle.from_1d(
            profile.values,
            [np.asarray(profile.coords[profile_dim].values)],
            [label or str(profile_dim)],
        )
