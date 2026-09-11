"""Build display-ordered 2D planes the way the fetch path does.

``prepare_2d_bundle`` packs a plane; it does not reorder one. Orientation is
a separate step -- ``build_plot_bundle`` turns the finished plane the right
way up at the pack -- so a test that wants a frame matching what the user sees
has to run it too.
"""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from nbs_viewer.models.plot.plot_geometry import (
    PlotBundle,
    display_flips,
    prepare_2d_bundle,
)
from nbs_viewer.models.plot.plot_view_frame import PlotViewFrame, frame_from_bundle


def orient_block(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    reversed_axes: Sequence[int],
    storage_to_tensor: dict | None = None,
) -> Tuple[np.ndarray, list]:
    """
    Reverse a loaded block along the given axes, coordinates with it.

    The production path does this with one ``isel`` per flipped dimension on a
    labelled array, where the coordinate follows the data because they are the
    same object -- and where an axis the load indexed away simply is not among
    its dimensions. A test that builds a block by hand has plain numpy, so it
    flips the two in step and says which array axis each storage axis became.

    Parameters
    ----------
    y : np.ndarray
        Loaded block.
    axis_arrays : sequence of np.ndarray
        Coordinate array per *storage* axis.
    reversed_axes : sequence of int
        Storage axes whose order must reverse.
    storage_to_tensor : dict, optional
        Array axis per storage axis. Identity when omitted, which is right
        for a load that kept every axis.

    Returns
    -------
    tuple
        ``(y, axis_arrays)`` in display order.
    """
    arrays = [np.asarray(axis) for axis in axis_arrays]
    for storage_axis in reversed_axes:
        tensor_axis = (
            storage_axis
            if storage_to_tensor is None
            else storage_to_tensor.get(storage_axis)
        )
        if tensor_axis is None:
            continue
        y = np.flip(y, axis=tensor_axis)
        arrays[storage_axis] = arrays[storage_axis][::-1]
    return y, arrays


def oriented_plane(
    y: np.ndarray,
    row_axis: np.ndarray,
    col_axis: np.ndarray,
    render_mode: str = "image",
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[bool, bool]]:
    """
    Reverse a storage plane into display order.

    Returns
    -------
    tuple
        ``(y, row_axis, col_axis, (row_reversed, col_reversed))``.
    """
    row_reversed, col_reversed = display_flips(row_axis, col_axis, render_mode)
    y, (row_axis, col_axis) = orient_block(
        y,
        [row_axis, col_axis],
        [axis for axis, flip in enumerate((row_reversed, col_reversed)) if flip],
    )
    return y, row_axis, col_axis, (row_reversed, col_reversed)


def display_bundle(
    y: np.ndarray,
    row_axis: np.ndarray,
    col_axis: np.ndarray,
    axis_names: Sequence[str] = ("dim_0", "dim_1"),
    render_mode: str = "image",
) -> PlotBundle:
    """
    Orient a storage plane and pack it into a bundle.
    """
    y, row_axis, col_axis, (row_reversed, col_reversed) = oriented_plane(
        y, row_axis, col_axis, render_mode
    )
    return prepare_2d_bundle(
        y,
        [row_axis, col_axis],
        list(axis_names),
        render_mode_hint=render_mode,
        row_reversed=row_reversed,
        col_reversed=col_reversed,
    )


def display_frame(
    y: np.ndarray,
    row_axis: np.ndarray,
    col_axis: np.ndarray,
    axis_names: Sequence[str] = ("dim_0", "dim_1"),
    render_mode: str = "image",
) -> PlotViewFrame:
    """
    Orient a storage plane and return the frame the user would draw on.
    """
    return frame_from_bundle(
        display_bundle(y, row_axis, col_axis, axis_names, render_mode)
    )


def roi_profile_from_block(
    y,
    axis_arrays,
    axis_names,
    request,
    plan,
):
    """
    Reduce an oriented block to an ROI profile, with no transform.

    What ``RunFetch.get_plot_bundle`` runs between the load and the pack for
    a request that carries a region. The production path calls the two halves
    itself so it can transform in between; with an empty transform the
    composition ``materialize_view`` performs is the same answer, so a test
    about fetch geometry can use it directly.

    Parameters
    ----------
    y : np.ndarray
        Loaded, oriented block.
    axis_arrays : sequence of np.ndarray
        Per-storage-axis coordinate arrays.
    axis_names : sequence of str
        Name per storage axis.
    request : PlotRequest
        ROI profile request.
    plan : FetchPlan
        Plan the block was loaded with.

    Returns
    -------
    tuple
        ``(profile, coords, names)``.
    """
    import xarray as xr

    from nbs_viewer.models.plot.plot_axes import PlotAxes
    from nbs_viewer.models.plot.plot_bundle import materialize_view

    axis_names = list(axis_names)
    # The block is what the plan loaded, so an axis the slice indexed away is
    # not one of its dimensions -- the same rule ``RunFetch._read_block``
    # applies. ``axis_names`` and ``axis_arrays`` stay per *storage* axis.
    surviving = [
        axis
        for axis, item in enumerate(plan.slice_info)
        if not isinstance(item, (int, np.integer))
    ]
    data = xr.DataArray(
        np.asarray(y),
        dims=[axis_names[axis] for axis in surviving],
        coords={
            axis_names[axis]: np.asarray(axis_arrays[axis])
            for axis in surviving
        },
    )
    axes = PlotAxes.of(
        request.view,
        axis_names,
        plane=(
            None
            if plan.plane_axes is None
            else (
                axis_names[plan.plane_axes[0]],
                axis_names[plan.plane_axes[1]],
            )
        ),
    ).to_profile(request.profile_axis, request.spatial_reduce)
    profile = materialize_view(
        data,
        axes,
        region=request.region,
        mask_mode=request.mask_mode,
        region_frame=plan.region_frame,
    )
    dim = profile.dims[0]
    return (
        profile.values,
        [np.asarray(profile.coords[dim].values)],
        [str(dim)],
    )


def labelled_block(y, axis_arrays, axis_names):
    """
    Build the labelled array the load boundary produces.

    ``RunFetch._read_block`` names the loaded array's dimensions and attaches
    the coordinates it read, and everything downstream addresses it by name. A
    test that builds a block by hand has to do the same, so it is doing it
    once here rather than in every test body.

    Parameters
    ----------
    y : np.ndarray
        Loaded, oriented block.
    axis_arrays : sequence of np.ndarray
        Coordinate array per axis.
    axis_names : sequence of str
        Name per axis.

    Returns
    -------
    xarray.DataArray
        Labelled block.
    """
    import xarray as xr

    names = list(axis_names)
    return xr.DataArray(
        np.asarray(y),
        dims=names,
        coords={
            name: np.asarray(array)
            for name, array in zip(names, axis_arrays)
        },
    )


def profile_axes(
    parent,
    axis_names,
    profile_storage_axis,
    spatial_reduce="sum",
    plane_axes=None,
):
    """
    Name a parent view and derive the ROI profile view from it.

    Parameters
    ----------
    parent : Projection
        Parent 2-D view.
    axis_names : sequence of str
        Name per storage axis.
    profile_storage_axis : int
        Storage axis the profile runs along.
    spatial_reduce : str, optional
        ``sum`` or ``mean`` within the ROI.
    plane_axes : tuple of int, optional
        Parent plot plane storage axes, when it is not the parent's own.

    Returns
    -------
    PlotAxes
        Named profile view.
    """
    from nbs_viewer.models.plot.plot_axes import PlotAxes

    names = list(axis_names)
    plane = (
        None
        if plane_axes is None
        else (names[plane_axes[0]], names[plane_axes[1]])
    )
    return PlotAxes.of(parent, names, plane=plane).to_profile(
        profile_storage_axis, spatial_reduce
    )
