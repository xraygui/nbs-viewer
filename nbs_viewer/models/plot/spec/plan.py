"""
What to read out of storage for one request, and which indices of it.

The lower of the view pipeline's two fixed layers. A PlotRequest next
door says what ends up on the plot; :func:`plan_fetch` is the one pure
function that turns it into the array indices to read, returning a
:class:`FetchPlan`. It is also the only place a load is narrowed, so the
display-to-storage mapping has one owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from ..plane.frame import PlotViewFrame
from .region import compile_with_mask_mode
from ..plane.roles import SliceItem
from .request import PlotRequest


@dataclass(frozen=True)
class FetchPlan:
    """
    What to read, which indices of it, and the frame the loaded plane lands in.

    The bottom of the two fixed layers: a :class:`PlotRequest` says what ends
    up on the plot, ``plan_fetch`` says what to read. Equality covers the load
    identity only -- the frames are derived and carry numpy arrays, so they
    are excluded from comparison.

    It used to carry the indices but not the keys, so anything executing a
    plan needed the request beside it to know *what* to read, and the block
    cache kept ``(ykey, xkeys, norm_keys)`` as a separate key -- which was
    exactly the missing half, held next to the plan rather than in it.

    The run is implied: a plan is executed by the source that made it.

    Parameters
    ----------
    ykey : str
        The data key being plotted.
    xkeys : tuple of str
        Selected X-axis keys, which decide the coordinates the load resolves.
    norm_keys : tuple of str
        Normalization keys read alongside, each on its own derived slice.
    slice_info : tuple
        Per-storage-axis slice or index for chunked loading.
    dims : tuple of str
        Dimension name of each ``slice_info`` entry. Without them the plan
        said which index to read on each storage axis but not which dimension
        that axis was, so everything executing it needed a named view beside
        it to translate.
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

    ykey: str
    xkeys: Tuple[str, ...]
    norm_keys: Tuple[str, ...]
    slice_info: Tuple[SliceItem, ...]
    dims: Tuple[str, ...]
    plane_axes: Optional[Tuple[int, int]] = None
    plane_frame: Optional[PlotViewFrame] = field(default=None, compare=False)
    region_frame: Optional[PlotViewFrame] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if len(self.dims) != len(self.slice_info):
            raise ValueError(
                f"{len(self.dims)} dimension names for "
                f"{len(self.slice_info)} load items"
            )

    def reads_the_same(self, other: "FetchPlan") -> bool:
        """
        Whether two plans read the same block, ignoring the window.

        What the block cache needs: a held block can serve a new plan when it
        is the same key under the same X selection, and so carries the same
        coordinates and dimension names. The window is handled separately
        because containment is not equality.

        Two things are deliberately *not* compared. The norm keys: the cache
        holds the block as read and the norms beside it, so switching a
        normalization reads at most the norm. And the plot plane: the block
        is in storage order, so which two axes are drawn does not change what
        was read -- it did while the load flipped the plane.

        Parameters
        ----------
        other : FetchPlan
            Plan to compare against.

        Returns
        -------
        bool
            True when only the load window may differ.
        """
        return (self.ykey, self.xkeys, self.dims) == (
            other.ykey,
            other.xkeys,
            other.dims,
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
        return FetchPlan(
            ykey=request.ykey,
            xkeys=request.xkeys,
            norm_keys=request.norm_keys,
            slice_info=tuple(items),
            dims=request.dims,
            plane_axes=plane_axes,
            plane_frame=plane_frame,
        )

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
    region_frame = plane_frame.region_for_bbox(
        plane_frame.storage_bbox(loaded)
    )
    return FetchPlan(
        ykey=request.ykey,
        xkeys=request.xkeys,
        norm_keys=request.norm_keys,
        slice_info=tuple(items),
        dims=request.dims,
        plane_axes=plane_axes,
        plane_frame=plane_frame,
        region_frame=region_frame,
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

def kept_axes(items: Sequence[SliceItem]) -> Tuple[int, ...]:
    """
    Return the storage axes a load keeps.

    An integer item indexes its axis away; a slice keeps it.

    Parameters
    ----------
    items : sequence of int or slice
        Per-storage-axis load items.

    Returns
    -------
    tuple of int
        Storage axes present in the loaded array, in order.
    """
    return tuple(
        axis for axis, item in enumerate(items) if isinstance(item, slice)
    )
