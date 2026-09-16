"""
The words a plot plane is described in.

Every type here answers a question about the plane itself -- which storage
axes map onto it, how an axis that does not is collapsed, which of the two
drawn axes is meant, what part of the plane is kept, and whether a region
selects the inside or the outside of a shape. Nothing here knows about a run,
a request or a session.

**This package imports nothing else in ``models/plot``.** That is what makes
it vocabulary rather than a layer: everything else here describes data,
fetches it or draws it, and all of them need these words, so the words cannot
need anything back. Whenever something in this package starts wanting a
request or a region, the thing that wants it is not vocabulary and belongs
above -- which is how ``storage_axis_to_plot_axis`` was found taking a frame
it should never have had, and how ``default_profile_label`` was found to be
ROI text.

The property used to belong to ``view/``, which was only ever half a sink: it
owned ``ViewCrop`` while the sole thing that builds one,
``RectRegion.to_view_crop``, lived a package away.

``MaskMode`` moved here from ``region.py``, where a note argued it belonged
beside the mask-mode compile, "the thing it configures". That held while that
function was its only consumer. It now has four, three of them outside
``region.py``, and two packages were importing from ``geometry`` purely to
type a two-valued string.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, Tuple, Union

SliceItem = Union[int, slice]
SpatialReduce = Literal["sum", "mean"]
PlotAxisName = Literal["plot_x", "plot_y"]
MaskMode = Literal["inside", "outside"]


class DimRole(str, Enum):
    """How a storage dimension participates in the projection."""

    INDEX = "index"
    PLOT_X = "plot_x"
    PLOT_Y = "plot_y"
    SUM = "sum"
    MEAN = "mean"


ROLE_LABELS = {
    DimRole.INDEX: "Index",
    DimRole.PLOT_X: "Plot X",
    DimRole.PLOT_Y: "Plot Y",
    DimRole.SUM: "Sum",
    DimRole.MEAN: "Mean",
}

SLICE_ROLES = (DimRole.INDEX, DimRole.SUM, DimRole.MEAN)


@dataclass(frozen=True)
class ViewCrop:
    """
    Integer storage-index crop on the 2D plot plane.

    Display-to-storage conversion happens at construction time. Only the
    bounds needed to narrow a load slice are retained, so the crop is
    hashable and safe to embed in a ``Projection`` / ``PlotRequest``.

    Parameters
    ----------
    storage_bbox : tuple of int
        Half-open bounding box ``(row_start, row_stop, col_start, col_stop)``
        on the raw storage plane.
    plot_y_axis : int
        Storage axis index mapped to plot Y.
    plot_x_axis : int
        Storage axis index mapped to plot X.
    """

    storage_bbox: Tuple[int, int, int, int]
    plot_y_axis: int
    plot_x_axis: int

    def __post_init__(self) -> None:
        r0, r1, c0, c1 = self.storage_bbox
        if r1 <= r0 or c1 <= c0:
            raise ValueError(
                f"storage_bbox must be non-empty half-open, got {self.storage_bbox}"
            )
        if self.plot_y_axis == self.plot_x_axis:
            raise ValueError("plot_y_axis and plot_x_axis must differ")
        if self.plot_y_axis < 0 or self.plot_x_axis < 0:
            raise ValueError("plot axis indices must be non-negative")
