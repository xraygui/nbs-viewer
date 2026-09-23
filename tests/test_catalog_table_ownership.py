"""Tests for CatalogBase ownership of CatalogTableModel."""

from nbs_viewer.models.catalog.memory import MemoryCatalog
from nbs_viewer.models.sources.testSource import create_runs
from nbs_viewer.models.catalog.table import CatalogTableModel


def test_ensure_table_model_row_count():
    catalog = MemoryCatalog(create_runs(runs=5))
    table = catalog.ensure_table_model()
    assert isinstance(table, CatalogTableModel)
    assert table.rowCount() == 5
    assert table.columnCount() == len(catalog.columns)


def test_ensure_table_model_returns_same_instance():
    catalog = MemoryCatalog(create_runs(runs=3))
    first = catalog.ensure_table_model()
    second = catalog.ensure_table_model()
    assert first is second


def test_refresh_table_model_after_search():
    catalog = MemoryCatalog(create_runs(runs=10))
    table = catalog.ensure_table_model()
    assert table.rowCount() == 10

    catalog.filter_by_time(since="2026-08-01", until="2026-08-01")
    assert len(catalog) == 0
    catalog.refresh_table_model()
    assert table is catalog.ensure_table_model()
    assert table.rowCount() == 0

    catalog.filter_by_time(since="2026-08-01", until="2026-08-02")
    catalog.refresh_table_model()
    assert table.rowCount() == 10


def test_add_runs_updates_owned_table_via_signal():
    catalog = MemoryCatalog(create_runs(runs=2))
    table = catalog.ensure_table_model()
    assert table.rowCount() == 2

    catalog.add_runs(create_runs(runs=3))
    assert table.rowCount() == 5
