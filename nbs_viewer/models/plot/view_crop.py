"""
Persistent spatial crop for the main 2D plot display.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .cube_view import (
    CubeViewSpec,
    MaterializeRequest,
    SliceItem,
    _fetch_plot_plane_storage_axes,
    _narrow_fetch_slice,
)
from .plot_geometry import storage_bbox_from_display_bbox
from .plot_view_frame import PlotViewFrame, region_frame_for_bbox
from .region import RectRegion, compile_covering_rect, compile_with_mask_mode


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
        Half-open bounding box on the raw storage plane used for narrowed
        loads before :func:`prepare_2d_bundle` orientation.
    plot_y_axis : int
        Storage axis index mapped to plot Y.
    plot_x_axis : int
        Storage axis index mapped to plot X.
    source_key : tuple
        ``(xkey, ykey, run_uid)`` of the cropped dataset.
    spatial_fingerprint : tuple
        Hashable fingerprint of full-plane shape and axis assignment.
    full_frame : PlotViewFrame
        View frame of the oriented full plane before crop.
    row_axis : np.ndarray
        Storage row-center coordinates for the full plane.
    col_axis : np.ndarray
        Storage column-center coordinates for the full plane.
    """

    display_bbox: Tuple[int, int, int, int]
    storage_bbox: Tuple[int, int, int, int]
    plot_y_axis: int
    plot_x_axis: int
    source_key: tuple
    spatial_fingerprint: tuple
    full_frame: PlotViewFrame
    row_axis: np.ndarray
    col_axis: np.ndarray


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
    )


def apply_view_crop_to_slice_info(
    slice_info: Tuple[SliceItem, ...],
    crop: ViewCrop,
) -> Tuple[SliceItem, ...]:
    """
    Intersect plot-plane load slices with a view crop bounding box.

    Parameters
    ----------
    slice_info : tuple
        Per-storage-axis slice tuple from :meth:`CubeViewSpec.to_load_slice_info`.
    crop : ViewCrop
        Active crop with storage-index bounds.

    Returns
    -------
    tuple
        Narrowed slice tuple for chunked loading.
    """
    r0, r1, c0, c1 = crop.storage_bbox
    items = list(slice_info)
    items[crop.plot_y_axis] = _narrow_fetch_slice(
        items[crop.plot_y_axis],
        r0,
        r1,
        crop.full_frame.n_plot_y,
    )
    items[crop.plot_x_axis] = _narrow_fetch_slice(
        items[crop.plot_x_axis],
        c0,
        c1,
        crop.full_frame.n_plot_x,
    )
    return tuple(items)


def fetch_context_with_view_crop(
    request: MaterializeRequest,
    crop: ViewCrop,
    parent_spec: Optional[CubeViewSpec] = None,
) -> Tuple[Tuple[SliceItem, ...], PlotViewFrame]:
    """
    Build fetch slices for an ROI request when a persistent view crop is active.

    The ROI is compiled on the oriented full plane, then both the crop and ROI
    bounds are applied in storage-index space.

    Parameters
    ----------
    request : MaterializeRequest
        Derivative or masked fetch request including a region.
    crop : ViewCrop
        Active persistent view crop.
    parent_spec : CubeViewSpec, optional
        Parent cube view for plot-plane storage axis lookup.

    Returns
    -------
    tuple
        ``(slice_info, region_frame)`` for ``getData`` and materialization.

    Raises
    ------
    ValueError
        If the request has no region or the ROI does not intersect the crop.
    """
    if request.region is None:
        raise ValueError("fetch_context_with_view_crop requires request.region")

    region_frame = crop.full_frame
    compiled = compile_with_mask_mode(
        region_frame,
        request.region,
        request.mask_mode,
    )
    if compiled.pixel_count == 0:
        raise ValueError("ROI does not cover any cells")

    display_bbox = compiled.bbox
    r0, r1, c0, c1 = display_bbox
    if r1 <= r0 or c1 <= c0:
        raise ValueError("ROI bounding box is empty")

    storage_roi = storage_bbox_from_display_bbox(
        display_bbox,
        crop.row_axis,
        crop.col_axis,
        region_frame.shape,
    )
    plot_y_axis, plot_x_axis = _fetch_plot_plane_storage_axes(
        request.spec,
        region_frame,
        parent_spec,
    )
    base_slice = apply_view_crop_to_slice_info(
        request.spec.to_load_slice_info(),
        crop,
    )
    items = list(base_slice)
    items[plot_y_axis] = _narrow_fetch_slice(
        items[plot_y_axis],
        storage_roi[0],
        storage_roi[1],
        region_frame.n_plot_y,
    )
    items[plot_x_axis] = _narrow_fetch_slice(
        items[plot_x_axis],
        storage_roi[2],
        storage_roi[3],
        region_frame.n_plot_x,
    )
    materialize_frame = region_frame_for_bbox(region_frame, display_bbox)
    return tuple(items), materialize_frame


def view_crop_from_region(
    region: RectRegion,
    full_frame: PlotViewFrame,
    parent_spec: CubeViewSpec,
    source_key: tuple,
    row_axis: np.ndarray,
    col_axis: np.ndarray,
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
    row_axis : np.ndarray
        Storage row-center coordinates for the full plane.
    col_axis : np.ndarray
        Storage column-center coordinates for the full plane.

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
    storage_bbox = storage_bbox_from_display_bbox(
        display_bbox,
        row_axis,
        col_axis,
        full_frame.shape,
    )
    plot_y_axis, plot_x_axis = _fetch_plot_plane_storage_axes(
        parent_spec,
        full_frame,
        parent_spec,
    )
    return ViewCrop(
        display_bbox=display_bbox,
        storage_bbox=storage_bbox,
        plot_y_axis=plot_y_axis,
        plot_x_axis=plot_x_axis,
        source_key=source_key,
        spatial_fingerprint=spatial_fingerprint_from_frame(full_frame),
        full_frame=full_frame,
        row_axis=np.asarray(row_axis, dtype=float).copy(),
        col_axis=np.asarray(col_axis, dtype=float).copy(),
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
