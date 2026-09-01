"""Tests for PlotModel plot-data map, keys, and run-list protocol."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.cube_view import CubeViewSpec, DimRole, default_spec
from nbs_viewer.models.plot.plot_geometry import prepare_2d_bundle
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.plotDataModel import PlotDataModel
from nbs_viewer.models.plot.plotModel import PlotModel
from nbs_viewer.models.plot.runListModel import RunListModel
from nbs_viewer.models.plot.runModel import RunModel
from nbs_viewer.models.plot.view_crop import ViewCrop
from tests.fixtures.catalog_recipes import line_scan_run


def _make_run_model(memory_run: MemoryRun) -> RunModel:
    return RunModel(memory_run)


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


def test_ensure_plot_data_same_keys_same_instance(qapp):
    run_list = RunListModel()
    plot_model = PlotModel(run_list)
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    run_list.add_run(run_model)

    first = plot_model.ensure_plot_data(run_model, "time", "det")
    second = plot_model.ensure_plot_data(run_model, "time", "det")
    assert first is second
    assert isinstance(first, PlotDataModel)


def test_ensure_plot_data_different_keys_different_instances(qapp):
    run_list = RunListModel()
    plot_model = PlotModel(run_list)
    run_model = _make_run_model(_custom_run(1, ("time", "det", "i0")))
    run_list.add_run(run_model)

    first = plot_model.ensure_plot_data(run_model, "time", "det")
    second = plot_model.ensure_plot_data(run_model, "time", "i0")
    assert first is not second


def test_remove_run_drops_plot_data(qapp):
    run_list = RunListModel()
    plot_model = PlotModel(run_list)
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    run_list.add_run(run_model)
    plot_model.set_selected_keys(["time"], ["det"])
    assert any(key[2] == run_model.uid for key in plot_model.plot_data_map)

    run_list.remove_run(run_model)
    assert all(key[2] != run_model.uid for key in plot_model.plot_data_map)


def test_uncheck_keeps_plot_data_in_map(qapp):
    run_list = RunListModel()
    plot_model = PlotModel(run_list)
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    run_list.add_run(run_model)
    plot_model.set_selected_keys(["time"], ["det"])
    assert len(plot_model.plot_data_map) >= 1

    run_list.set_uids_visible([run_model.uid], False)
    assert any(key[2] == run_model.uid for key in plot_model.plot_data_map)
    assert list(plot_model.iter_visible_plot_data()) == []


def test_visibility_ensures_plot_data_when_keys_selected(qapp):
    run_list = RunListModel(is_main_display=False)
    run_list.set_auto_add(False)
    plot_model = PlotModel(run_list)
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    run_list.add_run(run_model)
    plot_model.set_selected_keys(["time"], ["det"])
    run_list.set_uids_visible([run_model.uid], False)
    plot_model.drop_plot_data_for_uid(run_model.uid)
    assert run_model.uid not in {key[2] for key in plot_model.plot_data_map}

    run_list.set_uids_visible([run_model.uid], True)
    assert ("time", "det", run_model.uid) in plot_model.plot_data_map


def test_two_plot_models_independent_keys_and_maps(qapp):
    run_list = RunListModel()
    first = PlotModel(run_list)
    second = PlotModel(run_list)
    run_model = _make_run_model(_custom_run(1, ("time", "det", "i0")))
    run_list.add_run(run_model)

    first.set_selected_keys(["time"], ["det"])
    second.set_selected_keys(["time"], ["i0"])

    assert first.get_selected_keys()[1] == ["det"]
    assert second.get_selected_keys()[1] == ["i0"]
    assert ("time", "det", run_model.uid) in first.plot_data_map
    assert ("time", "i0", run_model.uid) in second.plot_data_map
    assert ("time", "i0", run_model.uid) not in first.plot_data_map


def test_cube_view_and_crop_without_canvas(qapp):
    plot_model = PlotModel(RunListModel())
    spec = default_spec(3, 2)
    plot_model.set_view_state(
        indices=spec.to_load_slice_info(),
        dimension=2,
        cube_view_spec=spec,
    )
    assert plot_model.dimension == 2
    assert plot_model.cube_view_spec == spec

    crop = MagicMock(spec=ViewCrop)
    plot_model.set_view_crop(crop)
    assert plot_model.view_crop is crop
    plot_model.clear_view_crop()
    assert plot_model.view_crop is None


def test_apply_view_crop_from_region(qapp):
    run_list = RunListModel()
    plot_model = PlotModel(run_list)
    run_model = _make_run_model(_custom_run(1, ("x", "y")))
    run_list.add_run(run_model)
    plot_model.set_selected_keys(["x"], ["y"])

    parent = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    plot_model.set_view_state(
        indices=parent.to_load_slice_info(),
        dimension=2,
        cube_view_spec=parent,
    )

    plot_data = plot_model.ensure_plot_data(run_model, "x", "y")
    plot_data.last_bundle = prepare_2d_bundle(
        np.zeros((5, 6)),
        [np.arange(5), np.arange(6)],
        ["y", "x"],
        render_mode_hint="image",
    )
    run_model.get_dimension_axes = MagicMock(
        return_value=(
            [np.arange(5), np.arange(6)],
            ["y", "x"],
            None,
        )
    )

    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    crop = plot_model.apply_view_crop_from_region(region)

    assert plot_model.view_crop is crop
    assert crop.display_bbox == (2, 4, 2, 4)
    assert crop.source_key == ("x", "y", run_model.uid)


def test_apply_view_crop_from_region_rejects_second_crop(qapp):
    run_list = RunListModel()
    plot_model = PlotModel(run_list)
    run_model = _make_run_model(_custom_run(1, ("x", "y")))
    run_list.add_run(run_model)
    plot_model.set_selected_keys(["x"], ["y"])

    parent = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    plot_model.set_view_state(
        indices=parent.to_load_slice_info(),
        dimension=2,
        cube_view_spec=parent,
    )

    plot_data = plot_model.ensure_plot_data(run_model, "x", "y")
    plot_data.last_bundle = prepare_2d_bundle(
        np.zeros((5, 6)),
        [np.arange(5), np.arange(6)],
        ["y", "x"],
        render_mode_hint="image",
    )
    run_model.get_dimension_axes = MagicMock(
        return_value=(
            [np.arange(5), np.arange(6)],
            ["y", "x"],
            None,
        )
    )

    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    plot_model.apply_view_crop_from_region(region)

    with pytest.raises(ValueError, match="Clear the current crop"):
        plot_model.apply_view_crop_from_region(region)


def test_default_selection_on_first_run(qapp):
    run_list = RunListModel()
    plot_model = PlotModel(run_list)
    run_model = _make_run_model(_custom_run(1, ("time", "det")))
    run_list.add_run(run_model)
    x_keys, y_keys, _ = plot_model.get_selected_keys()
    assert x_keys == ["time"]
    assert y_keys == ["det"]


def test_views_do_not_construct_plot_data_except_image_grid():
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
                    if alias.name == "PlotDataModel":
                        imported.add(name)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in imported:
                    if str(path) not in allowed:
                        hits.append(f"{path}:{func.id}")
    assert hits == []
