"""Tests for persistent view crop on the main display fetch path."""

import numpy as np

from nbs_viewer.models.plot.cube_view import (
    CubeViewSpec,
    DimRole,
    MaterializeRequest,
    profile_view_spec,
)
from nbs_viewer.models.plot.derived_fetch import region_frame_for_roi_preview
from nbs_viewer.models.plot.plot_geometry import (
    prepare_2d_bundle,
    storage_bbox_from_display_bbox,
)
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle, region_frame_for_bbox
from nbs_viewer.models.plot.region import RectRegion, compile_covering_rect
from nbs_viewer.models.plot.view_crop import (
    ViewCrop,
    apply_view_crop_to_slice_info,
    fetch_context_with_view_crop,
    spatial_fingerprint_from_frame,
    view_crop_from_region,
)


def _make_full_frame(y_count=5, x_count=6):
    bundle = prepare_2d_bundle(
        np.zeros((y_count, x_count)),
        [np.arange(y_count), np.arange(x_count)],
        ["y", "x"],
        render_mode_hint="image",
    )
    return frame_from_bundle(bundle)


def test_apply_view_crop_narrows_plot_plane_axes():
    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    full_frame = _make_full_frame()
    crop = ViewCrop(
        display_bbox=(1, 3, 2, 5),
        storage_bbox=(1, 3, 2, 5),
        plot_y_axis=2,
        plot_x_axis=3,
        source_key=("x", "y", "uid"),
        spatial_fingerprint=spatial_fingerprint_from_frame(full_frame),
        full_frame=full_frame,
        row_axis=np.arange(5, dtype=float),
        col_axis=np.arange(6, dtype=float),
    )
    slice_info = parent.to_load_slice_info()

    narrowed = apply_view_crop_to_slice_info(slice_info, crop)

    assert narrowed[0] == 1
    assert narrowed[1] == slice(None)
    assert narrowed[2] == slice(1, 3)
    assert narrowed[3] == slice(2, 5)


def test_view_crop_from_region_matches_compile_bbox():
    full_frame = _make_full_frame(y_count=5, x_count=6)
    parent = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    source_key = ("x", "y", "uid")
    row_axis = np.arange(5, dtype=float)
    col_axis = np.arange(6, dtype=float)

    crop = view_crop_from_region(
        region,
        full_frame,
        parent,
        source_key,
        row_axis,
        col_axis,
    )

    assert crop.display_bbox == (2, 4, 2, 4)
    assert crop.storage_bbox == (1, 3, 2, 4)
    assert crop.plot_y_axis == 0
    assert crop.plot_x_axis == 1
    assert crop.source_key == source_key
    assert crop.full_frame == full_frame


def test_storage_bbox_inverts_row_flip_for_bottom_roi():
    ny, nx = 2200, 2600
    row_axis = np.arange(ny, dtype=float)
    col_axis = np.arange(nx, dtype=float)
    y = np.zeros((ny, nx))
    bundle = prepare_2d_bundle(
        y,
        [row_axis, col_axis],
        ["dim_0", "dim_1"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=581.93, y0=156.16, x1=1478.57, y1=899.24)
    parent = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    crop = view_crop_from_region(
        region,
        frame,
        parent,
        ("x", "y", "uid"),
        row_axis,
        col_axis,
    )

    assert crop.display_bbox == (1300, 2044, 582, 1480)
    assert crop.storage_bbox == (156, 900, 582, 1480)

    y_crop = y[crop.storage_bbox[0] : crop.storage_bbox[1], crop.storage_bbox[2] : crop.storage_bbox[3]]
    cropped = prepare_2d_bundle(
        y_crop,
        [
            row_axis[crop.storage_bbox[0] : crop.storage_bbox[1]],
            col_axis[crop.storage_bbox[2] : crop.storage_bbox[3]],
        ],
        ["dim_0", "dim_1"],
        render_mode_hint="image",
    )
    left, right, bottom, top = cropped.extent
    assert left <= region.x0
    assert right >= region.x1
    assert bottom <= min(region.y0, region.y1) + 1.0
    assert top >= max(region.y0, region.y1) - 1.0


def test_cropped_fetch_matches_full_plane_slice():
    e_count, s_count, y_count, x_count = 4, 3, 5, 6
    y = (
        np.arange(e_count)[:, None, None, None] * 1000
        + np.arange(y_count)[None, None, :, None] * 10
        + np.arange(x_count)[None, None, None, :]
    ).astype(float)
    y_step = y.sum(axis=1)[1]

    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    row_axis = np.arange(y_count, dtype=float)
    col_axis = np.arange(x_count, dtype=float)
    full_bundle = prepare_2d_bundle(
        y_step,
        [row_axis, col_axis],
        ["y", "x"],
        render_mode_hint="image",
    )
    full_frame = frame_from_bundle(full_bundle)
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    crop = view_crop_from_region(
        region,
        full_frame,
        parent,
        ("x", "y", "uid"),
        row_axis,
        col_axis,
    )

    full_slice = parent.to_load_slice_info()
    cropped_slice = apply_view_crop_to_slice_info(full_slice, crop)

    sr0, sr1, sc0, sc1 = crop.storage_bbox
    assert y[1].sum(axis=0)[sr0:sr1, sc0:sc1].shape == (
        sr1 - sr0,
        sc1 - sc0,
    )
    assert cropped_slice[2] == slice(sr0, sr1)
    assert cropped_slice[3] == slice(sc0, sc1)


def test_region_frame_for_roi_preview_uses_full_frame_on_nd_load():
    y_count, x_count = 5, 6
    full_bundle = prepare_2d_bundle(
        np.zeros((y_count, x_count)),
        [np.arange(y_count), np.arange(x_count)],
        ["y", "x"],
        render_mode_hint="image",
    )
    full_frame = frame_from_bundle(full_bundle)
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    compiled = compile_covering_rect(full_frame, region)
    cropped_frame = region_frame_for_bbox(full_frame, compiled.bbox)
    cropped_bundle = prepare_2d_bundle(
        np.zeros(cropped_frame.shape),
        [
            np.arange(cropped_frame.shape[0]),
            np.arange(cropped_frame.shape[1]),
        ],
        ["y", "x"],
        render_mode_hint="image",
    )

    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    crop = view_crop_from_region(
        region,
        full_frame,
        parent,
        ("x", "y", "uid"),
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
    )
    request = MaterializeRequest(
        profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="sum"),
        region=region,
    )

    nd_frame = region_frame_for_roi_preview(
        request,
        parent,
        cropped_bundle,
        crop,
    )
    plane_frame = region_frame_for_roi_preview(
        request,
        parent,
        cropped_bundle,
        None,
    )

    assert nd_frame.shape == full_frame.shape
    assert plane_frame.shape == cropped_frame.shape


def test_crop_status_text_uses_data_coordinates():
    full_frame = _make_full_frame(y_count=20, x_count=30)
    parent = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    region = RectRegion(x0=4.5, x1=14.5, y0=3.5, y1=12.5)
    crop = view_crop_from_region(
        region,
        full_frame,
        parent,
        ("x", "y", "uid"),
        np.arange(20, dtype=float),
        np.arange(30, dtype=float),
    )
    from nbs_viewer.models.plot.view_crop import crop_status_text

    text = crop_status_text(crop)
    assert "913" not in text
    assert "4.50" in text or "4.5" in text


def test_storage_bbox_from_display_bbox_round_trip_without_flip():
    bbox = (1, 4, 2, 5)
    row_axis = np.arange(10, 0, -1, dtype=float)
    col_axis = np.arange(12, dtype=float)
    assert storage_bbox_from_display_bbox(bbox, row_axis, col_axis, (10, 12)) == bbox


def test_fetch_context_with_view_crop_stack_profile():
    e_count, s_count, ny, nx = 10, 5, 2200, 2600
    y = np.random.rand(e_count, s_count, ny, nx)
    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(3, 0, 0, 0),
    )
    row_axis = np.arange(ny, dtype=float)
    col_axis = np.arange(nx, dtype=float)
    plane = y[3].sum(axis=0)
    full_bundle = prepare_2d_bundle(
        plane,
        [row_axis, col_axis],
        ["dim_0", "dim_1"],
        render_mode_hint="image",
    )
    full_frame = frame_from_bundle(full_bundle)
    crop = view_crop_from_region(
        RectRegion(x0=581.93, y0=156.16, x1=1478.57, y1=899.24),
        full_frame,
        parent,
        ("x", "y", "uid"),
        row_axis,
        col_axis,
    )
    roi = RectRegion(x0=700, y0=200, x1=1200, y1=700)
    request = MaterializeRequest(
        profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="sum"),
        region=roi,
    )
    slice_info, mat_frame = fetch_context_with_view_crop(
        request,
        crop,
        parent,
    )
    y_load = y[tuple(slice_info)]
    assert y_load.ndim >= 2
    assert y_load.shape[-2:] == mat_frame.shape
    axes = [
        np.linspace(200, 500, e_count),
        np.arange(s_count),
        row_axis[slice_info[2]],
        col_axis[slice_info[3]],
    ]
    from nbs_viewer.models.plot.cube_view import materialize_view
    from nbs_viewer.models.plot.derived_fetch import plot_plane_storage_axes

    out, _, _ = materialize_view(
        y_load,
        axes,
        ["e", "s", "dim_0", "dim_1"],
        request,
        region_frame=mat_frame,
        plot_plane_storage_axes=plot_plane_storage_axes(parent),
    )
    assert out.ndim == 1
    assert out.size == e_count
