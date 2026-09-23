"""Tests for PlotRequest construction and RunSource fetch."""

from dataclasses import replace

import numpy as np
import pytest

from tests.fixtures.view import apply_projection
from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.plane.roles import DimRole, ViewCrop
from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.spec.region import PolygonRegion
from nbs_viewer.models.plot.spec.request import PlotRequest
from nbs_viewer.models.plot.run.source import RunSource
from nbs_viewer.models.sources.fixtures import (
    VPPEM_SHAPE,
    VPPEM_UID,
    make_vppem_data,
    make_vppem_metadata,
    make_vppem_run,
    vppem_factors,
)

# What ``RunSource.plot_axis_names`` answers for the VPPEM keys under the
# voltage selection: the event axis wears the X key's name.
VPPEM_NAMES = ("sampleVoltage_VSource", "dim_1", "dim_2")
STATS_NAMES = ("sampleVoltage_VSource",
)


def test_a_low_rank_key_projects_on_its_own_terms():
    """
    The fallback chain ``projection_for_shape`` used to implement is gone.

    A rank-agnostic intent projects onto each key's own rank, so the session
    never has to guess whether a stored rank-bound spec fits: a 1-D key beside
    a 2-D image gets a 1-D projection, not a discarded one.
    """
    intent = ViewIntent(
        plot_ndim=2, reduce_roles=(DimRole.INDEX,
), reduce_indices=(4,
)
    )
    image = intent.project(3, VPPEM_SHAPE)
    assert image.plot_ndim == 2
    assert image.indices[0] == 4
    assert image.base_slice() == (4, slice(None), slice(None))

    # The mixed-rank case projects at an overridden rank rather than
    # manufacturing a throwaway intent, which is what production does too.
    line = intent.project(1, (11,
), plot_ndim=1)
    assert line.ndim == 1
    assert line.plot_ndim == 1
    assert line.roles == (DimRole.PLOT_X,
)


def test_the_plan_narrows_the_load_with_the_request_crop():
    cube = ViewIntent(plot_ndim=2).project(3).with_index(0, 4)
    crop = ViewCrop(storage_bbox=(2, 10, 4, 20), plot_y_axis=1, plot_x_axis=2)
    req = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        view=replace(cube, crop=crop),
        dims=VPPEM_NAMES
)
    assert req.view.base_slice() == (4, slice(None), slice(None))
    assert req.plan().slice_info == (4, slice(2, 10), slice(4, 20))


def test_run_model_plot_bundle_from_request():
    run = make_vppem_run()
    model = RunSource(run)
    a, b, c = vppem_factors()
    cube = ViewIntent(plot_ndim=2).project(3).with_index(0, 4)
    xkeys = ["sampleVoltage_VSource"]
    ykey = "PCOEdge_image"

    req = PlotRequest(
        uid=run.uid,
        xkeys=xkeys,
        ykey=ykey,
        view=cube,
        dims=VPPEM_NAMES
)
    via_request = req.plot_bundle(model)

    assert via_request.render_mode == "image"
    expected = a[4] * np.outer(b, c)
    np.testing.assert_allclose(via_request.y, expected[::-1, :])


def test_run_model_plot_bundle_request_with_crop():
    run = make_vppem_run()
    model = RunSource(run)
    a, b, c = vppem_factors()
    cube = ViewIntent(plot_ndim=2).project(3).with_index(0, 4)
    crop = ViewCrop(storage_bbox=(2, 10, 4, 20), plot_y_axis=1, plot_x_axis=2)
    req = PlotRequest(
        uid=run.uid,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        view=replace(cube, crop=crop),
        dims=VPPEM_NAMES
)
    bundle = req.plot_bundle(model)
    expected = (a[4] * np.outer(b, c))[2:10, 4:20]
    np.testing.assert_allclose(bundle.y, expected[::-1, :])


def test_plot_data_model_holds_request_and_fetches():
    from nbs_viewer.models.plot.spec.projection import Projection
    from nbs_viewer.models.plot.trace.trace import Trace
    from nbs_viewer.models.plot.spec.request import PlotRequest
    from nbs_viewer.models.plot.trace.key import TraceKey

    run = make_vppem_run()
    model = RunSource(run)
    cube = Projection(
        ndim=3,
        plot_ndim=1,
        roles=(DimRole.PLOT_X, DimRole.MEAN, DimRole.MEAN),
        indices=(0, 0, 0),
        axis_order=(1, 2, 0)
)
    request = PlotRequest(
        uid=run.uid,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        view=cube,
        dims=VPPEM_NAMES
)
    plot_data = Trace(model, request)
    assert plot_data.trace_key == TraceKey(
        run.uid, "sampleVoltage_VSource", "PCOEdge_image"
    )
    bundle = plot_data.fetch()
    np.testing.assert_allclose(bundle.y, run.getData("PCOEdge_stats"))
    assert plot_data.last_fetched_request == request


def test_set_request_keeps_trace_key():
    from nbs_viewer.models.plot.trace.trace import Trace

    run = make_vppem_run()
    model = RunSource(run)
    cube = ViewIntent(plot_ndim=2).project(3).with_index(0, 4)
    first = PlotRequest(
        uid=run.uid,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        view=cube,
        dims=VPPEM_NAMES
)
    plot_data = Trace(model, first)
    key = plot_data.trace_key
    second = PlotRequest(
        uid=run.uid,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        transform="y = y * 2",
        view=cube.with_index(0, 5),
        dims=VPPEM_NAMES
)
    assert plot_data.set_request(second)
    assert plot_data.trace_key is key
    assert plot_data.request.transform == "y = y * 2"
    other = PlotRequest(
        uid=run.uid,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_stats",
        view=ViewIntent(plot_ndim=1).project(len((11,
)), (11,
)),
        dims=STATS_NAMES
)
    with pytest.raises(ValueError, match="does not match"):
        plot_data.set_request(other)


def test_ensure_trace_assembles_request(qapp):
    from nbs_viewer.models.plot.trace.key import TraceKey
    from tests.fixtures.plot_session import make_plot_session

    run = make_vppem_run()
    run_model = RunSource(run)
    plot_model, _ = make_plot_session()
    plot_model.collection.add_runs([run_model])
    cube = ViewIntent(plot_ndim=2).project(3).with_index(0, 4)
    apply_projection(plot_model.view_intent, cube)
    first = plot_model.ensure_trace(
        run_model, "sampleVoltage_VSource", "PCOEdge_image"
    )
    key = TraceKey(run.uid, "sampleVoltage_VSource", "PCOEdge_image")
    assert key in plot_model.traces
    assert first.request.view.indices[0] == 4
    # The names the session chose the projection against ride on the request.
    assert first.request.dims == VPPEM_NAMES
    same = plot_model.ensure_trace(
        run_model, "sampleVoltage_VSource", "PCOEdge_image"
    )
    assert same is first
    apply_projection(plot_model.view_intent, cube.with_index(0, 7))
    assert same.request.view.indices[0] == 7
    assert same.trace_key == key


def _vppem_frame(model, req):
    """
    Return the display frame of the parent 2-D plane for an ROI request.
    """
    return req.plot_bundle(model).view_frame()


def test_plot_bundle_records_the_display_reversal():
    """
    The bundle has to say how it was oriented. Nothing downstream can work it
    out afterwards: ``extent`` is normalised so bottom < top either way.
    """
    model = RunSource(make_vppem_run())
    req = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        view=ViewIntent(plot_ndim=2).project(3).with_index(0, 4),
        dims=VPPEM_NAMES
)

    bundle = req.plot_bundle(model)
    frame = bundle.view_frame()

    assert bundle.row_reversed is True
    assert bundle.col_reversed is False
    assert frame.row_reversed is True
    assert frame.storage_bbox((0, 3, 0, 4)) == (VPPEM_SHAPE[1] - 3, VPPEM_SHAPE[1], 0, 4)


def test_plot_bundle_roi_profile_masks_the_display_plane():
    """
    End-to-end ROI profile against the plane the user actually drew on.

    The triangle matters: a rectangle fills its own bounding box, so its mask
    survives the row reversal unchanged and cannot detect a storage-order
    mask.
    """
    run = make_vppem_run()
    model = RunSource(run)
    a, b, c = vppem_factors()
    parent_spec = ViewIntent(plot_ndim=2).project(3).with_index(0, 4)
    parent_req = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        view=parent_spec,
        dims=VPPEM_NAMES
)
    frame = _vppem_frame(model, parent_req)
    roi = PolygonRegion(vertices=((1.0, 1.0), (20.0, 1.0), (1.0, 16.0)))

    profile_req = parent_req.with_roi_profile(roi, profile_axis=0)
    bundle = profile_req.plot_bundle(model)

    mask = roi.compile_masked(frame, "inside").mask
    plane = np.outer(b, c)[::-1, :]
    expected = a * float(plane[mask].sum())

    assert bundle.ndim == 1
    np.testing.assert_allclose(bundle.y, expected, rtol=1e-9)


@pytest.mark.parametrize("along", ["plot_x", "plot_y"])
def test_an_in_plane_roi_profile_masks_the_display_plane(along):
    """
    The route the ROI window's live preview takes: a profile across the
    image it was drawn on, from the plane the canvas already holds.

    On VPPEM, whose rows are reversed for display, it summed the
    mirror-image rows -- an ROI over a bright band at the bottom of the image
    came back as the dark band at the top.
    """
    model = RunSource(make_vppem_run())
    parent_req = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        view=ViewIntent(plot_ndim=2).project(3).with_index(0, 4),
        dims=VPPEM_NAMES
)
    plane = parent_req.plot_bundle(model)
    assert plane.row_reversed
    roi = PolygonRegion(vertices=((1.0, 1.0), (20.0, 1.0), (1.0, 16.0)))

    bundle = parent_req.with_roi_profile(roi, profile_axis=along).plot_bundle(model, cached_plane=plane)

    mask = roi.compile_masked(plane.view_frame(), "inside").mask
    shown = np.where(mask, np.asarray(plane.y), np.nan)
    across = 0 if along == "plot_x" else 1
    expected = np.nansum(shown, axis=across)[mask.any(axis=across)]
    got = bundle.y[np.isfinite(bundle.y)]
    np.testing.assert_allclose(np.sort(got), np.sort(expected), rtol=1e-9)


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

    req = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        norm_keys=("PCOEdge_flat",
),
        view=ViewIntent(plot_ndim=2).project(3).with_index(0, 4),
        dims=VPPEM_NAMES
)
    bundle = req.plot_bundle(model)

    expected = (a[4] * np.outer(b, c) / flat)[::-1, :]
    np.testing.assert_allclose(bundle.y, expected, rtol=1e-9)


def test_a_request_rejects_names_that_disagree_with_its_view():
    """
    The names are checked where the request is made, not where it is fetched.

    Every stage after the load addresses an axis by name, so a count that
    disagrees with the rank, or a repeated name, would give one axis another's
    role.
    """
    cube = ViewIntent(plot_ndim=2).project(3).with_index(0, 4)

    def build(dims):
        return PlotRequest(
            uid=VPPEM_UID,
            xkeys=("sampleVoltage_VSource",
),
            ykey="PCOEdge_image",
            view=cube,
            dims=dims
)

    with pytest.raises(ValueError, match="rank-3"):
        build(("dim_1", "dim_2"))
    with pytest.raises(ValueError, match="duplicate"):
        build(("dim_1", "dim_1", "dim_2"))


def test_the_fetch_takes_the_names_from_the_request():
    """
    The session chose the projection against these names, so the fetch uses
    them rather than asking the source again before every read.
    """
    model = RunSource(make_vppem_run())
    asked = []
    original = model.plot_axis_names

    def counted(ykey, xkeys):
        asked.append(ykey)
        return original(ykey, xkeys)

    model.plot_axis_names = counted
    req = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        view=ViewIntent(plot_ndim=2).project(3).with_index(0, 4),
        dims=VPPEM_NAMES
)

    assert req.plan().dims == VPPEM_NAMES
    req.plot_bundle(model)
    assert "PCOEdge_image" not in asked


def test_a_request_may_name_an_axis_only_after_its_x_key():
    """
    Carried names are checked, not re-derived, and not trusted blindly.

    An axis named after a key is plotted against that key, so a request
    calling the event axis ``i0`` while plotting against the voltage would
    otherwise plot against ``i0`` without a word.
    """
    model = RunSource(make_vppem_run())
    req = PlotRequest(
        uid=VPPEM_UID,
        xkeys=("sampleVoltage_VSource",
),
        ykey="PCOEdge_image",
        view=ViewIntent(plot_ndim=2).project(3).with_index(0, 4),
        dims=("i0", "dim_1", "dim_2")
)

    with pytest.raises(ValueError, match="neither its own name nor the X key"):
        req.plot_bundle(model)
