"""
Headless tests for :class:`Trace` and :class:`TraceSet` (session plan step B).

A trace is model state: request identity plus the bundle that request last
produced. The matplotlib artist is a canvas concern, so the whole
``ensure_trace`` -> ``get_plot_bundle`` -> ``set_visible`` cycle has to run
with no canvas and without matplotlib being imported at all.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from nbs_viewer.models.plot.fetch.request import TraceKey
from nbs_viewer.models.plot.plot_session import PlotSession
from nbs_viewer.models.plot.run.source import RunSource
from nbs_viewer.models.plot.trace import Trace
from nbs_viewer.models.sources.testSource import create_test_catalog


def _session_with_run():
    plot = PlotSession(is_main_display=True)
    run = RunSource(create_test_catalog(1).get_runs()[0])
    plot.collection.add_runs([run])
    x_keys, y_keys, _norm = run.run.get_default_selection()
    plot.selection.set_selected_keys(x_keys[:1], y_keys[:1], [])
    return plot, run, x_keys[0], y_keys[0]


def test_trace_holds_no_artist_api():
    """The artist half of the old PlotDataModel is gone, not renamed."""
    for name in (
        "artist",
        "set_artist",
        "clear",
        "remove_artist_from_axes",
        "add_artist_to_axes",
        "move_artist_to_axes",
    ):
        assert not hasattr(Trace, name), f"Trace still exposes {name}"


def test_trace_drops_the_compatibility_properties():
    for name in (
        "_key",
        "_xkey",
        "_ykey",
        "_norm_keys",
        "_indices",
        "_cube_view_spec",
        "_dimension",
    ):
        assert not hasattr(Trace, name), f"Trace still exposes {name}"


def test_full_cycle_runs_without_a_canvas():
    plot, run, xkey, ykey = _session_with_run()
    trace = plot.ensure_trace(run, xkey, ykey)

    assert trace.trace_key == TraceKey(run.uid, xkey, ykey)
    assert trace.needs_fetch()

    bundle = trace.get_plot_bundle()
    assert bundle.y is not None
    assert trace.last_bundle is bundle
    assert not trace.needs_fetch()

    seen = []
    trace.visibility_changed.connect(lambda t, v: seen.append(v))
    trace.set_visible(False)
    trace.set_visible(True)
    assert seen == [False, True]
    assert trace.visible is True


def test_hide_then_show_does_not_refetch():
    plot, run, xkey, ykey = _session_with_run()
    trace = plot.ensure_trace(run, xkey, ykey)
    bundle = trace.get_plot_bundle()

    trace.set_visible(False)
    trace.set_visible(True)

    assert trace.last_bundle is bundle
    assert not trace.needs_fetch()


def test_new_run_data_invalidates_the_cached_bundle():
    """
    The cache rule for live data.

    ``needs_fetch`` compares requests, and a live scan changes the arrays
    without changing the request. Dropping the bundle on the run's
    ``data_changed`` is what stops a hidden trace coming back stale.
    """
    plot, run, xkey, ykey = _session_with_run()
    trace = plot.ensure_trace(run, xkey, ykey)
    trace.get_plot_bundle()
    assert not trace.needs_fetch()

    run.data_changed.emit()

    assert trace.last_bundle is None
    assert trace.needs_fetch()


def test_dropping_a_trace_announces_its_key():
    plot, run, xkey, ykey = _session_with_run()
    key = TraceKey(run.uid, xkey, ykey)
    assert key in plot.traces

    removed = []
    plot.traces.trace_removed.connect(removed.append)
    plot.collection.remove_uids([run.uid])

    assert removed == [key]
    assert key not in plot.traces


def test_dropping_a_trace_drops_its_outgoing_connections():
    """
    Removal is announced by key, so a subscriber cannot unsubscribe itself.

    The trace is a child of the set and so survives its own removal in Qt.
    Nothing else can reach it once the set has let go, which makes
    ``dispose`` the only place its own signals can be dropped.
    """
    plot, run, xkey, ykey = _session_with_run()
    key = TraceKey(run.uid, xkey, ykey)
    trace = plot.traces.get(key)

    seen = []
    trace.visibility_changed.connect(lambda *args: seen.append(args))
    trace.set_visible(not trace.visible)
    assert len(seen) == 1

    plot.collection.remove_uids([run.uid])

    trace.set_visible(not trace.visible)
    assert len(seen) == 1


def test_trace_module_imports_without_matplotlib():
    """
    The ownership guard that a unit test inside the suite cannot make.

    ``matplotlib`` is already imported by the time this suite runs, so the
    only honest check is a fresh interpreter that imports the model layer and
    asks whether matplotlib came with it.
    """
    root = Path(__file__).resolve().parents[1]
    code = (
        "import sys\n"
        "import nbs_viewer.models.plot.trace\n"
        "import nbs_viewer.models.plot.trace_set\n"
        "assert 'matplotlib' not in sys.modules, "
        "sorted(m for m in sys.modules if m.startswith('matplotlib'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=root, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
