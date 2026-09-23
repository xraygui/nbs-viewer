"""
What to read out of storage for one request, and which indices of it.

The lower of the view pipeline's two fixed layers. A PlotRequest next
door says what ends up on the plot; ``PlotRequest.plan`` turns it into the
array indices to read, returning a :class:`FetchPlan`. The planning lives
up there, with the description it reads, so this module can sit below the
request rather than importing it. What stays here is the plan itself and
:func:`narrow`, the one place a load is narrowed, so the display-to-storage
mapping has one owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

from ..plane.frame import PlotViewFrame
from ..plane.roles import SliceItem


@dataclass(frozen=True)
class FetchPlan:
    """
    What to read, which indices of it, and the frame the loaded plane lands in.

    The bottom of the two fixed layers: a :class:`PlotRequest` says what ends
    up on the plot, ``PlotRequest.plan`` says what to read. Equality covers the
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
