from typing import Any, List, Optional, Generator, Tuple
from qtpy.QtCore import QObject, Signal

from .base import CatalogBase
from ..data.memory import MemoryRun

class MemoryCatalog(CatalogBase):
    """
    Implementation for an in-memory catalog
    """

    def __init__(self, runs = None, parent = None):
        super().__init__(parent)
        self._catalog = {}
        if runs is not None:
            self.add_runs(runs)

    def __len__(self):
        return len(self._catalog)

    @property
    def columns(self) -> List[str]:
        """Get column names for display."""
        return MemoryRun.to_header()

    def get_run(self, uid: str) -> MemoryRun:
        if uid not in self._catalog:
            raise KeyError(f"No run found with UID {uid}")
        return self._catalog[uid]

    def items_slice(self, s: slice) -> Generator[Tuple[str, MemoryRun], None, None]:  # type: ignore
        runs = list(self._catalog.items())[s]
        for run in runs:
            yield run.uid, run

    def add_run(self, run: MemoryRun):
        self._catalog[run.uid] = run
        self.data_updated.emit()

    def add_runs(self, runs: List):
        for run in runs:
            self._catalog[run.uid] = run
        self.data_updated.emit()

    def remove_runs(self, uids: List[str]) -> None:
        for uid in uids:
            self._catalog.pop(uid, None)
        self.data_updated.emit()

    def remove_all_runs(self) -> None:
        self._catalog.clear()
        self.data_updated.emit()