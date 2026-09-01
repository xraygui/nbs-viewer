"""Tests for ROI-aware fetch slice_info (Phase 2b)."""

import numpy as np

from nbs_viewer.models.plot.cube_view import (
    CubeViewSpec,
    DimRole,
    MaterializeRequest,
    materialize_view,
    profile_view_spec,
)
from nbs_viewer.models.plot.plot_geometry import prepare_2d_bundle
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle, region_frame_for_bbox
from nbs_viewer.models.plot.region import RectRegion, compile_with_mask_mode


def test_to_fetch_slice_info_narrows_plot_plane_axes():
    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    y_count, x_count = 5, 6
    bundle = prepare_2d_bundle(
        np.zeros((y_count, x_count)),
        [np.arange(y_count), np.arange(x_count)],
        ["y", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    request = MaterializeRequest(
        profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="sum"),
        region=region,
    )

    slice_info = request.to_fetch_slice_info(
        region_frame=frame,
        parent_spec=parent,
    )

    assert slice_info[0] == slice(None)
    assert slice_info[1] == slice(None)
    compiled = compile_with_mask_mode(frame, region.normalized(), "inside")
    r0, r1, c0, c1 = compiled.bbox
    assert slice_info[2] == slice(r0, r1)
    assert slice_info[3] == slice(c0, c1)


def test_bbox_fetch_matches_full_materialize_stack_profile():
    e_count, s_count, y_count, x_count = 4, 3, 5, 6
    y = (
        np.arange(e_count)[:, None, None, None] * 1000
        + np.arange(y_count)[None, None, :, None] * 10
        + np.arange(x_count)[None, None, None, :]
    ).astype(float)

    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    y_parent = y.sum(axis=1)[1]
    bundle = prepare_2d_bundle(
        y_parent,
        [np.arange(y_count), np.arange(x_count)],
        ["y", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    request = MaterializeRequest(
        profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="sum"),
        region=region,
    )
    e_axis = np.linspace(200.0, 500.0, e_count)

    profile_full, _, names_full = materialize_view(
        y,
        [e_axis, np.arange(s_count), np.arange(y_count), np.arange(x_count)],
        ["en_energy", "scan", "y", "x"],
        request,
        region_frame=frame,
        plot_plane_storage_axes=(2, 3),
    )

    fetch_slice, cropped_frame = request.fetch_context(
        region_frame=frame,
        parent_spec=parent,
    )
    y_fetch = y[fetch_slice]
    axis_fetch = [
        axis[fetch_slice[i]] if isinstance(fetch_slice[i], slice) else axis
        for i, axis in enumerate(
            [e_axis, np.arange(s_count), np.arange(y_count), np.arange(x_count)]
        )
    ]

    profile_fetch, _, names_fetch = materialize_view(
        y_fetch,
        axis_fetch,
        ["en_energy", "scan", "y", "x"],
        request,
        region_frame=cropped_frame,
        plot_plane_storage_axes=(2, 3),
    )

    np.testing.assert_allclose(profile_fetch, profile_full, rtol=1e-5, equal_nan=True)
    assert names_fetch == names_full
    assert cropped_frame.shape == region_frame_for_bbox(
        frame, compile_with_mask_mode(frame, region.normalized(), "inside").bbox
    ).shape


def test_region_frame_for_bbox_matches_crop_shape():
    bundle = prepare_2d_bundle(
        np.zeros((8, 10)),
        [np.arange(8), np.arange(10)],
        ["y", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    cropped = region_frame_for_bbox(frame, (2, 5, 3, 7))
    assert cropped.shape == (3, 4)


def test_region_frame_for_bbox_image_extent_keeps_bottom_below_top():
    y_count, x_count = 100, 100
    bundle = prepare_2d_bundle(
        np.zeros((y_count, x_count)),
        [np.arange(y_count, dtype=float), np.arange(x_count, dtype=float)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=34.77, x1=94.99, y0=40.36, y1=57.37)
    compiled = compile_with_mask_mode(frame, region.normalized(), "inside")
    cropped = region_frame_for_bbox(frame, compiled.bbox)

    assert cropped.extent is not None
    left, right, bottom, top = cropped.extent
    assert bottom < top
    assert left < right
    assert compile_with_mask_mode(cropped, region, "inside").pixel_count > 0


def test_bbox_fetch_stack_profile_large_roi_recompiles_on_cropped_frame():
    e_count, d0_count, y_count, x_count = 20, 5, 100, 100
    y = np.random.default_rng(0).random((e_count, d0_count, y_count, x_count))
    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(10, 0, 0, 0),
    )
    bundle = prepare_2d_bundle(
        y[10, 0],
        [np.arange(y_count, dtype=float), np.arange(x_count, dtype=float)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=34.77, x1=94.99, y0=40.36, y1=57.37)
    request = MaterializeRequest(
        profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="sum"),
        region=region,
    )

    fetch_slice, cropped_frame = request.fetch_context(
        region_frame=frame,
        parent_spec=parent,
    )
    y_fetch = y[fetch_slice]
    axis_fetch = [
        axis[fetch_slice[i]] if isinstance(fetch_slice[i], slice) else axis
        for i, axis in enumerate(
            [
                np.arange(e_count, dtype=float),
                np.arange(d0_count, dtype=float),
                np.arange(y_count, dtype=float),
                np.arange(x_count, dtype=float),
            ]
        )
    ]

    profile, _, _ = materialize_view(
        y_fetch,
        axis_fetch,
        ["en_energy", "dim_0", "dim_1", "dim_2"],
        request,
        region_frame=cropped_frame,
        plot_plane_storage_axes=(2, 3),
    )

    assert profile.shape == (e_count,)
    assert np.isfinite(profile).any()
