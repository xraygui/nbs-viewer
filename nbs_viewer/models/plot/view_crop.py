"""
Persistent spatial crop for the main 2D plot display.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .cube_view import CubeViewSpec, _fetch_plot_plane_storage_axes
from .plot_view_frame import PlotViewFrame
from .region import RectRegion, compile_covering_rect


@dataclass(frozen=True)
class ViewCrop:
    """
    Storage-index crop applied to the main 2D plot fetch path.

    Parameters
    ----------
    display_bbox : tuple of int
        Half-open bounding box on the oriented display plane used for ROI
        compilation and status readouts.
    storage_bbox : tuple of int
        Half-open bounding box on the raw storage plane, used to narrow the
        load before :func:`orient_for_display` reverses it.
    plot_y_axis : int
        Storage axis index mapped to plot Y.
    plot_x_axis : int
        Storage axis index mapped to plot X.
    source_key : tuple
        ``(xkey, ykey, run_uid)`` of the cropped dataset.
    spatial_fingerprint : tuple
        Hashable fingerprint of full-plane shape and axis assignment.
    full_frame : PlotViewFrame
        View frame of the oriented full plane before crop. Carries the
        storage-to-display reversal, which is why the crop no longer has to
        keep a copy of the two coordinate arrays to recover it.
    """

    display_bbox: Tuple[int, int, int, int]
    storage_bbox: Tuple[int, int, int, int]
    plot_y_axis: int
    plot_x_axis: int
    source_key: tuple
    spatial_fingerprint: tuple
    full_frame: PlotViewFrame


def spatial_fingerprint_from_frame(frame: PlotViewFrame) -> tuple:
    """
    Build a fingerprint for crop invalidation from a full 2D view frame.

    Parameters
    ----------
    frame : PlotViewFrame
        Full parent 2D view frame.

    Returns
    -------
    tuple
        Fingerprint of shape and plot-axis assignment.
    """
    return (
        frame.shape,
        frame.plot_x_dim,
        frame.plot_y_dim,
        tuple(frame.axis_names),
        frame.row_reversed,
        frame.col_reversed,
    )


def view_crop_from_region(
    region: RectRegion,
    full_frame: PlotViewFrame,
    parent_spec: CubeViewSpec,
    source_key: tuple,
) -> ViewCrop:
    """
    Commit a drawn rectangle to a persistent view crop.

    Cell-intersects selection is used here rather than the cell-center rule
    used for ROI reduction, so the cropped plane still covers what was drawn.

    Parameters
    ----------
    region : RectRegion
        ROI in matplotlib data coordinates on the oriented plot plane.
    full_frame : PlotViewFrame
        Oriented view frame before crop is applied.
    parent_spec : CubeViewSpec
        Parent cube view for plot-plane storage axis lookup.
    source_key : tuple
        ``(xkey, ykey, run_uid)`` of the active dataset.

    Returns
    -------
    ViewCrop
        Frozen crop state for the main display fetch path.

    Raises
    ------
    ValueError
        If the region does not select a non-empty crop area.
    """
    compiled = compile_covering_rect(full_frame, region)
    if compiled.pixel_count == 0:
        raise ValueError("Crop region does not cover any cells")
    display_bbox = compiled.bbox
    r0, r1, c0, c1 = display_bbox
    if r1 <= r0 or c1 <= c0:
        raise ValueError("Crop bounding box is empty")
    plot_y_axis, plot_x_axis = _fetch_plot_plane_storage_axes(
        parent_spec,
        full_frame,
        parent_spec,
    )
    return ViewCrop(
        display_bbox=display_bbox,
        storage_bbox=full_frame.storage_bbox(display_bbox),
        plot_y_axis=plot_y_axis,
        plot_x_axis=plot_x_axis,
        source_key=source_key,
        spatial_fingerprint=spatial_fingerprint_from_frame(full_frame),
        full_frame=full_frame,
    )


def crop_status_text(crop: ViewCrop) -> str:
    """
    Return a short status line describing an active crop.

    Parameters
    ----------
    crop : ViewCrop
        Active view crop.

    Returns
    -------
    str
        Human-readable crop bounds in data coordinates when available.
    """
    from .plot_view_frame import region_frame_for_bbox

    cropped = region_frame_for_bbox(crop.full_frame, crop.display_bbox)
    if cropped.extent is not None:
        left, right, bottom, top = cropped.extent
        return (
            f"Crop active: ({left:.2f}, {bottom:.2f}) — "
            f"({right:.2f}, {top:.2f})"
        )
    r0, r1, c0, c1 = crop.display_bbox
    return f"Crop active: rows {r0}–{r1}, cols {c0}–{c1}"
