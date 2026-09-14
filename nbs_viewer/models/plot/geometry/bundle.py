"""
The payload the view layer draws, and how a finished array is packed into one.

A :class:`PlotBundle` is the end of the model side: an array already in
display order, the coordinates that put it on screen, and a record of which
axes were reversed to get there. Packing one is where display order begins --
everything upstream works in the order the source stored the data.

The decisions this file records are made next door in :mod:`orientation`.

Pure numpy logic with no Qt or matplotlib dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    List,
    Optional,
    Sequence,
    Tuple,
)

import numpy as np

from .orientation import (
    RenderMode,
    build_mesh_grids,
    extent_from_uniform_1d,
    pixel_extent,
    classify_render_mode,
    display_flips,
)

if TYPE_CHECKING:  # pragma: no cover - annotation only
    import xarray as xr

    from ..plot_request import PlotRequest


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
    row_reversed : bool
        Whether display row order is the reverse of storage order along the
        plot Y axis. Recorded so a display bounding box can be mapped back to
        storage indices without re-deriving it from coordinate arrays, which
        is impossible once ``extent`` has been normalised to ``bottom < top``.
    col_reversed : bool
        Same for the plot X axis.
    """

    ndim: int
    y: np.ndarray
    render_mode: RenderMode
    axis_names: List[str]
    x_line: Optional[np.ndarray] = None
    extent: Optional[Tuple[float, float, float, float]] = None
    mesh_x: Optional[np.ndarray] = None
    mesh_y: Optional[np.ndarray] = None
    row_reversed: bool = False
    col_reversed: bool = False


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
    *,
    row_reversed: bool = False,
    col_reversed: bool = False,
) -> PlotBundle:
    """
    Pack an already display-ordered 2D plane into a PlotBundle.

    Data orientation: row index maps to the vertical axis, column index to
    the horizontal axis (consistent with matplotlib imshow). This holds for
    both render modes. Which storage dimension ends up on which screen axis
    is decided upstream by the view spec's plot-axis roles, and the
    storage-to-display reversal is applied upstream too, by
    :func:`orient_for_display` immediately after the load; the renderer must
    not reorder anything again.

    Parameters
    ----------
    y : np.ndarray
        2D data array, in display order.
    x_axes : sequence of np.ndarray
        Axis coordinate arrays for non-sliced dimensions, in display order.
    axis_names : sequence of str
        Names for each axis dimension.
    render_mode_hint : str, optional
        Explicit render mode from plot hints.
    row_reversed : bool
        Whether the caller reversed the row axis to reach display order.
        Recorded on the bundle; it does not change what is packed here.
    col_reversed : bool
        Same for the column axis.

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
                extent = extent_from_uniform_1d(col_axis, row_axis)
            else:
                extent = pixel_extent(ny, nx)
        else:
            extent = pixel_extent(ny, nx)

        return PlotBundle(
            ndim=2,
            y=y,
            render_mode="image",
            axis_names=names[-2:],
            extent=extent,
            row_reversed=row_reversed,
            col_reversed=col_reversed,
        )

    mesh_axes = [np.asarray(axis) for axis in x_axes[-2:]]
    mesh_x, mesh_y = build_mesh_grids(y, mesh_axes)
    return PlotBundle(
        ndim=2,
        y=y,
        render_mode="mesh",
        axis_names=names[-2:],
        mesh_x=mesh_x,
        mesh_y=mesh_y,
        row_reversed=row_reversed,
        col_reversed=col_reversed,
    )


def build_plot_bundle(
    data: "xr.DataArray",
    request: "PlotRequest",
    *,
    render_mode_hint: Optional[str] = None,
    label: str = "",
):
    """
    Pack a finished labelled array into a :class:`PlotBundle`.

    **This is where display order begins.** Everything upstream works in the
    order the source stored the data; the reversal that puts a plane the right
    way up for ``imshow`` happens here, once, on a finished 2-D plane.

    It used to happen immediately after the load, on the whole N-D block,
    which meant a normalization array sharing a plot-plane axis had to be
    reversed to match, the block cache had to mirror its windows, and the
    render mode had to be classified before the reduce so the flip could be
    decided. None of that was about the data; it was about a matplotlib
    convention -- ``origin="upper"`` puts storage row 0 at the top -- reaching
    five stages back into the pipeline.

    The array's trailing dimensions are the plot axes and carry their own
    coordinates, so names and coordinate arrays are read off it rather than
    passed alongside.

    Parameters
    ----------
    data : xarray.DataArray
        Reduced, transformed array in plot order and source orientation.
    request : PlotRequest
        Used to detect ROI profile output.
    render_mode_hint : str, optional
        Declared ``image`` / ``mesh`` override for the key.
    label : str, optional
        Display name for a 1-D ROI profile.

    Returns
    -------
    PlotBundle
        Prepared payload for the view layer, in display order.

    Raises
    ------
    ValueError
        If an ROI profile is empty, or the output is neither 1-D nor 2-D.
    """
    y = np.asarray(data.values)
    names = [str(dim) for dim in (data.dims[-2:] if y.ndim >= 2 else data.dims)]
    coords = [
        np.asarray(data.coords[dim].values)
        if dim in data.coords
        else np.arange(data.sizes[dim], dtype=float)
        for dim in names
    ]
    if request.region is not None:
        if not np.isfinite(y).any():
            raise ValueError("ROI profile is empty after reduction")
        display_label = label or (names[0] if names else "profile")
        return prepare_1d_bundle(y, coords, [display_label])
    if y.ndim == 1:
        return prepare_1d_bundle(y, coords, names)
    if y.ndim == 2:
        # Classified before the flip, which is safe: uniformity is a property
        # of the coordinate differences, and reversing an array does not
        # change whether its steps are equal.
        render_mode = classify_render_mode(
            y.shape, coords, render_mode_hint=render_mode_hint
        )
        row_reversed, col_reversed = display_flips(
            coords[0], coords[1], render_mode
        )
        if row_reversed:
            y = np.flip(y, axis=0)
            coords[0] = coords[0][::-1]
        if col_reversed:
            y = np.flip(y, axis=1)
            coords[1] = coords[1][::-1]
        return prepare_2d_bundle(
            y,
            coords,
            names,
            render_mode_hint=render_mode,
            row_reversed=row_reversed,
            col_reversed=col_reversed,
        )
    raise ValueError(f"Unsupported plot dimensionality: {y.ndim}")
