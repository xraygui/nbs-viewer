"""
How a 2-D plane should be drawn, and where its coordinates put it.

Given a shape and its coordinate arrays, decide ``image`` or ``mesh``, build
the ``imshow`` extent or the ``pcolormesh`` grids, and say which axes must be
reversed for displayed coordinates to increase the way a reader expects.

Nothing here knows what a bundle is. These are the decisions a bundle
records, which is why ``RenderMode`` lives here with the function that
produces it rather than with the dataclass that carries one.

Pure numpy logic with no Qt or matplotlib dependencies.
"""

from __future__ import annotations

from typing import Literal, Optional, Sequence, Tuple

import numpy as np


RenderMode = Literal["line", "image", "mesh"]


def is_uniform_1d(
    coords: np.ndarray, rtol: float = 1e-5, atol: float = 0.0
) -> bool:
    """
    Return whether a 1D coordinate array has uniform spacing.

    Parameters
    ----------
    coords : np.ndarray
        Coordinate values.
    rtol : float
        Relative tolerance for comparing step sizes.
    atol : float
        Absolute tolerance for comparing step sizes.

    Returns
    -------
    bool
        True if spacing is uniform or the array has fewer than two points.
    """
    coords = np.asarray(coords).ravel()
    if coords.size < 2:
        return True
    diffs = np.diff(coords)
    if not np.all(np.isfinite(diffs)):
        return False
    return np.allclose(diffs, diffs[0], rtol=rtol, atol=atol)


def axis_length_matches(arr: np.ndarray, n: int) -> bool:
    """
    Return whether an axis array length matches data dimension size.

    Accepts center coordinates (length n) or edge coordinates (length n + 1).

    Parameters
    ----------
    arr : np.ndarray
        Axis coordinate array.
    n : int
        Expected data size along that dimension.

    Returns
    -------
    bool
        True if lengths are compatible.
    """
    length = np.asarray(arr).ravel().size
    return length == n or length == n + 1


def centers_to_edges(centers: np.ndarray) -> np.ndarray:
    """
    Convert 1D cell-center coordinates to edge coordinates.

    Parameters
    ----------
    centers : np.ndarray
        Cell-center coordinates.

    Returns
    -------
    np.ndarray
        Edge coordinates with length len(centers) + 1.
    """
    centers = np.asarray(centers, dtype=float).ravel()
    if centers.size == 0:
        return centers
    if centers.size == 1:
        half = 0.5
        return np.array([centers[0] - half, centers[0] + half])
    mid = (centers[:-1] + centers[1:]) / 2.0
    first = centers[0] - (mid[0] - centers[0])
    last = centers[-1] + (centers[-1] - mid[-1])
    return np.concatenate(([first], mid, [last]))


def display_flips(
    row_axis: np.ndarray,
    col_axis: np.ndarray,
    render_mode: RenderMode,
) -> Tuple[bool, bool]:
    """
    Decide which plot-plane axes reverse between storage and display order.

    ``imshow(origin="upper")`` places storage row 0 at the maximum y extent,
    so a row axis whose centers increase with storage index must be reversed
    for displayed coordinates to increase bottom-to-top. Columns are reversed
    in the mirror case. ``pcolormesh`` carries its own coordinate grids and is
    never reordered.

    Parameters
    ----------
    row_axis : np.ndarray
        Vertical axis center coordinates, one per storage row.
    col_axis : np.ndarray
        Horizontal axis center coordinates, one per storage column.
    render_mode : RenderMode
        Render mode of the plane.

    Returns
    -------
    tuple of bool
        ``(row_reversed, col_reversed)``.
    """
    if render_mode != "image":
        return False, False
    row = np.asarray(row_axis, dtype=float).ravel()
    col = np.asarray(col_axis, dtype=float).ravel()
    return (
        bool(row.size >= 2 and row[1] > row[0]),
        bool(col.size >= 2 and col[1] < col[0]),
    )


def extent_from_uniform_1d(
    x_coords: np.ndarray, y_coords: np.ndarray
) -> Tuple[float, float, float, float]:
    """
    Compute imshow extent from uniform 1D center coordinates.

    Parameters
    ----------
    x_coords : np.ndarray
        Horizontal axis centers.
    y_coords : np.ndarray
        Vertical axis centers.

    Returns
    -------
    tuple of float
        Extent as left, right, bottom, top with ``bottom < top``.
    """
    x_coords = np.asarray(x_coords, dtype=float).ravel()
    y_coords = np.asarray(y_coords, dtype=float).ravel()
    if x_coords.size >= 2:
        dx = abs(x_coords[1] - x_coords[0])
        x_lo = min(x_coords[0], x_coords[-1]) - dx / 2.0
        x_hi = max(x_coords[0], x_coords[-1]) + dx / 2.0
        left, right = x_lo, x_hi
    elif x_coords.size == 1:
        left = x_coords[0] - 0.5
        right = x_coords[0] + 0.5
    else:
        left, right = 0.0, 1.0

    if y_coords.size >= 2:
        dy = abs(y_coords[1] - y_coords[0])
        y_lo = min(y_coords[0], y_coords[-1]) - dy / 2.0
        y_hi = max(y_coords[0], y_coords[-1]) + dy / 2.0
        bottom, top = y_lo, y_hi
    elif y_coords.size == 1:
        bottom = y_coords[0] - 0.5
        top = y_coords[0] + 0.5
    else:
        bottom, top = 0.0, 1.0

    return (left, right, bottom, top)


def pixel_extent(ny: int, nx: int) -> Tuple[float, float, float, float]:
    """
    Compute imshow extent for pixel-index coordinates.

    Parameters
    ----------
    ny : int
        Number of rows.
    nx : int
        Number of columns.

    Returns
    -------
    tuple of float
        Extent as left, right, bottom, top.
    """
    return (-0.5, nx - 0.5, -0.5, ny - 0.5)


def _to_edge_coords(coords: np.ndarray, n: int) -> np.ndarray:
    """
    Return edge coordinates, converting centers when needed.

    Parameters
    ----------
    coords : np.ndarray
        Center or edge coordinates.
    n : int
        Number of data cells along the axis.

    Returns
    -------
    np.ndarray
        Edge coordinates.
    """
    coords = np.asarray(coords, dtype=float).ravel()
    if coords.size == n + 1:
        return coords
    if coords.size == n:
        return centers_to_edges(coords)
    return np.arange(n + 1, dtype=float)


def classify_render_mode(
    y_shape: Tuple[int, ...],
    x_axes: Sequence[np.ndarray],
    render_mode_hint: Optional[str] = None,
) -> RenderMode:
    """
    Classify how 2D data should be rendered.

    Parameters
    ----------
    y_shape : tuple of int
        Shape of the 2D y array.
    x_axes : sequence of np.ndarray
        Axis coordinate arrays after filtering empty dimensions.
    render_mode_hint : str, optional
        Explicit override from plot hints (``image`` or ``mesh``).

    Returns
    -------
    RenderMode
        ``image`` for uniform grids, ``mesh`` for non-uniform grids.
    """
    if render_mode_hint in ("image", "mesh"):
        return render_mode_hint

    if len(x_axes) < 2:
        return "image"

    for axis in x_axes:
        if np.asarray(axis).ndim == 2:
            return "mesh"

    row_axis = np.asarray(x_axes[-2]).ravel()
    col_axis = np.asarray(x_axes[-1]).ravel()
    ny, nx = y_shape[-2], y_shape[-1]

    if not axis_length_matches(row_axis, ny) or not axis_length_matches(col_axis, nx):
        return "mesh"

    if is_uniform_1d(row_axis) and is_uniform_1d(col_axis):
        return "image"

    return "mesh"


def build_mesh_grids(
    y: np.ndarray, x_axes: Sequence[np.ndarray]
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Build pcolormesh coordinate grids from axis data.

    Parameters
    ----------
    y : np.ndarray
        2D data array with shape (nrow, ncol).
    x_axes : sequence of np.ndarray
        Axis arrays for the last two dimensions.

    Returns
    -------
    tuple of np.ndarray
        Mesh X and Y arrays for pcolormesh.
    """
    ny, nx = y.shape
    if len(x_axes) >= 2:
        row_axis = np.asarray(x_axes[0])
        col_axis = np.asarray(x_axes[1])
        if row_axis.ndim == 2 and col_axis.ndim == 2:
            return col_axis, row_axis
        if row_axis.ndim == 2:
            col_1d = (
                col_axis.ravel()
                if col_axis.size > 0
                else np.arange(nx, dtype=float)
            )
            x_edges = _to_edge_coords(col_1d, nx)
            return row_axis, np.broadcast_to(
                x_edges.reshape(1, -1), row_axis.shape
            )
        if col_axis.ndim == 2:
            row_1d = (
                row_axis.ravel()
                if row_axis.size > 0
                else np.arange(ny, dtype=float)
            )
            y_edges = _to_edge_coords(row_1d, ny)
            return np.broadcast_to(y_edges.reshape(-1, 1), col_axis.shape), col_axis

        y_edges = _to_edge_coords(row_axis.ravel(), ny)
        x_edges = _to_edge_coords(col_axis.ravel(), nx)
    else:
        y_edges = np.arange(ny + 1, dtype=float)
        x_edges = np.arange(nx + 1, dtype=float)

    return np.meshgrid(x_edges, y_edges)
