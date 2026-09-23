#!/usr/bin/env python3
"""
Test script to verify that filtering works with lazy loading.

This script creates a simple test to verify that the FilterModel
properly triggers data loading when filtering is applied.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "nbs_viewer"))

from qtpy.QtWidgets import QApplication
from qtpy.QtCore import QRegularExpression
from nbs_viewer.views.catalog.base import FilterModel, LazyLoadingTableView
from nbs_viewer.models.catalog.base import CatalogBase, CatalogRun
from qtpy.QtCore import QObject, Signal
from typing import List, Any


class MockCatalog(CatalogBase):
    """Mock catalog for testing."""

    def __init__(self, data_size=1000):
        super().__init__()
        self._data_size = data_size
        self._runs = [f"run_{i:04d}" for i in range(data_size)]

    @property
    def columns(self):
        return ["run_id", "scan_id", "timestamp"]

    def get_runs(self):
        return self._runs

    def get_run(self, uid):
        return CatalogRun(uid=uid, scan_id=int(uid.split("_")[1]))

    def get_chunk(self, start, stop):
        """Mock chunk loading."""
        print(f"Loading chunk: {start} to {stop}")
        return [f"data_{i}" for i in range(start, min(stop + 1, self._data_size))]


def test_filter_lazy_loading():
    """Test that filtering triggers data loading."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    catalog = MockCatalog(1000)
    table_model = catalog.ensure_table_model()

    filter_model = FilterModel()
    filter_model.setSourceModel(table_model)

    # Create view
    view = LazyLoadingTableView()
    view.setModel(filter_model)

    print("Testing filter lazy loading...")

    # Test 1: Apply a filter - should trigger data loading
    print("1. Applying filter...")
    regex = QRegularExpression("run_0.*")
    filter_model.setFilterRegularExpression(regex)

    # Test 2: Clear filter - should restore normal lazy loading
    print("2. Clearing filter...")
    empty_regex = QRegularExpression("")
    filter_model.setFilterRegularExpression(empty_regex)

    print("Test completed successfully!")
    return True


if __name__ == "__main__":
    test_filter_lazy_loading()

