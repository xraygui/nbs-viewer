"""
The membership and selection children: what they own, and what the session
stopped announcing on their behalf.

Step H reversed a thinning. ``RunCollection`` had been demoted to a plain
container and its visibility state and signals moved onto ``PlotSession``,
which did not remove the work -- it relocated it, and forced the session to
subscribe to its own signals to react to changes it had just made. What these
tests pin is that the announcements are back with the state, and that the
session did not keep a forwarding layer in their place.
"""

from __future__ import annotations

import ast
from pathlib import Path

from nbs_viewer.models.plot.plot_session import PlotSession
from nbs_viewer.models.plot.run_collection import RunCollection
from nbs_viewer.models.plot.run.source import RunSource
from nbs_viewer.models.plot.selection import Selection
from tests.fixtures.catalog_recipes import line_scan_run, motor_scan_run
from tests.fixtures.plot_session import make_plot_session

SESSION_SOURCE = Path(__file__).resolve().parents[1] / (
    "nbs_viewer/models/plot/plot_session.py"
)


def _session_class() -> ast.ClassDef:
    tree = ast.parse(SESSION_SOURCE.read_text())
    return next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "PlotSession"
    )


def _session_signal_names(cls: ast.ClassDef) -> set:
    names = set()
    for node in cls.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "Signal":
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def test_the_session_owns_one_collection_and_one_selection(qapp):
    session, _ = make_plot_session()

    assert isinstance(session.collection, RunCollection)
    assert isinstance(session.selection, Selection)
    # Handed out, not forwarded.
    assert not hasattr(session, "add_runs")
    assert not hasattr(session, "set_uids_visible")
    assert not hasattr(session, "visible_models")
    assert not hasattr(session, "set_selected_keys")
    assert not hasattr(session, "available_keys")


def test_the_session_announces_nothing_about_runs_or_keys():
    """
    Signal ownership follows state ownership.

    A signal here would mean the session is announcing on a child's behalf,
    which is what made ``visible_models`` a join across two objects.
    """
    signals = _session_signal_names(_session_class())

    assert signals == {
        "transform_changed",
        "request_plot_update",
        "frozen_spectra_changed",
        "cache_status_changed",
    }


def test_the_session_subscribes_to_none_of_its_own_signals():
    """
    An object connecting to itself has an announcement in the wrong place.

    Every one of these was a real connection waiting for a second object:
    the region child took two, and this step took the last three.
    """
    cls = _session_class()
    own_signals = _session_signal_names(cls)
    offenders = []
    for node in ast.walk(cls):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "connect"):
            continue
        target = func.value
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr in own_signals
        ):
            offenders.append(target.attr)

    assert offenders == [], f"session subscribes to its own {offenders}"


def test_the_session_holds_no_membership_or_selection_state(qapp):
    """
    Guard against the state creeping back up, as it did once before.
    """
    session = PlotSession()
    banned = {
        "_sources",
        "_visible_uids",
        "_available_keys",
        "_auto_add",
        "_is_main_display",
        "_single_selection_mode",
        "_retain_selection",
    }
    present = banned & set(vars(session))

    assert present == set(), f"child state back on the session: {present}"


def test_visibility_is_the_collections_to_announce(qapp):
    """
    The visible set and the signal for it live in the same object.
    """
    session, _ = make_plot_session(is_main_display=False)
    session.collection.set_auto_add(False)
    run = RunSource(line_scan_run(1))
    session.collection.add_runs([run])
    assert session.collection.visible_uids == set()

    seen = []
    session.collection.visible_runs_changed.connect(seen.append)
    session.collection.set_uids_visible([run.uid], True)

    assert seen == [{run.uid}]
    assert session.collection.visible_models == [run]


def test_a_redundant_visibility_set_is_silent(qapp):
    session, _ = make_plot_session()
    run = RunSource(line_scan_run(1))
    session.collection.add_runs([run])

    seen = []
    session.collection.visible_runs_changed.connect(seen.append)
    session.collection.set_uids_visible([run.uid], True)

    assert seen == []


def test_single_selection_mode_is_a_collection_rule(qapp):
    session, _ = make_plot_session(single_selection_mode=True)
    first = RunSource(line_scan_run(1))
    second = RunSource(line_scan_run(2))
    session.collection.add_runs([first, second])

    session.collection.set_uids_visible([first.uid], True)
    assert session.collection.visible_uids == {first.uid}
    session.collection.set_uids_visible([second.uid], True)
    assert session.collection.visible_uids == {second.uid}


def test_setting_the_same_keys_twice_announces_once(qapp):
    """
    The selection mutator guards on real change, as the intent's do.

    Without it every signal that lands on the selection -- and several now
    do -- would restart the fetch of every trace.
    """
    session, _ = make_plot_session()
    run = RunSource(line_scan_run(1))
    session.collection.add_runs([run])

    seen = []
    session.selection.selected_keys_changed.connect(
        lambda x, y, n: seen.append((tuple(x), tuple(y)))
    )
    # Reversed against the run's own default, which the collection has
    # already applied by now.
    assert session.selection.set_selected_keys(["y"], ["time"]) is True
    assert session.selection.set_selected_keys(["y"], ["time"]) is False

    assert seen == [(("y",), ("time",))]


def test_losing_a_key_revalidates_the_default_selection(qapp):
    """
    The available-key universe pruning the selection used to be the session
    subscribing to its own ``available_keys_changed``. It is now a
    connection from the collection to the selection.
    """
    session, _ = make_plot_session()
    session.collection.add_runs([RunSource(motor_scan_run(1))])
    session.selection.set_selected_keys(["time"], ["det"])
    assert session.selection.get_selected_keys()[1] == ["det"]

    # The universe is the intersection over visible runs, and a line scan
    # has no ``det``, so adding one prunes it from the selection.
    session.collection.add_runs([RunSource(line_scan_run(2))])

    assert "det" not in session.collection.available_keys
    assert session.selection.get_selected_keys() == (["time"], [], [])


def test_removing_a_run_drops_its_override(qapp):
    """
    The selection learns of removal from the collection, not from the session.
    """
    session, _ = make_plot_session()
    run = RunSource(motor_scan_run(1))
    session.collection.add_runs([run])
    session.selection.set_selected_keys(["time"], ["det"])
    session.selection.set_selection_for(run.uid, ["time"], ["motor"])
    assert session.selection.selection_for(run.uid).y == ("motor",)

    session.collection.remove_uids([run.uid])
    session.collection.add_runs([RunSource(motor_scan_run(1))])

    assert session.selection.selection_for(run.uid).y == ("det",)


def test_a_selection_change_still_reaches_the_trace_set(qapp):
    """
    The join the session kept: collection x selection x view -> traces.
    """
    session, _ = make_plot_session()
    session.collection.add_runs([RunSource(motor_scan_run(1))])

    session.selection.set_selected_keys(["time"], ["det"])
    assert {key.ykey for key in session.traces} == {"det"}

    session.selection.set_selected_keys(["time"], ["motor"])
    assert {key.ykey for key in session.traces} == {"motor"}
