"""Tests for the persistent view crop on the main display fetch path."""

from dataclasses import replace

import numpy as np

from nbs_viewer.models.plot.view_spec import DimRole, Projection, ViewCrop
from nbs_viewer.models.plot.plot_request import (
    PlotRequest,
    crop_from_region,
    plan_fetch,
    roi_profile_request,
)
from nbs_viewer.models.plot.region import RectRegion

from tests.fixtures.display_plane import (
    display_bundle,
    display_frame,
    roi_profile_from_block,
)


def _make_full_frame(y_count=5, x_count=6):
    return display_frame(
        np.zeros((y_count, x_count)),
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
        ["y", "x"],
    )


def _plane_request(parent, crop=None):
    return PlotRequest(
        uid="uid",
        xkeys=("x",),
        ykey="y",
        norm_keys=(),
        view=replace(parent, crop=crop),
        dims=tuple(f"dim_{axis}" for axis in range(parent.ndim)),
    )


def test_plan_fetch_narrows_plot_plane_axes_with_a_crop():
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    crop = ViewCrop(storage_bbox=(1, 3, 2, 5), plot_y_axis=2, plot_x_axis=3)

    narrowed = plan_fetch(_plane_request(parent, crop)).slice_info

    assert narrowed[0] == 1
    assert narrowed[1] == slice(None)
    assert narrowed[2] == slice(1, 3)
    assert narrowed[3] == slice(2, 5)


def test_crop_from_region_maps_the_drawn_box_back_to_storage():
    full_frame = _make_full_frame(y_count=5, x_count=6)
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)

    crop = crop_from_region(region, full_frame, (0, 1))

    assert full_frame.row_reversed
    assert crop.storage_bbox == (1, 3, 2, 4)
    assert crop.plot_y_axis == 0
    assert crop.plot_x_axis == 1


def test_storage_bbox_inverts_row_flip_for_bottom_roi():
    ny, nx = 2200, 2600
    row_axis = np.arange(ny, dtype=float)
    col_axis = np.arange(nx, dtype=float)
    y = np.zeros((ny, nx))
    frame = display_frame(y, row_axis, col_axis)
    region = RectRegion(x0=581.93, y0=156.16, x1=1478.57, y1=899.24)

    crop = crop_from_region(region, frame, (0, 1))

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
    e_count, y_count, x_count = 4, 5, 6
    y = (
        np.arange(e_count)[:, None, None, None] * 1000
        + np.arange(y_count)[None, None, :, None] * 10
        + np.arange(x_count)[None, None, None, :]
    ).astype(float)
    y_step = y.sum(axis=1)[1]

    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    row_axis = np.arange(y_count, dtype=float)
    col_axis = np.arange(x_count, dtype=float)
    full_frame = display_frame(y_step, row_axis, col_axis, ["y", "x"])
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    crop = crop_from_region(region, full_frame, (2, 3))

    cropped_slice = plan_fetch(_plane_request(parent, crop)).slice_info

    sr0, sr1, sc0, sc1 = crop.storage_bbox
    assert y[1].sum(axis=0)[sr0:sr1, sc0:sc1].shape == (
        sr1 - sr0,
        sc1 - sc0,
    )
    assert cropped_slice[2] == slice(sr0, sr1)
    assert cropped_slice[3] == slice(sc0, sc1)


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
    not the ROI box on its own. The profile axis is off the plane, so it has
    to be widened back to the full axis even though the projection indexes it.
    """
    e_count, s_count, ny, nx = 10, 5, 2200, 2600
    y = np.random.default_rng(0).random((e_count, s_count, ny, nx))
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(3, 0, 0, 0),
    )
    row_axis = np.arange(ny, dtype=float)
    col_axis = np.arange(nx, dtype=float)
    full_frame = display_frame(y[3].sum(axis=0), row_axis, col_axis)
    crop = crop_from_region(
        RectRegion(x0=581.93, y0=156.16, x1=1478.57, y1=899.24),
        full_frame,
        (2, 3),
    )
    roi = RectRegion(x0=700, y0=200, x1=1200, y1=700)
    request = roi_profile_request(
        _plane_request(parent, crop), roi, profile_axis=0
    )

    plan = plan_fetch(request, plane_frame=full_frame)
    assert plan.slice_info[0] == slice(None)
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
    out, _, _ = roi_profile_from_block(
        y_load,
        axes,
        ["e", "s", "dim_0", "dim_1"],
        request,
        plan,
    )
    assert out.ndim == 1
    assert out.size == e_count
