"""
Request-to-bundle helpers: reduce, normalize, transform, and pack.

Orchestration lives on ``RunSource.get_plot_bundle``. These functions are
pure in the arrays they receive so they can be tested without a run.
"""

from __future__ import annotations

from typing import List, Literal, Optional, Sequence, Tuple, Union

import numpy as np
import xarray as xr
from asteval import Interpreter

from ..data.array_contract import REDUCE_SKIPNA
from .plot_axes import PlotAxes
from .plot_geometry import PlotBundle, prepare_1d_bundle
from .plot_request import PlotRequest
from .plot_view_frame import PlotViewFrame, frame_from_bundle
from .region import RegionDefinition, compile_with_mask_mode
from .view_spec import (
    DimRole,
    PlotAxisName,
    Projection,
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
    database read is needed. The plane is display-ordered and the masking
    stage works in the order the source stored the data, so the plane is
    turned back before it is masked.

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
    arrays, names = _plane_axis_arrays(plane, frame)
    values = np.asarray(plane.y)
    # ``mask_to_profile`` turns the display-ordered mask round to meet a
    # storage-ordered block, so the plane turns back first, coordinates with
    # it. Handed over as displayed, the mask was turned twice and an ROI drawn
    # low on a row-reversed image summed the mirror-image rows at the top.
    if frame.row_reversed:
        values = values[::-1, :]
        arrays[frame.plot_y_dim] = arrays[frame.plot_y_dim][::-1]
    if frame.col_reversed:
        values = values[:, ::-1]
        arrays[frame.plot_x_dim] = arrays[frame.plot_x_dim][::-1]
    data = xr.DataArray(
        values,
        dims=list(names),
        coords={name: array for name, array in zip(names, arrays)},
    )
    axes = PlotAxes.of(plane_view, names).to_profile(
        bundle_profile_axis, request.spatial_reduce
    )
    profile = materialize_view(
        data,
        axes,
        region=request.region,
        mask_mode=request.mask_mode,
        region_frame=frame,
    )
    if not np.isfinite(profile.values).any():
        raise ValueError("ROI profile is empty after reduction")
    profile_dim = profile.dims[0]
    return prepare_1d_bundle(
        profile.values,
        [np.asarray(profile.coords[profile_dim].values)],
        [label or str(profile_dim)],
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


def apply_normalization(
    data: xr.DataArray,
    norms: Sequence[xr.DataArray],
) -> xr.DataArray:
    """
    Divide ``data`` by each normalization array.

    Alignment is xarray's: shared dimensions match by name, and under
    ``arithmetic_join="exact"`` their coordinates must agree exactly or the
    divide raises. This replaces a hand-written broadcaster that matched by
    name and *fell back to matching by shape*, which is a coincidence rather
    than a reason.

    ``data`` may be the held block itself, and it is never written to: each
    divide returns a new array, and with no norms the block comes back as it
    is rather than copied on every fetch.

    A dimension the data does not have is rejected rather than broadcast. That
    is the one thing xarray would do too quietly: a norm array whose dimension
    is unknown to ``data`` produces an outer product -- ``(5, 3) / (5,)``
    becoming ``(5, 3, 5)`` -- instead of an error. A caller with a norm that
    lives on one of ``data``'s axes must say which.

    Parameters
    ----------
    data : xarray.DataArray
        Loaded, oriented block.
    norms : sequence of xarray.DataArray
        Normalization arrays, each on a subset of ``data``'s dimensions.

    Returns
    -------
    xarray.DataArray
        Normalized block.

    Raises
    ------
    ValueError
        If a norm carries a dimension ``data`` does not have.
    """
    out = data.astype(float, copy=False)
    for norm in norms:
        unknown = [dim for dim in norm.dims if dim not in out.dims]
        if unknown:
            raise ValueError(
                f"cannot broadcast norm axes {list(norm.dims)} onto plot axes "
                f"{list(out.dims)}"
            )
        out = out / norm
    return out


def apply_transform(
    data: xr.DataArray,
    axes: PlotAxes,
    transform_text: str,
) -> xr.DataArray:
    """
    Apply a user expression to the displayed values.

    ``y`` is the array and ``x`` the coordinate arrays of the dimensions the
    user is looking at -- the plot plane, or for a profile the plane the ROI
    was drawn on, so ``x`` means the same thing either way. An expression may
    rebind either; an empty string is a no-op.

    Parameters
    ----------
    data : xarray.DataArray
        Values to transform.
    axes : PlotAxes
        Named view, for the displayed dimensions.
    transform_text : str
        Expression. ``x`` and ``y`` are injected into the symbol table.

    Returns
    -------
    xarray.DataArray
        Transformed array, keeping its dimensions and coordinates.

    Raises
    ------
    ValueError
        If the expression changes the array's shape, which would leave every
        coordinate describing something else.
    """
    if not transform_text:
        return data
    display = [dim for dim in axes.display_dims if dim in data.coords]
    before = [np.asarray(data.coords[dim].values) for dim in display]
    # The interpreter gets copies of both. ``data`` can be the held block
    # itself -- a plane that needs no reduce reaches here uncopied -- and a
    # clip written ``y[y > t] = t`` assigns in place, which wrote the clip
    # into every later fetch. The same for an element of ``x``.
    coords = [np.array(axis, copy=True) for axis in before]

    interp = Interpreter()
    interp.symtable["y"] = np.array(data.values, copy=True)
    interp.symtable["x"] = coords
    result = interp(transform_text)
    values = np.asarray(
        result if result is not None else interp.symtable.get("y", data.values)
    )
    if values.shape != data.shape:
        raise ValueError(
            f"transform changed the shape from {data.shape} to {values.shape}; "
            "the coordinates would no longer describe the values"
        )
    out = data.copy(data=values)

    # An expression may rewrite x as well as y -- rescaling an energy axis, for
    # instance -- so the coordinates are read back rather than assumed.
    updated = interp.symtable.get("x", coords)
    for dim, original, after in zip(display, before, updated):
        after = np.asarray(after)
        if after.shape == original.shape and not np.array_equal(after, original):
            out = out.assign_coords({dim: after})
    return out


def _spatial_dims(axes: PlotAxes) -> Tuple[str, ...]:
    """
    Return the plane dimensions the ROI reduces over, by name.

    These are the plot plane's own axes carrying a SUM or MEAN role: the ROI
    collapses the plane it was drawn on, leaving the profile axis.

    Parameters
    ----------
    axes : PlotAxes
        Named profile view.

    Returns
    -------
    tuple of str
        Dimension names reduced inside the mask.
    """
    if axes.spec.plot_ndim != 1:
        return ()
    reducing = (DimRole.SUM, DimRole.MEAN)
    if axes.plane is not None:
        return tuple(
            dim for dim in axes.plane if axes.role(dim) in reducing
        )
    # No parent plane recorded: the plane is the projection's own trailing
    # pair, minus the profile axis it was rearranged to end on. Only reachable
    # from a caller that builds a profile view without naming its parent.
    order = axes.order
    if len(order) < 2:
        return ()
    return tuple(
        dim
        for dim in order[-2:]
        if dim != axes.profile and axes.role(dim) in reducing
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


def reduce_to_plane(data: xr.DataArray, axes: PlotAxes) -> xr.DataArray:
    """
    Collapse the reduced axes and transpose what is left into plot order.

    This was forty-five lines of index juggling: a ``remaining`` list tracking
    which storage axis each tensor axis came from, parallel lists of
    coordinates, names and roles deleted in step with it, and a permutation
    built by position. Every one of those answered "which axis is this now?",
    which a named array answers itself.

    Parameters
    ----------
    data : xarray.DataArray
        Loaded, oriented, normalized block.
    axes : PlotAxes
        Named view describing the output.

    Returns
    -------
    xarray.DataArray
        Reduced array in plot order: slice axes first, then Y, then X.

    Raises
    ------
    ValueError
        If the array carries a dimension the view does not name.
    """
    unknown = [dim for dim in data.dims if dim not in axes.names]
    if unknown:
        raise ValueError(
            f"array dimensions {unknown} are not named by the view {axes.names}"
        )
    for role, reduce_name in ((DimRole.SUM, "sum"), (DimRole.MEAN, "mean")):
        dims = [dim for dim in data.dims if axes.role(dim) is role]
        if dims:
            # skipna=False keeps this the plain reduce it has always been.
            # The NaN-aware one belongs to the masked ROI reduce and nowhere
            # else; xarray's default would erase the distinction.
            data = getattr(data, reduce_name)(dim=dims, skipna=REDUCE_SKIPNA)
    order = tuple(dim for dim in axes.order if dim in data.dims)
    if order != data.dims:
        data = data.transpose(*order)
    return data


def _reduce_dim(
    data: xr.DataArray, dim: str, role: DimRole
) -> xr.DataArray:
    """
    Collapse one dimension using the view's role semantics.
    """
    if role is DimRole.SUM:
        return data.sum(dim=dim, skipna=REDUCE_SKIPNA)
    if role is DimRole.MEAN:
        return data.mean(dim=dim, skipna=REDUCE_SKIPNA)
    raise ValueError(f"cannot reduce dimension with role {role!r}")


def _masked_reduce(
    data: xr.DataArray, dims: Sequence[str], role: DimRole
) -> xr.DataArray:
    """
    Collapse masked dimensions, NaN-aware, keeping empty bins as NaN.
    """
    if role is DimRole.SUM:
        profile = data.sum(dim=list(dims), skipna=True)
    elif role is DimRole.MEAN:
        profile = data.mean(dim=list(dims), skipna=True)
    else:
        raise ValueError(f"unexpected spatial reduce role {role!r}")
    empty = data.isnull().all(dim=list(dims))
    return profile.where(~empty)


def reduce_before_mask(
    data: xr.DataArray, axes: PlotAxes
) -> xr.DataArray:
    """
    Collapse every axis the ROI mask does not span.

    The first half of an ROI reduction. What survives is the finished plot
    plane -- or, when the profile runs along an axis the plane does not show,
    the stack of planes it runs over. Separating it from the masking half is
    what lets the transform run in between, on exactly the values the user
    sees on the image before an ROI is drawn on them.

    Parameters
    ----------
    data : xarray.DataArray
        Loaded, oriented, normalized block.
    axes : PlotAxes
        Named 1-D profile view, from :meth:`PlotAxes.to_profile`.

    Returns
    -------
    xarray.DataArray
        The plane, or the stack of planes, the mask will be applied to.

    Raises
    ------
    ValueError
        If ``axes`` is not a profile view or spans no spatial reduce axis.
    """
    if axes.spec.plot_ndim != 1:
        raise ValueError("ROI profile materialization requires plot_ndim=1")
    spatial = _spatial_dims(axes)
    if not spatial:
        raise ValueError("expected at least one spatial reduce axis")

    for dim in [
        dim
        for dim in data.dims
        if dim not in spatial
        and axes.role(dim) in (DimRole.SUM, DimRole.MEAN)
    ]:
        data = _reduce_dim(data, dim, axes.role(dim))
    return data


def mask_to_profile(
    data: xr.DataArray,
    axes: PlotAxes,
    region: RegionDefinition,
    mask_mode: MaskMode,
    region_frame: PlotViewFrame,
) -> xr.DataArray:
    """
    Mask a finished plot plane, or stack of them, down to a 1-D profile.

    The second half of an ROI reduction, run on values the transform has
    already been applied to: an ROI is drawn on what is displayed, so summing
    it must sum what is displayed.

    The mask is built as a named 2-D array, so xarray broadcasts it onto
    whichever axes of ``data`` the plane landed on. That replaced a hand
    transpose and reshape, which existed because the plane is not always the
    trailing pair -- profiling along a cube's slider axis leaves it at the
    *leading* axes, since the slider can outrank both plane axes.

    Parameters
    ----------
    data : xarray.DataArray
        Output of :func:`reduce_before_mask`, transformed, in the order the
        source stored it -- *not* display order. The mask is compiled on the
        display-ordered frame and turned round to meet it.
    axes : PlotAxes
        Named 1-D profile view.
    region : RegionDefinition
        ROI in data coordinates on the plot plane.
    mask_mode : str
        ``inside`` or ``outside`` the ROI.
    region_frame : PlotViewFrame
        Display frame of the block the plane axes actually hold.

    Returns
    -------
    xarray.DataArray
        1-D profile, with the profile axis's own coordinates on it.

    Raises
    ------
    ValueError
        If the plane is missing from ``data``, its shape disagrees with
        ``region_frame``, or the ROI covers no cells.
    """
    plane = axes.plane or (
        region_frame.axis_names[region_frame.plot_y_dim],
        region_frame.axis_names[region_frame.plot_x_dim],
    )
    missing = [dim for dim in plane if dim not in data.dims]
    if missing:
        raise ValueError(
            f"plot plane axes {plane} are not present in the fetched array "
            f"{data.dims}"
        )
    plane_shape = tuple(data.sizes[dim] for dim in plane)
    if plane_shape != region_frame.shape:
        raise ValueError(
            f"plot plane shape {plane_shape} does not match region frame "
            f"{region_frame.shape}"
        )

    compiled = compile_with_mask_mode(region_frame, region, mask_mode)
    if compiled.pixel_count == 0:
        raise ValueError("ROI does not cover any cells")

    # The ROI is compiled on the frame the user drew on, which is in display
    # order; the block is in the order the source stored it. One of the two
    # has to turn round, and a boolean plane is the cheaper one -- the block
    # can be a stack of them.
    mask = compiled.mask
    if region_frame.row_reversed:
        mask = mask[::-1, :]
    if region_frame.col_reversed:
        mask = mask[:, ::-1]

    data = data.astype(float)
    data = data.where(xr.DataArray(mask, dims=list(plane)))

    spatial = _spatial_dims(axes)
    roles = {axes.role(dim) for dim in spatial}
    if len(roles) != 1:
        raise ValueError("mixed spatial reduce roles are not supported")
    profile = _masked_reduce(data, spatial, next(iter(roles)))

    profile_dim = axes.profile
    if profile_dim is None:
        raise ValueError("profile view has no profile dimension")
    if profile_dim in plane:
        # The profile runs along the plane itself, so its coordinates come
        # from the frame the mask was compiled on rather than from the axis
        # array: on a mesh those are cell centres the frame alone knows.
        plot_axis = "plot_y" if profile_dim == plane[0] else "plot_x"
        coords = _profile_coords(
            region_frame, plot_axis, int(profile.sizes[profile_dim])
        )
        # Those run in display order and the profile in storage order, so
        # along a reversed axis they pair up only once turned round.
        flipped = (
            region_frame.row_reversed
            if plot_axis == "plot_y"
            else region_frame.col_reversed
        )
        if flipped:
            coords = coords[::-1]
        name = (
            region_frame.plot_x_name
            if plot_axis == "plot_x"
            else region_frame.plot_y_name
        )
        profile = profile.assign_coords({profile_dim: coords})
        if name != profile_dim:
            profile = profile.rename({profile_dim: name})
    return profile


def materialize_view(
    data: xr.DataArray,
    axes: PlotAxes,
    *,
    region: Optional[RegionDefinition] = None,
    mask_mode: MaskMode = "inside",
    region_frame: Optional[PlotViewFrame] = None,
) -> xr.DataArray:
    """
    Reduce and transpose loaded data to match a view.

    With a region this composes :func:`reduce_before_mask` and
    :func:`mask_to_profile` back to back, which is right wherever no transform
    runs between them: the cached-plane path masks a plane the transform has
    already been applied to. The load path calls the two stages itself so it
    can transform in between.

    Parameters
    ----------
    data : xarray.DataArray
        Loaded, oriented block.
    axes : PlotAxes
        Named view describing the output.
    region : RegionDefinition, optional
        ROI in data coordinates on the plot plane.
    mask_mode : str
        ``inside`` or ``outside`` the ROI when reducing masked data.
    region_frame : PlotViewFrame, optional
        View frame required when ``region`` is set.

    Returns
    -------
    xarray.DataArray
        Reduced array in plot order.

    Raises
    ------
    ValueError
        If a region is given without a frame, or with a 2-D output view.
    """
    if region is None:
        return reduce_to_plane(data, axes)
    if region_frame is None:
        raise ValueError("region_frame is required when region is set")
    if axes.spec.plot_ndim != 1:
        raise ValueError(
            f"ROI materialization always reduces to a profile, got "
            f"plot_ndim {axes.spec.plot_ndim}"
        )
    return mask_to_profile(
        reduce_before_mask(data, axes),
        axes,
        region,
        mask_mode,
        region_frame,
    )
