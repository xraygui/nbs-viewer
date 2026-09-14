"""
Immutable description of one plottable trace.

The upper of the view pipeline's two fixed layers. A :class:`PlotRequest` is
frozen and hashable so it can serve as the fingerprint of a fetch; what to
*read* for one is :mod:`plan` next door. Long-lived traces are identified by
:class:`TraceKey`, a subset of the request, so view / crop / transform
changes reuse the artist.

The two functions that build a request from something a user drew are here
with it: a committed crop rectangle, and an ROI profile.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Sequence, Tuple

from ..view import DimRole, PlotAxes, Projection, SpatialReduce, ViewCrop
from ..geometry import (
    MaskMode,
    PlotViewFrame,
    RectRegion,
    RegionDefinition,
    compile_covering_rect,
    expand_region_for_profile,
)


def build_plot_request(
    *,
    uid: str,
    xkeys: Sequence[str],
    ykey: str,
    projection: Projection,
    dims: Sequence[str],
    norm_keys: Optional[Sequence[str]] = None,
    transform: str = "",
) -> "PlotRequest":
    """
    Assemble a :class:`PlotRequest` around an already-chosen projection.

    Choosing the projection is ``ViewIntent.project``'s job and happens
    exactly once, in the session; this only packages it with run identity.

    Parameters
    ----------
    uid : str
        Run uid.
    xkeys : sequence of str
        X-axis keys.
    ykey : str
        Y data key.
    projection : Projection
        Rank-bound view for this key, crop included.
    dims : sequence of str
        Dimension name per storage axis of ``ykey`` under ``xkeys`` -- the
        names the projection was chosen against.
    norm_keys : sequence of str, optional
        Normalization keys.
    transform : str
        Effective transform expression.

    Returns
    -------
    PlotRequest
        Frozen request for the fetch path.
    """
    return PlotRequest(
        uid=uid,
        xkeys=tuple(xkeys),
        ykey=ykey,
        norm_keys=tuple(norm_keys or ()),
        view=projection,
        dims=tuple(dims),
        transform=transform or "",
    )


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
    norm_keys: Tuple[str, ...]
    view: Projection
    dims: Tuple[str, ...]
    region: Optional[RegionDefinition] = None
    mask_mode: MaskMode = "inside"
    profile_axis: Optional[int] = None
    spatial_reduce: SpatialReduce = "sum"
    transform: str = ""

    def __post_init__(self) -> None:
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
            spatial_reduce="sum",
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
            fan_out_index=fan_out_index,
        )


def crop_from_region(
    region: RectRegion,
    plane_frame: PlotViewFrame,
    plane_axes: Tuple[int, int],
) -> ViewCrop:
    """
    Commit a drawn rectangle to the storage-index crop of a request.

    Cell-intersects selection is used here rather than the cell-center rule
    used for ROI reduction, so the cropped plane still covers what was drawn.

    Parameters
    ----------
    region : RectRegion
        Rectangle in data coordinates on the oriented plot plane.
    plane_frame : PlotViewFrame
        Frame of the full plane, before the crop.
    plane_axes : tuple of int
        ``(plot_y_axis, plot_x_axis)`` storage axes of that plane.

    Returns
    -------
    ViewCrop
        Storage-index crop to attach to a view.

    Raises
    ------
    ValueError
        If the rectangle selects no cells.
    """
    compiled = compile_covering_rect(plane_frame, region)
    if compiled.pixel_count == 0:
        raise ValueError("Crop region does not cover any cells")
    r0, r1, c0, c1 = compiled.bbox
    if r1 <= r0 or c1 <= c0:
        raise ValueError("Crop bounding box is empty")
    plot_y_axis, plot_x_axis = plane_axes
    return ViewCrop(
        storage_bbox=plane_frame.storage_bbox(compiled.bbox),
        plot_y_axis=int(plot_y_axis),
        plot_x_axis=int(plot_x_axis),
    )


def roi_profile_request(
    parent: PlotRequest,
    region: RegionDefinition,
    *,
    profile_axis,
    spatial_reduce: SpatialReduce = "sum",
    mask_mode: MaskMode = "inside",
    plane_frame: Optional[PlotViewFrame] = None,
    span_full: bool = False,
) -> PlotRequest:
    """
    Derive an ROI profile request from the request that drew the plane.

    The parent request already names the run, the keys, the projection and
    the crop, so a profile is that request plus the four things a reduction
    adds: the region, the mask mode, the axis the profile runs along, and how
    the masked cells collapse.

    Parameters
    ----------
    parent : PlotRequest
        Request for the parent 2-D plane.
    region : RegionDefinition
        ROI in data coordinates on that plane.
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
        If the parent request has no 2-D plane.
    """
    plane_axes = parent.plane_axes
    if plane_axes is None:
        raise ValueError("an ROI profile needs a 2-D parent plane")
    if not isinstance(profile_axis, int):
        profile_axis = parent.view.storage_axis_for(profile_axis)
    if (
        span_full
        and region.separable_for_profile
        and profile_axis in plane_axes
        and plane_frame is not None
    ):
        region = expand_region_for_profile(
            plane_frame,
            region,
            parent.view.plot_axis_for(profile_axis),
        )
    # The transform is inherited, not cleared. An ROI is drawn on what the
    # user sees, and what they see is f(y): clearing it here was why the same
    # ROI on a cube came back transformed along the two plane axes and
    # untransformed along the slider axis.
    return replace(
        parent,
        region=region,
        mask_mode=mask_mode,
        profile_axis=int(profile_axis),
        spatial_reduce=spatial_reduce,
    )


