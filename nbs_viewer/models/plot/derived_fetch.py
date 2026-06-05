"""
Fetch :class:`PlotBundle` products derived from a 2D ROI.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from .cube_view import (
    CubeViewSpec,
    DimRole,
    MaterializeRequest,
    SpatialReduce,
    display_plane_profile_spec,
    is_plot_plane_storage_axis,
    materialize_view,
    plot_axis_to_storage_axis,
    profile_storage_axis,
    profile_view_spec,
    storage_axis_to_plot_axis,
)
from .plot_geometry import PlotBundle, prepare_1d_bundle, prepare_2d_bundle
from .plot_view_frame import frame_from_bundle
from .region import (
    RectRegion,
    compile_rect_with_mask_mode,
    expand_rect_for_profile,
)


def _compiled_for_mask(
    frame,
    region: RectRegion,
    mask_mode: str,
):
    """
    Compile a rectangle region, optionally inverting the mask.
    """
    return compile_rect_with_mask_mode(frame, region, mask_mode)


def _require_non_empty(compiled) -> None:
    """
    Raise if the compiled region selects no cells.
    """
    if compiled.pixel_count == 0:
        raise ValueError("ROI does not cover any cells")


def _crop_mesh_grids(
    mesh_x: np.ndarray,
    mesh_y: np.ndarray,
    shape: Tuple[int, int],
    r0: int,
    r1: int,
    c0: int,
    c1: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Crop ``pcolormesh`` coordinate grids to a storage bounding box.

    Parameters
    ----------
    mesh_x, mesh_y : np.ndarray
        Parent mesh coordinate arrays.
    shape : tuple of int
        Shape of the parent cell array ``(n_rows, n_cols)``.
    r0, r1, c0, c1 : int
        Half-open row and column slice bounds.

    Returns
    -------
    tuple of np.ndarray
        Cropped ``mesh_x`` and ``mesh_y``.
    """
    ny, nx = shape
    mesh_x = np.asarray(mesh_x, dtype=float)
    mesh_y = np.asarray(mesh_y, dtype=float)
    if mesh_x.shape == (ny + 1, nx + 1) and mesh_y.shape == (ny + 1, nx + 1):
        return mesh_x[r0 : r1 + 1, c0 : c1 + 1], mesh_y[r0 : r1 + 1, c0 : c1 + 1]
    if mesh_x.shape == (ny, nx) and mesh_y.shape == (ny, nx):
        return mesh_x[r0:r1, c0:c1], mesh_y[r0:r1, c0:c1]
    raise ValueError(
        f"Mesh grid shape {mesh_x.shape} does not match cell shape {shape}"
    )


def _plane_bundle_from_mesh_crop(
    parent: PlotBundle,
    frame,
    y_crop: np.ndarray,
    r0: int,
    r1: int,
    c0: int,
    c1: int,
) -> PlotBundle:
    """
    Build a mesh :class:`PlotBundle` for a cropped ROI plane.
    """
    if parent.mesh_x is None or parent.mesh_y is None:
        raise ValueError("Mesh parent bundle is missing mesh coordinates")
    mesh_x, mesh_y = _crop_mesh_grids(
        parent.mesh_x,
        parent.mesh_y,
        parent.y.shape,
        r0,
        r1,
        c0,
        c1,
    )
    names = list(frame.axis_names)
    while len(names) < 2:
        names.append(f"dim_{len(names)}")
    return PlotBundle(
        ndim=2,
        y=y_crop,
        render_mode="mesh",
        axis_names=names[-2:],
        mesh_x=mesh_x,
        mesh_y=mesh_y,
    )


def _axis_centers_for_crop(
    frame,
    storage_dim: int,
    i0: int,
    i1: int,
) -> np.ndarray:
    """
    Return cell-center coordinates for a slice along a storage axis.
    """
    from .region_mesh import (
        _cell_x_bounds_mesh,
        _cell_y_bounds_mesh,
        _image_cell_bounds,
    )

    centers = []
    for i in range(i0, i1):
        if frame.render_mode == "image":
            if storage_dim == 0:
                _, _, y0, y1 = _image_cell_bounds(frame, i, 0)
            else:
                x0, x1, _, _ = _image_cell_bounds(frame, 0, i)
                y0, y1 = 0.0, 0.0
                centers.append(0.5 * (x0 + x1))
                continue
            centers.append(0.5 * (y0 + y1))
            continue
        if storage_dim == frame.plot_x_dim:
            x0, x1 = _cell_x_bounds_mesh(frame, i, 0)
            centers.append(0.5 * (x0 + x1))
        else:
            y0, y1 = _cell_y_bounds_mesh(frame, i, 0)
            centers.append(0.5 * (y0 + y1))
    return np.asarray(centers, dtype=float)


def _default_parent_spec_2d() -> CubeViewSpec:
    """
    Return a trailing-axis 2D parent spec for materializing from a 2D bundle.
    """
    return CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )


def display_plane_spec(parent_spec: Optional[CubeViewSpec] = None) -> CubeViewSpec:
    """
    Return a 2D cube view spec for the displayed plot plane.

    Parameters
    ----------
    parent_spec : CubeViewSpec, optional
        Full N-D parent view. When ``ndim > 2``, slice and reduce roles on
        non-plot axes are already reflected in a 2D ``parent_bundle``.

    Returns
    -------
    CubeViewSpec
        Two-axis view with ``plot_ndim == 2``.
    """
    if parent_spec is not None and parent_spec.ndim == 2 and parent_spec.plot_ndim == 2:
        return parent_spec
    return _default_parent_spec_2d()


def _storage_axis_arrays_for_bundle(
    bundle: PlotBundle, frame
) -> Tuple[list, list]:
    """
    Build per-storage-axis coordinate arrays for a displayed 2D bundle.
    """
    names = list(bundle.axis_names)
    while len(names) < 2:
        names.append(f"dim_{len(names)}")
    ny, nx = frame.shape
    row_axis = np.arange(ny, dtype=float)
    col_axis = np.arange(nx, dtype=float)
    if frame.render_mode == "mesh" and bundle.mesh_x is not None:
        mesh_x = np.asarray(bundle.mesh_x, dtype=float)
        mesh_y = np.asarray(bundle.mesh_y, dtype=float)
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


def resolve_profile_region(
    parent_frame,
    roi: RectRegion,
    profile_storage_axis: int,
    parent_spec: CubeViewSpec,
    *,
    span_full: bool = False,
) -> RectRegion:
    """
    Return the ROI rectangle to freeze into a profile materialize request.

    Parameters
    ----------
    parent_frame : PlotViewFrame
        Parent 2D view frame.
    roi : RectRegion
        User ROI in data coordinates.
    profile_storage_axis : int
        Storage axis along which profile coordinates run.
    parent_spec : CubeViewSpec
        Parent cube view for plot-axis lookup.
    span_full : bool
        Expand the ROI to the full plot extent along in-plane profile axes.

    Returns
    -------
    RectRegion
        Possibly expanded rectangle for profile reduction.
    """
    roi = roi.normalized()
    if not span_full:
        return roi
    plot_axes = set(parent_spec.plot_axis_order())
    if profile_storage_axis not in plot_axes:
        return roi
    profile_axis = storage_axis_to_plot_axis(
        parent_frame,
        profile_storage_axis,
        parent_spec=parent_spec,
    )
    return expand_rect_for_profile(parent_frame, roi, profile_axis)


def _plot_plane_storage_axes(
    parent_spec: Optional[CubeViewSpec],
) -> Optional[Tuple[int, int]]:
    """
    Return parent plot Y and plot X storage axis indices when known.
    """
    if parent_spec is None or parent_spec.plot_ndim != 2:
        return None
    plot_order = parent_spec.plot_axis_order()
    if len(plot_order) < 2:
        return None
    return plot_order[-2], plot_order[-1]


def materialize_request_for_profile(
    parent_spec: CubeViewSpec,
    region: RectRegion,
    profile_axis,
    spatial_reduce: str,
    mask_mode: str = "inside",
    *,
    parent_frame=None,
    span_full_profile_axis: bool = False,
) -> MaterializeRequest:
    """
    Build a materialize request for an ROI profile.

    Parameters
    ----------
    parent_spec : CubeViewSpec
        Parent cube view.
    region : RectRegion
        ROI in data coordinates on the parent plot plane.
    profile_axis : str or int
        ``plot_x``, ``plot_y``, or a profile storage axis index.
    spatial_reduce : str
        ``sum`` or ``mean`` within the ROI on plot-plane axes.
    mask_mode : str
        ``inside`` or ``outside`` the ROI.
    parent_frame : PlotViewFrame, optional
        Parent view frame for span-full expansion.
    span_full_profile_axis : bool
        Expand the ROI to the full plot extent along in-plane profile axes.

    Returns
    -------
    MaterializeRequest
        Frozen view request for ``materialize_view``.
    """
    if isinstance(profile_axis, int):
        profile_storage_axis = profile_axis
    else:
        profile_storage_axis = plot_axis_to_storage_axis(parent_spec, profile_axis)
    if parent_frame is not None:
        region = resolve_profile_region(
            parent_frame,
            region,
            profile_storage_axis,
            parent_spec,
            span_full=span_full_profile_axis,
        )
    else:
        region = region.normalized()
    output_spec = profile_view_spec(
        parent_spec, profile_storage_axis, spatial_reduce
    )
    return MaterializeRequest(output_spec, region, mask_mode)


def fetch_materialized_bundle(
    request: MaterializeRequest,
    *,
    run_model=None,
    xkeys=None,
    ykey: str = "",
    norm_keys=None,
    slice_info=None,
    parent_spec: Optional[CubeViewSpec] = None,
    parent_bundle: Optional[PlotBundle] = None,
    region_frame=None,
    label: str = "",
) -> PlotBundle:
    """
    Fetch a plot bundle by applying a materialize request to loaded data.

    Parameters
    ----------
    request : MaterializeRequest
        View and ROI parameters.
    run_model
        Object providing ``_fetch_plot_arrays`` or ``get_plot_bundle``.
    xkeys : list, optional
        Plot x keys for loading.
    ykey : str, optional
        Plot y key for loading.
    norm_keys : list, optional
        Normalization keys.
    slice_info : tuple, optional
        Legacy slice indices when loading without a cube spec on the request.
    parent_spec : CubeViewSpec, optional
        Parent 2D cube view used to interpret a 2D ``parent_bundle``.
    parent_bundle : PlotBundle, optional
        Pre-loaded 2D parent plane.
    region_frame : PlotViewFrame, optional
        View frame for ROI compilation.
    label : str
        Optional display label for 1D output.

    Returns
    -------
    PlotBundle
        Materialized plot payload.
    """
    if request.region is None:
        raise ValueError("fetch_materialized_bundle requires request.region")

    if parent_bundle is not None:
        if parent_bundle.ndim != 2:
            raise ValueError("parent_bundle must be 2D for in-plane profile fetch")
        frame = region_frame or frame_from_bundle(parent_bundle)
        materialize_request = _request_for_display_plane(request, parent_spec)
        if materialize_request.spec.ndim != 2:
            raise ValueError(
                "MaterializeRequest spec ndim must match the displayed 2D plane"
            )
        axis_arrays, axis_names = _storage_axis_arrays_for_bundle(
            parent_bundle, frame
        )
        plot_plane = (0, 1)
        profile, axes, names = materialize_view(
            parent_bundle.y,
            axis_arrays,
            axis_names,
            materialize_request,
            region_frame=frame,
            plot_plane_storage_axes=plot_plane,
        )
    else:
        if run_model is None:
            raise ValueError("run_model or parent_bundle required")
        if region_frame is None:
            raise ValueError("region_frame required when loading from run_model")
        load_slice = request.spec.to_load_slice_info()
        xlist, axis_names, y = run_model._fetch_plot_arrays(
            xkeys,
            ykey,
            norm_keys,
            load_slice,
            cube_view_spec=None,
            preserve_storage_axes=True,
        )
        plot_plane = _plot_plane_storage_axes(parent_spec)
        profile, axes, names = materialize_view(
            y,
            xlist,
            axis_names,
            request,
            region_frame=region_frame,
            plot_plane_storage_axes=plot_plane,
        )

    if request.spec.plot_ndim != 1:
        raise ValueError("fetch_materialized_bundle currently supports 1D output only")
    if not np.isfinite(profile).any():
        raise ValueError("ROI profile is empty after reduction")
    display_label = label or names[0]
    return prepare_1d_bundle(profile, axes, [display_label])


def fetch_derived_plane_bundle(
    run_model=None,
    xkey: str = "",
    ykey: str = "",
    norm_keys=None,
    slice_info=None,
    cube_view_spec=None,
    *,
    parent_bundle: Optional[PlotBundle] = None,
    region: Optional[RectRegion] = None,
    mask_mode: str = "inside",
) -> PlotBundle:
    """
    Build a 2D bundle cropped to the ROI bounding box with mask applied.

    Parameters
    ----------
    run_model
        Object providing ``get_plot_bundle``.
    xkey, ykey : str
        Plot data keys.
    norm_keys : list, optional
        Normalization keys.
    slice_info : tuple, optional
        Slice indices for the parent cube view.
    cube_view_spec : CubeViewSpec, optional
        Cube view specification.
    region : RectRegion, optional
        ROI definition.
    mask_mode : str
        ``inside`` or ``outside`` the ROI.

    Returns
    -------
    PlotBundle
        Masked 2D crop suitable for image or mesh rendering.
    """
    if region is None:
        raise ValueError("region is required")

    if parent_bundle is not None:
        bundle = parent_bundle
    else:
        if run_model is None:
            raise ValueError("run_model or parent_bundle required")
        bundle = run_model.get_plot_bundle(
            [xkey],
            ykey,
            norm_keys,
            slice_info=slice_info,
            cube_view_spec=cube_view_spec,
        )
    if bundle.ndim != 2:
        raise ValueError("Derived plane requires a 2D parent bundle")

    frame = frame_from_bundle(bundle)
    region = region.normalized()
    compiled = _compiled_for_mask(frame, region, mask_mode)
    _require_non_empty(compiled)

    r0, r1, c0, c1 = compiled.bbox
    if r1 <= r0 or c1 <= c0:
        raise ValueError("ROI bounding box is empty")

    y_crop = np.asarray(bundle.y[r0:r1, c0:c1], dtype=float)
    mask_crop = compiled.mask[r0:r1, c0:c1]
    if mask_mode == "inside":
        y_crop = np.where(mask_crop, y_crop, np.nan)
    else:
        y_crop = np.where(~mask_crop, y_crop, np.nan)

    if not np.isfinite(y_crop).any():
        raise ValueError("ROI plane is empty after masking")

    if bundle.render_mode == "mesh":
        return _plane_bundle_from_mesh_crop(
            bundle, frame, y_crop, r0, r1, c0, c1
        )

    names = list(bundle.axis_names)
    row_axis = _axis_centers_for_crop(frame, 0, r0, r1)
    col_axis = _axis_centers_for_crop(frame, 1, c0, c1)
    return prepare_2d_bundle(
        y_crop,
        [row_axis, col_axis],
        names,
        render_mode_hint="image",
    )


def _spatial_reduce_from_profile_spec(spec: CubeViewSpec) -> SpatialReduce:
    """
    Return the spatial reduce op encoded in a profile output spec.
    """
    for role in spec.roles:
        if role == DimRole.SUM:
            return "sum"
        if role == DimRole.MEAN:
            return "mean"
    return "sum"


def _request_for_display_plane(
    request: MaterializeRequest,
    parent_spec: Optional[CubeViewSpec],
) -> MaterializeRequest:
    """
    Adapt a profile request to the displayed 2D bundle when possible.
    """
    if parent_spec is None or request.spec.ndim == 2:
        return request
    profile_axis = profile_storage_axis(request.spec)
    if not is_plot_plane_storage_axis(parent_spec, profile_axis):
        return request
    plane_spec = display_plane_profile_spec(
        parent_spec,
        profile_axis,
        _spatial_reduce_from_profile_spec(request.spec),
    )
    return MaterializeRequest(plane_spec, request.region, request.mask_mode)


def _profile_uses_nd_load(
    request: MaterializeRequest,
    parent_spec: Optional[CubeViewSpec],
) -> bool:
    """
    Return whether a profile request must load beyond the 2D display plane.
    """
    if parent_spec is None:
        return request.spec.ndim > 2
    profile_axis = profile_storage_axis(request.spec)
    return not is_plot_plane_storage_axis(parent_spec, profile_axis)


def fetch_derivative_preview(
    plot_model,
    region: RectRegion,
    *,
    output_kind: str,
    request: Optional[MaterializeRequest] = None,
    mask_mode: str = "inside",
    parent_spec: Optional[CubeViewSpec] = None,
    parent_bundle: Optional[PlotBundle] = None,
) -> PlotBundle:
    """
    Fetch a derivative bundle for dialog preview from a plot data model.

    Parameters
    ----------
    plot_model : PlotDataModel
        Active 2D plot model.
    region : RectRegion
        Current ROI.
    output_kind : str
        ``profile`` or ``plane``.
    request : MaterializeRequest, optional
        Frozen profile request when ``output_kind`` is ``profile``.
    mask_mode : str
        ROI mask mode for plane preview.
    parent_spec : CubeViewSpec, optional
        Parent cube view.
    parent_bundle : PlotBundle, optional
        Cached parent 2D bundle when valid for the request.

    Returns
    -------
    PlotBundle
        Preview payload (1D or 2D).
    """
    if parent_bundle is None and plot_model.last_bundle is not None:
        parent_bundle = plot_model.last_bundle
    if parent_bundle is None:
        raise ValueError("No parent 2D bundle available for derivative fetch")

    if output_kind == "profile":
        if request is None:
            raise ValueError("request is required for profile preview")
        frame = frame_from_bundle(parent_bundle)
        if parent_bundle is not None and not _profile_uses_nd_load(
            request, parent_spec
        ):
            return fetch_materialized_bundle(
                request,
                parent_bundle=parent_bundle,
                parent_spec=parent_spec,
                region_frame=frame,
            )
        return fetch_materialized_bundle(
            request,
            run_model=plot_model._run,
            xkeys=[plot_model._xkey],
            ykey=plot_model._ykey,
            norm_keys=plot_model._norm_keys,
            parent_spec=parent_spec,
            region_frame=frame,
        )

    return fetch_derived_plane_bundle(
        parent_bundle=parent_bundle,
        region=region,
        mask_mode=mask_mode,
        run_model=plot_model._run,
        xkey=plot_model._xkey,
        ykey=plot_model._ykey,
        norm_keys=plot_model._norm_keys,
    )
