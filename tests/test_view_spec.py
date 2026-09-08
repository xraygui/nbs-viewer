"""Headless tests for ViewIntent, ViewSpec, ViewCrop, and PlotRequest."""

import pytest

from nbs_viewer.models.plot.cube_view import DimRole, default_spec
from nbs_viewer.models.plot.plot_request import PlotRequest, plan_fetch
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.view_spec import (
    ViewCrop,
    ViewIntent,
    ViewSpec,
    default_view_spec,
    plot_axis_names,
)
from nbs_viewer.models.sources.fixtures import VPPEM_SHAPE, VPPEM_UID


def test_default_view_spec_matches_cube_default():
    for ndim in (1, 2, 3, 4):
        for plot_ndim in (1, 2):
            if ndim < plot_ndim:
                continue
            view = default_view_spec(ndim, plot_ndim)
            cube = default_spec(ndim, plot_ndim)
            assert view.roles == cube.roles
            assert view.indices == cube.indices
            assert view.axis_order == cube.axis_order
            assert view.base_slice() == cube.to_load_slice_info()


def test_view_spec_roundtrip_cube_view_spec():
    cube = default_spec(3, 2).with_index(0, 4)
    view = ViewSpec.from_cube_view_spec(cube)
    assert view.to_cube_view_spec() == cube
    assert view.base_slice() == (4, slice(None), slice(None))


def test_view_spec_rejects_ndim_below_plot_ndim():
    with pytest.raises(ValueError, match="below plot_ndim"):
        ViewSpec(
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
    view = default_view_spec(3, 2).with_index(0, 4)
    view = ViewSpec(
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
    view = ViewSpec(
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
        ViewSpec(
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
        ViewSpec(
            ndim=3,
            plot_ndim=2,
            roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
            indices=(0, 0, 0),
            crop=crop,
        )


def test_plan_fetch_intersects_the_crop_with_an_indexed_axis():
    crop = ViewCrop(storage_bbox=(2, 10, 4, 20), plot_y_axis=1, plot_x_axis=2)
    view = ViewSpec(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(4, 0, 0),
        crop=crop,
    )
    request = PlotRequest(
        uid=VPPEM_UID, xkeys=("x",), ykey="y", norm_keys=(), view=view
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
    spec = intent.project(3, VPPEM_SHAPE)
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
        axis_order=(1, 2, 0),
    )
    spec = intent.project(3, VPPEM_SHAPE)
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
    spec = intent.project(3, VPPEM_SHAPE)
    assert spec.roles == (DimRole.INDEX, DimRole.MEAN, DimRole.PLOT_X)
    assert spec.indices[0] == 0


def test_view_intent_project_clamps_index_to_shape():
    intent = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.INDEX,),
        reduce_indices=(99,),
    )
    spec = intent.project(3, VPPEM_SHAPE)
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


def test_view_intent_from_view_spec_roundtrip():
    original = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.INDEX, DimRole.MEAN),
        reduce_indices=(2, 0),
        axis_order=(0, 1, 2),
    )
    projected = original.project(3, VPPEM_SHAPE)
    lifted = ViewIntent.from_view_spec(projected)
    assert lifted.project(3, VPPEM_SHAPE) == projected


def test_plot_axis_names_compatibility():
    intent_1d = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.MEAN, DimRole.MEAN),
        reduce_indices=(0, 0),
        axis_order=(1, 2, 0),
    )
    image_spec = intent_1d.project(3, VPPEM_SHAPE)
    stats_spec = ViewIntent(plot_ndim=1).project(1, (11,))

    image_names = plot_axis_names(
        image_spec, ["sampleVoltage_VSource", "dim_1", "dim_2"]
    )
    stats_names = plot_axis_names(stats_spec, ["sampleVoltage_VSource"])
    assert image_names == ("sampleVoltage_VSource",)
    assert image_names == stats_names

    detector_intent = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.INDEX, DimRole.MEAN),
        reduce_indices=(0, 0),
        axis_order=(0, 1, 2),
    )
    detector_spec = detector_intent.project(3, VPPEM_SHAPE)
    detector_names = plot_axis_names(
        detector_spec, ["sampleVoltage_VSource", "dim_1", "dim_2"]
    )
    assert detector_names == ("dim_2",)
    assert detector_names != stats_names


def test_plot_request_hash_and_equality():
    view = default_view_spec(3, 2).with_index(0, 4)
    a = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=view,
    )
    b = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=view,
    )
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1


def test_plot_request_identity_changes_with_view_and_transform():
    base_view = default_view_spec(3, 2).with_index(0, 4)
    other_view = default_view_spec(3, 2).with_index(0, 5)
    base = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=base_view,
    )
    by_index = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=other_view,
    )
    by_transform = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=(),
        view=base_view,
        transform="y = y * 2",
    )
    by_norm = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        norm_keys=("i0",),
        view=base_view,
    )
    assert len({base, by_index, by_transform, by_norm}) == 4


def test_plot_request_empty_transform_means_off():
    view = default_view_spec(1, 1)
    off = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_stats",
        norm_keys=(),
        view=view,
        transform="",
    )
    assert off.transform == ""


def test_plot_request_roi_requires_1d_view():
    view_2d = default_view_spec(2, 2)
    with pytest.raises(ValueError, match="plot_ndim == 1"):
        PlotRequest(
            uid=VPPEM_UID,
            xkeys=("x",),
            ykey="image",
            norm_keys=(),
            view=view_2d,
            region=RectRegion(0.0, 1.0, 0.0, 1.0),
        )


def test_plot_request_roi_profile_ok():
    view_1d = ViewSpec(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.MEAN, DimRole.PLOT_X),
        indices=(0, 0),
    )
    req = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("x",),
        ykey="image",
        norm_keys=(),
        view=view_1d,
        region=RectRegion(0.0, 1.0, 0.0, 1.0),
        mask_mode="outside",
    )
    assert req.region is not None
    assert req.mask_mode == "outside"


def test_view_crop_rejects_empty_bbox():
    with pytest.raises(ValueError, match="non-empty"):
        ViewCrop(storage_bbox=(2, 2, 0, 3), plot_y_axis=0, plot_x_axis=1)
