"""
Combining and freezing, at the data layer where they belong.

Neither of these worked before step E. Both were ``RunSource`` subclasses
overriding ``get_plot_data`` -- a method that no longer exists on
``RunSource`` at all -- so combining silently plotted its first source and a
"frozen" run was a live alias of its parent that followed the session
selection. The tests below are the first coverage either feature has ever
had, which is why they assert against known arrays rather than shapes: the
old tests checked ``bundle.y.shape == (100,)`` and passed throughout.

The motivating case for the pair is
:func:`test_one_run_normalizes_a_set_of_others`: using one run as the
normalization input for several others, which ``PlotRequest.norm_keys``
cannot express because it resolves every norm key against the run being
plotted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from nbs_viewer.models.data.combined import (
    REQUESTED,
    CombinationMethod,
    CombinedRun,
    CombineError,
    truncate_to_common,
)
from nbs_viewer.models.data.frozen import FreezeError, FrozenRun
from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.run.source import RunSource
from tests.fixtures.catalog_recipes import line_scan_run, motor_scan_run
from tests.fixtures.plot_session import make_plot_session


def _norm_run(
    scan_id: int,
    *,
    length: int = 64,
    i0: float = 1.0,
    motor_stop: float = 10.0,
) -> MemoryRun:
    """
    Build a motor scan carrying both a detector and a reference channel.

    Parameters
    ----------
    scan_id : int
        Scan index, which also scales ``det``.
    length : int, optional
        Number of points.
    i0 : float, optional
        Constant value of the ``i0`` reference channel.
    motor_stop : float, optional
        End of the motor axis. Pass different values to two sources when a
        test needs to tell a combined axis from a single-sourced one.
    """
    motor = np.linspace(0, motor_stop, length)
    data = {
        "time": np.linspace(0, 1, length),
        "motor": motor,
        "det": np.ones(length) * (scan_id + 1),
        "i0": np.ones(length) * i0,
    }
    metadata = dict(motor_scan_run(scan_id).metadata)
    metadata["uid"] = f"norm-{scan_id}"
    return MemoryRun(metadata, data)


class _UnfinishedRun(MemoryRun):
    """A run still acquiring, so it must not be freezable."""

    def scanFinished(self) -> bool:
        return False


def _plot(session, run) -> np.ndarray:
    """Return the y array the session would draw for ``run``."""
    key = next(k for k in session.traces if k.uid == run.uid)
    return session.traces.get(key).fetch().y


# ----------------------------------------------------------------------
# Combining
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,expected",
    [(CombinationMethod.AVERAGE, 2.5), (CombinationMethod.SUM, 5.0)],
)
def test_a_combined_run_plots_the_combination(qapp, method, expected):
    """
    Bug 1. The inherited fetch path read one backing run, so a combination
    plotted its first source exactly and said nothing about it.
    """
    session, _ = make_plot_session(is_main_display=True)
    first = RunSource(_norm_run(0))  # det == 1.0
    second = RunSource(_norm_run(3))  # det == 4.0
    session.collection.add_runs([first, second])
    session.selection.set_selected_keys(["motor"], ["det"])

    combined = session.collection.combine([first, second], method=method)

    y = _plot(session, combined)
    assert np.allclose(y, expected)
    # ... and not the first source, which is what it used to do.
    assert not np.allclose(y, _plot(session, first))


def test_axis_coordinates_come_from_the_primary_source(qapp):
    """
    An averaged motor position is not a coordinate anyone asked for.
    """
    session, _ = make_plot_session(is_main_display=True)
    first = RunSource(_norm_run(0, motor_stop=10.0))
    second = RunSource(_norm_run(3, motor_stop=20.0))
    session.collection.add_runs([first, second])
    session.selection.set_selected_keys(["motor"], ["det"])

    combined = session.collection.combine([first, second])

    motor = combined.run.getData("motor")
    assert np.allclose(motor, first.run.getData("motor"))
    # The midpoint of the two axes is what averaging them would give.
    midpoint = (first.run.getData("motor") + second.run.getData("motor")) / 2
    assert not np.allclose(motor, midpoint)
    # The drawn x axis follows, since axes reach the bundle through getData.
    key = next(k for k in session.traces if k.uid == combined.uid)
    assert np.allclose(
        session.traces.get(key).fetch().x_line,
        first.run.getData("motor"),
    )


def test_one_run_normalizes_a_set_of_others(qapp):
    """
    The motivating case: one run as the reference for several others.

    ``norm_keys`` cannot express this -- it resolves every norm key against
    the run being plotted -- so it goes through an expression with the
    reference pinned to its own key.
    """
    session, _ = make_plot_session(is_main_display=True)
    reference = RunSource(_norm_run(9, i0=4.0))
    frozen = RunSource(FrozenRun(reference.run, "i0"))
    session.collection.add_runs([frozen])

    normalized = []
    for scan_id in (0, 1, 3):
        live = RunSource(_norm_run(scan_id))
        session.collection.add_runs([live])
        normalized.append(
            session.collection.combine(
                [],
                method=CombinationMethod.EXPRESSION,
                expression="runlist[0] / runlist[1]",
                sources=[(live.run, REQUESTED), (frozen.run, "i0")],
            )
        )

    session.selection.set_selected_keys(["motor"], ["det"])

    # det is (scan_id + 1); the shared reference is 4.0 everywhere.
    for run, scan_id in zip(normalized, (0, 1, 3)):
        assert np.allclose(_plot(session, run), (scan_id + 1) / 4.0)


def test_a_pinned_source_needs_the_key_it_is_pinned_to(qapp):
    session, _ = make_plot_session()
    live = RunSource(_norm_run(0))
    reference = RunSource(_norm_run(1))

    with pytest.raises(CombineError, match="pinned to 'missing'"):
        CombinedRun(
            [(live.run, REQUESTED), (reference.run, "missing")],
            method=CombinationMethod.EXPRESSION,
            expression="runlist[0] / runlist[1]",
        )


def test_a_combination_needs_a_requested_source(qapp):
    """
    Without one it has no keys to offer, so nothing could select it.
    """
    reference = RunSource(_norm_run(1))

    with pytest.raises(CombineError, match="at least one source bound"):
        CombinedRun(
            [(reference.run, "i0")],
            method=CombinationMethod.EXPRESSION,
            expression="runlist[0]",
        )


def test_only_average_and_sum_demand_compatible_sources(qapp):
    """
    The compatibility rule that forced the key-space hack.

    AVERAGE and SUM combine the same measurement across runs, so they need a
    shared key and matching shapes. An EXPRESSION's sources play different
    roles by design -- a live run divided by a fixed reference of a different
    length is the case this whole pair exists for -- so it is not checked.
    """
    session, _ = make_plot_session()
    short = RunSource(_norm_run(0, length=64))
    long_reference = RunSource(FrozenRun(_norm_run(1, length=100), "i0"))

    with pytest.raises(CombineError, match="different data shapes"):
        session.collection.validate_combine(
            [short, long_reference], CombinationMethod.AVERAGE
        )
    session.collection.validate_combine(
        [short, long_reference], CombinationMethod.EXPRESSION
    )


def test_a_source_data_change_reaches_the_combination_once(qapp):
    """
    The old class connected every source's ``data_changed`` twice -- once in
    its own loop and once through ``RunSource._connect_run`` -- so every
    combined run handled each change two times.
    """
    session, _ = make_plot_session()
    first = RunSource(_norm_run(0))
    second = RunSource(_norm_run(1))
    session.collection.add_runs([first, second])
    combined = session.collection.combine([first, second])

    seen = []
    combined.run.data_changed.connect(lambda: seen.append(1))
    first.run.data_changed.emit()

    assert len(seen) == 1


# ----------------------------------------------------------------------
# Freezing
# ----------------------------------------------------------------------


def test_a_frozen_run_does_not_follow_the_selection(qapp):
    """
    A reference that tracks the session selection is not a reference.

    The old class inherited its parent's whole key space and substituted its
    pinned key only inside the dead fetch path, so selecting another key
    moved the "frozen" trace with it.
    """
    session, _ = make_plot_session(is_main_display=True)
    parent = RunSource(_norm_run(0))
    session.collection.add_runs([parent])
    frozen = RunSource(FrozenRun(parent.run, "det"))
    session.collection.add_runs([frozen])

    assert set(frozen.available_keys) == {"time", "motor", "det"}
    assert "i0" not in frozen.available_keys

    session.selection.set_selected_keys(["motor"], ["i0"])
    frozen_keys = {key.ykey for key in session.traces if key.uid == frozen.uid}

    assert frozen_keys == set(), "the frozen run followed the selection"


def test_a_frozen_run_does_not_change_when_its_parent_does(qapp):
    """
    Capture, not reference. The arrays are copies and nothing links back.
    """
    parent_run = _norm_run(0)
    frozen = FrozenRun(parent_run, "det")
    before = np.array(frozen.getData("det"), copy=True)

    # In place, so a capture that merely referenced the parent's array would
    # change with it. Rebinding the dict entry would not prove anything.
    parent_run._data["det"] *= 100.0
    parent_run.data_changed.emit()

    assert np.allclose(frozen.getData("det"), before)
    assert not np.allclose(frozen.getData("det"), parent_run.getData("det"))


def test_freezing_an_unfinished_run_is_refused(qapp):
    """
    A snapshot of a growing run would not be stable, so it is not taken.
    """
    unfinished = _UnfinishedRun(_norm_run(0).metadata, {"time": np.arange(4.0)})

    with pytest.raises(FreezeError, match="still acquiring"):
        FrozenRun(unfinished, "time")


def test_freeze_skips_an_unfinished_run_but_keeps_the_others(qapp):
    session, _ = make_plot_session()
    finished = RunSource(_norm_run(0))
    unfinished = RunSource(
        _UnfinishedRun(_norm_run(1).metadata, dict(_norm_run(1)._data))
    )

    frozen = session.collection.freeze(
        [(finished, "det"), (unfinished, "det")]
    )

    assert len(frozen) == 1
    assert frozen[0].display_name == "det of 0"


def test_freezing_a_key_the_run_lacks_is_refused(qapp):
    with pytest.raises(FreezeError, match="no key 'nope'"):
        FrozenRun(_norm_run(0), "nope")


# ----------------------------------------------------------------------
# Truncation
# ----------------------------------------------------------------------


def test_truncation_clips_shared_axes_and_leaves_trailing_ones():
    plane = np.arange(100 * 5, dtype=float).reshape(100, 5)
    line = np.arange(64, dtype=float)

    clipped_plane, clipped_line = truncate_to_common([plane, line])

    assert clipped_plane.shape == (64, 5)
    assert clipped_line.shape == (64,)


def test_a_frozen_reference_truncates_to_a_shorter_run(qapp):
    """
    The frozen side is complete by the freeze rule, so the shorter array is
    the still-filling run -- which keeps plotting as it grows.
    """
    session, _ = make_plot_session(is_main_display=True)
    long_reference = RunSource(FrozenRun(_norm_run(9, length=100, i0=2.0), "i0"))
    short_live = RunSource(_norm_run(0, length=64))
    session.collection.add_runs([long_reference, short_live])

    combined = session.collection.combine(
        [],
        method=CombinationMethod.EXPRESSION,
        expression="runlist[0] / runlist[1]",
        sources=[(short_live.run, REQUESTED), (long_reference.run, "i0")],
    )
    session.selection.set_selected_keys(["motor"], ["det"])

    y = _plot(session, combined)
    assert y.shape == (64,)
    assert np.allclose(y, 1.0 / 2.0)


# ----------------------------------------------------------------------
# Structural guards
# ----------------------------------------------------------------------


def test_the_plot_layer_holds_no_catalog_runs():
    """
    Synthesising data is a data-layer job; both classes moved for that reason.
    """
    plot_root = Path(__file__).resolve().parents[1] / "nbs_viewer/models/plot"
    offenders = []
    for path in sorted(plot_root.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                getattr(base, "id", getattr(base, "attr", ""))
                for base in node.bases
            }
            if "CatalogRun" in bases:
                offenders.append(f"{path.name}:{node.name}")

    assert offenders == [], f"CatalogRun subclasses under models/plot: {offenders}"


def test_get_plot_data_is_gone():
    """
    The dead API both classes were written against.

    It did not merely lack callers -- ``RunSource.get_plot_data`` had already
    been deleted, so every ``super().get_plot_data(...)`` in it would have
    raised. The algorithm was ported into ``CombinedRun.getData`` and the
    name is now unused.
    """
    root = Path(__file__).resolve().parents[1] / "nbs_viewer"
    hits = [
        f"{path.relative_to(root)}"
        for path in root.rglob("*.py")
        if "get_plot_data" in path.read_text()
    ]

    assert hits == [], f"get_plot_data still referenced in {hits}"


def test_line_scans_still_combine_through_the_catalog_path(qapp):
    """
    The ordinary AVERAGE case over the standard recipe, end to end.
    """
    session, _ = make_plot_session(is_main_display=True)
    first = RunSource(line_scan_run(1))
    second = RunSource(line_scan_run(2))
    session.collection.add_runs([first, second])
    session.selection.set_selected_keys(["time"], ["y"])

    combined = session.collection.combine([first, second])
    y = _plot(session, combined)

    expected = (_plot(session, first) + _plot(session, second)) / 2
    assert np.allclose(y, expected)
