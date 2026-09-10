"""
Tests that build real widgets.

These are the first tests in this suite to construct a ``QWidget``. Until the
``qapp`` fixture became a real ``QApplication`` they were impossible, and not
merely awkward: a ``QWidget`` under ``QCoreApplication`` makes Qt call
``abort()``, which kills the pytest process with SIGABRT and loses every other
result in the run. Nothing here is new capability in the application — it is
coverage the suite structurally could not reach.

Each test below pins a contract that was previously verified only by a
throwaway script under a hand-rolled ``QApplication``:

- the canvas draws traces the session created (step C),
- hiding and showing keeps the artist and does not refetch (step B),
- the ROI window constructs and populates itself (the class of bugs 9 and 10,
  which were constructor mismatches no model-side test could reach).

Widget tests are slower than model tests because they wait on the Qt event
loop, so prefer a model-side test whenever the behaviour can be reached
without a widget. Reach for this file when the thing under test *is* the
widget wiring.
"""

from __future__ import annotations

import pytest
from qtpy.QtCore import QEventLoop, QTimer

from nbs_viewer.models.plot.presenter import PlotPresenter
from nbs_viewer.models.plot.run_source import RunSource
from tests.fixtures.catalog_recipes import image_scan_run


def _pump(ms: int = 400) -> None:
    """
    Run the Qt event loop briefly.

    The canvas coalesces repaints behind a 100 ms timer and fetches on worker
    threads, so a test has to let the loop run before asserting. Waiting on
    time rather than on a signal is blunt, but it is what makes these tests
    read like the sequence a user performs.

    Parameters
    ----------
    ms : int, optional
        Milliseconds to let the loop run.
    """
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec_()


@pytest.fixture
def plot_widgets(qapp):
    """
    Return ``(presenter, session, canvas)`` showing one 2-D key, one run.

    Imports the canvas inside the fixture so that collecting this module
    never pulls in matplotlib's Qt backend for a run that deselects it.
    """
    from nbs_viewer.views.plot.mplCanvas.single_canvas import MplCanvas

    presenter = PlotPresenter("widget-test", is_main_display=True)
    session = presenter.session
    canvas = MplCanvas(presenter)
    run = RunSource(image_scan_run(1, n_y=6, n_x=8, n_z=3))
    session.collection.add_runs([run])
    session.collection.set_uids_visible({run.uid}, True)
    session.selection.set_selected_keys(["en_energy"], ["detector_image"], [])
    _pump()
    yield presenter, session, canvas
    canvas.deleteLater()


@pytest.fixture
def roi_window_class(qapp):
    """
    Yield :class:`RoiWindow` with its instance registry cleared around the test.

    ``RoiWindow`` keeps a class-level ``_instances`` dict keyed by presenter
    id, so without this a window outlives the test that made it and the next
    ``open_or_raise`` for the same id hands back a stale one.
    """
    from nbs_viewer.views.plot.roi.window import RoiWindow

    RoiWindow._instances.clear()
    yield RoiWindow
    for window in list(RoiWindow._instances.values()):
        window.close()
        window.deleteLater()
    RoiWindow._instances.clear()


def test_the_canvas_draws_a_trace_the_session_created(plot_widgets):
    """
    Step C's contract: the canvas learns of traces rather than asking for one.

    Membership belongs to the session, so selecting a key must produce both a
    trace and the artist the canvas files under its key, with no call from the
    canvas to ``ensure_trace``.
    """
    _presenter, session, canvas = plot_widgets

    assert len(session.traces) == 1
    key = next(iter(session.traces))
    assert canvas.artist_for(key) is not None
    assert key in canvas._connected_traces


def test_hide_then_show_keeps_the_artist_and_does_not_refetch(plot_widgets):
    """
    Step B's contract: visibility is an artist flag, not a teardown.

    The old code hid a trace by destroying its artist, so showing it again
    started a worker and re-read the database. This is the regression that
    change was made to prevent, and it cannot be observed without a canvas —
    the artist is the thing being reused.
    """
    _presenter, session, canvas = plot_widgets
    run_uid = next(iter(session.collection.visible_uids))
    key = next(iter(session.traces))
    artist_before = canvas.artist_for(key)
    fetched_before = session.traces.get(key).last_fetched_request

    session.collection.set_uids_visible({run_uid}, False)
    _pump()
    assert canvas.artist_for(key) is artist_before
    assert not canvas.artist_for(key).get_visible()

    session.collection.set_uids_visible({run_uid}, True)
    _pump()

    assert canvas.artist_for(key) is artist_before
    assert canvas.artist_for(key).get_visible()
    assert session.traces.get(key).last_fetched_request is fetched_before


def test_the_roi_window_opens_and_offers_profile_axes(
    plot_widgets, roi_window_class
):
    """
    Construction smoke test for the widget with the most constructor coupling.

    Bugs 9 and 10 were both positional-argument mismatches on widget
    constructors — live crashes that no model-side test could reach, because
    the failure is in building the widget at all. Opening the ROI window
    against a 3-D key also exercises the profile-axis dropdown, which is
    populated from the parent projection.
    """
    presenter, session, _canvas = plot_widgets
    session.selection.set_selected_keys(["en_energy"], ["detector_cube"], [])
    session.view_intent.set_plot_ndim(2)
    _pump()

    window = roi_window_class.open_or_raise(presenter)
    _pump()

    assert window.isVisible()
    axes = [
        window.profile_axis_combo.itemData(i)
        for i in range(window.profile_axis_combo.count())
    ]
    assert axes, "a rank-3 key offered no profile axis"
    assert set(axes) <= {0, 1, 2}
