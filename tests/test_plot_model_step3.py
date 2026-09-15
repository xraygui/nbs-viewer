"""Tests for PlotSession plot-data map, keys, and run-list protocol."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.view.spec import DimRole, Projection, ViewCrop
from nbs_viewer.models.plot.geometry.region import RectRegion
from nbs_viewer.models.plot.fetch.request import TraceKey
from nbs_viewer.models.plot.trace import Trace
from nbs_viewer.models.plot.session import PlotSession
from tests.fixtures.view import apply_projection
from nbs_viewer.models.plot.run.source import RunSource
from tests.fixtures.catalog_recipes import image_scan_run, line_scan_run
from tests.fixtures.display_plane import display_bundle
from tests.fixtures.plot_session import make_plot_session


def _make_run_model(memory_run: MemoryRun) -> RunSource:
    return RunSource(memory_run)


def _custom_run(scan_id: int, keys: tuple[str, ...], *, length: int = 100) -> MemoryRun:
    base = line_scan_run(scan_id)
    t = np.linspace(0, 1, length)
    data = {}
    for key in keys:
        if key == "time":
            data[key] = t
        else:
            data[key] = np.ones(length, dtype=float) * (scan_id + 1)
    return MemoryRun(base.metadata, data)


def test_ensure_trace_same_keys_same_instance(qapp):
    plot_model, _ = make_plot_session()
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    plot_model.collection.add_runs([run_model])

    first = plot_model.ensure_trace(run_model, "time", "det")
    second = plot_model.ensure_trace(run_model, "time", "det")
    assert first is second
    assert isinstance(first, Trace)


def test_ensure_trace_different_keys_different_instances(qapp):
    plot_model, _ = make_plot_session()
    run_model = _make_run_model(_custom_run(1, ("time", "det", "i0")))
    plot_model.collection.add_runs([run_model])

    first = plot_model.ensure_trace(run_model, "time", "det")
    second = plot_model.ensure_trace(run_model, "time", "i0")
    assert first is not second


def test_remove_run_drops_plot_data(qapp):
    plot_model, _ = make_plot_session()
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    plot_model.collection.add_runs([run_model])
    plot_model.selection.set_selected_keys(["time"], ["det"])
    assert any(key.uid == run_model.uid for key in plot_model.traces)

    plot_model.collection.remove_uids([run_model.uid])
    assert all(key.uid != run_model.uid for key in plot_model.traces)


def test_uncheck_keeps_plot_data_in_map(qapp):
    plot_model, _ = make_plot_session()
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    plot_model.collection.add_runs([run_model])
    plot_model.selection.set_selected_keys(["time"], ["det"])
    assert len(plot_model.traces) >= 1

    plot_model.collection.set_uids_visible([run_model.uid], False)
    assert any(key.uid == run_model.uid for key in plot_model.traces)
    assert list(plot_model.iter_visible_traces()) == []


def test_visibility_does_not_rebuild_the_trace_set(qapp):
    """
    Showing a run reuses its traces rather than recreating them.

    Retention is membership x selection, so a visibility change has nothing
    to rebuild -- and rebuilding would hand the canvas a new ``Trace`` for
    an artist it has already filed under the same key.
    """
    plot_model, _ = make_plot_session(is_main_display=False)
    plot_model.collection.set_auto_add(False)
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    plot_model.collection.add_runs([run_model])
    plot_model.selection.set_selected_keys(["time"], ["det"])

    key = TraceKey(run_model.uid, "time", "det")
    trace = plot_model.traces.get(key)
    assert trace is not None

    plot_model.collection.set_uids_visible([run_model.uid], False)
    plot_model.collection.set_uids_visible([run_model.uid], True)

    assert plot_model.traces.get(key) is trace


def test_two_plot_models_independent_keys_and_maps(qapp):
    first, _ = make_plot_session()
    second, _ = make_plot_session()
    run_a = _make_run_model(_custom_run(1, ("time", "det", "i0")))
    run_b = _make_run_model(_custom_run(2, ("time", "det", "i0")))
    first.collection.add_runs([run_a])
    second.collection.add_runs([run_b])

    first.selection.set_selected_keys(["time"], ["det"])
    second.selection.set_selected_keys(["time"], ["i0"])

    assert first.selection.get_selected_keys()[1] == ["det"]
    assert second.selection.get_selected_keys()[1] == ["i0"]
    assert TraceKey(run_a.uid, "time", "det") in first.traces
    assert TraceKey(run_b.uid, "time", "i0") in second.traces
    assert TraceKey(run_a.uid, "time", "i0") not in first.traces


def test_cube_view_and_crop_without_canvas(qapp):
    plot_model = PlotSession()
    plot_model.view_intent.set_plot_ndim(2)
    assert plot_model.view_intent.plot_ndim == 2

    crop = ViewCrop(storage_bbox=(0, 2, 0, 3), plot_y_axis=0, plot_x_axis=1)
    plot_model.region.set_view_crop(crop, ("x", "y", "uid"))
    assert plot_model.region.view_crop is crop
    plot_model.region.set_view_crop(None)
    assert plot_model.region.view_crop is None


def _image_session(qapp):
    """
    Return ``(plot_model, run_model, plot_data)`` showing a 2-D image plane.
    """
    plot_model, _ = make_plot_session()
    run_model = _make_run_model(image_scan_run(1, n_y=5, n_x=6))
    plot_model.collection.add_runs([run_model])
    plot_model.selection.set_selected_keys(["pixel"], ["detector_image"])

    parent = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    apply_projection(plot_model.view_intent, parent)
    plot_data = plot_model.ensure_trace(
        run_model, "pixel", "detector_image"
    )
    plot_data.last_bundle = display_bundle(
        np.zeros((5, 6)),
        np.arange(5, dtype=float),
        np.arange(6, dtype=float),
        ["row", "pixel"],
    )
    return plot_model, run_model, plot_data


def test_apply_view_crop_from_region(qapp):
    plot_model, run_model, plot_data = _image_session(qapp)

    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    crop = plot_model.region.apply_view_crop_from_region(region)

    assert plot_model.region.view_crop is crop
    assert crop.storage_bbox == (1, 3, 2, 4)
    assert plot_model.region.crop_applies_to(plot_data.trace_key)


def test_apply_view_crop_from_region_rejects_second_crop(qapp):
    plot_model, _run_model, _plot_data = _image_session(qapp)

    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    plot_model.region.apply_view_crop_from_region(region)

    with pytest.raises(ValueError, match="Clear the current crop"):
        plot_model.region.apply_view_crop_from_region(region)


def test_default_selection_on_first_run(qapp):
    plot_model, _ = make_plot_session()
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    plot_model.collection.add_runs([run_model])
    x_keys, y_keys, _ = plot_model.selection.get_selected_keys()
    assert x_keys == ["time"]
    assert y_keys == ["det"]


def test_plot_model_modules_are_snake_case():
    """
    The naming the refactor settled on, pinned so it cannot drift back.

    ``models/plot/`` was the package the refactor rewrote, so it is the one
    held to the rule. The camelCase modules still under ``models/cache/``
    and ``models/sources/`` are untouched by it and are repo hygiene, not
    this guard's business.
    """
    plot_root = (
        Path(__file__).resolve().parents[1] / "nbs_viewer" / "models" / "plot"
    )
    offenders = [
        path.name
        for path in plot_root.glob("*.py")
        if path.stem != path.stem.lower()
    ]
    assert offenders == []


def test_views_do_not_construct_traces_except_image_grid():
    views_root = Path(__file__).resolve().parents[1] / "nbs_viewer" / "views"
    allowed = {
        str(views_root / "plot" / "mplCanvas" / "image_grid_canvas.py"),
    }
    hits = []
    for path in views_root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    if alias.name == "Trace":
                        imported.add(name)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in imported:
                    if str(path) not in allowed:
                        hits.append(f"{path}:{func.id}")
    assert hits == []
