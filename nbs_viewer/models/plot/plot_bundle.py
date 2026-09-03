"""
Request-to-bundle helpers: reduce, normalize, transform, and pack.

Orchestration lives on ``RunModel.get_plot_bundle``. These functions are
pure in the arrays they receive so they can be tested without a run.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple, Union

import numpy as np
from asteval import Interpreter

from .cube_view import DimRole, MaterializeRequest, materialize_view
from .plot_geometry import (
    prepare_1d_bundle,
    prepare_2d_bundle,
)
from .plot_request import PlotRequest

SliceItem = Union[int, slice]


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
        Array loaded with :meth:`ViewSpec.load_slice` (or the ROI-narrowed
        equivalent).
    axis_arrays : sequence of np.ndarray
        Per-storage-axis coordinate arrays.
    axis_names : sequence of str
        Name per storage axis.
    request : PlotRequest
        View, optional region, and mask mode.
    region_frame : PlotViewFrame, optional
        Parent 2-D frame required when ``request.region`` is set.
    plot_plane_storage_axes : tuple of int, optional
        Parent plot Y and plot X storage indices for ROI profiles.

    Returns
    -------
    tuple
        ``(y, axis_arrays, axis_names)`` on the plot plane.
    """
    materialize_request = MaterializeRequest(
        spec=request.view.to_cube_view_spec(),
        region=request.region,
        mask_mode=request.mask_mode,
    )
    return materialize_view(
        y,
        axis_arrays,
        axis_names,
        materialize_request,
        region_frame=region_frame,
        plot_plane_storage_axes=plot_plane_storage_axes,
    )


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
            y, coords, names, render_mode_hint=render_mode_hint
        )
    raise ValueError(f"Unsupported plot dimensionality: {y.ndim}")
