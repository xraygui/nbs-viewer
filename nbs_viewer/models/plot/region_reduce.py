"""
Reduce masked 2D planes and build axis profiles for Workflow A.
"""

from __future__ import annotations

from typing import Literal, Tuple

import numpy as np

from .plot_view_frame import PlotViewFrame
from .region import CompiledRegion

ReduceOp = Literal["sum", "mean"]
ProfileAxis = Literal["plot_x", "plot_y"]


def reduce_masked_plane(
    y: np.ndarray,
    compiled: CompiledRegion,
    op: ReduceOp,
) -> float:
    """
    Reduce all masked values in a 2D array to a scalar.

    Parameters
    ----------
    y : np.ndarray
        Data array matching ``compiled.mask`` shape.
    compiled : CompiledRegion
        Compiled region mask.
    op : str
        ``sum`` or ``mean``.

    Returns
    -------
    float
        Reduced value, or NaN if the mask is empty.
    """
    values = y[compiled.mask]
    if values.size == 0:
        return float("nan")
    if op == "sum":
        return float(np.nansum(values))
    if op == "mean":
        return float(np.nanmean(values))
    raise ValueError(f"Unknown reduce op {op!r}")


def _profile_axis_index(frame: PlotViewFrame, profile_axis: ProfileAxis) -> int:
    """
    Return the storage axis index for a profile axis name.
    """
    if profile_axis == "plot_x":
        return frame.plot_x_dim
    if profile_axis == "plot_y":
        return frame.plot_y_dim
    raise ValueError(f"Unknown profile axis {profile_axis!r}")


def _profile_coords(
    frame: PlotViewFrame, profile_axis: ProfileAxis, n_profile: int
) -> np.ndarray:
    """
    Return profile bin-center coordinates along one plot axis.
    """
    if frame.render_mode == "mesh":
        from .region_mesh import _mesh_separable_edge_grids

        edges = _mesh_separable_edge_grids(frame)
        if edges is not None:
            x_edges, y_edges = edges
            axis_edges = x_edges if profile_axis == "plot_x" else y_edges
            if axis_edges.size == n_profile + 1:
                return 0.5 * (axis_edges[:-1] + axis_edges[1:])
            if axis_edges.size == n_profile:
                return np.asarray(axis_edges, dtype=float)
    return np.array(
        [
            _coord_for_profile_index(frame, profile_axis, k)
            for k in range(n_profile)
        ],
        dtype=float,
    )


def _coord_for_profile_index(
    frame: PlotViewFrame, profile_axis: ProfileAxis, index: int
) -> float:
    """
    Return a representative data coordinate for a profile bin.
    """
    if frame.render_mode == "image" and frame.extent is not None:
        left, right, bottom, top = frame.extent
        if profile_axis == "plot_x":
            nx = frame.shape[1]
            dx = (right - left) / nx if nx else 1.0
            return float(left + (index + 0.5) * dx)
        ny = frame.shape[0]
        dy = (top - bottom) / ny if ny else 1.0
        return float(top - (index + 0.5) * dy)

    if frame.render_mode == "mesh":
        from .region_mesh import _cell_x_bounds_mesh, _cell_y_bounds_mesh

        if profile_axis == "plot_x":
            x0, x1 = _cell_x_bounds_mesh(frame, index, 0)
            return 0.5 * (x0 + x1)
        y0, y1 = _cell_y_bounds_mesh(frame, index, 0)
        return 0.5 * (y0 + y1)

    if profile_axis == "plot_x":
        return float(index)
    return float(index)


def apply_region_profile(
    y: np.ndarray,
    frame: PlotViewFrame,
    compiled: CompiledRegion,
    profile_axis: ProfileAxis,
    op: ReduceOp,
) -> Tuple[np.ndarray, np.ndarray, str]:
    """
    Reduce masked data along one plot axis, producing a 1D profile.

    Parameters
    ----------
    y : np.ndarray
        Display-oriented 2D data matching ``frame.shape``.
    frame : PlotViewFrame
        View frame for coordinate metadata.
    compiled : CompiledRegion
        Compiled region mask.
    profile_axis : str
        ``plot_x`` or ``plot_y`` — axis along which profile coordinates run.
    op : str
        ``sum`` or ``mean``.

    Returns
    -------
    tuple
        ``(profile, coords, axis_name)`` where ``profile`` is 1D, ``coords``
        are bin-center data coordinates, and ``axis_name`` labels the profile.
    """
    y = np.asarray(y, dtype=float)
    mask = compiled.mask
    profile_dim = _profile_axis_index(frame, profile_axis)
    reduce_dim = 1 - profile_dim
    n_profile = frame.shape[profile_dim]
    profile = np.full(n_profile, np.nan, dtype=float)

    if profile_dim == 0:
        for i in range(n_profile):
            row_mask = mask[i, :]
            if row_mask.any():
                row_vals = y[i, row_mask]
                profile[i] = (
                    np.nansum(row_vals) if op == "sum" else np.nanmean(row_vals)
                )
    else:
        for j in range(n_profile):
            col_mask = mask[:, j]
            if col_mask.any():
                col_vals = y[col_mask, j]
                profile[j] = (
                    np.nansum(col_vals) if op == "sum" else np.nanmean(col_vals)
                )

    coords = _profile_coords(frame, profile_axis, n_profile)
    if profile_axis == "plot_x":
        name = frame.plot_x_name
    else:
        name = frame.plot_y_name
    return profile, coords, name
