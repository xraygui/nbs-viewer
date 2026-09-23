"""
Map matplotlib data-coordinate regions to boolean cell masks.

Two selection rules live here. ROI reduction uses cell-center-inside, so a
cell contributes only when its center lies within the shape. View cropping
uses cell-intersects, so the extracted plane still covers the drawn
rectangle.

Where a cell *is* belongs to the frame, not to this module: the bounds come
from :mod:`frame`, and what is rasterized here is a shape against
them.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from .frame import PlotViewFrame


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


def cell_centers(frame: PlotViewFrame) -> Tuple[np.ndarray, np.ndarray]:
    """
    Return data-coordinate centers for every cell in a view frame.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the displayed plane.

    Returns
    -------
    tuple of np.ndarray
        ``(centers_x, centers_y)``, both with shape ``frame.shape``.

    Raises
    ------
    ValueError
        If a mesh frame is missing coordinates or its grids do not match the
        cell shape.
    """
    ny, nx = frame.shape
    if frame.render_mode == "image":
        left, right, bottom, top = frame.data_limits()
        dx = (right - left) / nx if nx else 1.0
        dy = (top - bottom) / ny if ny else 1.0
        centers_x = left + (np.arange(nx, dtype=float) + 0.5) * dx
        centers_y = top - (np.arange(ny, dtype=float) + 0.5) * dy
        return (
            np.broadcast_to(centers_x[None, :], (ny, nx)).copy(),
            np.broadcast_to(centers_y[:, None], (ny, nx)).copy()
)

    mesh_x = frame.mesh_x
    mesh_y = frame.mesh_y
    if mesh_x is None or mesh_y is None:
        raise ValueError("Mesh frame requires mesh_x and mesh_y")
    mesh_x = np.asarray(mesh_x, dtype=float)
    mesh_y = np.asarray(mesh_y, dtype=float)
    if mesh_x.shape == (ny + 1, nx + 1) and mesh_y.shape == (ny + 1, nx + 1):
        centers_x = 0.25 * (
            mesh_x[:-1, :-1] + mesh_x[1:, :-1] + mesh_x[:-1, 1:] + mesh_x[1:, 1:]
        )
        centers_y = 0.25 * (
            mesh_y[:-1, :-1] + mesh_y[1:, :-1] + mesh_y[:-1, 1:] + mesh_y[1:, 1:]
        )
        return centers_x, centers_y
    if mesh_x.shape == (ny, nx) and mesh_y.shape == (ny, nx):
        return mesh_x.copy(), mesh_y.copy()
    raise ValueError(
        f"Mesh grid shape {mesh_x.shape} does not match cell shape {frame.shape}"
    )


def mask_from_data_rect(
    frame: PlotViewFrame,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> np.ndarray:
    """
    Build a boolean mask for cells whose centers fall inside a rectangle.

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
    centers_x, centers_y = cell_centers(frame)
    return (
        (centers_x >= x0)
        & (centers_x <= x1)
        & (centers_y >= y0)
        & (centers_y <= y1)
    )


def mask_from_ellipse(
    frame: PlotViewFrame,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    angle: float = 0.0,
) -> np.ndarray:
    """
    Build a boolean mask for cells whose centers fall inside an ellipse.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the displayed plane.
    cx, cy : float
        Ellipse center in data coordinates.
    rx, ry : float
        Semi-axis lengths along the ellipse's local X and Y.
    angle : float, optional
        Rotation of the local X axis in degrees, counter-clockwise.

    Returns
    -------
    np.ndarray
        Boolean mask with shape ``frame.shape``.
    """
    rx = abs(float(rx))
    ry = abs(float(ry))
    if rx == 0.0 or ry == 0.0:
        return np.zeros(frame.shape, dtype=bool)
    centers_x, centers_y = cell_centers(frame)
    theta = np.deg2rad(float(angle))
    cos_t = np.cos(theta)
    sin_t = np.sin(theta)
    dx = centers_x - float(cx)
    dy = centers_y - float(cy)
    local_x = dx * cos_t + dy * sin_t
    local_y = -dx * sin_t + dy * cos_t
    return (local_x / rx) ** 2 + (local_y / ry) ** 2 <= 1.0


def mask_from_vertices(
    frame: PlotViewFrame,
    vertices,
) -> np.ndarray:
    """
    Build a boolean mask for cells whose centers fall inside a polygon.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the displayed plane.
    vertices : array-like
        Sequence of ``(x, y)`` data coordinates describing a closed path.

    Returns
    -------
    np.ndarray
        Boolean mask with shape ``frame.shape``.

    Raises
    ------
    ValueError
        If fewer than three vertices are supplied.
    """
    from matplotlib.path import Path

    verts = np.asarray(vertices, dtype=float)
    if verts.ndim != 2 or verts.shape[1] != 2 or verts.shape[0] < 3:
        raise ValueError("A polygon mask needs at least three (x, y) vertices")
    centers_x, centers_y = cell_centers(frame)
    points = np.column_stack((centers_x.ravel(), centers_y.ravel()))
    inside = Path(verts).contains_points(points)
    return inside.reshape(frame.shape)


def cell_mask_at_point(
    frame: PlotViewFrame,
    x: float,
    y: float,
) -> np.ndarray:
    """
    Build a single-cell mask for the cell center nearest a data point.

    Used as the sub-cell fallback: a shape smaller than one cell selects no
    centers, so the cell holding its centroid is selected instead.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame for the displayed plane.
    x, y : float
        Data coordinates of the point.

    Returns
    -------
    np.ndarray
        Boolean mask with at most one selected cell.
    """
    mask = np.zeros(frame.shape, dtype=bool)
    if not (np.isfinite(x) and np.isfinite(y)):
        return mask
    x_lo, x_hi, y_lo, y_hi = frame.data_limits()
    if not (x_lo <= x <= x_hi and y_lo <= y <= y_hi):
        return mask
    centers_x, centers_y = cell_centers(frame)
    x_span = (x_hi - x_lo) or 1.0
    y_span = (y_hi - y_lo) or 1.0
    distance = ((centers_x - x) / x_span) ** 2 + ((centers_y - y) / y_span) ** 2
    if not np.isfinite(distance).any():
        return mask
    mask[np.unravel_index(np.nanargmin(distance), frame.shape)] = True
    return mask


def _mask_covering_rect_image(
    frame: PlotViewFrame,
    x0: float,
    x1: float,
    y0: float,
    y1: float
) -> np.ndarray:
    """
    Build a rectangular mask on a uniform ``image`` grid using index bounds.
    """
    left, right, bottom, top = frame.data_limits()
    ny, nx = frame.shape
    dx = (right - left) / nx if nx else 1.0
    dy = (top - bottom) / ny if ny else 1.0
    col0 = int(np.floor((x0 - left) / dx)) if dx else 0
    col1 = int(np.ceil((x1 - left) / dx)) if dx else nx
    row0 = int(np.floor((top - y1) / dy)) if dy else 0
    row1 = int(np.ceil((top - y0) / dy)) if dy else ny
    col0 = max(0, min(col0, nx))
    col1 = max(0, min(col1, nx))
    row0 = max(0, min(row0, ny))
    row1 = max(0, min(row1, ny))
    mask = np.zeros((ny, nx), dtype=bool)
    if row1 > row0 and col1 > col0:
        mask[row0:row1, col0:col1] = True
    return mask


def _mask_covering_rect_mesh_separable(
    frame: PlotViewFrame,
    x0: float,
    x1: float,
    y0: float,
    y1: float
) -> np.ndarray | None:
    """
    Vectorized rectangular mask for separable ``pcolormesh`` edge grids.
    """
    edges = frame.mesh_separable_edge_grids()
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


def _mask_covering_rect_mesh_bbox(
    frame: PlotViewFrame,
    x0: float,
    x1: float,
    y0: float,
    y1: float
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
            cx0, cx1, cy0, cy1 = frame.mesh_cell_bounds(int(row), int(col))
            if _intervals_overlap(x0, x1, cx0, cx1) and _intervals_overlap(
                y0, y1, cy0, cy1
            ):
                mask[row, col] = True
    return mask


def mask_covering_data_rect(
    frame: PlotViewFrame,
    x0: float,
    x1: float,
    y0: float,
    y1: float
) -> np.ndarray:
    """
    Build a boolean mask for cells intersecting a data-coordinate rectangle.

    This is the viewport rule used by :class:`~..plane.roles.ViewCrop`: every cell the
    rectangle touches is kept, so the cropped plane covers what was drawn.
    ROI reduction uses :func:`mask_from_data_rect` instead, which tests cell
    centers so edge cells are not partially counted.

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
        return _mask_covering_rect_image(frame, x0, x1, y0, y1)
    fast = _mask_covering_rect_mesh_separable(frame, x0, x1, y0, y1)
    if fast is not None:
        return fast
    return _mask_covering_rect_mesh_bbox(frame, x0, x1, y0, y1)


def mask_from_axis_slice(
    frame: PlotViewFrame,
    axis: str,
    v0: float,
    v1: float,
) -> np.ndarray:
    """
    Build a mask selecting cells whose centers fall inside an axis band.

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
    centers_x, centers_y = cell_centers(frame)
    if axis == "plot_x":
        coords = centers_x
    elif axis == "plot_y":
        coords = centers_y
    else:
        raise ValueError(f"Unknown axis {axis!r}")
    return (coords >= v0) & (coords <= v1)
