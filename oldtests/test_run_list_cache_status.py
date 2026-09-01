"""Tests for cache status aggregation on RunListModel and PlotPresenter."""

from types import SimpleNamespace

from nbs_viewer.models.cache.chunk_cache_progress import ChunkCacheProgress
from nbs_viewer.models.plot.displayManager import PlotPresenter
from nbs_viewer.models.plot.runListModel import RunListModel


def _fake_run_model(chunk_cache):
    return SimpleNamespace(
        uid="test-uid",
        _run=SimpleNamespace(_chunk_cache=chunk_cache),
    )


def test_run_list_model_aggregates_multiple_cache_progress_sources():
    model = RunListModel()
    progress_a = ChunkCacheProgress()
    progress_b = ChunkCacheProgress()
    cache_a = SimpleNamespace(progress=progress_a)
    cache_b = SimpleNamespace(progress=progress_b)

    statuses = []
    model.cache_status_changed.connect(statuses.append)

    model._run_models["uid-a"] = _fake_run_model(cache_a)
    model._run_models["uid-b"] = _fake_run_model(cache_b)
    model._refresh_cache_progress_connections()

    progress_a.update("uid-a", "det", 2, 4, active=True)
    progress_b.update("uid-b", "det", 1, 3, active=True)

    assert statuses[-1] == "Fetching 4/7"


def test_run_list_model_clears_cache_status_when_runs_removed():
    model = RunListModel()
    progress = ChunkCacheProgress()
    cache = SimpleNamespace(progress=progress)

    statuses = []
    model.cache_status_changed.connect(statuses.append)

    model._run_models["uid-a"] = _fake_run_model(cache)
    model._refresh_cache_progress_connections()
    progress.update("uid-a", "det", 2, 4, active=True)

    model._run_models.clear()
    model._refresh_cache_progress_connections()

    assert statuses[-1] == ""


def test_plot_presenter_forwards_cache_status():
    presenter = PlotPresenter("sess")
    statuses = []
    presenter.status_changed.connect(statuses.append)

    presenter.run_list.cache_status_changed.emit("Fetching 1/4")

    assert statuses == ["Fetching 1/4"]
