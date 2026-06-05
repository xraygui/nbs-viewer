"""
Fetch :class:`PlotBundle` products derived from a 2D ROI.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from .analysis_region import AnalysisRegion
from .cube_view import (
    CubeViewSpec,
    DimRole,
    MaterializeRequest,
    materialize_view,
    plot_axis_to_storage_axis,
    profile_view_spec,
)
from .derivative_spec import DerivativeSpec
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


def materialize_request_for_profile(
    parent_spec: CubeViewSpec,
    region: RectRegion,
    profile_axis: str,
    spatial_reduce: str,
    mask_mode: str = "inside",
    *,
    parent_frame=None,
    span_full_profile_axis: bool = False,
) -> MaterializeRequest:
    """
    Build a materialize request for an in-plane ROI profile.

    Parameters
    ----------
    parent_spec : CubeViewSpec
        Parent 2D cube view.
    region : RectRegion
        ROI in data coordinates on the parent plot plane.
    profile_axis : str
        ``plot_x`` or ``plot_y``.
    spatial_reduce : str
        ``sum`` or ``mean`` within the ROI on the orthogonal plot axis.
    mask_mode : str
        ``inside`` or ``outside`` the ROI.
    parent_frame : PlotViewFrame, optional
        Parent view frame for span-full expansion.
    span_full_profile_axis : bool
        Expand the ROI to the full plot extent along ``profile_axis``.

    Returns
    -------
    MaterializeRequest
        Frozen view request for ``materialize_view``.
    """
    region = region.normalized()
    if span_full_profile_axis:
        if parent_frame is None:
            raise ValueError("parent_frame is required for span_full_profile_axis")
        region = expand_rect_for_profile(parent_frame, region, profile_axis)
    profile_storage_axis = plot_axis_to_storage_axis(parent_spec, profile_axis)
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
        plane_spec = display_plane_spec(parent_spec)
        if request.spec.ndim != plane_spec.ndim:
            raise ValueError(
                "MaterializeRequest spec ndim must match the displayed 2D plane"
            )
        axis_arrays, axis_names = _storage_axis_arrays_for_bundle(
            parent_bundle, frame
        )
        profile, axes, names = materialize_view(
            parent_bundle.y,
            axis_arrays,
            axis_names,
            request,
            region_frame=frame,
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
        )
        profile, axes, names = materialize_view(
            y,
            xlist,
            axis_names,
            request,
            region_frame=region_frame,
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
    analysis: Optional[AnalysisRegion] = None,
    spec: Optional[DerivativeSpec] = None,
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
        ROI definition when ``analysis`` is not given.
    analysis : AnalysisRegion, optional
        Legacy analysis descriptor.
    spec : DerivativeSpec, optional
        Derivative settings when ``analysis`` is not given.

    Returns
    -------
    PlotBundle
        Masked 2D crop suitable for image or mesh rendering.
    """
    if analysis is not None:
        region = analysis.definition
        mask_mode = analysis.mask_mode
        label = analysis.label
    elif region is not None:
        mask_mode = spec.mask_mode if spec is not None else "inside"
        label = (
            (spec.label or spec.default_label()) if spec is not None else ""
        )
    else:
        raise ValueError("Provide analysis or region")

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


def fetch_derived_profile_bundle(
    run_model=None,
    xkey: str = "",
    ykey: str = "",
    norm_keys=None,
    slice_info=None,
    cube_view_spec=None,
    analysis: Optional[AnalysisRegion] = None,
    *,
    parent_bundle: Optional[PlotBundle] = None,
    region: Optional[RectRegion] = None,
    spec: Optional[DerivativeSpec] = None,
) -> PlotBundle:
    """
    Build a 1D profile bundle by reducing masked data along one plot axis.

    Parameters
    ----------
    run_model
        Object providing ``get_plot_bundle``.
    xkey, ykey : str
        Plot data keys.
    norm_keys : list, optional
        Normalization keys.
    slice_info : tuple, optional
        Slice indices.
    cube_view_spec : CubeViewSpec, optional
        Cube view specification.
    analysis : AnalysisRegion, optional
        Region and reduction settings.
    region : RectRegion, optional
        ROI when using ``spec`` instead of ``analysis``.
    spec : DerivativeSpec, optional
        Derivative settings paired with ``region``.

    Returns
    -------
    PlotBundle
        1D line bundle for the profile.
    """
    if analysis is not None:
        region = analysis.definition
        mask_mode = analysis.mask_mode
        profile_axis = analysis.profile_axis
        reduce = analysis.reduce
        label = analysis.label
        span_full = False
    elif region is not None and spec is not None:
        mask_mode = spec.mask_mode
        profile_axis = spec.profile_axis
        reduce = spec.reduce
        label = spec.label
        span_full = spec.span_full_profile_axis
    else:
        raise ValueError("Provide analysis or (region, spec)")

    parent_spec = display_plane_spec(cube_view_spec)
    if parent_bundle is None:
        if run_model is None:
            raise ValueError("run_model or parent_bundle required")
        parent_bundle = run_model.get_plot_bundle(
            [xkey],
            ykey,
            norm_keys,
            slice_info=slice_info,
            cube_view_spec=cube_view_spec,
        )
    if parent_bundle.ndim != 2:
        raise ValueError("Derived profile requires a 2D parent bundle")

    frame = frame_from_bundle(parent_bundle)
    region = region.normalized()
    request = materialize_request_for_profile(
        parent_spec,
        region,
        profile_axis,
        reduce,
        mask_mode,
        parent_frame=frame,
        span_full_profile_axis=span_full,
    )
    default_name = (
        frame.plot_x_name if profile_axis == "plot_x" else frame.plot_y_name
    )
    return fetch_materialized_bundle(
        request,
        parent_bundle=parent_bundle,
        parent_spec=parent_spec,
        region_frame=frame,
        label=label or (
            spec.default_label(default_name) if spec is not None else default_name
        ),
    )


def region_for_derivative_fetch(
    parent_bundle: PlotBundle,
    region: RectRegion,
    spec: DerivativeSpec,
) -> RectRegion:
    """
    Return the ROI rectangle to use for a derivative fetch.

    Parameters
    ----------
    parent_bundle : PlotBundle
        Parent 2D bundle.
    region : RectRegion
        User ROI in data coordinates.
    spec : DerivativeSpec
        Derivative operation settings.

    Returns
    -------
    RectRegion
        Possibly expanded rectangle for profile reduction.
    """
    region = region.normalized()
    if spec.output_kind != "profile" or not spec.span_full_profile_axis:
        return region
    frame = frame_from_bundle(parent_bundle)
    return expand_rect_for_profile(frame, region, spec.profile_axis)


def fetch_derivative_preview_bundle(
    plot_model,
    slice_info,
    cube_view_spec,
    region: RectRegion,
    spec: DerivativeSpec,
    parent_bundle: Optional[PlotBundle] = None,
) -> PlotBundle:
    """
    Fetch a derivative bundle for dialog preview from a plot data model.

    Parameters
    ----------
    plot_model : PlotDataModel
        Active 2D plot model.
    slice_info : tuple
        Current slice indices.
    cube_view_spec : CubeViewSpec or None
        Current cube view.
    region : RectRegion
        Current ROI.
    spec : DerivativeSpec
        Derivative operation settings.

    Returns
    -------
    PlotBundle
        Preview payload (1D or 2D).
    """
    if parent_bundle is None and plot_model.last_bundle is not None:
        parent_bundle = plot_model.last_bundle
    if parent_bundle is None:
        raise ValueError("No parent 2D bundle available for derivative fetch")

    if spec.output_kind == "profile":
        return fetch_derived_profile_bundle(
            parent_bundle=parent_bundle,
            region=region,
            spec=spec,
            run_model=plot_model._run,
            xkey=plot_model._xkey,
            ykey=plot_model._ykey,
            norm_keys=plot_model._norm_keys,
            slice_info=slice_info,
            cube_view_spec=cube_view_spec,
        )
    region = region_for_derivative_fetch(parent_bundle, region, spec)
    return fetch_derived_plane_bundle(
        parent_bundle=parent_bundle,
        region=region,
        spec=spec,
        run_model=plot_model._run,
        xkey=plot_model._xkey,
        ykey=plot_model._ykey,
        norm_keys=plot_model._norm_keys,
        slice_info=slice_info,
        cube_view_spec=cube_view_spec,
    )
