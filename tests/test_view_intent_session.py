"""
The session's view-intent gestures, headless.

These four methods are what ``DimensionControl`` calls instead of owning a
spec. Moving them onto the session is what makes them testable at all -- the
suite runs on ``QCoreApplication`` and cannot build the widget -- so they are
tested here rather than only reached through a scratch script.
"""

from __future__ import annotations

from nbs_viewer.models.plot.plot_session import PlotSession
from nbs_viewer.models.plot.runSource import RunSource
from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.view_spec import DimRole
from nbs_viewer.models.sources.testSource import create_test_catalog


def _session(ykey="image", xkey="x", include_nd=False):
    catalog = create_test_catalog(1, include_nd=include_nd)
    runs = [RunSource(r) for r in catalog.get_runs()]
    run = next(r for r in runs if ykey in r.available_keys)
    session = PlotSession(is_main_display=True)
    session.add_run(run)
    session.set_uids_visible([run.uid], True)
    session.set_selected_keys([xkey], [ykey], [])
    session.follow_x_selection()
    return session, run


def test_driving_axes_picks_the_highest_rank_visible_key():
    session, run = _session()
    session.set_selected_keys(["x"], ["y", "image"], [])
    driving = session.driving_axes()
    assert driving is not None
    _run_model, ykey, layout = driving
    assert ykey == "image"
    assert layout.shape == (100, 32)


def test_driving_axes_is_none_without_a_multidimensional_key():
    session, _run = _session(ykey="y")
    assert session.driving_axes() is None
    assert session.driving_projection() is None


def test_set_plot_ndim_reaches_every_trace():
    session, run = _session()
    session.set_plot_ndim(2)
    assert session.dimension == 2
    trace = session.traces.get(next(iter(session.traces)))
    assert trace.request.view.plot_ndim == 2


def test_set_axis_reduce_lands_on_the_intent_and_the_request():
    """
    The regression: this built a ``Projection`` by name in a module that only
    imported it for annotations, so moving any slider raised ``NameError``.
    No test could reach it, because the only caller was a widget.
    """
    session, run = _session()
    projection = session.driving_projection()
    assert projection is not None
    slice_axis = projection.slice_axis_order()[0]

    session.set_axis_reduce({slice_axis: (DimRole.INDEX, 7)})

    assert 7 in session.view_intent.reduce_indices
    trace = session.traces.get(next(iter(session.traces)))
    assert trace.request.view.indices[slice_axis] == 7
    assert trace.request.view.base_slice()[slice_axis] == 7


def test_set_axis_reduce_carries_a_sum_role():
    session, run = _session()
    projection = session.driving_projection()
    slice_axis = projection.slice_axis_order()[0]

    session.set_axis_reduce({slice_axis: (DimRole.SUM, 0)})

    assert DimRole.SUM in session.view_intent.reduce_roles
    trace = session.traces.get(next(iter(session.traces)))
    assert trace.request.view.roles[slice_axis] == DimRole.SUM


def test_set_axis_reduce_clamps_to_the_axis_length():
    session, run = _session()
    projection = session.driving_projection()
    slice_axis = projection.slice_axis_order()[0]
    size = session.driving_axes()[2].shape[slice_axis]

    session.set_axis_reduce({slice_axis: (DimRole.INDEX, size + 50)})

    trace = session.traces.get(next(iter(session.traces)))
    assert trace.request.view.indices[slice_axis] == size - 1


def test_move_view_axis_records_a_named_order():
    session, run = _session()
    before = session.driving_projection().axis_order

    session.move_view_axis(0, direction=1)

    order = session.view_intent.dim_order
    assert order != ()
    assert all(isinstance(name, str) for name in order)
    assert session.driving_projection().axis_order != before


def test_move_view_axis_off_the_ends_is_a_no_op():
    """
    Moving past either end changes nothing and announces nothing.

    This used to assert ``session.view_intent is intent``. The session now
    owns one live intent it mutates rather than replaces, so that identity is
    trivially true and the assertion was vacuous. The observable no-op is
    that no signal fired and no field moved.
    """
    session, run = _session()
    intent = session.view_intent
    before = (intent.dim_order, intent.xkey, intent.plot_ndim)
    fired = []
    intent.changed.connect(lambda: fired.append(1))

    session.move_view_axis(0, direction=-1)
    ndim = len(session.driving_axes()[2].shape)
    session.move_view_axis(ndim - 1, direction=1)

    assert fired == []
    assert (intent.dim_order, intent.xkey, intent.plot_ndim) == before


def test_a_new_x_selection_supersedes_a_manual_order():
    session, run = _session()
    session.move_view_axis(0, direction=1)
    assert session.view_intent.dim_order != ()

    session.set_selected_keys(["time"], ["image"], [])
    session.follow_x_selection()

    assert session.view_intent.dim_order == ()
    assert session.view_intent.xkey == "time"


def test_the_reduce_policy_survives_a_plot_ndim_change():
    session, run = _session()
    slice_axis = session.driving_projection().slice_axis_order()[0]
    session.set_axis_reduce({slice_axis: (DimRole.INDEX, 5)})

    session.set_plot_ndim(2)
    session.set_plot_ndim(1)

    assert 5 in session.view_intent.reduce_indices
    trace = session.traces.get(next(iter(session.traces)))
    assert trace.request.view.indices[slice_axis] == 5


def test_gestures_reach_a_rank_three_key():
    session, run = _session(
        ykey="PCOEdge_image", xkey="sampleVoltage_VSource", include_nd=True
    )
    session.set_plot_ndim(2)
    projection = session.driving_projection()
    assert projection.ndim == 3

    slice_axis = projection.slice_axis_order()[0]
    session.set_axis_reduce({slice_axis: (DimRole.INDEX, 3)})

    trace = session.traces.get(next(iter(session.traces)))
    assert trace.request.view.indices[slice_axis] == 3
    bundle = trace.get_plot_bundle()
    assert bundle.render_mode in ("image", "mesh")
    assert bundle.y.ndim == 2


def test_the_session_wires_the_intent_to_requests_then_a_refetch():
    """
    Order is load-bearing: held requests must be rewritten before the
    refetch is scheduled, or the refetch reads the old projection.
    """
    session, run = _session()
    session.set_selected_keys(["time"], ["image"], [])
    trace = next(iter(session.traces.values()))

    seen = []
    session.request_plot_update.connect(
        lambda: seen.append(trace.request.view.indices)
    )
    session.set_axis_reduce({0: (DimRole.INDEX, 3)})

    assert seen, "request_plot_update did not fire"
    assert seen[0] == trace.request.view.indices


def test_leaving_two_d_invalidates_region_state():
    """
    Crop and ROI geometry live on the 2-D plane, so leaving it clears them.
    Entering it does not: there is no stale geometry to clear.
    """
    session, run = _session()
    session.set_selected_keys(["time"], ["image"], [])
    reasons = []
    session.region_invalidation_requested.connect(reasons.append)

    session.view_intent.set_plot_ndim(2)
    assert reasons == []

    session.view_intent.set_plot_ndim(1)
    assert reasons == ["switched out of 2D mode"]
