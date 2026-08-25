from .base import SourceModel, CatalogLoadError
from ..catalog.memory import MemoryCatalog
from ..data.memory import MemoryRun
from uuid import uuid4
import numpy as np
from datetime import datetime, timedelta

def create_metadata(date='2026-08-01', runs=10):
    base_datetime = datetime.strptime(date, "%Y-%m-%d")
    return [{"scan_id": i, "plan_name": "test", "date": base_datetime + timedelta(minutes=10 * i), "exit_status": "Success", "uid": str(uuid4())} for i in range(runs)]

def create_data(runs=10):
    return [{"time": np.linspace(0, 1, 50), 'y': np.sin(np.linspace(0, 1, 50)*np.pi)} for i in range(runs)]

def create_runs(runs=10):
    metadata = create_metadata(runs=runs)
    data = create_data(runs=runs)
    return [MemoryRun(m, d) for m, d in zip(metadata, data)]

def create_test_catalog(runs=10):
    runs = create_runs(runs)
    c = MemoryCatalog(runs)
    return c

class TestSourceModel(SourceModel):
    def __init__(self, runs=10):
        self.runs = runs
        self.catalog = create_test_catalog(runs)

    def get_source(self):
        return self.catalog, "Test Catalog"

    def is_configured(self):
        return True

    def get_display_label(self):
        return "Test Catalog"