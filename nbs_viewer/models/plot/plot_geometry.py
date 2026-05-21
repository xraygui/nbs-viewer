"""
Plot geometry preparation and 2D render-mode classification.

Pure numpy logic with no Qt or matplotlib dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, Tuple

import numpy as np

RenderMode = Literal["line", "image", "mesh"]


@dataclass
class PlotBundle:
    """
    Prepared plot payload for the view layer.

    Parameters
    ----------
    ndim : int
        Number of plot dimensions (1 or 2).
    y : np.ndarray
        Data array oriented for display (row = vertical, column = horizontal).
    render_mode : RenderMode
        How the view should render this data.
    axis_names : list of str
        Names for axis labels.
    x_line : np.ndarray or None
        X coordinates for 1D line plots.
    extent : tuple of float or None
        imshow extent as left, right, bottom, top.
    mesh_x : np.ndarray or None
        X coordinates for pcolormesh.
    mesh_y : np.ndarray or None
        Y coordinates for pcolormesh.
    """

    ndim: int
    y: np.ndarray
    render_mode: RenderMode
    axis_names: List[str]
    x_line: Optional[np.ndarray] = None
    extent: Optional[Tuple[float, float, float, float]] = None
    mesh_x: Optional[np.ndarray] = None
    mesh_y: Optional[np.ndarray] = None


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


def _extent_from_uniform_1d(
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
        Extent as left, right, bottom, top.
    """
    x_coords = np.asarray(x_coords, dtype=float).ravel()
    y_coords = np.asarray(y_coords, dtype=float).ravel()
    if x_coords.size >= 2:
        dx = x_coords[1] - x_coords[0]
        left = x_coords[0] - dx / 2.0
        right = x_coords[-1] + dx / 2.0
    elif x_coords.size == 1:
        left = x_coords[0] - 0.5
        right = x_coords[0] + 0.5
    else:
        left, right = 0.0, 1.0

    if y_coords.size >= 2:
        dy = y_coords[1] - y_coords[0]
        bottom = y_coords[0] - dy / 2.0
        top = y_coords[-1] + dy / 2.0
    elif y_coords.size == 1:
        bottom = y_coords[0] - 0.5
        top = y_coords[0] + 0.5
    else:
        bottom, top = 0.0, 1.0

    return (left, right, bottom, top)


def _pixel_extent(ny: int, nx: int) -> Tuple[float, float, float, float]:
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


def _build_mesh_grids(
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
        row_axis = np.asarray(x_axes[-2])
        col_axis = np.asarray(x_axes[-1])
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


def prepare_1d_bundle(
    y: np.ndarray,
    x_axes: Sequence[np.ndarray],
    axis_names: Sequence[str],
) -> PlotBundle:
    """
    Build a PlotBundle for 1D line data.

    Parameters
    ----------
    y : np.ndarray
        1D y values.
    x_axes : sequence of np.ndarray
        X axis arrays.
    axis_names : sequence of str
        Axis dimension names.

    Returns
    -------
    PlotBundle
        Prepared 1D bundle.
    """
    x_line = np.asarray(x_axes[0]).ravel() if x_axes else np.arange(y.size)
    names = list(axis_names) if axis_names else ["index"]
    return PlotBundle(
        ndim=1,
        y=np.asarray(y),
        render_mode="line",
        axis_names=names,
        x_line=x_line,
    )


def prepare_2d_bundle(
    y: np.ndarray,
    x_axes: Sequence[np.ndarray],
    axis_names: Sequence[str],
    render_mode_hint: Optional[str] = None,
) -> PlotBundle:
    """
    Build a PlotBundle for 2D data with auto-detected render mode.

    Data orientation: row index maps to the vertical axis, column index to
    the horizontal axis (consistent with matplotlib imshow).

    Parameters
    ----------
    y : np.ndarray
        2D data array from the data layer.
    x_axes : sequence of np.ndarray
        Axis coordinate arrays for non-sliced dimensions.
    axis_names : sequence of str
        Names for each axis dimension.
    render_mode_hint : str, optional
        Explicit render mode from plot hints.

    Returns
    -------
    PlotBundle
        Prepared 2D bundle with render mode and coordinates.
    """
    y = np.asarray(y)
    if y.ndim != 2:
        raise ValueError(f"prepare_2d_bundle expects 2D data, got shape {y.shape}")

    names = list(axis_names) if axis_names else []
    while len(names) < 2:
        names.append(f"dim_{len(names)}")

    render_mode = classify_render_mode(
        y.shape, x_axes, render_mode_hint=render_mode_hint
    )

    if render_mode == "image":
        ny, nx = y.shape
        if len(x_axes) >= 2:
            row_axis = np.asarray(x_axes[-2]).ravel()
            col_axis = np.asarray(x_axes[-1]).ravel()
            if row_axis.size > 1 and col_axis.size > 1:
                extent = _extent_from_uniform_1d(col_axis, row_axis)
            else:
                extent = _pixel_extent(ny, nx)
        else:
            extent = _pixel_extent(ny, nx)

        return PlotBundle(
            ndim=2,
            y=y,
            render_mode="image",
            axis_names=names[-2:],
            extent=extent,
        )

    y_mesh = y.T
    if len(x_axes) >= 2:
        mesh_axes = [x_axes[-1], x_axes[-2]]
    else:
        mesh_axes = list(x_axes)
    mesh_x, mesh_y = _build_mesh_grids(y_mesh, mesh_axes)
    return PlotBundle(
        ndim=2,
        y=y_mesh,
        render_mode="mesh",
        axis_names=names[-2:],
        mesh_x=mesh_x,
        mesh_y=mesh_y,
    )


def get_render_mode_hint(plot_hints: dict, ykey: str) -> Optional[str]:
    """
    Read an explicit render_mode override from Bluesky plot hints.

    Parameters
    ----------
    plot_hints : dict
        Plot hints dictionary from run metadata.
    ykey : str
        Y data key to match.

    Returns
    -------
    str or None
        ``image``, ``mesh``, or None if no override.
    """
    for field_list in plot_hints.values():
        if not isinstance(field_list, list):
            continue
        for field in field_list:
            if not isinstance(field, dict):
                continue
            signal = field.get("signal")
            if isinstance(signal, list):
                signal = signal[-1] if signal else None
            if signal == ykey:
                mode = field.get("render_mode")
                if mode in ("image", "mesh"):
                    return mode
    return None
