"""Headless tests for PlotSession membership and visibility (step 3a)."""

from __future__ import annotations

from nbs_viewer.models.plot.plot_session import PlotSession
from nbs_viewer.models.plot.plot_request import TraceKey
from nbs_viewer.views.dataSource.run_list_item_model import RunListItemModel
from nbs_viewer.models.plot.run_source import RunSource
from nbs_viewer.models.sources.testSource import create_test_catalog


def _make_session(n_runs: int = 1):
    plot = PlotSession(is_main_display=True)
    run_list = RunListItemModel(plot.collection)
    runs = [RunSource(r) for r in create_test_catalog(n_runs).get_runs()]
    return plot, run_list, runs


def test_session_owns_collection_not_list():
    plot, run_list, runs = _make_session(1)
    plot.collection.add_runs([runs[0]])
    assert runs[0].uid in plot.collection
    assert run_list.collection is plot.collection
    # The Qt adapter mirrors membership; it cannot change it.
    assert not hasattr(run_list, "add_runs")
    assert not hasattr(run_list, "set_uids_visible")


def test_add_remove_rebuilds_plot_data_keys():
    plot, _run_list, runs = _make_session(1)
    run = runs[0]
    plot.collection.add_runs([run])
    x_keys, y_keys, _norm = run.run.get_default_selection()
    plot.selection.set_selected_keys(x_keys, y_keys[:1], [])

    desired = {
        TraceKey(run.uid, x, y)
        for x in x_keys
        for y in y_keys[:1]
    }
    assert set(plot.traces) == desired

    plot.collection.remove_uids([run.uid])
    assert set(plot.traces) == set()
    assert len(plot.collection) == 0


def test_hide_show_retains_plot_data():
    plot, _run_list, runs = _make_session(1)
    run = runs[0]
    plot.collection.add_runs([run])
    x_keys, y_keys, _norm = run.run.get_default_selection()
    plot.selection.set_selected_keys(x_keys, y_keys[:1], [])
    keys_before = set(plot.traces)
    assert keys_before

    plot.collection.set_uids_visible([run.uid], False)
    assert run.uid not in plot.collection.visible_uids
    assert set(plot.traces) == keys_before
    assert list(plot.iter_visible_traces()) == []

    plot.collection.set_uids_visible([run.uid], True)
    assert run.uid in plot.collection.visible_uids
    assert set(plot.traces) == keys_before
    assert len(list(plot.iter_visible_traces())) == len(keys_before)


def test_list_rows_track_session_membership():
    plot, run_list, runs = _make_session(1)
    plot.collection.add_runs([runs[0]])
    assert runs[0].uid in plot.collection
    assert run_list.rowCount() == 1
    assert run_list.get_run_at_index(run_list.index(0, 0)) is runs[0]


def test_selection_override_and_clear():
    plot, _run_list, runs = _make_session(2)
    for run in runs:
        plot.collection.add_runs([run])
    x_keys, y_keys, norm_keys = runs[0].run.get_default_selection()
    plot.selection.set_selected_keys(x_keys, y_keys[:1], norm_keys)

    uid0, uid1 = runs[0].uid, runs[1].uid
    plot.selection.set_selection_for(uid0, x_keys, y_keys[:1], [])
    assert plot.selection.selection_for(uid0).norm == ()
    assert plot.selection.selection_for(uid1).norm == tuple(norm_keys)

    plot.selection.clear_overrides()
    assert plot.selection.selection_for(uid0).norm == tuple(norm_keys)
    assert plot.selection.selection_for(uid1).y == tuple(y_keys[:1])


def test_retained_keys_respect_per_run_selection():
    plot, _run_list, runs = _make_session(2)
    for run in runs:
        plot.collection.add_runs([run])
    x_keys, y_keys, _norm = runs[0].run.get_default_selection()
    plot.selection.set_selected_keys(x_keys, y_keys[:1], [])
    plot.selection.set_selection_for(runs[0].uid, x_keys, [], [])

    keys = set(plot.traces)
    assert all(k.uid != runs[0].uid for k in keys)
    assert any(k.uid == runs[1].uid for k in keys)


def test_run_source_has_no_session_selection_api():
    run = RunSource(create_test_catalog(1).get_runs()[0])
    assert not hasattr(run, "set_selected_keys")
    assert not hasattr(run, "get_selected_keys")
    assert not hasattr(run, "set_visible")
    assert not hasattr(run, "set_transform")
