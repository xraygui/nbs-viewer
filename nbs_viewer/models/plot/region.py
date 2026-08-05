"""
Region definitions that compile to boolean cell masks on a plot view frame.

A region is frozen, serializable, and free of Qt and matplotlib-widget
imports so it can be compiled and tested headlessly. Selection uses
cell-center-inside semantics for every shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import ClassVar, Dict, Literal, Tuple, Type

import numpy as np

from .plot_view_frame import PlotViewFrame
from .region_mesh import (
    _data_limits,
    cell_mask_at_point,
    mask_covering_data_rect,
    mask_from_axis_slice,
    mask_from_data_rect,
)

PlotAxisName = Literal["plot_x", "plot_y"]
MaskMode = Literal["inside", "outside"]


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


def _compiled_from_mask(mask: np.ndarray) -> CompiledRegion:
    """
    Wrap a boolean mask in a :class:`CompiledRegion`.
    """
    return CompiledRegion(
        mask=mask,
        bbox=_bbox_from_mask(mask),
        pixel_count=int(mask.sum()),
    )


REGION_TYPES: Dict[str, Type["RegionDefinition"]] = {}


def register_region_type(cls: Type["RegionDefinition"]) -> Type["RegionDefinition"]:
    """
    Register a region class under its ``region_type`` id.

    Parameters
    ----------
    cls : type
        Concrete :class:`RegionDefinition` subclass.

    Returns
    -------
    type
        The same class, so this can be used as a decorator.
    """
    REGION_TYPES[cls.region_type] = cls
    return cls


def region_from_dict(payload: dict) -> "RegionDefinition":
    """
    Rebuild a region from its serialized form.

    Parameters
    ----------
    payload : dict
        Mapping produced by :meth:`RegionDefinition.to_dict`.

    Returns
    -------
    RegionDefinition
        Reconstructed region.

    Raises
    ------
    ValueError
        If ``region_type`` is missing or unregistered.
    """
    region_type = payload.get("region_type")
    cls = REGION_TYPES.get(region_type)
    if cls is None:
        raise ValueError(f"Unknown region_type {region_type!r}")
    return cls.from_dict(payload)


class RegionDefinition(ABC):
    """
    Abstract region definition that compiles against a view frame.

    Attributes
    ----------
    region_type : str
        Stable id used for serialization and view-side registry lookup.
    """

    region_type: ClassVar[str] = ""

    @abstractmethod
    def compile(self, frame: PlotViewFrame) -> CompiledRegion:
        """
        Compile this region for the given view frame.
        """

    @abstractmethod
    def data_bounds(self) -> Tuple[float, float, float, float]:
        """
        Return the region's extent as ``(x0, x1, y0, y1)`` in data coordinates.
        """

    @abstractmethod
    def describe(self) -> str:
        """
        Return a short human-readable summary for list displays.
        """

    @property
    def separable_for_profile(self) -> bool:
        """
        Return whether the shape is separable along both plot axes.

        Only separable shapes may be expanded by span-full, since expanding a
        non-separable shape along one axis discards the drawn geometry.
        """
        return False

    def has_area(self) -> bool:
        """
        Return whether the region encloses a nonzero data-coordinate area.
        """
        x0, x1, y0, y1 = self.data_bounds()
        return x1 > x0 and y1 > y0

    def centroid(self) -> Tuple[float, float]:
        """
        Return the center of the region's data bounds.
        """
        x0, x1, y0, y1 = self.data_bounds()
        return (0.5 * (x0 + x1), 0.5 * (y0 + y1))

    def expand_for_profile(
        self, frame: PlotViewFrame, profile_axis: PlotAxisName
    ) -> "RegionDefinition":
        """
        Return the region expanded to the full plot extent along one axis.

        The base implementation returns ``self``, which is correct for every
        non-separable shape.
        """
        return self

    def to_dict(self) -> dict:
        """
        Return a JSON-friendly mapping including ``region_type``.
        """
        return {"region_type": self.region_type, **asdict(self)}

    @classmethod
    def from_dict(cls, payload: dict) -> "RegionDefinition":
        """
        Rebuild a region of this class from :meth:`to_dict` output.
        """
        fields = {k: v for k, v in payload.items() if k != "region_type"}
        return cls(**fields)

    def _compile_mask(
        self, frame: PlotViewFrame, mask: np.ndarray
    ) -> CompiledRegion:
        """
        Wrap a mask, falling back to one cell for sub-cell shapes.

        A shape smaller than a single cell contains no cell centers and would
        otherwise compile to an empty mask, so the cell holding its centroid
        is selected instead.
        """
        if not mask.any() and self.has_area():
            mask = cell_mask_at_point(frame, *self.centroid())
        return _compiled_from_mask(mask)


@register_region_type
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

    region_type: ClassVar[str] = "rect"

    x0: float
    x1: float
    y0: float
    y1: float

    def normalized(self) -> "RectRegion":
        """
        Return a copy with ordered corner values.
        """
        x0, x1 = (self.x0, self.x1) if self.x0 <= self.x1 else (self.x1, self.x0)
        y0, y1 = (self.y0, self.y1) if self.y0 <= self.y1 else (self.y1, self.y0)
        return RectRegion(x0=x0, x1=x1, y0=y0, y1=y1)

    def compile(self, frame: PlotViewFrame) -> CompiledRegion:
        """
        Compile the rectangle to a cell mask using cell centers.
        """
        region = self.normalized()
        mask = mask_from_data_rect(
            frame, region.x0, region.x1, region.y0, region.y1
        )
        return self._compile_mask(frame, mask)

    def data_bounds(self) -> Tuple[float, float, float, float]:
        """
        Return the ordered rectangle corners.
        """
        region = self.normalized()
        return (region.x0, region.x1, region.y0, region.y1)

    def describe(self) -> str:
        """
        Return a corner summary for list displays.
        """
        x0, x1, y0, y1 = self.data_bounds()
        return f"Rect ({x0:.4g}, {y0:.4g})–({x1:.4g}, {y1:.4g})"

    @property
    def separable_for_profile(self) -> bool:
        """
        Rectangles are separable along both plot axes.
        """
        return True

    def expand_for_profile(
        self, frame: PlotViewFrame, profile_axis: PlotAxisName
    ) -> "RectRegion":
        """
        Expand the rectangle to the plot data limits along the profile axis.

        For a profile along plot X (e.g. en_energy on the horizontal axis),
        the rectangle spans the full plot X range so every profile bin is
        included. The orthogonal limits are left unchanged so reduction still
        uses the drawn band on plot Y (e.g. tes_mca_energies).
        """
        x0, x1, y0, y1 = self.data_bounds()
        x_lo, x_hi, y_lo, y_hi = _data_limits(frame)
        if profile_axis == "plot_x":
            return RectRegion(x0=x_lo, x1=x_hi, y0=y0, y1=y1).normalized()
        if profile_axis == "plot_y":
            return RectRegion(x0=x0, x1=x1, y0=y_lo, y1=y_hi).normalized()
        raise ValueError(f"Unknown profile axis {profile_axis!r}")


@register_region_type
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

    region_type: ClassVar[str] = "axis_slice"

    axis: PlotAxisName
    v0: float
    v1: float

    def compile(self, frame: PlotViewFrame) -> CompiledRegion:
        """
        Compile the axis slice to a cell mask using cell centers.
        """
        mask = mask_from_axis_slice(frame, self.axis, self.v0, self.v1)
        return _compiled_from_mask(mask)

    def data_bounds(self) -> Tuple[float, float, float, float]:
        """
        Return the band limits, unbounded along the orthogonal axis.
        """
        v0, v1 = (self.v0, self.v1) if self.v0 <= self.v1 else (self.v1, self.v0)
        infinite = (float("-inf"), float("inf"))
        if self.axis == "plot_x":
            return (v0, v1, *infinite)
        return (*infinite, v0, v1)

    def describe(self) -> str:
        """
        Return a band summary for list displays.
        """
        v0, v1 = (self.v0, self.v1) if self.v0 <= self.v1 else (self.v1, self.v0)
        name = "X" if self.axis == "plot_x" else "Y"
        return f"Band {name} {v0:.4g}–{v1:.4g}"

    @property
    def separable_for_profile(self) -> bool:
        """
        Axis bands are separable along both plot axes.
        """
        return True


def compile_with_mask_mode(
    frame: PlotViewFrame,
    region: RegionDefinition,
    mask_mode: MaskMode = "inside",
) -> CompiledRegion:
    """
    Compile any region, optionally inverting the mask.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the parent 2D plot.
    region : RegionDefinition
        Region in matplotlib data coordinates.
    mask_mode : str
        ``inside`` or ``outside`` the region.

    Returns
    -------
    CompiledRegion
        Compiled mask on the plot plane.
    """
    compiled = region.compile(frame)
    if mask_mode == "inside":
        return compiled
    if mask_mode == "outside":
        return _compiled_from_mask(~compiled.mask)
    raise ValueError(f"Unknown mask_mode {mask_mode!r}")


def compile_covering_rect(
    frame: PlotViewFrame,
    region: RectRegion,
) -> CompiledRegion:
    """
    Compile a rectangle using cell-intersects semantics for view cropping.

    Crop is 2D-to-2D extraction, so the result must still cover the drawn
    rectangle. ROI reduction uses :func:`compile_with_mask_mode` instead.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the plane being cropped.
    region : RectRegion
        Rectangle in matplotlib data coordinates.

    Returns
    -------
    CompiledRegion
        Compiled mask covering every touched cell.
    """
    x0, x1, y0, y1 = region.data_bounds()
    return _compiled_from_mask(mask_covering_data_rect(frame, x0, x1, y0, y1))


def expand_region_for_profile(
    frame: PlotViewFrame,
    region: RegionDefinition,
    profile_axis: PlotAxisName,
) -> RegionDefinition:
    """
    Expand a region to the full plot extent along the profile axis.

    Non-separable shapes are returned unchanged, since their own extent is
    the intended limit of the reduction.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the parent 2D plot.
    region : RegionDefinition
        User-drawn region in data coordinates.
    profile_axis : str
        ``plot_x`` or ``plot_y``.

    Returns
    -------
    RegionDefinition
        Region with one axis expanded to data limits where applicable.
    """
    if not region.separable_for_profile:
        return region
    return region.expand_for_profile(frame, profile_axis)
