from typing import Any, List, Optional, Generator, Tuple
from datetime import datetime, date

from databroker.queries import TimeRange

from .base import CatalogBase
from ..data.memory import MemoryRun


class MemoryCatalog(CatalogBase):
    """
    Implementation for an in-memory catalog.

    Like BlueskyCatalog, search mutates the visible catalog in place while
    keeping the full run set in ``_base_catalog``.
    """

    def __init__(self, runs=None, parent=None):
        super().__init__(parent)
        self._base_catalog = {}
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

    def get_runs(self) -> List[MemoryRun]:
        """Get all currently visible runs."""
        return list(self._catalog.values())

    def items_slice(self, s: slice) -> Generator[Tuple[str, MemoryRun], None, None]:
        runs = list(self._catalog.values())[s]
        for run in runs:
            yield run.uid, run

    def add_run(self, run: MemoryRun):
        self._base_catalog[run.uid] = run
        self._catalog[run.uid] = run
        self.data_updated.emit()

    def add_runs(self, runs: List):
        for run in runs:
            self._base_catalog[run.uid] = run
            self._catalog[run.uid] = run
        self.data_updated.emit()

    def remove_runs(self, uids: List[str]) -> None:
        for uid in uids:
            self._base_catalog.pop(uid, None)
            self._catalog.pop(uid, None)
        self.data_updated.emit()

    def remove_all_runs(self) -> None:
        self._base_catalog.clear()
        self._catalog.clear()
        self.data_updated.emit()

    @staticmethod
    def _run_timestamp(run: MemoryRun) -> Optional[float]:
        """
        Convert a run's date/time metadata to a Unix timestamp.

        Parameters
        ----------
        run : MemoryRun
            Run to inspect.

        Returns
        -------
        float or None
            Timestamp in seconds since the epoch, or None if unavailable.
        """
        value = getattr(run, "date", None)
        if value is None:
            value = run.metadata.get("time", run.metadata.get("date"))
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, datetime):
            return value.timestamp()
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time()).timestamp()
        return None

    def _in_time_range(
        self,
        run: MemoryRun,
        since: Optional[float],
        until: Optional[float],
    ) -> bool:
        """
        Check whether a run falls within a time range.

        Parameters
        ----------
        run : MemoryRun
            Run to test.
        since : float or None
            Inclusive lower bound as Unix timestamp.
        until : float or None
            Exclusive upper bound as Unix timestamp.

        Returns
        -------
        bool
            True if the run matches the range (or has no timestamp).
        """
        timestamp = self._run_timestamp(run)
        if timestamp is None:
            return True
        if since is not None and timestamp < since:
            return False
        if until is not None and timestamp >= until:
            return False
        return True

    def search(self, query: Any) -> "MemoryCatalog":
        """
        Search for runs matching query, mutating the visible catalog in place.

        Parameters
        ----------
        query : Any
            Search criteria. Currently supports ``TimeRange``.

        Returns
        -------
        MemoryCatalog
            Self, with ``_catalog`` filtered from ``_base_catalog``.

        Raises
        ------
        TypeError
            If the query type is not supported.
        """
        if isinstance(query, TimeRange):
            self._catalog = {
                uid: run
                for uid, run in self._base_catalog.items()
                if self._in_time_range(run, query.since, query.until)
            }
            return self
        raise TypeError(f"Unsupported query type for MemoryCatalog: {type(query)}")

    def filter_by_time(
        self, since: Optional[str] = None, until: Optional[str] = None
    ) -> "MemoryCatalog":
        """
        Filter runs by time range.

        Parameters
        ----------
        since : str, optional
            Start time (YYYY-MM-DD), by default None.
        until : str, optional
            End time (YYYY-MM-DD), by default None.

        Returns
        -------
        MemoryCatalog
            Self with filtered visible catalog.
        """
        return self.search(TimeRange(since=since, until=until))
