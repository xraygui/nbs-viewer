"""Base interfaces for catalog models."""

from abc import ABC, abstractmethod
from typing import Any, List, Optional, Dict, Generator, Tuple
import collections
from qtpy.QtCore import Signal, QObject
from importlib.metadata import entry_points
from ..data.base import CatalogRun


def load_catalog_models():
    """
    Load catalog models from entrypoints.

    Returns
    -------
    dict
        A dictionary of catalog model names and their corresponding classes.
    """
    catalog_models = {}
    for ep in entry_points(group="nbs_viewer.catalog_models"):
        # print("Loading catalog model: ", ep.name)
        catalog_models[ep.name] = ep.load()
    return catalog_models


def iterfy(x):
    """
    Make a parameter iterable while treating strings as single items.

    Parameters
    ----------
    x : Any
        The input parameter to be iterfied.

    Returns
    -------
    Iterable
        The input parameter as an iterable.
    """
    if isinstance(x, collections.abc.Iterable) and not isinstance(x, (str, bytes)):
        return x
    else:
        return [x]


class CatalogBase(QObject):
    """
    Abstract base class for all catalog models.

    This class defines the interface that all catalog implementations must follow.
    It provides basic catalog operations and state management.

    Signals
    -------
    data_updated : Signal
        Emitted when catalog data changes
    selection_changed : Signal(list)
        Emitted when run selection changes with list of selected CatalogRun objects
    new_run_available : Signal(str)
        Emitted when a new run is available with run UID
    item_selected : Signal(object)
        Emitted when a single run is selected with the CatalogRun object
    item_deselected : Signal(object)
        Emitted when a single run is deselected with the CatalogRun object
    """

    data_updated = Signal()
    selection_changed = Signal(list)  # List[CatalogRun]
    new_run_available = Signal(str)  # uid of new run
    item_selected = Signal(object)  # CatalogRun
    item_deselected = Signal(object)  # CatalogRun

    def __init__(self, parent: Optional[QObject] = None):
        """Initialize the catalog model."""
        super().__init__(parent)
        self._selection = set()  # Set of selected UIDs
        self._filters = []
        self._runs = []

    @property
    def columns(self) -> List[str]:
        """Get the column names for this catalog."""
        raise NotImplementedError

    def get_runs(self) -> List[Any]:
        """
        Get all available runs.

        Returns
        -------
        List[Any]
            List of run objects.
        """
        raise NotImplementedError

    def get_run(self, uid: str) -> CatalogRun:
        """
        Get a specific run by UID.

        Parameters
        ----------
        uid : str
            Unique identifier for the run

        Returns
        -------
        CatalogRun
            The run object

        Raises
        ------
        KeyError
            If run with given UID is not found
        """
        raise NotImplementedError

    def search(self, query: Dict) -> "CatalogBase":
        """
        Search for runs matching query.

        Parameters
        ----------
        query : Dict
            Search criteria.

        Returns
        -------
        CatalogBase
            New catalog containing matching runs.
        """
        raise NotImplementedError

    def add_filter(self, filter_func) -> None:
        """
        Add a filter function to the catalog.

        Parameters
        ----------
        filter_func : callable
            Function that takes a run and returns bool.
        """
        self._filters.append(filter_func)
        self.data_updated.emit()

    def clear_filters(self) -> None:
        """Remove all filters."""
        self._filters = []
        self.data_updated.emit()

    def select_run(self, uid: str) -> None:
        """
        Select a run by UID.

        Parameters
        ----------
        uid : str
            Unique identifier for the run
        """
        if uid not in self._selection:
            self._selection.add(uid)
            run = self.get_run(uid)
            self.item_selected.emit(run)
            self.selection_changed.emit(self.get_selected_runs())

    def deselect_run(self, uid: str) -> None:
        """
        Deselect a run by UID.

        Parameters
        ----------
        uid : str
            Unique identifier for the run
        """
        if uid in self._selection:
            self._selection.discard(uid)
            run = self.get_run(uid)
            self.item_deselected.emit(run)
            self.selection_changed.emit(self.get_selected_runs())

    def clear_selection(self) -> None:
        """Clear all selections."""
        selection_copy = self._selection.copy()
        for uid in selection_copy:
            self.deselect_run(uid)
        self._selection.clear()
        self.selection_changed.emit([])

    def get_selected_runs(self) -> List[CatalogRun]:
        """
        Get currently selected runs.

        Returns
        -------
        List[CatalogRun]
            List of selected run objects
        """
        return [self.get_run(uid) for uid in self._selection]

    def __len__(self) -> int:
        """Get number of runs in catalog."""
        return len(self._runs)
