"""
Immutable description of one plottable trace, and the plan that fetches it.

The two fixed layers of the view pipeline live here. A :class:`PlotRequest`
is frozen and hashable so it can serve as the fingerprint of a fetch;
:func:`plan_fetch` is the one pure function that turns it into the array
indices to read, returning a :class:`FetchPlan`. Long-lived traces
are identified by :class:`TraceKey`, a subset of the request, so view / crop
/ transform changes reuse the artist.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Optional, Sequence, Tuple, Union

from .plot_view_frame import PlotViewFrame, region_frame_for_bbox
from .region import (
    MaskMode,
    RectRegion,
    RegionDefinition,
    compile_covering_rect,
    compile_with_mask_mode,
    expand_region_for_profile,
)
from .view_spec import (
    DimRole,
    SpatialReduce,
    ViewCrop,
    Projection,
    plot_axis_to_storage_axis,
    storage_axis_to_plot_axis,
)

SliceItem = Union[int, slice]


def build_plot_request(
    *,
    uid: str,
    xkeys: Sequence[str],
    ykey: str,
    projection: Projection,
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
        X-axis key selection used for dimension analysis.
    ykey : str
        Y data key.
    norm_keys : tuple of str
        Normalization keys. Empty means no normalization.
    view : Projection
        Rank-bound view of the plane that is loaded, including its optional
        crop. When ``region`` is set this is still the *parent* 2-D plane:
        the ROI reduces it afterwards, and the plane's identity is what the
        mask, the profile axis and the crop are all expressed against.
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


def narrow(item: SliceItem, start: int, stop: int) -> slice:
    """
    Intersect one axis' load item with half-open ``[start, stop)``.

    The single narrowing helper. Crop bounds and ROI bounding-box bounds are
    the same kind of thing at the fetch layer -- a spatial restriction that
    shrinks the load -- so they go through one function and cannot drift
    apart.

    Parameters
    ----------
    item : int or slice
        Current load item for one storage axis.
    start, stop : int
        Half-open bounds to intersect with.

    Returns
    -------
    slice
        Narrowed load slice.

    Raises
    ------
    ValueError
        If ``item`` is an integer index or the intersection is empty.
    """
    if isinstance(item, int):
        raise ValueError("cannot narrow an indexed axis")
    if not isinstance(item, slice):
        return slice(int(start), int(stop))
    current_start = 0 if item.start is None else int(item.start)
    new_start = max(current_start, int(start))
    new_stop = int(stop) if item.stop is None else min(int(item.stop), int(stop))
    if new_start >= new_stop:
        raise ValueError(
            f"narrowed bounds [{start}, {stop}) do not intersect {item}"
        )
    return slice(new_start, new_stop)


@dataclass(frozen=True)
class FetchPlan:
    """
    What array indices to read, and the frame the loaded plane lands in.

    The bottom of the two fixed layers: a :class:`PlotRequest` says what ends
    up on the plot, ``plan_fetch`` says what to read. Equality covers the load
    identity only -- the frames are derived and carry numpy arrays, so they
    are excluded from comparison.

    Parameters
    ----------
    slice_info : tuple
        Per-storage-axis slice or index for chunked loading.
    plane_axes : tuple of int, optional
        Storage axes of the plot plane, ``(plot_y, plot_x)``. None when the
        request has no 2-D plane.
    plane_frame : PlotViewFrame, optional
        Display frame of the *full* plot plane. It is what a drawn ROI is
        compiled against, and what maps the resulting box back to storage
        indices.
    region_frame : PlotViewFrame, optional
        Display frame matching the block that ``slice_info`` actually loads,
        for compiling the ROI mask against it. None when there is no region.
    """

    slice_info: Tuple[SliceItem, ...]
    plane_axes: Optional[Tuple[int, int]] = None
    plane_frame: Optional[PlotViewFrame] = field(default=None, compare=False)
    region_frame: Optional[PlotViewFrame] = field(default=None, compare=False)


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
        profile_axis = plot_axis_to_storage_axis(
            parent.view, profile_axis
        )
    if (
        span_full
        and region.separable_for_profile
        and profile_axis in plane_axes
        and plane_frame is not None
    ):
        region = expand_region_for_profile(
            plane_frame,
            region,
            storage_axis_to_plot_axis(
                plane_frame,
                profile_axis,
                parent_spec=parent.view,
            ),
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


def plan_fetch(
    request: PlotRequest,
    *,
    plane_frame: Optional[PlotViewFrame] = None,
) -> FetchPlan:
    """
    Turn a plot description into the array indices that produce it.

    The one planner. Crop and ROI both narrow the load, through :func:`narrow`
    and the same display-to-storage mapping, so the three narrowing paths this
    replaced cannot disagree about orientation again. A profile axis the
    projection holds at a single index widens the other way: it must be read
    in full, or the profile is one point long.

    Parameters
    ----------
    request : PlotRequest
        What ends up on the plot.
    plane_frame : PlotViewFrame, optional
        Display frame of the full parent plot plane. Required when
        ``request.region`` is set, because the region is in data coordinates
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
    view = request.view
    items: List[SliceItem] = list(view.base_slice())
    plane_axes = request.plane_axes

    if request.region is not None and request.profile_axis not in plane_axes:
        items[request.profile_axis] = slice(None)

    crop = view.crop
    if crop is not None:
        r0, r1, c0, c1 = crop.storage_bbox
        items[crop.plot_y_axis] = narrow(items[crop.plot_y_axis], r0, r1)
        items[crop.plot_x_axis] = narrow(items[crop.plot_x_axis], c0, c1)

    if request.region is None:
        return FetchPlan(tuple(items), plane_axes, plane_frame)

    if plane_frame is None:
        raise ValueError("plan_fetch needs plane_frame when request.region is set")

    compiled = compile_with_mask_mode(
        plane_frame, request.region, request.mask_mode
    )
    if compiled.pixel_count == 0:
        raise ValueError("ROI does not cover any cells")
    r0, r1, c0, c1 = plane_frame.storage_bbox(compiled.bbox)
    if r1 <= r0 or c1 <= c0:
        raise ValueError("ROI bounding box is empty")

    row_axis, col_axis = plane_axes
    items[row_axis] = narrow(items[row_axis], r0, r1)
    items[col_axis] = narrow(items[col_axis], c0, c1)

    # The block actually loaded is the ROI box intersected with the crop, so
    # derive the region frame from the narrowed slices rather than from the
    # ROI box, or the mask would not match the array it is applied to.
    loaded = (
        items[row_axis].start,
        items[row_axis].stop,
        items[col_axis].start,
        items[col_axis].stop,
    )
    region_frame = region_frame_for_bbox(
        plane_frame, plane_frame.storage_bbox(loaded)
    )
    return FetchPlan(tuple(items), plane_axes, plane_frame, region_frame)
