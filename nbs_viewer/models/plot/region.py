"""
Region definitions that compile to boolean cell masks on a plot view frame.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Tuple

import numpy as np

from .plot_view_frame import PlotViewFrame
from .region_mesh import _data_limits, mask_from_axis_slice, mask_from_data_rect


@dataclass(frozen=True)
class CompiledRegion:
    """
    Compiled region mask on the displayed 2D plane.

    Parameters
    ----------
    mask : np.ndarray
        Boolean mask with shape matching the view frame.
    bbox : tuple of int
        Inclusive min and exclusive max storage indices
        ``(row_start, row_stop, col_start, col_stop)``.
    pixel_count : int
        Number of selected cells.
    """

    mask: np.ndarray
    bbox: Tuple[int, int, int, int]
    pixel_count: int


def _bbox_from_mask(mask: np.ndarray) -> Tuple[int, int, int, int]:
    """
    Compute a tight bounding box for a boolean mask.
    """
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any() or not cols.any():
        return (0, 0, 0, 0)
    row_idx = np.flatnonzero(rows)
    col_idx = np.flatnonzero(cols)
    return (
        int(row_idx[0]),
        int(row_idx[-1]) + 1,
        int(col_idx[0]),
        int(col_idx[-1]) + 1,
    )


class RegionDefinition(ABC):
    """
    Abstract region definition that compiles against a view frame.
    """

    @abstractmethod
    def compile(self, frame: PlotViewFrame) -> CompiledRegion:
        """
        Compile this region for the given view frame.
        """


@dataclass(frozen=True)
class RectRegion(RegionDefinition):
    """
    Axis-aligned rectangle in matplotlib data coordinates.

    Parameters
    ----------
    x0, x1 : float
        Horizontal limits.
    y0, y1 : float
        Vertical limits.
    """

    x0: float
    x1: float
    y0: float
    y1: float

    def normalized(self) -> RectRegion:
        """
        Return a copy with ordered corner values.
        """
        x0, x1 = (self.x0, self.x1) if self.x0 <= self.x1 else (self.x1, self.x0)
        y0, y1 = (self.y0, self.y1) if self.y0 <= self.y1 else (self.y1, self.y0)
        return RectRegion(x0=x0, x1=x1, y0=y0, y1=y1)

    def compile(self, frame: PlotViewFrame) -> CompiledRegion:
        """
        Compile the rectangle to a cell mask.
        """
        region = self.normalized()
        mask = mask_from_data_rect(
            frame, region.x0, region.x1, region.y0, region.y1
        )
        return CompiledRegion(
            mask=mask,
            bbox=_bbox_from_mask(mask),
            pixel_count=int(mask.sum()),
        )


PlotAxisName = Literal["plot_x", "plot_y"]
MaskMode = Literal["inside", "outside"]


def compile_rect_with_mask_mode(
    frame: PlotViewFrame,
    region: RectRegion,
    mask_mode: MaskMode = "inside",
) -> CompiledRegion:
    """
    Compile a rectangle ROI, optionally inverting the mask.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the parent 2D plot.
    region : RectRegion
        Rectangle in matplotlib data coordinates.
    mask_mode : str
        ``inside`` or ``outside`` the ROI.

    Returns
    -------
    CompiledRegion
        Compiled mask on the plot plane.
    """
    compiled = region.compile(frame)
    if mask_mode == "inside":
        return compiled
    if mask_mode == "outside":
        mask = ~compiled.mask
        return CompiledRegion(
            mask=mask,
            bbox=_bbox_from_mask(mask),
            pixel_count=int(mask.sum()),
        )
    raise ValueError(f"Unknown mask_mode {mask_mode!r}")


def expand_rect_for_profile(
    frame: PlotViewFrame,
    region: RectRegion,
    profile_axis: PlotAxisName,
) -> RectRegion:
    """
    Expand an ROI to the full plot extent along the profile axis.

    For a profile along plot X (e.g. en_energy on the horizontal axis), the
    ROI spans the full plot X range so every profile bin is included. The
    orthogonal limits are left unchanged so reduction still uses the drawn
    band on plot Y (e.g. tes_mca_energies).

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the parent 2D plot.
    region : RectRegion
        User-drawn rectangle in data coordinates.
    profile_axis : str
        ``plot_x`` or ``plot_y``.

    Returns
    -------
    RectRegion
        Rectangle with one axis expanded to data limits.
    """
    region = region.normalized()
    x_lo, x_hi, y_lo, y_hi = _data_limits(frame)
    if profile_axis == "plot_x":
        return RectRegion(
            x0=x_lo, x1=x_hi, y0=region.y0, y1=region.y1
        ).normalized()
    if profile_axis == "plot_y":
        return RectRegion(
            x0=region.x0, x1=region.x1, y0=y_lo, y1=y_hi
        ).normalized()
    raise ValueError(f"Unknown profile axis {profile_axis!r}")



@dataclass(frozen=True)
class AxisSliceRegion(RegionDefinition):
    """
    Band selection along plot X or plot Y in data coordinates.

    Parameters
    ----------
    axis : str
        ``plot_x`` or ``plot_y``.
    v0, v1 : float
        Data-coordinate limits along that axis.
    """

    axis: PlotAxisName
    v0: float
    v1: float

    def compile(self, frame: PlotViewFrame) -> CompiledRegion:
        """
        Compile the axis slice to a cell mask.
        """
        mask = mask_from_axis_slice(frame, self.axis, self.v0, self.v1)
        return CompiledRegion(
            mask=mask,
            bbox=_bbox_from_mask(mask),
            pixel_count=int(mask.sum()),
        )
