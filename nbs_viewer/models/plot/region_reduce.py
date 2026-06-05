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


