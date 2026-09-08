"""Tests for PlotRequest construction from legacy view state and RunSource fetch."""

import numpy as np
import pytest

from nbs_viewer.models.plot.view_spec import (
    DimRole,
    default_spec,
)
from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.region import PolygonRegion, compile_with_mask_mode
from nbs_viewer.models.plot.plot_request import (
    build_plot_request,
    plan_fetch,
    roi_profile_request,
    projection_for_shape,
)
from nbs_viewer.models.plot.runSource import RunSource
from nbs_viewer.models.plot.view_spec import ViewCrop
from nbs_viewer.models.sources.fixtures import (
    VPPEM_SHAPE,
    VPPEM_UID,
    make_vppem_data,
    make_vppem_metadata,
    make_vppem_run,
    vppem_factors,
)


def test_projection_for_shape_prefers_matching_cube_spec():
    cube = default_spec(3, 2).with_index(0, 4)
    view = projection_for_shape(
        shape=VPPEM_SHAPE,
        plot_ndim=2,
        projection=cube,
        slice_info=(0, slice(None), slice(None)),
    )
    assert view.indices[0] == 4
    assert view.base_slice() == (4, slice(None), slice(None))


def test_projection_for_shape_uses_slice_info_when_no_cube():
    slice_info = (3, slice(None), slice(None))
    view = projection_for_shape(
        shape=VPPEM_SHAPE,
        plot_ndim=2,
        slice_info=slice_info,
    )
    assert view.roles[0] == DimRole.INDEX
    assert view.indices[0] == 3
    assert view.plot_ndim == 2


def test_projection_for_shape_rank1_with_2d_plot_ndim_falls_back():
    view = projection_for_shape(shape=(11,), plot_ndim=2)
    assert view.ndim == 1
    assert view.plot_ndim == 1
    assert view.roles == (DimRole.PLOT_X,)


def test_plan_fetch_narrows_the_load_with_the_request_crop():
    cube = default_spec(3, 2).with_index(0, 4)
    crop = ViewCrop(storage_bbox=(2, 10, 4, 20), plot_y_axis=1, plot_x_axis=2)
    req = build_plot_request(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",),
        ykey="PCOEdge_image",
        shape=VPPEM_SHAPE,
        plot_ndim=2,
        projection=cube,
        crop=crop,
    )
    assert req.view.base_slice() == (4, slice(None), slice(None))
    assert plan_fetch(req).slice_info == (4, slice(2, 10), slice(4, 20))


def test_run_model_get_plot_bundle_from_request():
    run = make_vppem_run()
    model = RunSource(run)
    a, b, c = vppem_factors()
    cube = default_spec(3, 2).with_index(0, 4)
    xkeys = ["sampleVoltage_VSource"]
    ykey = "PCOEdge_image"

    req = build_plot_request(
        uid=run.uid,
        xkeys=xkeys,
        ykey=ykey,
        shape=VPPEM_SHAPE,
        plot_ndim=2,
        projection=cube,
    )
    via_request = model.get_plot_bundle(req)

    assert via_request.render_mode == "image"
    expected = a[4] * np.outer(b, c)
    np.testing.assert_allclose(via_request.y, expected[::-1, :])


def test_run_model_get_plot_bundle_request_with_crop():
    run = make_vppem_run()
    model = RunSource(run)
    a, b, c = vppem_factors()
    cube = default_spec(3, 2).with_index(0, 4)
    crop = ViewCrop(storage_bbox=(2, 10, 4, 20), plot_y_axis=1, plot_x_axis=2)
    req = build_plot_request(
        uid=run.uid,
        xkeys=["sampleVoltage_VSource"],
        ykey="PCOEdge_image",
        shape=VPPEM_SHAPE,
        plot_ndim=2,
        projection=cube,
        crop=crop,
    )
    bundle = model.get_plot_bundle(req)
    expected = (a[4] * np.outer(b, c))[2:10, 4:20]
    np.testing.assert_allclose(bundle.y, expected[::-1, :])


def test_plot_data_model_holds_request_and_fetches():
    from nbs_viewer.models.plot.view_spec import (
    Projection,
)
    from nbs_viewer.models.plot.trace import Trace
    from nbs_viewer.models.plot.plot_request import TraceKey, build_plot_request

    run = make_vppem_run()
    model = RunSource(run)
    cube = Projection(
        ndim=3,
        plot_ndim=1,
        roles=(DimRole.PLOT_X, DimRole.MEAN, DimRole.MEAN),
        indices=(0, 0, 0),
        axis_order=(1, 2, 0),
    )
    request = build_plot_request(
        uid=run.uid,
        xkeys=["sampleVoltage_VSource"],
        ykey="PCOEdge_image",
        shape=VPPEM_SHAPE,
        plot_ndim=1,
        projection=cube,
    )
    plot_data = Trace(model, request)
    assert plot_data.trace_key == TraceKey(
        run.uid, "sampleVoltage_VSource", "PCOEdge_image"
    )
    bundle = plot_data.get_plot_bundle()
    np.testing.assert_allclose(bundle.y, run.getData("PCOEdge_stats"))
    assert plot_data.last_fetched_request == request


def test_set_request_keeps_trace_key():
    from nbs_viewer.models.plot.trace import Trace

    run = make_vppem_run()
    model = RunSource(run)
    cube = default_spec(3, 2).with_index(0, 4)
    first = build_plot_request(
        uid=run.uid,
        xkeys=["sampleVoltage_VSource"],
        ykey="PCOEdge_image",
        shape=VPPEM_SHAPE,
        plot_ndim=2,
        projection=cube,
    )
    plot_data = Trace(model, first)
    key = plot_data.trace_key
    second = build_plot_request(
        uid=run.uid,
        xkeys=["sampleVoltage_VSource"],
        ykey="PCOEdge_image",
        shape=VPPEM_SHAPE,
        plot_ndim=2,
        projection=cube.with_index(0, 5),
        transform="y = y * 2",
    )
    assert plot_data.set_request(second)
    assert plot_data.trace_key is key
    assert plot_data.request.transform == "y = y * 2"
    other = build_plot_request(
        uid=run.uid,
        xkeys=["sampleVoltage_VSource"],
        ykey="PCOEdge_stats",
        shape=(11,),
        plot_ndim=1,
    )
    with pytest.raises(ValueError, match="does not match"):
        plot_data.set_request(other)


def test_ensure_trace_assembles_request(qapp):
    from nbs_viewer.models.plot.plot_request import TraceKey
    from tests.fixtures.plot_session import make_plot_session

    run = make_vppem_run()
    run_model = RunSource(run)
    plot_model, _ = make_plot_session()
    plot_model.add_run(run_model)
    cube = default_spec(3, 2).with_index(0, 4)
    plot_model.set_view_state(
        indices=cube.base_slice(),
        dimension=2,
        cube_view_spec=cube,
    )
    first = plot_model.ensure_trace(
        run_model, "sampleVoltage_VSource", "PCOEdge_image"
    )
    key = TraceKey(run.uid, "sampleVoltage_VSource", "PCOEdge_image")
    assert key in plot_model.traces
    assert first.request.view.indices[0] == 4
    same = plot_model.ensure_trace(
        run_model, "sampleVoltage_VSource", "PCOEdge_image"
    )
    assert same is first
    plot_model.set_view_state(
        indices=cube.with_index(0, 7).base_slice(),
        dimension=2,
        cube_view_spec=cube.with_index(0, 7),
    )
    assert same.request.view.indices[0] == 7
    assert same.trace_key == key


def _vppem_frame(model, req):
    """
    Return the display frame of the parent 2-D plane for an ROI request.
    """
    return frame_from_bundle(model.get_plot_bundle(req))


def test_get_plot_bundle_records_the_display_reversal():
    """
    The bundle has to say how it was oriented. Nothing downstream can work it
    out afterwards: ``extent`` is normalised so bottom < top either way.
    """
    model = RunSource(make_vppem_run())
    req = build_plot_request(
        uid=VPPEM_UID,
        xkeys=["sampleVoltage_VSource"],
        ykey="PCOEdge_image",
        shape=VPPEM_SHAPE,
        plot_ndim=2,
        projection=default_spec(3, 2).with_index(0, 4),
    )

    bundle = model.get_plot_bundle(req)
    frame = frame_from_bundle(bundle)

    assert bundle.row_reversed is True
    assert bundle.col_reversed is False
    assert frame.row_reversed is True
    assert frame.storage_bbox((0, 3, 0, 4)) == (VPPEM_SHAPE[1] - 3, VPPEM_SHAPE[1], 0, 4)


def test_get_plot_bundle_roi_profile_masks_the_display_plane():
    """
    End-to-end ROI profile against the plane the user actually drew on.

    The triangle matters: a rectangle fills its own bounding box, so its mask
    survives the row reversal unchanged and cannot detect a storage-order
    mask.
    """
    run = make_vppem_run()
    model = RunSource(run)
    a, b, c = vppem_factors()
    parent_spec = default_spec(3, 2).with_index(0, 4)
    parent_req = build_plot_request(
        uid=VPPEM_UID,
        xkeys=["sampleVoltage_VSource"],
        ykey="PCOEdge_image",
        shape=VPPEM_SHAPE,
        plot_ndim=2,
        projection=parent_spec,
    )
    frame = _vppem_frame(model, parent_req)
    roi = PolygonRegion(vertices=((1.0, 1.0), (20.0, 1.0), (1.0, 16.0)))

    profile_req = roi_profile_request(parent_req, roi, profile_axis=0)
    bundle = model.get_plot_bundle(profile_req)

    mask = compile_with_mask_mode(frame, roi, "inside").mask
    plane = np.outer(b, c)[::-1, :]
    expected = a * float(plane[mask].sum())

    assert bundle.ndim == 1
    np.testing.assert_allclose(bundle.y, expected, rtol=1e-9)


def test_normalizing_by_a_plane_shaped_key_follows_the_display_reversal():
    """
    A flat field shares the detector axes with the image, so it must be
    reversed the same way. Orienting only ``y`` would divide by the wrong rows.
    """
    data = make_vppem_data()
    n_rows, n_cols = VPPEM_SHAPE[1:]
    flat = 1.0 + np.arange(n_rows, dtype=float)[:, None] * np.ones(n_cols)
    data["PCOEdge_flat"] = np.broadcast_to(
        flat[None, :, :], VPPEM_SHAPE
    ).copy()
    model = RunSource(MemoryRun(make_vppem_metadata(), data))
    a, b, c = vppem_factors()

    req = build_plot_request(
        uid=VPPEM_UID,
        xkeys=["sampleVoltage_VSource"],
        ykey="PCOEdge_image",
        shape=VPPEM_SHAPE,
        norm_keys=["PCOEdge_flat"],
        plot_ndim=2,
        projection=default_spec(3, 2).with_index(0, 4),
    )
    bundle = model.get_plot_bundle(req)

    expected = (a[4] * np.outer(b, c) / flat)[::-1, :]
    np.testing.assert_allclose(bundle.y, expected, rtol=1e-9)
