"""
Request-to-bundle helpers: reduce, normalize, transform, and pack.

Orchestration lives on ``RunSource.get_plot_bundle``. These functions are
pure in the arrays they receive so they can be tested without a run.
"""

from __future__ import annotations

from typing import List, Literal, Optional, Sequence, Tuple, Union

import numpy as np
from asteval import Interpreter

from .plot_geometry import PlotBundle, prepare_1d_bundle
from .plot_request import PlotRequest
from .plot_view_frame import PlotViewFrame, frame_from_bundle
from .region import RegionDefinition, compile_with_mask_mode
from .view_spec import (
    DimRole,
    PlotAxisName,
    SpatialReduce,
    Projection,
    profile_storage_axis,
    profile_view_spec,
    storage_axis_to_plot_axis,
)

SliceItem = Union[int, slice]
MaskMode = Literal["inside", "outside"]



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
    plane_view = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    axis_arrays, axis_names = _plane_axis_arrays(plane, frame)
    y, coords, names = materialize_view(
        plane.y,
        axis_arrays,
        axis_names,
        profile_view_spec(
            plane_view, bundle_profile_axis, request.spatial_reduce
        ),
        region=request.region,
        mask_mode=request.mask_mode,
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


def _spatial_reduce_storage_axes(
    spec: Projection,
    plot_plane_storage_axes: Optional[Tuple[int, int]],
) -> frozenset[int]:
    """
    Return storage axes reduced within the ROI on the parent plot plane.
    """
    if spec.plot_ndim != 1:
        return frozenset()
    profile_axis = profile_storage_axis(spec)
    if plot_plane_storage_axes is not None:
        return frozenset(
            storage_axis
            for storage_axis in plot_plane_storage_axes
            if spec.roles[storage_axis] in (DimRole.SUM, DimRole.MEAN)
        )
    order = spec.axis_order
    if len(order) < 2:
        return frozenset()
    plot_plane = {order[-2], order[-1]}
    return frozenset(
        storage_axis
        for storage_axis in plot_plane
        if storage_axis != profile_axis
        and spec.roles[storage_axis] in (DimRole.SUM, DimRole.MEAN)
    )


def _global_reduce_storage_axes(
    spec: Projection,
    spatial_storage_axes: frozenset[int],
) -> frozenset[int]:
    """
    Return SUM/MEAN storage axes reduced before ROI masking.
    """
    return frozenset(
        storage_axis
        for storage_axis, role in enumerate(spec.roles)
        if role in (DimRole.SUM, DimRole.MEAN)
        and storage_axis not in spatial_storage_axes
    )


def _profile_coords(
    frame: PlotViewFrame, profile_axis: PlotAxisName, n_profile: int
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
    frame: PlotViewFrame, profile_axis: PlotAxisName, index: int
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


def _reduce_axis_index(
    remaining: Sequence[int],
    storage_axis: int,
) -> int:
    """
    Return the tensor axis index for a storage dimension.
    """
    return list(remaining).index(storage_axis)


def _materialize_without_region(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    axis_names: Sequence[str],
    spec: Projection,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Apply a projection without ROI masking.
    """
    remaining = [i for i in range(spec.ndim) if spec.roles[i] != DimRole.INDEX]
    arrays = [np.asarray(axis_arrays[i]) for i in remaining]
    names = [axis_names[i] for i in remaining]
    roles = [spec.roles[i] for i in remaining]

    for j in range(len(remaining) - 1, -1, -1):
        role = roles[j]
        if role == DimRole.SUM:
            y = np.sum(y, axis=j)
            del arrays[j], names[j], roles[j], remaining[j]
        elif role == DimRole.MEAN:
            y = np.mean(y, axis=j)
            del arrays[j], names[j], roles[j], remaining[j]

    non_plot = [
        j for j, role in enumerate(roles) if role not in (DimRole.PLOT_X, DimRole.PLOT_Y)
    ]
    y_positions = [j for j, role in enumerate(roles) if role == DimRole.PLOT_Y]
    x_positions = [j for j, role in enumerate(roles) if role == DimRole.PLOT_X]

    if spec.plot_ndim == 1:
        perm = non_plot + x_positions
    else:
        perm = non_plot + y_positions + x_positions

    if len(perm) != y.ndim:
        raise ValueError(
            f"transpose rank {len(perm)} does not match data ndim {y.ndim}"
        )

    if perm != list(range(y.ndim)):
        y = np.transpose(y, perm)
        arrays = [arrays[p] for p in perm]
        names = [names[p] for p in perm]

    if spec.plot_ndim == 1:
        arrays = arrays[-1:]
        names = names[-1:]
    elif spec.plot_ndim == 2:
        arrays = arrays[-2:]
        names = names[-2:]

    return y, arrays, names


def _reduce_along_axis(y: np.ndarray, axis: int, role: DimRole) -> np.ndarray:
    """
    Collapse one tensor axis using the spec role semantics.
    """
    if role == DimRole.SUM:
        return np.sum(y, axis=axis)
    if role == DimRole.MEAN:
        return np.mean(y, axis=axis)
    raise ValueError(f"cannot reduce axis with role {role!r}")


def _masked_reduce_along_axes(
    y: np.ndarray,
    axes: Tuple[int, ...],
    role: DimRole,
) -> np.ndarray:
    """
    Collapse tensor axes after ROI masking with NaN-aware reducers.
    """
    if role == DimRole.SUM:
        profile = np.nansum(y, axis=axes)
    elif role == DimRole.MEAN:
        profile = np.nanmean(y, axis=axes)
    else:
        raise ValueError(f"unexpected spatial reduce role {role!r}")
    empty_bins = np.isnan(y).all(axis=axes)
    return np.where(empty_bins, np.nan, profile)


def reduce_before_mask(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    spec: Projection,
    *,
    plot_plane_storage_axes: Optional[Tuple[int, int]] = None,
) -> Tuple[np.ndarray, List[np.ndarray], List[int]]:
    """
    Collapse every axis the ROI mask does not span.

    The first half of an ROI reduction. What survives is the finished plot
    plane -- or, when the profile runs along an axis the plane does not show,
    the stack of planes it runs over. Separating it from the masking half is
    what lets the transform run in between, on exactly the values the user
    sees on the image before an ROI is drawn on them.

    Parameters
    ----------
    y : np.ndarray
        Loaded, oriented, normalized block.
    axis_arrays : sequence of np.ndarray
        Per-storage-axis coordinate arrays.
    spec : Projection
        1-D profile output spec, from :func:`profile_view_spec`.
    plot_plane_storage_axes : tuple of int, optional
        Parent plot Y and plot X storage axes.

    Returns
    -------
    tuple
        ``(y, arrays, remaining)``. ``remaining`` names the storage axis
        behind each tensor axis of ``y``, and ``arrays`` its coordinates.

    Raises
    ------
    ValueError
        If ``spec`` is not a profile spec or spans no spatial reduce axis.
    """
    if spec.plot_ndim != 1:
        raise ValueError("ROI profile materialization requires plot_ndim=1")

    spatial_storage_axes = _spatial_reduce_storage_axes(
        spec, plot_plane_storage_axes
    )
    if not spatial_storage_axes:
        raise ValueError("expected at least one spatial reduce axis")
    global_storage_axes = _global_reduce_storage_axes(
        spec, spatial_storage_axes
    )

    remaining = [i for i in range(spec.ndim) if spec.roles[i] != DimRole.INDEX]
    arrays = [np.asarray(axis_arrays[i]) for i in remaining]
    roles = [spec.roles[i] for i in remaining]

    for j in range(len(remaining) - 1, -1, -1):
        if remaining[j] in global_storage_axes:
            y = _reduce_along_axis(y, j, roles[j])
            del arrays[j], roles[j], remaining[j]

    return y, arrays, remaining


def mask_to_profile(
    y: np.ndarray,
    arrays: Sequence[np.ndarray],
    remaining: Sequence[int],
    axis_names: Sequence[str],
    spec: Projection,
    region: RegionDefinition,
    mask_mode: MaskMode,
    region_frame: PlotViewFrame,
    *,
    plot_plane_storage_axes: Optional[Tuple[int, int]] = None,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Mask a finished plot plane, or stack of them, down to a 1-D profile.

    The second half of an ROI reduction, run on values the transform has
    already been applied to: an ROI is drawn on what is displayed, so summing
    it must sum what is displayed.

    Parameters
    ----------
    y : np.ndarray
        Output of :func:`reduce_before_mask`, transformed.
    arrays : sequence of np.ndarray
        Coordinate array per surviving tensor axis.
    remaining : sequence of int
        Storage axis behind each tensor axis of ``y``.
    axis_names : sequence of str
        Full per-storage-axis names of the y key.
    spec : Projection
        1-D profile output spec.
    region : RegionDefinition
        ROI in data coordinates on the plot plane.
    mask_mode : str
        ``inside`` or ``outside`` the ROI.
    region_frame : PlotViewFrame
        Display frame of the block the plane axes actually hold.
    plot_plane_storage_axes : tuple of int, optional
        Parent plot Y and plot X storage axes.

    Returns
    -------
    tuple
        ``(profile, [coords], [axis_name])``.

    Raises
    ------
    ValueError
        If the plane is missing from ``y``, its shape disagrees with
        ``region_frame``, or the ROI covers no cells.
    """
    profile_axis_idx = profile_storage_axis(spec)
    remaining = list(remaining)
    arrays = list(arrays)

    if y.ndim < 2:
        raise ValueError(
            f"expected at least 2D plot plane before ROI reduction, got {y.shape}"
        )

    # The ROI plane is wherever its two storage axes landed, which is not
    # always the trailing pair: profiling along a slider axis of a cube
    # leaves the plane at the *leading* axes, because ``remaining`` is in
    # ascending storage order and the slider axis can outrank both plane
    # axes. Locate the plane instead of assuming it.
    plane_storage = (
        plot_plane_storage_axes
        if plot_plane_storage_axes is not None
        else (region_frame.plot_y_dim, region_frame.plot_x_dim)
    )
    try:
        plane_tensor = tuple(
            _reduce_axis_index(remaining, storage_axis)
            for storage_axis in plane_storage
        )
    except ValueError:
        raise ValueError(
            f"plot plane axes {plane_storage} are not present in the "
            f"fetched array for spec {spec}"
        ) from None
    plane_shape = tuple(y.shape[axis] for axis in plane_tensor)
    if plane_shape != region_frame.shape:
        raise ValueError(
            f"plot plane shape {plane_shape} does not match region frame "
            f"{region_frame.shape}"
        )

    compiled = compile_with_mask_mode(
        region_frame,
        region,
        mask_mode,
    )
    if compiled.pixel_count == 0:
        raise ValueError("ROI does not cover any cells")

    y = np.asarray(y, dtype=float)
    # ``plane_tensor`` is (display row, display column). When storage order
    # disagrees with display order the mask is transposed to match rather
    # than reshaped blindly -- the axes it broadcasts over are named, never
    # inferred from position.
    plane_mask = compiled.mask
    if plane_tensor[0] > plane_tensor[1]:
        plane_mask = plane_mask.T
        mask_axes = (plane_tensor[1], plane_tensor[0])
    else:
        mask_axes = plane_tensor
    mask_shape = [1] * y.ndim
    mask_shape[mask_axes[0]] = plane_mask.shape[0]
    mask_shape[mask_axes[1]] = plane_mask.shape[1]
    mask = plane_mask.reshape(mask_shape)
    y = np.where(mask, y, np.nan)

    spatial_storage_axes = _spatial_reduce_storage_axes(
        spec, plot_plane_storage_axes
    )
    spatial_tensor_axes = tuple(
        _reduce_axis_index(remaining, storage_axis)
        for storage_axis in sorted(spatial_storage_axes)
    )
    spatial_roles = {spec.roles[storage_axis] for storage_axis in spatial_storage_axes}
    if len(spatial_roles) != 1:
        raise ValueError("mixed spatial reduce roles are not supported")
    spatial_role = next(iter(spatial_roles))
    profile = _masked_reduce_along_axes(y, spatial_tensor_axes, spatial_role)

    if plot_plane_storage_axes is not None:
        on_plot_plane = profile_axis_idx in plot_plane_storage_axes
    else:
        on_plot_plane = profile_axis_idx in (
            region_frame.plot_x_dim,
            region_frame.plot_y_dim,
        )
    if on_plot_plane:
        if plot_plane_storage_axes is not None:
            plot_y_storage, plot_x_storage = plot_plane_storage_axes
            profile_axis = (
                "plot_x"
                if profile_axis_idx == plot_x_storage
                else "plot_y"
            )
        else:
            profile_axis = storage_axis_to_plot_axis(
                region_frame, profile_axis_idx
            )
        coords = _profile_coords(
            region_frame, profile_axis, int(profile.shape[-1])
        )
        axis_name = (
            region_frame.plot_x_name
            if profile_axis == "plot_x"
            else region_frame.plot_y_name
        )
    else:
        profile_axis_index = _reduce_axis_index(remaining, profile_axis_idx)
        coords = np.asarray(arrays[profile_axis_index], dtype=float)
        if coords.shape != profile.shape:
            raise ValueError(
                f"profile coordinate length {coords.shape} does not match "
                f"profile shape {profile.shape}"
            )
        axis_name = axis_names[profile_axis_idx]

    return np.asarray(profile, dtype=float).reshape(-1), [coords], [axis_name]


def materialize_view(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    axis_names: Sequence[str],
    spec: Projection,
    *,
    region: Optional[RegionDefinition] = None,
    mask_mode: MaskMode = "inside",
    region_frame: Optional[PlotViewFrame] = None,
    plot_plane_storage_axes: Optional[Tuple[int, int]] = None,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Reduce and transpose loaded data to match a projection.

    With a region this composes :func:`reduce_before_mask` and
    :func:`mask_to_profile` back to back, which is right wherever no
    transform runs between them: the cached-plane path masks a plane the
    transform has already been applied to. The load path calls the two
    stages itself so it can transform in between.

    Parameters
    ----------
    y : np.ndarray
        Array loaded with :meth:`Projection.base_slice` for ``spec``.
    axis_arrays : sequence of np.ndarray
        Per-storage-axis coordinate arrays (full length along each axis).
    axis_names : sequence of str
        Names per storage axis.
    spec : Projection
        Projection describing the output view.
    region : RegionDefinition, optional
        ROI in data coordinates on the parent 2D plot plane.
    mask_mode : str
        ``inside`` or ``outside`` the ROI when reducing masked data.
    region_frame : PlotViewFrame, optional
        Parent 2D view frame required when ``region`` is set.
    plot_plane_storage_axes : tuple of int, optional
        Parent plot Y and plot X storage axis indices for stack profiles.

    Returns
    -------
    tuple
        ``(y, axis_arrays, axis_names)`` oriented for plot_geometry.
    """
    if region is None:
        return _materialize_without_region(y, axis_arrays, axis_names, spec)
    if region_frame is None:
        raise ValueError("region_frame is required when region is set")
    if spec.plot_ndim != 1:
        raise ValueError(
            f"ROI materialization always reduces to a profile, got "
            f"plot_ndim {spec.plot_ndim}"
        )
    y, arrays, remaining = reduce_before_mask(
        y,
        axis_arrays,
        spec,
        plot_plane_storage_axes=plot_plane_storage_axes,
    )
    return mask_to_profile(
        y,
        arrays,
        remaining,
        axis_names,
        spec,
        region,
        mask_mode,
        region_frame,
        plot_plane_storage_axes=plot_plane_storage_axes,
    )
