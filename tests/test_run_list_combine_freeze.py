"""Tests for RunListModel combine / freeze factories."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.combinedRunModel import (
    CombinationMethod,
    CombineError,
    CombinedRunModel,
)
from nbs_viewer.models.plot.frozenRunModel import FrozenRunModel
from nbs_viewer.models.plot.runListModel import RunListModel
from nbs_viewer.models.plot.runModel import RunModel
from tests.fixtures.catalog_recipes import line_scan_run


def _make_run_model(memory_run: MemoryRun) -> RunModel:
    return RunModel(memory_run)


def _run_model_with_keys(memory_run: MemoryRun, keys: tuple[str, ...]) -> RunModel:
    model = RunModel(memory_run)
    model._catalog_keys = list(keys)
    return model


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


def test_combine_runs_adds_one_combined_entry(qapp):
    run_list = RunListModel()
    first = _make_run_model(line_scan_run(1))
    second = _make_run_model(line_scan_run(2))
    run_list.add_runs([first, second])
    before = len(run_list.available_models)

    combined = run_list.combine_runs(
        [first, second], method=CombinationMethod.SUM
    )

    assert isinstance(combined, CombinedRunModel)
    assert combined in run_list.available_models
    assert len(run_list.available_models) == before + 1
    assert combined.combination_method == CombinationMethod.SUM
    assert set(combined.source_runs) == {first, second}


def test_validate_combine_rejects_single_run(qapp):
    run_list = RunListModel()
    first = _make_run_model(line_scan_run(1))
    with pytest.raises(CombineError, match="at least 2"):
        run_list.validate_combine([first])


def test_validate_combine_rejects_no_common_keys(qapp):
    run_list = RunListModel()
    first = _run_model_with_keys(line_scan_run(1), ("time", "det_a"))
    second = _run_model_with_keys(line_scan_run(2), ("energy", "det_b"))
    with pytest.raises(CombineError, match="no common data keys"):
        run_list.validate_combine([first, second])


def test_validate_combine_rejects_shape_mismatch(qapp):
    run_list = RunListModel()
    first = _make_run_model(_custom_run(1, ("time", "det"), length=100))
    second = _make_run_model(_custom_run(2, ("time", "det"), length=50))
    with pytest.raises(CombineError, match="different data shapes"):
        run_list.validate_combine([first, second])


def test_combine_runs_rejects_incompatible(qapp):
    run_list = RunListModel()
    first = _run_model_with_keys(line_scan_run(1), ("time", "det_a"))
    second = _run_model_with_keys(line_scan_run(2), ("energy", "det_b"))
    before = len(run_list.available_models)
    with pytest.raises(CombineError):
        run_list.combine_runs([first, second])
    assert len(run_list.available_models) == before


def test_freeze_runs_adds_frozen_entries_for_selected_y(qapp):
    run_list = RunListModel()
    first = _make_run_model(_custom_run(1, ("time", "det", "i0")))
    second = _make_run_model(_custom_run(2, ("time", "det", "i0")))
    run_list.add_runs([first, second])
    first.set_selected_keys(["time"], ["det", "i0"])
    second.set_selected_keys(["time"], ["det"])
    before = len(run_list.available_models)

    frozen = run_list.freeze_runs([first, second])

    assert len(frozen) == 3
    assert all(isinstance(item, FrozenRunModel) for item in frozen)
    assert len(run_list.available_models) == before + 3
    assert {item.display_name for item in frozen} == {
        "det of 1",
        "i0 of 1",
        "det of 2",
    }


def test_freeze_runs_noop_without_selected_y(qapp):
    run_list = RunListModel()
    first = _make_run_model(line_scan_run(1))
    run_list.add_run(first)
    first.set_selected_keys(["time"], [])
    before = len(run_list.available_models)
    frozen = run_list.freeze_runs([first])
    assert frozen == []
    assert len(run_list.available_models) == before


def test_views_do_not_construct_combined_or_frozen_run_models():
    views_root = Path(__file__).resolve().parents[1] / "nbs_viewer" / "views"
    forbidden = {"CombinedRunModel", "FrozenRunModel"}
    hits = []
    for path in views_root.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    if alias.name in forbidden:
                        imported.add(name)
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in imported:
                    hits.append(f"{path}:{func.id}")
    assert hits == []
