"""Tests for cache status aggregation on the session and PlotPresenter."""

from types import SimpleNamespace

from nbs_viewer.models.cache.chunk_cache_progress import ChunkCacheProgress
from nbs_viewer.models.plot.display_manager import PlotPresenter
from nbs_viewer.models.plot.run_source import RunSource
from tests.fixtures.catalog_recipes import line_scan_run
from tests.fixtures.plot_session import make_plot_session


def _run_with_cache(scan_id, progress):
    """
    Return a real run whose chunk cache reports through ``progress``.

    The session discovers progress sources by walking its members, so the
    run has to go through the collection's own add path to be found.
    """
    source = RunSource(line_scan_run(scan_id))
    source._run._chunk_cache = SimpleNamespace(progress=progress)
    return source


def test_session_aggregates_multiple_cache_progress_sources(qapp):
    session, _run_list = make_plot_session()
    progress_a = ChunkCacheProgress()
    progress_b = ChunkCacheProgress()

    statuses = []
    session.cache_status_changed.connect(statuses.append)

    run_a = _run_with_cache(1, progress_a)
    run_b = _run_with_cache(2, progress_b)
    session.collection.add_runs([run_a, run_b])

    progress_a.update(run_a.uid, "det", 2, 4, active=True)
    progress_b.update(run_b.uid, "det", 1, 3, active=True)

    assert statuses[-1] == "Fetching 4/7"


def test_session_clears_cache_status_when_runs_removed(qapp):
    session, _run_list = make_plot_session()
    progress = ChunkCacheProgress()

    statuses = []
    session.cache_status_changed.connect(statuses.append)

    run = _run_with_cache(1, progress)
    session.collection.add_runs([run])
    progress.update(run.uid, "det", 2, 4, active=True)

    session.collection.remove_uids([run.uid])

    assert statuses[-1] == ""


def test_plot_presenter_forwards_cache_status(qapp):
    presenter = PlotPresenter("sess")
    statuses = []
    presenter.status_changed.connect(statuses.append)

    presenter.session.cache_status_changed.emit("Fetching 1/4")

    assert statuses == ["Fetching 1/4"]
