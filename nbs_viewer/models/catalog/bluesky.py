"""Bluesky catalog implementation."""

from typing import Any, List, Optional, Dict
from qtpy.QtCore import QObject
from databroker.queries import TimeRange

from .base import CatalogBase
from .table import CatalogTableModel
from ..data import BlueskyRun, NBSRun


class BlueskyCatalog(CatalogBase):
    """
    Catalog implementation for Bluesky data.

    This class manages a collection of runs from a Bluesky catalog,
    providing access to run data and metadata.
    """

    def __init__(self, catalog: Any, parent: Optional[QObject] = None):
        """
        Initialize the catalog.

        Parameters
        ----------
        catalog : Any
            The Bluesky catalog object.
        parent : QObject, optional
            Parent object, by default None.
        """
        super().__init__(parent)
        self._catalog = catalog
        self._wrapped_runs = {}

    def __len__(self):
        return len(self._catalog)

    def __getattr__(self, name):
        return getattr(self._catalog, name)

    @property
    def columns(self) -> List[str]:
        """Get column names for display."""
        return BlueskyRun.to_header()

    def get_runs(self) -> List[BlueskyRun]:
        """Get all available runs."""
        runs = []
        for uid, run in self._catalog.items():
            if uid not in self._wrapped_runs:
                self._wrapped_runs[uid] = self.wrap_run(run, uid)
            runs.append(self._wrapped_runs[uid])
        return runs

    def wrap_run(self, run, uid):
        return BlueskyRun(run, uid, self._catalog)

    def get_run(self, uid: str) -> BlueskyRun:
        """
        Get a specific run by UID.

        Parameters
        ----------
        uid : str
            The run's unique identifier.

        Returns
        -------
        BlueskyRun
            The requested run.

        Raises
        ------
        KeyError
            If run not found.
        """
        if uid not in self._wrapped_runs:
            if uid not in self._catalog:
                raise KeyError(f"No run found with UID {uid}")
            self._wrapped_runs[uid] = self.wrap_run(self._catalog[uid], uid)
        return self._wrapped_runs[uid]

    def items_slice(self, slice_obj: Optional[slice] = None):
        """
        Returns a generator of (key, RUN_WRAPPER) pairs for a slice of items in the catalog.

        Parameters
        ----------
        slice_obj : slice, optional
            A slice object to apply to the catalog items. If None, returns all items.

        Yields
        ------
        Tuple[Any, RUN_WRAPPER]
            Key-value pairs where the value is wrapped in a RUN_WRAPPER.
        """
        sliced_items = (
            self._catalog.items()[slice_obj] if slice_obj else self._catalog.items()
        )
        for key, value in sliced_items:
            # print(f"Wrapping run {key}")
            yield key, self.wrap_run(value, key)

    def search(self, query: Dict) -> "BlueskyCatalog":
        """
        Search for runs matching query.

        Parameters
        ----------
        query : Dict
            Search criteria.

        Returns
        -------
        BlueskyCatalog
            New catalog containing matching runs.
        """
        return self.__class__(self._catalog.search(query), self)

    def filter_by_time(
        self, since: Optional[str] = None, until: Optional[str] = None
    ) -> "BlueskyCatalog":
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
        BlueskyCatalog
            New catalog with filtered runs.
        """
        return self.search(TimeRange(since=since, until=until))


class NBSCatalog(BlueskyCatalog):
    """Catalog implementation for NBS data."""

    def wrap_run(self, run, uid):
        return NBSRun(run, uid, self._catalog)

    @property
    def columns(self) -> List[str]:
        """Get column names for display."""
        return NBSRun.to_header()  # Use NBSRun headers instead of BlueskyRun
