"""
Request-to-bundle helpers: reduce, normalize, transform, and pack.

Orchestration lives on ``RunSource.get_plot_bundle``. These functions are
pure in the arrays they receive so they can be tested without a run.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple, Union

import numpy as np
from asteval import Interpreter

from .cube_view import (
    CubeViewSpec,
    DimRole,
    MaterializeRequest,
    materialize_view,
    profile_view_spec,
)
from .plot_geometry import (
    PlotBundle,
    prepare_1d_bundle,
    prepare_2d_bundle,
)
from .plot_request import PlotRequest
from .plot_view_frame import frame_from_bundle

SliceItem = Union[int, slice]


def _materialize_request(request: PlotRequest) -> MaterializeRequest:
    """
    Build the reduce spec for a request.

    Without a region the view *is* the output. With one, the view is the
    parent plane and the output is the profile it reduces to, so the profile
    axis and the spatial reduce are folded into a 1-D spec here -- at the
    reduce, not in the request, which keeps the plane's identity intact for
    the fetch and the mask.

    Parameters
    ----------
    request : PlotRequest
        View, optional region, profile axis, and spatial reduce.

    Returns
    -------
    MaterializeRequest
        Spec plus ROI parameters for :func:`materialize_view`.
    """
    spec = request.view.to_cube_view_spec()
    if request.region is not None:
        spec = profile_view_spec(
            spec, request.profile_axis, request.spatial_reduce
        )
    return MaterializeRequest(
        spec=spec,
        region=request.region,
        mask_mode=request.mask_mode,
    )


def reduce_to_plot_plane(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    axis_names: Sequence[str],
    request: PlotRequest,
    *,
    region_frame=None,
    plot_plane_storage_axes: Optional[Tuple[int, int]] = None,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Reduce non-plot axes and orient the array to plot-axis order.

    This is ``materialize_view`` with the view and region taken from
    ``request``. INDEX axes are assumed already applied in the load slice.

    Parameters
    ----------
    y : np.ndarray
        Array loaded with the slices from ``plan_fetch``, already reversed
        into display order along the plot-plane axes.
    axis_arrays : sequence of np.ndarray
        Per-storage-axis coordinate arrays.
    axis_names : sequence of str
        Name per storage axis.
    request : PlotRequest
        View, optional region, mask mode, profile axis, and spatial reduce.
    region_frame : PlotViewFrame, optional
        Frame of the loaded block, required when ``request.region`` is set.
    plot_plane_storage_axes : tuple of int, optional
        Plot Y and plot X storage indices of the parent plane.

    Returns
    -------
    tuple
        ``(y, axis_arrays, axis_names)`` on the plot plane.
    """
    return materialize_view(
        y,
        axis_arrays,
        axis_names,
        _materialize_request(request),
        region_frame=region_frame,
        plot_plane_storage_axes=plot_plane_storage_axes,
    )


def _plane_axis_arrays(
    plane: PlotBundle, frame
) -> Tuple[List[np.ndarray], List[str]]:
    """
    Build per-axis coordinate arrays for an already-displayed 2-D plane.

    Parameters
    ----------
    plane : PlotBundle
        Displayed 2-D bundle.
    frame : PlotViewFrame
        Its view frame.

    Returns
    -------
    tuple
        ``(axis_arrays, axis_names)`` indexed by the frame's plot dims.
    """
    names = list(plane.axis_names)
    while len(names) < 2:
        names.append(f"dim_{len(names)}")
    ny, nx = frame.shape
    row_axis = np.arange(ny, dtype=float)
    col_axis = np.arange(nx, dtype=float)
    if frame.render_mode == "mesh" and plane.mesh_x is not None:
        mesh_x = np.asarray(plane.mesh_x, dtype=float)
        mesh_y = np.asarray(plane.mesh_y, dtype=float)
        if mesh_x.shape == (ny, nx):
            row_axis = np.nanmean(mesh_y, axis=1)
            col_axis = np.nanmean(mesh_x, axis=0)
    axis_arrays = [None, None]
    axis_arrays[frame.plot_y_dim] = row_axis
    axis_arrays[frame.plot_x_dim] = col_axis
    axis_names = [None, None]
    axis_names[frame.plot_y_dim] = names[0]
    axis_names[frame.plot_x_dim] = names[1]
    return axis_arrays, axis_names


def reduce_cached_plane(
    plane: PlotBundle,
    request: PlotRequest,
    *,
    label: str = "",
) -> PlotBundle:
    """
    Reduce an already-loaded display plane to an ROI profile.

    The one genuine optimisation in the fetch path: when the profile runs
    along an axis the plane already shows, the answer is in memory and no
    database read is needed. The plane is display-ordered, so the mask
    compiled on its frame applies directly.

    Parameters
    ----------
    plane : PlotBundle
        Cached 2-D bundle for ``request.view``'s plot plane.
    request : PlotRequest
        Profile request whose ``profile_axis`` lies on that plane.
    label : str
        Optional display label for the profile.

    Returns
    -------
    PlotBundle
        1-D profile payload.

    Raises
    ------
    ValueError
        If the plane is not 2-D, the profile axis is off it, or the ROI
        reduces to nothing.
    """
    if plane.ndim != 2:
        raise ValueError("cached_plane must be a 2-D bundle")
    plane_axes = request.plane_axes
    if plane_axes is None or request.profile_axis not in plane_axes:
        raise ValueError("cached_plane cannot serve an off-plane profile")

    frame = frame_from_bundle(plane)
    bundle_profile_axis = 0 if request.profile_axis == plane_axes[0] else 1
    plane_view = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    materialize_request = MaterializeRequest(
        spec=profile_view_spec(
            plane_view, bundle_profile_axis, request.spatial_reduce
        ),
        region=request.region,
        mask_mode=request.mask_mode,
    )
    axis_arrays, axis_names = _plane_axis_arrays(plane, frame)
    y, coords, names = materialize_view(
        plane.y,
        axis_arrays,
        axis_names,
        materialize_request,
        region_frame=frame,
        plot_plane_storage_axes=(frame.plot_y_dim, frame.plot_x_dim),
    )
    if not np.isfinite(y).any():
        raise ValueError("ROI profile is empty after reduction")
    return prepare_1d_bundle(y, coords, [label or names[0]])


def slice_info_for_key(
    slice_info: Tuple[SliceItem, ...],
    y_dim_names: Sequence[str],
    key_dim_names: Sequence[str],
) -> Tuple[SliceItem, ...]:
    """
    Map a y-key load slice onto another key by dimension name.

    Parameters
    ----------
    slice_info : tuple
        Load slice aligned with ``y_dim_names``.
    y_dim_names : sequence of str
        Storage dimension names of the y key.
    key_dim_names : sequence of str
        Storage dimension names of the other key.

    Returns
    -------
    tuple
        Load slice of length ``len(key_dim_names)``.
    """
    y_names = list(y_dim_names)
    items: List[SliceItem] = []
    for name in key_dim_names:
        if name in y_names:
            items.append(slice_info[y_names.index(name)])
        else:
            items.append(slice(None))
    return tuple(items)


def _roles_for_key(
    y_dim_names: Sequence[str],
    y_roles: Sequence[DimRole],
    key_dim_names: Sequence[str],
) -> List[Optional[DimRole]]:
    y_names = list(y_dim_names)
    if key_dim_names and all(name in y_names for name in key_dim_names):
        return [y_roles[y_names.index(name)] for name in key_dim_names]
    return [
        y_roles[i] if i < len(y_roles) else None
        for i in range(len(key_dim_names))
    ]


def reduce_loaded_array(
    arr: np.ndarray,
    key_dim_names: Sequence[str],
    y_dim_names: Sequence[str],
    y_roles: Sequence[DimRole],
) -> Tuple[np.ndarray, List[str]]:
    """
    Reduce a loaded array using the y view's roles on matching dimensions.

    INDEX roles are assumed already applied at load, so those axes are not
    present in ``arr`` and are skipped here. SUM / MEAN collapse matching
    remaining axes. Plot axes are kept.

    Parameters
    ----------
    arr : np.ndarray
        Array loaded with a name-aligned slice.
    key_dim_names : sequence of str
        Full storage names of ``arr`` before INDEX dropping.
    y_dim_names : sequence of str
        Full storage names of the y key.
    y_roles : sequence of DimRole
        Role per y storage axis.

    Returns
    -------
    tuple
        ``(reduced_array, surviving_axis_names)``.
    """
    roles = _roles_for_key(y_dim_names, y_roles, key_dim_names)
    surviving_roles: List[Optional[DimRole]] = []
    surviving_names: List[str] = []
    for name, role in zip(key_dim_names, roles):
        if role == DimRole.INDEX:
            continue
        surviving_roles.append(role)
        surviving_names.append(name)

    out = np.asarray(arr)
    n_keep = len(surviving_roles)
    if n_keep == 0:
        return np.asarray(out, dtype=float), []
    if out.ndim != n_keep:
        raise ValueError(
            f"loaded array rank {out.ndim} does not match "
            f"{n_keep} non-INDEX axes {surviving_names}"
        )
    for axis in range(n_keep - 1, -1, -1):
        role = surviving_roles[axis]
        if role == DimRole.SUM:
            out = np.sum(out, axis=axis)
            del surviving_names[axis]
        elif role == DimRole.MEAN:
            out = np.mean(out, axis=axis)
            del surviving_names[axis]
    return np.asarray(out, dtype=float), surviving_names


def _aligned_norm(
    arr: np.ndarray,
    arr_names: Sequence[str],
    y: np.ndarray,
    y_names: Sequence[str],
) -> np.ndarray:
    """
    Broadcast a reduced norm array onto ``y`` using axis names.
    """
    arr = np.asarray(arr, dtype=float)
    if arr.ndim == 0:
        return arr
    if arr.shape == y.shape:
        return arr
    y_name_list = list(y_names)[: y.ndim]
    names = list(arr_names)[: arr.ndim]
    present = [name for name in y_name_list if name in names]
    if len(present) != arr.ndim:
        raise ValueError(
            f"cannot broadcast norm axes {names} onto plot axes {y_name_list}"
        )
    perm = [names.index(name) for name in present]
    if perm != list(range(arr.ndim)):
        arr = np.transpose(arr, perm)
    out = arr
    for i, name in enumerate(y_name_list):
        if name not in names:
            out = np.expand_dims(out, axis=i)
    return out


def apply_normalization(
    y: np.ndarray,
    y_axis_names: Sequence[str],
    norms: Sequence[Tuple[np.ndarray, Sequence[str]]],
) -> np.ndarray:
    """
    Divide ``y`` by the product of reduced normalization arrays.

    Each norm is already reduced according to *its* dimensions. Remaining
    axes are aligned to ``y`` by name, then by equal shape.

    Parameters
    ----------
    y : np.ndarray
        Plot-plane y array.
    y_axis_names : sequence of str
        Names of the plot-plane axes of ``y``.
    norms : sequence of tuple
        ``(array, axis_names)`` for each reduced normalization key.

    Returns
    -------
    np.ndarray
        Normalized y array.
    """
    out = np.asarray(y, dtype=float)
    for arr, names in norms:
        aligned = _aligned_norm(arr, names, out, y_axis_names)
        out = out / aligned
    return out


def apply_transform(
    xlist: Sequence[np.ndarray],
    y: np.ndarray,
    transform_text: str,
) -> Tuple[List[np.ndarray], np.ndarray]:
    """
    Apply a user expression to ``y`` (and optionally ``x``).

    The interpreter is created per call. An empty string is a no-op.

    Parameters
    ----------
    xlist : sequence of np.ndarray
        Plot-plane coordinate arrays.
    y : np.ndarray
        Plot-plane data.
    transform_text : str
        Expression. ``x`` and ``y`` are injected into the symbol table.

    Returns
    -------
    tuple
        ``(xlist, y)`` after the expression, or the inputs when empty.
    """
    coords = [np.asarray(axis) for axis in xlist]
    if not transform_text:
        return coords, y
    interp = Interpreter()
    interp.symtable["y"] = y
    interp.symtable["x"] = coords
    result = interp(transform_text)
    if result is not None:
        y = result
    else:
        y = interp.symtable.get("y", y)
    return coords, y


def build_plot_bundle(
    y: np.ndarray,
    coords: Sequence[np.ndarray],
    names: Sequence[str],
    request: PlotRequest,
    *,
    render_mode_hint: Optional[str] = None,
    label: str = "",
    row_reversed: bool = False,
    col_reversed: bool = False,
):
    """
    Pack plot-plane arrays into a :class:`PlotBundle`.

    Parameters
    ----------
    y : np.ndarray
        Plot-plane data.
    coords : sequence of np.ndarray
        Plot-plane coordinate arrays.
    names : sequence of str
        Plot-plane axis names.
    request : PlotRequest
        Used to detect ROI profile output.
    render_mode_hint : str, optional
        Explicit ``image`` / ``mesh`` hint for 2-D data.
    label : str, optional
        Display name for a 1-D ROI profile.
    row_reversed : bool
        Whether the caller reversed the plot Y axis to reach display order.
    col_reversed : bool
        Whether the caller reversed the plot X axis.

    Returns
    -------
    PlotBundle
        Prepared payload for the view layer.

    Raises
    ------
    ValueError
        If ``y`` is missing, an ROI profile is empty, or ``y.ndim`` is not
        1 or 2.
    """
    if request.region is not None:
        if not np.isfinite(y).any():
            raise ValueError("ROI profile is empty after reduction")
        display_label = label or (names[0] if names else "profile")
        return prepare_1d_bundle(y, coords, [display_label])
    if y is None:
        raise ValueError(f"Plot data for {request.ykey!r} is missing")
    if y.ndim == 1:
        return prepare_1d_bundle(y, coords, names)
    if y.ndim == 2:
        return prepare_2d_bundle(
            y,
            coords,
            names,
            render_mode_hint=render_mode_hint,
            row_reversed=row_reversed,
            col_reversed=col_reversed,
        )
    raise ValueError(f"Unsupported plot dimensionality: {y.ndim}")
