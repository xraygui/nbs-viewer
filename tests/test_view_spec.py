"""Headless tests for ViewIntent, Projection, ViewCrop, and PlotRequest."""

import pytest

from tests.fixtures.view import intent_from_projection
from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.plane.roles import DimRole, ViewCrop
from nbs_viewer.models.plot.spec.projection import Projection
from nbs_viewer.models.plot.spec.request import PlotRequest
from nbs_viewer.models.plot.spec.plan import plan_fetch
from nbs_viewer.models.plot.spec.region import RectRegion
from nbs_viewer.models.sources.fixtures import VPPEM_SHAPE, VPPEM_UID


VPPEM_NAMES = ("sampleVoltage_VSource", "dim_1", "dim_2")


def test_projection_without_names_uses_trailing_axes():
    """With no dimension names there is nothing to orient by."""
    for ndim in (1, 2, 3, 4):
        for plot_ndim in (1, 2):
            if ndim < plot_ndim:
                continue
            view = ViewIntent(plot_ndim=plot_ndim).project(ndim)
            assert view.axis_order == tuple(range(ndim))
            assert view.indices == (0,) * ndim
            expected = (DimRole.INDEX,) * (ndim - plot_ndim) + (
                (DimRole.PLOT_X,)
                if plot_ndim == 1
                else (DimRole.PLOT_Y, DimRole.PLOT_X)
            )
            assert view.roles == expected


def test_view_spec_rejects_ndim_below_plot_ndim():
    with pytest.raises(ValueError, match="below plot_ndim"):
        Projection(
            ndim=1,
            plot_ndim=2,
            roles=(DimRole.PLOT_X,),
            indices=(0,),
        )


def test_view_spec_base_slice_ignores_crop():
    """
    A crop rides on the view but is applied by ``plan_fetch``, the one place
    a load is narrowed.
    """
    crop = ViewCrop(
        storage_bbox=(2, 10, 4, 20),
        plot_y_axis=1,
        plot_x_axis=2,
    )
    view = ViewIntent(plot_ndim=2).project(3, dim_names=VPPEM_NAMES).with_index(0, 4)
    view = Projection(
        ndim=view.ndim,
        plot_ndim=view.plot_ndim,
        roles=view.roles,
        indices=view.indices,
        axis_order=view.axis_order,
        crop=crop,
    )
    assert view.base_slice() == (4, slice(None), slice(None))


def test_view_spec_crop_allowed_on_a_profile_view():
    """
    An ROI profile reduces the plane to 1-D, so the crop is the only record
    of the plane left. Rejecting it here made an ROI on a cropped plane
    unrepresentable.
    """
    crop = ViewCrop(storage_bbox=(0, 2, 0, 3), plot_y_axis=0, plot_x_axis=1)
    view = Projection(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.INDEX, DimRole.PLOT_X),
        indices=(0, 0),
        crop=crop,
    )
    assert view.crop is crop


def test_view_spec_crop_axes_must_be_in_range():
    crop = ViewCrop(storage_bbox=(0, 2, 0, 3), plot_y_axis=0, plot_x_axis=5)
    with pytest.raises(ValueError, match="out of range"):
        Projection(
            ndim=2,
            plot_ndim=1,
            roles=(DimRole.INDEX, DimRole.PLOT_X),
            indices=(0, 0),
            crop=crop,
        )


def test_view_spec_crop_axes_must_match_plot_order():
    crop = ViewCrop(storage_bbox=(0, 2, 0, 3), plot_y_axis=0, plot_x_axis=1)
    with pytest.raises(ValueError, match="crop plot axes must match"):
        # default 3-D 2-D plot has plot axes (1, 2), not (0, 1)
        Projection(
            ndim=3,
            plot_ndim=2,
            roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
            indices=(0, 0, 0),
            crop=crop,
        )


def test_plan_fetch_intersects_the_crop_with_an_indexed_axis():
    crop = ViewCrop(storage_bbox=(2, 10, 4, 20), plot_y_axis=1, plot_x_axis=2)
    view = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(4, 0, 0),
        crop=crop,
    )
    request = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("x",),
        ykey="y",
        norm_keys=(),
        view=view,
        dims=VPPEM_NAMES,
    )
    plan = plan_fetch(request)
    assert plan.slice_info == (4, slice(2, 10), slice(4, 20))
    assert plan.plane_axes == (1, 2)


def test_view_intent_project_3d_to_2d():
    intent = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.INDEX,),
        reduce_indices=(4,),
    )
    spec = intent.project(3, VPPEM_SHAPE, VPPEM_NAMES)
    assert spec.ndim == 3
    assert spec.plot_ndim == 2
    assert spec.roles == (DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X)
    assert spec.indices[0] == 4
    assert spec.base_slice() == (4, slice(None), slice(None))


def test_view_intent_project_3d_to_1d_mean_mean():
    intent = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.MEAN, DimRole.MEAN),
        reduce_indices=(0, 0),
        dim_order=("dim_1", "dim_2", "sampleVoltage_VSource"),
    )
    spec = intent.project(3, VPPEM_SHAPE, VPPEM_NAMES)
    assert spec.roles[0] == DimRole.PLOT_X
    assert spec.roles[1] == DimRole.MEAN
    assert spec.roles[2] == DimRole.MEAN
    assert spec.base_slice() == (slice(None), slice(None), slice(None))


def test_view_intent_project_drops_outermost_reduce_for_smaller_rank():
    """3-D intent (2 reduce axes) projected to 2-D keeps the innermost reduce."""
    intent = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.INDEX, DimRole.SUM),
        reduce_indices=(3, 0),
    )
    spec = intent.project(2, (11, 32))
    assert spec.ndim == 2
    assert spec.roles == (DimRole.SUM, DimRole.PLOT_X)
    assert spec.indices[0] == 0


def test_view_intent_project_pads_outermost_when_reduce_short():
    intent = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.MEAN,),
        reduce_indices=(0,),
    )
    spec = intent.project(3, VPPEM_SHAPE, VPPEM_NAMES)
    assert spec.roles == (DimRole.INDEX, DimRole.MEAN, DimRole.PLOT_X)
    assert spec.indices[0] == 0


def test_view_intent_project_clamps_index_to_shape():
    intent = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.INDEX,),
        reduce_indices=(99,),
    )
    spec = intent.project(3, VPPEM_SHAPE, VPPEM_NAMES)
    assert spec.indices[0] == VPPEM_SHAPE[0] - 1


def test_view_intent_refuses_rank_below_plot_ndim():
    intent = ViewIntent(plot_ndim=2)
    with pytest.raises(ValueError, match="cannot project intent"):
        intent.project(1, (11,))


def test_view_intent_1d_key_with_1d_plot():
    intent = ViewIntent(plot_ndim=1)
    spec = intent.project(1, (11,))
    assert spec.roles == (DimRole.PLOT_X,)
    assert spec.base_slice() == (slice(None),)


def test_projection_round_trips_through_the_test_lift():
    original = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.INDEX, DimRole.MEAN),
        reduce_indices=(2, 0),
    )
    projected = original.project(3, VPPEM_SHAPE, VPPEM_NAMES)
    lifted = intent_from_projection(projected)
    assert lifted.project(3, VPPEM_SHAPE) == projected


def test_projected_axis_names_compatibility():
    intent_1d = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.MEAN, DimRole.MEAN),
        reduce_indices=(0, 0),
        dim_order=("dim_1", "dim_2", "sampleVoltage_VSource"),
    )
    image_spec = intent_1d.project(3, VPPEM_SHAPE, VPPEM_NAMES)
    stats_spec = ViewIntent(plot_ndim=1).project(1, (11,))

    image_names = image_spec.plot_dim_names(["sampleVoltage_VSource", "dim_1", "dim_2"])
    stats_names = stats_spec.plot_dim_names(["sampleVoltage_VSource"])
    assert image_names == ("sampleVoltage_VSource",)
    assert image_names == stats_names

    detector_intent = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.INDEX, DimRole.MEAN),
        reduce_indices=(0, 0),
    )
    detector_spec = detector_intent.project(3, VPPEM_SHAPE, VPPEM_NAMES)
    detector_names = detector_spec.plot_dim_names(["sampleVoltage_VSource", "dim_1", "dim_2"])
    assert detector_names == ("dim_2",)
    assert detector_names != stats_names


def test_plot_request_hash_and_equality():
    view = ViewIntent(plot_ndim=2).project(3, dim_names=VPPEM_NAMES).with_index(0, 4)
    a = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=view,
        dims=VPPEM_NAMES,
    )
    b = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=view,
        dims=VPPEM_NAMES,
    )
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_plot_request_identity_changes_with_view_and_transform():
    base_view = ViewIntent(plot_ndim=2).project(3, dim_names=VPPEM_NAMES).with_index(0, 4)
    other_view = ViewIntent(plot_ndim=2).project(3, dim_names=VPPEM_NAMES).with_index(0, 5)
    base = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=base_view,
        dims=VPPEM_NAMES,
    )
    by_index = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=other_view,
        dims=VPPEM_NAMES,
    )
    by_transform = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=base_view,
        dims=VPPEM_NAMES,
        transform="y = y * 2",
    )
    by_norm = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=("i0",),
        view=base_view,
        dims=VPPEM_NAMES,
    )
    assert len({base, by_index, by_transform, by_norm}) == 4


def test_plot_request_empty_transform_means_off():
    view = ViewIntent(plot_ndim=1).project(1)
    off = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_stats",
        norm_keys=(),
        view=view,
        dims=("sampleVoltage_VSource",),
        transform="",
    )
    assert off.transform == ""


def test_plot_request_roi_requires_the_parent_plane():
    """
    A profile request carries the plane the ROI was drawn on, not the profile
    it reduces to. A 1-D view has no plane for the region to mean anything on.
    """
    view_1d = Projection(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.MEAN, DimRole.PLOT_X),
        indices=(0, 0),
    )
    with pytest.raises(ValueError, match="plot_ndim == 2"):
        PlotRequest(
            uid=VPPEM_UID,
            xkeys=("x",),
            ykey="image",
            norm_keys=(),
            view=view_1d,
            dims=("dim_0", "dim_1"),
            region=RectRegion(0.0, 1.0, 0.0, 1.0),
            profile_axis=1,
        )


def test_plot_request_roi_requires_a_profile_axis():
    with pytest.raises(ValueError, match="require a profile_axis"):
        PlotRequest(
            uid=VPPEM_UID,
            xkeys=("x",),
            ykey="image",
            norm_keys=(),
            view=ViewIntent(plot_ndim=2).project(2),
            dims=("dim_0", "dim_1"),
            region=RectRegion(0.0, 1.0, 0.0, 1.0),
        )


def test_plot_request_roi_rejects_a_reduced_profile_axis():
    """
    A profile axis has to be on the plane or held at an index. A summed axis
    is already gone by the time the profile is taken.
    """
    view = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0),
    )
    with pytest.raises(ValueError, match="plot-plane axis or an indexed axis"):
        PlotRequest(
            uid=VPPEM_UID,
            xkeys=("x",),
            ykey="image",
            norm_keys=(),
            view=view,
            dims=("dim_0", "dim_1", "dim_2"),
            region=RectRegion(0.0, 1.0, 0.0, 1.0),
            profile_axis=0,
        )


def test_plot_request_roi_profile_ok():
    view = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0),
    )
    req = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("x",),
        ykey="image",
        norm_keys=(),
        view=view,
        dims=("dim_0", "dim_1", "dim_2"),
        region=RectRegion(0.0, 1.0, 0.0, 1.0),
        mask_mode="outside",
        profile_axis=0,
        spatial_reduce="mean",
    )
    assert req.region is not None
    assert req.mask_mode == "outside"
    assert req.plane_axes == (1, 2)
    assert req.output_ndim == 1


def test_view_crop_rejects_empty_bbox():
    with pytest.raises(ValueError, match="non-empty"):
        ViewCrop(storage_bbox=(2, 2, 0, 3), plot_y_axis=0, plot_x_axis=1)


def test_projection_1d_trailing_axis():
    spec = ViewIntent(plot_ndim=1).project(4)
    assert spec.roles == (
        DimRole.INDEX,
        DimRole.INDEX,
        DimRole.INDEX,
        DimRole.PLOT_X,
    )
    assert spec.base_slice() == (0, 0, 0, slice(None))


def test_projection_2d_trailing_axes():
    spec = ViewIntent(plot_ndim=2).project(4)
    assert spec.roles[-2:] == (DimRole.PLOT_Y, DimRole.PLOT_X)
    assert spec.base_slice()[-2:] == (slice(None), slice(None))


def test_spec_from_slice_info_roundtrip():
    legacy = (0, 0, slice(None))
    spec = Projection.from_slice_info(legacy, plot_ndim=1)
    assert spec.roles[0] == DimRole.INDEX
    assert spec.roles[-1] == DimRole.PLOT_X


def test_swap_rows_exchanges_roles():
    spec = ViewIntent(plot_ndim=1).project(3, dim_names=VPPEM_NAMES)
    swapped = spec.swap_rows(1)
    d0, d1 = spec.axis_order[0], spec.axis_order[1]
    assert swapped.roles[d0] == spec.roles[d1]
    assert swapped.roles[d1] == spec.roles[d0]


def test_construction_assigns_plot_x_from_axis_order():
    spec = Projection(
        ndim=3,
        plot_ndim=1,
        roles=(DimRole.SUM, DimRole.INDEX, DimRole.INDEX),
        indices=(0, 0, 0),
        axis_order=(2, 0, 1),
    )
    assert spec.roles[1] == DimRole.PLOT_X
    assert spec.roles[0] == DimRole.SUM


def test_swap_rows_moves_plot_axis():
    spec = ViewIntent(plot_ndim=1).project(3, dim_names=VPPEM_NAMES)
    swapped = spec.swap_rows(2)
    assert swapped.roles[swapped.axis_order[-1]] == DimRole.PLOT_X


def test_with_slice_role():
    spec = ViewIntent(plot_ndim=1).project(3, dim_names=VPPEM_NAMES)
    updated = spec.with_slice_role(0, DimRole.SUM)
    assert updated.roles[0] == DimRole.SUM


def test_changing_plot_ndim_reassigns_the_plane():
    """Switching 1-D to 2-D is a mutation on the intent, not a spec rewrite."""
    intent = ViewIntent(plot_ndim=1)
    assert intent.set_plot_ndim(2) is True
    spec2 = intent.project(4)
    assert spec2.plot_ndim == 2
    assert spec2.roles[-2:] == (DimRole.PLOT_Y, DimRole.PLOT_X)


def test_construction_fixes_duplicate_plot_x():
    spec = Projection(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.PLOT_X, DimRole.PLOT_X),
        indices=(0, 0),
    )
    assert sum(1 for r in spec.roles if r == DimRole.PLOT_X) == 1
