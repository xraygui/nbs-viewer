"""Tests for persistent view crop on the main display fetch path."""

import numpy as np

from nbs_viewer.models.plot.cube_view import (
    CubeViewSpec,
    DimRole,
    MaterializeRequest,
    materialize_view,
    profile_view_spec,
)
from nbs_viewer.models.plot.plot_geometry import orient_for_display
from nbs_viewer.models.plot.derived_fetch import region_frame_for_roi_preview
from nbs_viewer.models.plot.plot_request import PlotRequest, plan_fetch
from nbs_viewer.models.plot.plot_view_frame import region_frame_for_bbox
from nbs_viewer.models.plot.region import RectRegion, compile_covering_rect
from nbs_viewer.models.plot.view_crop import view_crop_from_region
from nbs_viewer.models.plot.view_spec import ViewCrop as SlimViewCrop, ViewSpec

from tests.fixtures.display_plane import display_bundle, display_frame


def _make_full_frame(y_count=5, x_count=6):
    return display_frame(
        np.zeros((y_count, x_count)),
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
        ["y", "x"],
    )


def _profile_request(parent, region, crop=None, profile_storage_axis=0):
    """
    Build the ROI profile request the fetch path would carry.
    """
    spec = profile_view_spec(
        parent, profile_storage_axis=profile_storage_axis, spatial_reduce="sum"
    )
    return PlotRequest(
        uid="uid",
        xkeys=("x",),
        ykey="y",
        norm_keys=(),
        view=ViewSpec.from_cube_view_spec(spec, crop=crop),
        region=region,
    )


def test_plan_fetch_narrows_plot_plane_axes_with_a_crop():
    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    crop = SlimViewCrop(storage_bbox=(1, 3, 2, 5), plot_y_axis=2, plot_x_axis=3)
    request = PlotRequest(
        uid="uid",
        xkeys=("x",),
        ykey="y",
        norm_keys=(),
        view=ViewSpec.from_cube_view_spec(parent, crop=crop),
    )

    narrowed = plan_fetch(request).slice_info

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
    frame = display_frame(y, row_axis, col_axis)
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
    )

    assert crop.display_bbox == (1300, 2044, 582, 1480)
    assert crop.storage_bbox == (156, 900, 582, 1480)

    sr0, sr1, sc0, sc1 = crop.storage_bbox
    cropped = display_bundle(
        y[sr0:sr1, sc0:sc1], row_axis[sr0:sr1], col_axis[sc0:sc1]
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
    full_frame = display_frame(y_step, row_axis, col_axis, ["y", "x"])
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    crop = view_crop_from_region(
        region,
        full_frame,
        parent,
        ("x", "y", "uid"),
    )

    request = PlotRequest(
        uid="uid",
        xkeys=("x",),
        ykey="y",
        norm_keys=(),
        view=ViewSpec.from_cube_view_spec(
            parent,
            crop=SlimViewCrop(
                storage_bbox=crop.storage_bbox,
                plot_y_axis=crop.plot_y_axis,
                plot_x_axis=crop.plot_x_axis,
            ),
        ),
    )
    cropped_slice = plan_fetch(request).slice_info

    sr0, sr1, sc0, sc1 = crop.storage_bbox
    assert y[1].sum(axis=0)[sr0:sr1, sc0:sc1].shape == (
        sr1 - sr0,
        sc1 - sc0,
    )
    assert cropped_slice[2] == slice(sr0, sr1)
    assert cropped_slice[3] == slice(sc0, sc1)


def test_region_frame_for_roi_preview_uses_full_frame_on_nd_load():
    y_count, x_count = 5, 6
    full_frame = _make_full_frame(y_count, x_count)
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    compiled = compile_covering_rect(full_frame, region)
    cropped_frame = region_frame_for_bbox(full_frame, compiled.bbox)
    cropped_bundle = display_bundle(
        np.zeros(cropped_frame.shape),
        np.arange(cropped_frame.shape[0], dtype=float),
        np.arange(cropped_frame.shape[1], dtype=float),
        ["y", "x"],
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
    )
    from nbs_viewer.models.plot.view_crop import crop_status_text

    text = crop_status_text(crop)
    assert "913" not in text
    assert "4.50" in text or "4.5" in text


def test_storage_bbox_is_identity_when_nothing_was_reversed():
    bbox = (1, 4, 2, 5)
    frame = display_frame(
        np.zeros((10, 12)),
        np.arange(10, 0, -1, dtype=float),
        np.arange(12, dtype=float),
    )
    assert not frame.row_reversed and not frame.col_reversed
    assert frame.storage_bbox(bbox) == bbox


def test_roi_under_a_crop_loads_the_intersection_and_a_matching_frame():
    """
    Crop and ROI narrow the same load. The region frame must describe the
    block that is actually read -- the ROI box intersected with the crop --
    not the ROI box on its own.
    """
    e_count, s_count, ny, nx = 10, 5, 2200, 2600
    y = np.random.default_rng(0).random((e_count, s_count, ny, nx))
    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(3, 0, 0, 0),
    )
    row_axis = np.arange(ny, dtype=float)
    col_axis = np.arange(nx, dtype=float)
    full_frame = display_frame(y[3].sum(axis=0), row_axis, col_axis)
    crop = view_crop_from_region(
        RectRegion(x0=581.93, y0=156.16, x1=1478.57, y1=899.24),
        full_frame,
        parent,
        ("x", "y", "uid"),
    )
    roi = RectRegion(x0=700, y0=200, x1=1200, y1=700)
    request = _profile_request(
        parent,
        roi,
        crop=SlimViewCrop(
            storage_bbox=crop.storage_bbox,
            plot_y_axis=crop.plot_y_axis,
            plot_x_axis=crop.plot_x_axis,
        ),
    )

    plan = plan_fetch(request, plane_frame=full_frame, plane_axes=(2, 3))
    y_load = y[tuple(plan.slice_info)]
    assert y_load.shape[-2:] == plan.region_frame.shape

    crop_rows = range(*crop.storage_bbox[:2])
    assert plan.slice_info[2].start in crop_rows
    assert plan.slice_info[2].stop <= crop.storage_bbox[1]

    axes = [
        np.linspace(200, 500, e_count),
        np.arange(s_count),
        row_axis[plan.slice_info[2]],
        col_axis[plan.slice_info[3]],
    ]
    y_load, axes = orient_for_display(
        y_load,
        axes,
        plan.reversed_axes_for(axes, "image"),
        {0: 0, 1: 1, 2: 2, 3: 3},
    )
    out, _, _ = materialize_view(
        y_load,
        axes,
        ["e", "s", "dim_0", "dim_1"],
        MaterializeRequest(
            request.view.to_cube_view_spec(), request.region, request.mask_mode
        ),
        region_frame=plan.region_frame,
        plot_plane_storage_axes=plan.plane_axes,
    )
    assert out.ndim == 1
    assert out.size == e_count
