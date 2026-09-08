"""Tests for RunListItemModel combine / freeze factories."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.combinedRunSource import (
    CombinationMethod,
    CombineError,
    CombinedRunSource,
)
from nbs_viewer.models.plot.frozenRunSource import FrozenRunSource
from nbs_viewer.models.plot.plot_session import PlotSession
from nbs_viewer.views.dataSource.run_list_item_model import RunListItemModel
from nbs_viewer.models.plot.runSource import RunSource
from tests.fixtures.catalog_recipes import line_scan_run
from tests.fixtures.plot_session import make_plot_session


def _bound_session() -> tuple[PlotSession, RunListItemModel]:
    return make_plot_session()


def _make_run_model(memory_run: MemoryRun) -> RunSource:
    return RunSource(memory_run)


def _run_model_with_keys(memory_run: MemoryRun, keys: tuple[str, ...]) -> RunSource:
    model = RunSource(memory_run)
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
    session, run_list = _bound_session()
    first = _make_run_model(line_scan_run(1))
    second = _make_run_model(line_scan_run(2))
    session.add_runs([first, second])
    before = len(session.available_models)

    combined = session.combine_runs(
        [first, second], method=CombinationMethod.SUM
    )

    assert isinstance(combined, CombinedRunSource)
    assert combined in session.available_models
    assert len(session.available_models) == before + 1
    assert combined.combination_method == CombinationMethod.SUM
    assert set(combined.source_runs) == {first, second}
    assert run_list.rowCount() == len(session.available_models)


def test_validate_combine_rejects_single_run(qapp):
    session, _ = _bound_session()
    first = _make_run_model(line_scan_run(1))
    with pytest.raises(CombineError, match="at least 2"):
        session.validate_combine([first])


def test_validate_combine_rejects_no_common_keys(qapp):
    session, _ = _bound_session()
    first = _run_model_with_keys(line_scan_run(1), ("time", "det_a"))
    second = _run_model_with_keys(line_scan_run(2), ("energy", "det_b"))
    with pytest.raises(CombineError, match="no common data keys"):
        session.validate_combine([first, second])


def test_validate_combine_rejects_shape_mismatch(qapp):
    session, _ = _bound_session()
    first = _make_run_model(_custom_run(1, ("time", "det"), length=100))
    second = _make_run_model(_custom_run(2, ("time", "det"), length=50))
    with pytest.raises(CombineError, match="different data shapes"):
        session.validate_combine([first, second])


def test_combine_runs_rejects_incompatible(qapp):
    session, _ = _bound_session()
    first = _run_model_with_keys(line_scan_run(1), ("time", "det_a"))
    second = _run_model_with_keys(line_scan_run(2), ("energy", "det_b"))
    before = len(session.available_models)
    with pytest.raises(CombineError):
        session.combine_runs([first, second])
    assert len(session.available_models) == before


def test_freeze_runs_adds_frozen_entries_for_selected_y(qapp):
    session, _ = _bound_session()
    first = _make_run_model(_custom_run(1, ("time", "det", "i0")))
    second = _make_run_model(_custom_run(2, ("time", "det", "i0")))
    session.add_runs([first, second])
    session.set_selection_for(first.uid, ["time"], ["det", "i0"])
    session.set_selection_for(second.uid, ["time"], ["det"])
    before = len(session.available_models)

    frozen = session.freeze_runs([first, second])

    assert len(frozen) == 3
    assert all(isinstance(item, FrozenRunSource) for item in frozen)
    assert len(session.available_models) == before + 3
    assert {item.display_name for item in frozen} == {
        "det of 1",
        "i0 of 1",
        "det of 2",
    }


def test_freeze_runs_noop_without_selected_y(qapp):
    session, _ = _bound_session()
    first = _make_run_model(line_scan_run(1))
    session.add_run(first)
    session.set_selection_for(first.uid, ["time"], [])
    before = len(session.available_models)
    frozen = session.freeze_runs([first])
    assert frozen == []
    assert len(session.available_models) == before


def test_views_do_not_construct_combined_or_frozen_run_models():
    views_root = Path(__file__).resolve().parents[1] / "nbs_viewer" / "views"
    forbidden = {"CombinedRunSource", "FrozenRunSource"}
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
