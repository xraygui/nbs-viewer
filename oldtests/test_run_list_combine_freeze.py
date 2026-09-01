"""Tests for RunListModel combine / freeze factories."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nbs_viewer.models.plot.combinedRunModel import (
    CombinationMethod,
    CombineError,
    CombinedRunModel,
)
from nbs_viewer.models.plot.frozenRunModel import FrozenRunModel
from nbs_viewer.models.plot.runListModel import RunListModel
from nbs_viewer.models.plot.runModel import RunModel


def _mock_catalog_run(uid, scan_id, keys, shape=(100,), plan_name="test"):
    run = MagicMock()
    run.uid = uid
    run.scan_id = scan_id
    run.available_keys = list(keys)
    run.get_default_selection.return_value = (
        [keys[0]] if keys else [],
        [keys[1]] if len(keys) > 1 else [],
        [],
    )
    run.getShape.return_value = shape
    run.data_changed = MagicMock()
    run.data_changed.connect = MagicMock()
    run.data_changed.disconnect = MagicMock()
    run.keys_ready = MagicMock()
    run.keys_ready.connect = MagicMock()
    run.keys_error = MagicMock()
    run.keys_error.connect = MagicMock()
    run.start = {}
    run.metadata = {}
    run.display_name = f"scan {scan_id}"
    run.plan_name = plan_name
    return run


def _make_run_model(uid, scan_id, keys=("time", "det"), shape=(100,)):
    return RunModel(_mock_catalog_run(uid, scan_id, keys, shape=shape))


def test_combine_runs_adds_one_combined_entry():
    run_list = RunListModel()
    first = _make_run_model("uid-1", 1)
    second = _make_run_model("uid-2", 2)
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


def test_validate_combine_rejects_single_run():
    run_list = RunListModel()
    first = _make_run_model("uid-1", 1)
    with pytest.raises(CombineError, match="at least 2"):
        run_list.validate_combine([first])


def test_validate_combine_rejects_no_common_keys():
    run_list = RunListModel()
    first = _make_run_model("uid-1", 1, keys=("time", "det_a"))
    second = _make_run_model("uid-2", 2, keys=("energy", "det_b"))
    with pytest.raises(CombineError, match="no common data keys"):
        run_list.validate_combine([first, second])


def test_validate_combine_rejects_shape_mismatch():
    run_list = RunListModel()
    first = _make_run_model("uid-1", 1, shape=(100,))
    second = _make_run_model("uid-2", 2, shape=(50,))
    with pytest.raises(CombineError, match="different data shapes"):
        run_list.validate_combine([first, second])


def test_combine_runs_rejects_incompatible():
    run_list = RunListModel()
    first = _make_run_model("uid-1", 1, keys=("time", "det_a"))
    second = _make_run_model("uid-2", 2, keys=("energy", "det_b"))
    before = len(run_list.available_models)
    with pytest.raises(CombineError):
        run_list.combine_runs([first, second])
    assert len(run_list.available_models) == before


def test_freeze_runs_adds_frozen_entries_for_selected_y():
    run_list = RunListModel()
    first = _make_run_model("uid-1", 1, keys=("time", "det", "i0"))
    second = _make_run_model("uid-2", 2, keys=("time", "det", "i0"))
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


def test_freeze_runs_noop_without_selected_y():
    run_list = RunListModel()
    first = _make_run_model("uid-1", 1)
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
