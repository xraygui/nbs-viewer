"""Tests for the one fetch planner and the display-ordered ROI mask.

These are ground-truth tests: the expected profile is computed by masking the
oriented stack directly, never from ``compiled.bbox``. The previous versions
compared the narrowed fetch against the same bounding box the fetch was built
from, which pinned two errors that cancelled -- a mask applied in display
order to a storage-order array, and a display bounding box applied straight
onto storage slices.
"""

import numpy as np
import pytest

from nbs_viewer.models.plot.view_spec import DimRole, Projection
from nbs_viewer.models.plot.plot_request import (
    PlotRequest,
    plan_fetch,
    roi_profile_request,
)
from nbs_viewer.models.plot.geometry.frame import region_frame_for_bbox
from nbs_viewer.models.plot.geometry.region import (
    PolygonRegion,
    RectRegion,
    compile_with_mask_mode,
)

from tests.fixtures.display_plane import (
    display_frame,
    oriented_plane,
    roi_profile_from_block,
)

E_COUNT, S_COUNT, NY, NX = 4, 3, 7, 8
PARENT = Projection(
    ndim=4,
    plot_ndim=2,
    roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
    indices=(1, 0, 0, 0),
)
# A right triangle, not a rectangle. A rectangular ROI fills its own
# bounding box, so its mask is invariant under the row/column reversal and it
# cannot tell a display-order mask from a storage-order one -- which is how
# the mask bug and the fetch bug hid each other for so long.
ROI = PolygonRegion(vertices=((1.0, 0.4), (5.4, 0.4), (1.0, 4.6)))

ORIENTATIONS = {
    "both ascending": (False, False),
    "row descending": (True, False),
    "col descending": (False, True),
    "both descending": (True, True),
}


def _stack():
    """
    A 4-D stack whose every cell names its own storage position.
    """
    return (
        np.arange(E_COUNT)[:, None, None, None] * 1000
        + np.arange(S_COUNT)[None, :, None, None] * 100
        + np.arange(NY)[None, None, :, None] * 10
        + np.arange(NX)[None, None, None, :]
    ).astype(float)


def _axes(row_descending, col_descending):
    row = np.arange(NY, dtype=float)
    col = np.arange(NX, dtype=float)
    if row_descending:
        row = row[::-1].copy()
    if col_descending:
        col = col[::-1].copy()
    return row, col


def _plane_request(parent=PARENT):
    """
    The request that draws the parent plane, with no ROI on it yet.
    """
    return PlotRequest(
        uid="uid",
        xkeys=("x",),
        ykey="y",
        norm_keys=(),
        view=parent,
        dims=tuple(f"dim_{axis}" for axis in range(parent.ndim)),
    )


def _profile_request(profile_axis=0, spatial_reduce="sum", region=ROI):
    return roi_profile_request(
        _plane_request(),
        region,
        profile_axis=profile_axis,
        spatial_reduce=spatial_reduce,
    )


def _ground_truth_profile(stack, row_axis, col_axis, frame):
    """
    Sum the ROI over the display plane, one value per energy step.

    Computed straight from the oriented stack and the compiled mask, with no
    narrowing and no view spec, so it does not share machinery with the code
    under test.
    """
    plane_stack = stack[PARENT.indices[0]].sum(axis=0)
    oriented, _, _, _ = oriented_plane(plane_stack, row_axis, col_axis)
    mask = compile_with_mask_mode(frame, ROI, "inside").mask

    profile = []
    for step in range(E_COUNT):
        step_plane, _, _, _ = oriented_plane(
            stack[step].sum(axis=0), row_axis, col_axis
        )
        profile.append(float(step_plane[mask].sum()))
    assert oriented.shape == mask.shape
    return np.asarray(profile)


@pytest.mark.parametrize(
    "row_descending,col_descending", ORIENTATIONS.values(), ids=ORIENTATIONS
)
def test_roi_profile_matches_ground_truth_in_every_orientation(
    row_descending, col_descending
):
    """
    The ROI mask must be applied to display-ordered data.

    Three of the four orientations were wrong before: the mask was compiled on
    the display plane and applied to a storage-order array.
    """
    stack = _stack()
    row_axis, col_axis = _axes(row_descending, col_descending)
    frame = display_frame(stack[1].sum(axis=0), row_axis, col_axis, ["y", "x"])
    expected = _ground_truth_profile(stack, row_axis, col_axis, frame)

    request = _profile_request()
    plan = plan_fetch(request, plane_frame=frame)

    loaded = stack[plan.slice_info]
    axis_arrays = [
        np.linspace(200.0, 500.0, E_COUNT),
        np.arange(S_COUNT, dtype=float),
        row_axis[plan.slice_info[2]],
        col_axis[plan.slice_info[3]],
    ]
    # No orientation. The block the fetch path holds is in the order the
    # source stored it; the ROI mask turns round instead, against the frame
    # the user drew on.
    profile, _, _ = roi_profile_from_block(
        loaded,
        axis_arrays,
        ["en_energy", "scan", "y", "x"],
        request,
        plan,
    )

    np.testing.assert_allclose(profile, expected)


@pytest.mark.parametrize(
    "row_descending,col_descending", ORIENTATIONS.values(), ids=ORIENTATIONS
)
def test_narrowed_fetch_reads_the_cells_the_roi_covers(
    row_descending, col_descending
):
    """
    The narrowing is a database optimisation, so the block it reads must
    contain every cell the ROI selects.
    """
    stack = _stack()
    row_axis, col_axis = _axes(row_descending, col_descending)
    frame = display_frame(stack[1].sum(axis=0), row_axis, col_axis, ["y", "x"])
    compiled = compile_with_mask_mode(frame, ROI, "inside")

    plan = plan_fetch(_profile_request(), plane_frame=frame)
    rows, cols = plan.slice_info[2], plan.slice_info[3]
    covered = np.zeros(frame.shape, dtype=bool)
    covered_storage = np.zeros(frame.shape, dtype=bool)
    covered_storage[rows, cols] = True
    oriented_cover, _, _, _ = oriented_plane(
        covered_storage, row_axis, col_axis
    )
    covered |= oriented_cover

    assert np.all(covered[compiled.mask])
    assert (rows.stop - rows.start) * (cols.stop - cols.start) < NY * NX


def test_profile_along_an_off_plane_axis_reads_that_axis_in_full():
    """
    A profile along energy holds energy at a single INDEX on the parent
    projection, so the planner has to widen it or the fetch returns one point.
    """
    stack = _stack()
    row_axis, col_axis = _axes(False, False)
    frame = display_frame(stack[1].sum(axis=0), row_axis, col_axis, ["y", "x"])

    plan = plan_fetch(_profile_request(), plane_frame=frame)

    assert plan.slice_info[0] == slice(None)
    assert stack[plan.slice_info].shape[0] == E_COUNT


def test_plan_fetch_rejects_an_roi_that_covers_no_cells():
    row_axis, col_axis = _axes(False, False)
    frame = display_frame(
        np.zeros((NY, NX)), row_axis, col_axis, ["y", "x"]
    )
    request = _profile_request(
        region=RectRegion(x0=100.0, x1=101.0, y0=100.0, y1=101.0)
    )
    with pytest.raises(ValueError, match="does not cover any cells"):
        plan_fetch(request, plane_frame=frame)


def test_region_frame_for_bbox_matches_crop_shape():
    frame = display_frame(
        np.zeros((8, 10)),
        np.arange(8, dtype=float),
        np.arange(10, dtype=float),
        ["y", "x"],
    )
    cropped = region_frame_for_bbox(frame, (2, 5, 3, 7))
    assert cropped.shape == (3, 4)


def test_region_frame_for_bbox_image_extent_keeps_bottom_below_top():
    y_count, x_count = 100, 100
    frame = display_frame(
        np.zeros((y_count, x_count)),
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
        ["dim_1", "dim_2"],
    )
    region = RectRegion(x0=34.77, x1=94.99, y0=40.36, y1=57.37)
    compiled = compile_with_mask_mode(frame, region.normalized(), "inside")
    cropped = region_frame_for_bbox(frame, compiled.bbox)

    assert cropped.extent is not None
    left, right, bottom, top = cropped.extent
    assert bottom < top
    assert left < right
    assert compile_with_mask_mode(cropped, region, "inside").pixel_count > 0


def test_large_roi_on_a_big_plane_recompiles_on_the_narrowed_frame():
    e_count, d0_count, y_count, x_count = 20, 5, 100, 100
    stack = np.random.default_rng(0).random((e_count, d0_count, y_count, x_count))
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(10, 0, 0, 0),
    )
    row_axis = np.arange(y_count, dtype=float)
    col_axis = np.arange(x_count, dtype=float)
    frame = display_frame(stack[10, 0], row_axis, col_axis, ["dim_1", "dim_2"])
    region = RectRegion(x0=34.77, x1=94.99, y0=40.36, y1=57.37)
    request = roi_profile_request(
        _plane_request(parent), region, profile_axis=0
    )

    plan = plan_fetch(request, plane_frame=frame)
    loaded = stack[plan.slice_info]
    axis_arrays = [
        np.arange(e_count, dtype=float),
        np.arange(d0_count, dtype=float),
        row_axis[plan.slice_info[2]],
        col_axis[plan.slice_info[3]],
    ]
    profile, _, _ = roi_profile_from_block(
        loaded,
        axis_arrays,
        ["en_energy", "dim_0", "dim_1", "dim_2"],
        request,
        plan,
    )

    assert profile.shape == (e_count,)
    assert np.isfinite(profile).all()
