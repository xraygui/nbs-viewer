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

from nbs_viewer.models.displays.presenter import PlotPresenter
from nbs_viewer.models.plot.run.source import RunSource
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


@pytest.mark.parametrize(
    "role_name, reduce_name", [("SUM", "sum"), ("MEAN", "mean")]
)
def test_the_reduce_combo_actually_reduces_the_slider_axis(
    plot_widgets, role_name, reduce_name
):
    """
    Bug: picking Sum or Mean on a slider axis produced no plot at all.

    ``DimRole`` subclasses ``str`` and the combo stores its roles as item
    data, which Qt round-trips through a ``QVariant`` and hands back as a
    plain ``str``. Every check between the combo and the reduce stage
    compares with ``==`` or ``in`` and so accepted it; the reduce stage
    matches with ``is`` and so skipped the axis, leaving a rank-3 array for
    a pack that only takes planes -- "Unsupported plot dimensionality: 3".

    Only a widget can reach this: the model layer is handed a real
    ``DimRole`` by every caller that is not a ``QComboBox``.
    """
    import numpy as np

    from nbs_viewer.models.plot.plane.roles import DimRole
    from nbs_viewer.views.plot.controls.dimension import DimensionControl

    presenter, session, canvas = plot_widgets
    session.selection.set_selected_keys(["en_energy"], ["detector_cube"], [])
    session.view_intent.set_plot_ndim(2)
    dimension_control = DimensionControl(presenter, canvas)
    _pump()
    dimension_control.create_sliders()

    assert dimension_control._slice_rows, "no slider axis to reduce"
    row = dimension_control._slice_rows[0]
    reduced_axis = row.storage_axis
    trace = next(iter(session.traces.values()))
    block = trace.run.load(
        "detector_cube", dims=trace.request.dims, xkeys=("en_energy",)
    )

    role = getattr(DimRole, role_name)
    row.role_combo.setCurrentIndex(row.role_combo.findData(role))
    _pump()

    assert trace.request.view.roles[reduced_axis] is role
    bundle = trace.fetch()
    assert bundle.ndim == 2
    expected = getattr(block, reduce_name)(
        dim=trace.request.dims[reduced_axis]
    )
    np.testing.assert_allclose(
        np.sort(bundle.y, axis=None), np.sort(expected.values, axis=None)
    )


def test_a_re_created_image_rescales_the_axes(qapp):
    """
    Bug: swapping the plot axes left the image drawn against stale limits.

    ``imshow`` sets the axis limits only while the axes still autoscale, and
    ``set_xlim`` / ``set_ylim`` turn that off for good. The update path calls
    both, so the *next* image created on those axes -- which is what an
    orientation change produces, since it tears the 2-D axes down first --
    inherited the limits of the orientation before it, and the plane was
    drawn cut off until the next slider step took the update path again.
    """
    import numpy as np
    from matplotlib.figure import Figure

    from nbs_viewer.models.plot.spec.bundle import PlotBundle
    from nbs_viewer.views.plot.mplCanvas.renderers import ImageRenderer

    tall = PlotBundle.from_2d(
        np.zeros((32, 4)), [np.arange(32.0), np.arange(4.0)], ["row", "col"]
    )
    wide = PlotBundle.from_2d(
        np.zeros((4, 32)), [np.arange(4.0), np.arange(32.0)], ["col", "row"]
    )
    fig = Figure()
    axes = fig.add_subplot(111)
    state = {}

    artist, _cbar = ImageRenderer.create(axes, fig, tall, "y", state)
    ImageRenderer.update(artist, tall, True, state)
    artist.remove()
    ImageRenderer.create(axes, fig, wide, "y", state)

    left, right, bottom, top = wide.extent
    assert axes.get_xlim() == (left, right)
    assert axes.get_ylim() == (bottom, top)


def test_swapping_the_plot_axes_rescales_the_drawn_plane(plot_widgets):
    """
    The gesture the stale limits were reported from, end to end.

    Stepping the index slider first is what makes this fail: it renders
    through the update path, which is what turns the axes' autoscaling off.
    """
    from nbs_viewer.views.plot.controls.dimension import DimensionControl

    presenter, session, canvas = plot_widgets
    session.selection.set_selected_keys(["en_energy"], ["detector_cube"], [])
    session.view_intent.set_plot_ndim(2)
    dimension_control = DimensionControl(presenter, canvas)
    _pump()
    dimension_control.create_sliders()

    dimension_control._slice_rows[0].slider.setValue(1)
    _pump()
    dimension_control._plot_rows[0].move_down_requested.emit()
    _pump()

    trace = next(iter(session.traces.values()))
    left, right, bottom, top = trace.last_bundle.extent
    assert canvas.axes.get_xlim() == (left, right)
    assert canvas.axes.get_ylim() == (bottom, top)


def _panel_bounds(panel):
    """
    Return the height limits a panel is currently pinned between.
    """
    return panel.minimumHeight(), panel.maximumHeight()


def _toggled_bounds(panel):
    """
    Return the bounds a collapse-and-re-expand cycle settles the panel at.

    Toggling twice is the workaround this bug was reported with, and it is
    the only statement of "the right height" that does not re-implement the
    panel's own arithmetic in the test.
    """
    panel.toggle()
    _pump()
    panel.toggle()
    _pump()
    return _panel_bounds(panel)


def test_an_expanded_panel_follows_its_content_growing_and_shrinking(qapp):
    """
    Bug: an open panel kept the height its content had when it was opened.

    ``refresh_expanded_size`` measured the inner widget the moment it was
    called, which is before Qt has laid the new content out: freshly built
    rows are still hidden, a box layout skips hidden widgets, and the
    ``maximumHeight`` cap computed from that total squashed the content that
    appeared a moment later. The same staleness in reverse left a panel at
    full height around content that had gone away.
    """
    from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget

    from nbs_viewer.views.common.panel import CollapsiblePanel

    content = QWidget()
    content_layout = QVBoxLayout(content)
    panel = CollapsiblePanel("Content", content, initially_expanded=True)
    panel.show()
    _pump()
    empty_bounds = _panel_bounds(panel)

    rows = [QLabel(f"row {i}") for i in range(4)]
    for row in rows:
        content_layout.addWidget(row)
    panel.refresh_expanded_size()
    _pump()

    grown_bounds = _panel_bounds(panel)
    assert grown_bounds[1] > empty_bounds[1]
    assert grown_bounds == _toggled_bounds(panel)

    for row in rows:
        content_layout.removeWidget(row)
        row.deleteLater()
    panel.refresh_expanded_size()
    _pump()

    assert _panel_bounds(panel) == empty_bounds
    panel.deleteLater()


def test_the_dimension_panel_resizes_when_a_key_is_selected(plot_widgets):
    """
    The reported gesture: the dimension rows appear under an open panel.
    """
    from nbs_viewer.views.plot.controls.control_panel import ControlPanel

    presenter, session, canvas = plot_widgets
    controls = ControlPanel(presenter, canvas, enable_spatial_controls=True)
    controls.show()
    panel = controls.dimension_control_panel
    if panel.is_collapsed:
        panel.toggle()
    _pump()

    session.selection.set_selected_keys(["en_energy"], [], [])
    _pump()
    empty_bounds = _panel_bounds(panel)

    session.selection.set_selected_keys(["en_energy"], ["detector_image"], [])
    _pump()

    grown_bounds = _panel_bounds(panel)
    assert grown_bounds[1] > empty_bounds[1]
    assert grown_bounds == _toggled_bounds(panel)

    session.selection.set_selected_keys(["en_energy"], [], [])
    _pump()

    assert _panel_bounds(panel) == empty_bounds
    controls.deleteLater()
