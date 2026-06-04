"""
Map matplotlib data-coordinate regions to boolean cell masks.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from .plot_view_frame import PlotViewFrame


def _data_limits(frame: PlotViewFrame) -> Tuple[float, float, float, float]:
    """
    Return axis data limits as x_lo, x_hi, y_lo, y_hi.
    """
    if frame.render_mode == "image":
        if frame.extent is None:
            ny, nx = frame.shape
            return (-0.5, nx - 0.5, -0.5, ny - 0.5)
        left, right, bottom, top = frame.extent
        return (float(left), float(right), float(bottom), float(top))

    mesh_x = frame.mesh_x
    mesh_y = frame.mesh_y
    if mesh_x is None or mesh_y is None:
        raise ValueError("Mesh frame requires mesh_x and mesh_y")
    return (
        float(np.nanmin(mesh_x)),
        float(np.nanmax(mesh_x)),
        float(np.nanmin(mesh_y)),
        float(np.nanmax(mesh_y)),
    )


def _normalize_rect(
    x0: float, x1: float, y0: float, y1: float
) -> Tuple[float, float, float, float]:
    """
    Return rectangle bounds with x0 <= x1 and y0 <= y1.
    """
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    return x0, x1, y0, y1


def _intervals_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    """
    Return whether two closed intervals overlap.
    """
    return a0 <= b1 and b0 <= a1


def _image_cell_bounds(
    frame: PlotViewFrame, row: int, col: int
) -> Tuple[float, float, float, float]:
    """
    Return x_lo, x_hi, y_lo, y_hi for an image cell at storage (row, col).
    """
    left, right, bottom, top = _data_limits(frame)
    ny, nx = frame.shape
    dx = (right - left) / nx if nx else 1.0
    dy = (top - bottom) / ny if ny else 1.0
    x_lo = left + col * dx
    x_hi = left + (col + 1) * dx
    y_lo = bottom + row * dy
    y_hi = bottom + (row + 1) * dy
    return x_lo, x_hi, y_lo, y_hi


def _mesh_cell_bounds(
    frame: PlotViewFrame, row: int, col: int
) -> Tuple[float, float, float, float]:
    """
    Return x_lo, x_hi, y_lo, y_hi for a mesh cell at storage (row, col).
    """
    mesh_x = frame.mesh_x
    mesh_y = frame.mesh_y
    ny, nx = frame.shape
    corners_x = [mesh_x[row, col]]
    corners_y = [mesh_y[row, col]]
    if row + 1 < ny:
        corners_x.append(mesh_x[row + 1, col])
        corners_y.append(mesh_y[row + 1, col])
    if col + 1 < nx:
        corners_x.append(mesh_x[row, col + 1])
        corners_y.append(mesh_y[row, col + 1])
    if row + 1 < ny and col + 1 < nx:
        corners_x.append(mesh_x[row + 1, col + 1])
        corners_y.append(mesh_y[row + 1, col + 1])
    return (
        float(np.nanmin(corners_x)),
        float(np.nanmax(corners_x)),
        float(np.nanmin(corners_y)),
        float(np.nanmax(corners_y)),
    )


def _storage_indices_for_plot_axis(
    frame: PlotViewFrame, axis: str, index: int
) -> Tuple[int, int]:
    """
    Return storage (row, col) indices for a cell index along plot X or Y.
    """
    if axis == "plot_x":
        if frame.plot_x_dim == 0:
            return index, 0
        return 0, index
    if axis == "plot_y":
        if frame.plot_y_dim == 0:
            return index, 0
        return 0, index
    raise ValueError(f"Unknown axis {axis!r}")


def _cell_x_bounds_mesh(
    frame: PlotViewFrame, index: int, along: int
) -> Tuple[float, float]:
    """
    Return horizontal data bounds for a cell along plot X.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame.
    index : int
        Cell index along plot X.
    along : int
        Reference index along plot Y for mesh cells.

    Returns
    -------
    tuple of float
        ``(x_lo, x_hi)``.
    """
    row, col = _storage_indices_for_plot_axis(frame, "plot_x", index)
    if frame.plot_y_dim == 0:
        row = along
    else:
        col = along
    x_lo, x_hi, _, _ = (
        _image_cell_bounds(frame, row, col)
        if frame.render_mode == "image"
        else _mesh_cell_bounds(frame, row, col)
    )
    return x_lo, x_hi


def _cell_y_bounds_mesh(
    frame: PlotViewFrame, index: int, along: int
) -> Tuple[float, float]:
    """
    Return vertical data bounds for a cell along plot Y.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame.
    index : int
        Cell index along plot Y.
    along : int
        Reference index along plot X for mesh cells.

    Returns
    -------
    tuple of float
        ``(y_lo, y_hi)``.
    """
    row, col = _storage_indices_for_plot_axis(frame, "plot_y", index)
    if frame.plot_x_dim == 0:
        col = along
    else:
        row = along
    _, _, y_lo, y_hi = (
        _image_cell_bounds(frame, row, col)
        if frame.render_mode == "image"
        else _mesh_cell_bounds(frame, row, col)
    )
    return y_lo, y_hi


def _mask_from_data_rect_image(
    frame: PlotViewFrame,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> np.ndarray:
    """
    Build a rectangular mask on a uniform ``image`` grid using index bounds.
    """
    left, right, bottom, top = _data_limits(frame)
    ny, nx = frame.shape
    dx = (right - left) / nx if nx else 1.0
    dy = (top - bottom) / ny if ny else 1.0
    col0 = int(np.floor((x0 - left) / dx)) if dx else 0
    col1 = int(np.ceil((x1 - left) / dx)) if dx else nx
    row0 = int(np.floor((y0 - bottom) / dy)) if dy else 0
    row1 = int(np.ceil((y1 - bottom) / dy)) if dy else ny
    col0 = max(0, min(col0, nx))
    col1 = max(0, min(col1, nx))
    row0 = max(0, min(row0, ny))
    row1 = max(0, min(row1, ny))
    mask = np.zeros((ny, nx), dtype=bool)
    if row1 > row0 and col1 > col0:
        mask[row0:row1, col0:col1] = True
    return mask


def _mesh_separable_edge_grids(
    frame: PlotViewFrame,
) -> Tuple[np.ndarray, np.ndarray] | None:
    """
    Return 1D X and Y edge arrays when the mesh is a separable grid.
    """
    mesh_x = frame.mesh_x
    mesh_y = frame.mesh_y
    if mesh_x is None or mesh_y is None:
        return None
    ny, nx = frame.shape
    if mesh_x.shape != mesh_y.shape:
        return None
    if mesh_x.shape == (ny + 1, nx + 1):
        x_edges = np.asarray(mesh_x[0, :], dtype=float)
        y_edges = np.asarray(mesh_y[:, 0], dtype=float)
        if not (
            np.allclose(mesh_x, mesh_x[0:1, :], equal_nan=True)
            and np.allclose(mesh_y, mesh_y[:, 0:1], equal_nan=True)
        ):
            return None
        return x_edges, y_edges
    if mesh_x.shape != (ny, nx):
        return None
    if not (
        np.allclose(mesh_x, mesh_x[0:1, :], equal_nan=True)
        and np.allclose(mesh_y, mesh_y[:, 0:1], equal_nan=True)
    ):
        return None
    x_edges = np.asarray(mesh_x[0, :], dtype=float)
    y_edges = np.asarray(mesh_y[:, 0], dtype=float)
    return x_edges, y_edges


def _mask_from_data_rect_mesh_separable(
    frame: PlotViewFrame,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> np.ndarray | None:
    """
    Vectorized rectangular mask for separable ``pcolormesh`` edge grids.
    """
    edges = _mesh_separable_edge_grids(frame)
    if edges is None:
        return None
    x_edges, y_edges = edges
    ny, nx = frame.shape
    if x_edges.size == nx + 1 and y_edges.size == ny + 1:
        x_lo = x_edges[:-1]
        x_hi = x_edges[1:]
        y_lo = y_edges[:-1]
        y_hi = y_edges[1:]
    elif x_edges.size == nx and y_edges.size == ny:
        x_lo = x_hi = x_edges
        y_lo = y_hi = y_edges
    else:
        return None
    return (
        (x_lo[None, :] <= x1)
        & (x_hi[None, :] >= x0)
        & (y_lo[:, None] <= y1)
        & (y_hi[:, None] >= y0)
    )


def _mask_from_data_rect_mesh_bbox(
    frame: PlotViewFrame,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> np.ndarray:
    """
    Build a mesh mask by scanning only a row/column bounding box.
    """
    mesh_x = frame.mesh_x
    mesh_y = frame.mesh_y
    ny, nx = frame.shape
    row_hit = (np.nanmax(mesh_y, axis=1) >= y0) & (np.nanmin(mesh_y, axis=1) <= y1)
    col_hit = (np.nanmax(mesh_x, axis=0) >= x0) & (np.nanmin(mesh_x, axis=0) <= x1)
    rows = np.flatnonzero(row_hit)
    cols = np.flatnonzero(col_hit)
    mask = np.zeros((ny, nx), dtype=bool)
    if rows.size == 0 or cols.size == 0:
        return mask
    for row in rows:
        for col in cols:
            cx0, cx1, cy0, cy1 = _mesh_cell_bounds(frame, int(row), int(col))
            if _intervals_overlap(x0, x1, cx0, cx1) and _intervals_overlap(
                y0, y1, cy0, cy1
            ):
                mask[row, col] = True
    return mask


def mask_from_data_rect(
    frame: PlotViewFrame,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> np.ndarray:
    """
    Build a boolean mask for cells intersecting a data-coordinate rectangle.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the displayed plane.
    x0, x1 : float
        Horizontal data limits.
    y0, y1 : float
        Vertical data limits.

    Returns
    -------
    np.ndarray
        Boolean mask with shape ``frame.shape``.
    """
    x0, x1, y0, y1 = _normalize_rect(x0, x1, y0, y1)
    if frame.render_mode == "image":
        return _mask_from_data_rect_image(frame, x0, x1, y0, y1)
    fast = _mask_from_data_rect_mesh_separable(frame, x0, x1, y0, y1)
    if fast is not None:
        return fast
    return _mask_from_data_rect_mesh_bbox(frame, x0, x1, y0, y1)


def mask_from_axis_slice(
    frame: PlotViewFrame,
    axis: str,
    v0: float,
    v1: float,
) -> np.ndarray:
    """
    Build a mask selecting cells overlapping a band along plot X or plot Y.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame.
    axis : str
        ``plot_x`` or ``plot_y``.
    v0, v1 : float
        Data-coordinate limits along that axis.

    Returns
    -------
    np.ndarray
        Boolean mask with shape ``frame.shape``.
    """
    if v0 > v1:
        v0, v1 = v1, v0
    ny, nx = frame.shape
    mask = np.zeros((ny, nx), dtype=bool)
    get_bounds = (
        _image_cell_bounds
        if frame.render_mode == "image"
        else _mesh_cell_bounds
    )
    for row in range(ny):
        for col in range(nx):
            cx0, cx1, cy0, cy1 = get_bounds(frame, row, col)
            if axis == "plot_x":
                overlap = _intervals_overlap(v0, v1, cx0, cx1)
            elif axis == "plot_y":
                overlap = _intervals_overlap(v0, v1, cy0, cy1)
            else:
                raise ValueError(f"Unknown axis {axis!r}")
            if overlap:
                mask[row, col] = True
    return mask
