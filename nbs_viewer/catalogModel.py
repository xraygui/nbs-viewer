from databroker.queries import In, NotIn, TimeRange
from abc import ABC, abstractmethod
import collections
from .runModel import BlueskyRun, NBSRun
from typing import Optional
from importlib.metadata import entry_points


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
        catalog_models[ep.name] = ep.load()
    return catalog_models


def iterfy(x):
    """
    This function guarantees that a parameter passed will act like a list (or tuple) for the purposes of iteration,
    while treating a string as a single item in a list.

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


class CatalogBase(ABC):

    @classmethod
    @property
    @abstractmethod
    def RUN_WRAPPER(cls):
        raise NotImplementedError

    @property
    def columns(self):
        """
        Returns the METADATA_KEYS of the RUN_WRAPPER class.

        Returns
        -------
        list
            The list of metadata keys defined in the RUN_WRAPPER class.
        """
        return self.RUN_WRAPPER.to_header()

    def __init__(self, catalog, parent=None):
        self._catalog = catalog
        self._parent = parent

    def __getattr__(self, name):
        """
        Forward any undefined attributes or methods to the underlying _catalog object.

        Parameters
        ----------
        name : str
            The name of the attribute or method being accessed.

        Returns
        -------
        Any
            The attribute or method from the underlying _catalog object.

        Raises
        ------
        AttributeError
            If the attribute or method is not found in the underlying _catalog object.
        """
        return getattr(self._catalog, name)

    def __getitem__(self, key):
        return self.RUN_WRAPPER(self._catalog[key], key, self)

    def __len__(self):
        return self._catalog.__len__()

    def values(self):
        """
        Returns an iterator of RUN_WRAPPER objects for the values in the catalog.

        Yields
        ------
        RUN_WRAPPER
            Wrapped run objects from the catalog.
        """
        for key, value in self._catalog.items():
            yield self.RUN_WRAPPER(value, key, self)

    def items(self):
        """
        Returns an iterator of (key, RUN_WRAPPER) pairs for the items in the catalog.

        Yields
        ------
        Tuple[Any, RUN_WRAPPER]
            Key-value pairs where the value is wrapped in a RUN_WRAPPER.
        """
        for key, value in self._catalog.items():
            yield key, self.RUN_WRAPPER(value, key, self)

    def values_slice(self, slice_obj: Optional[slice] = None):
        """
        Returns a generator of RUN_WRAPPER objects for a slice of values in the catalog.

        Parameters
        ----------
        slice_obj : slice, optional
            A slice object to apply to the catalog values. If None, returns all values.

        Yields
        ------
        RUN_WRAPPER
            Wrapped run objects from the sliced catalog values.
        """
        sliced_items = (
            self._catalog.items()[slice_obj] if slice_obj else self._catalog.items()
        )
        for key, value in sliced_items:
            yield self.RUN_WRAPPER(value, key, self)

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
            yield key, self.RUN_WRAPPER(value, key, self)

    def search(self, expr):
        return self.__class__(self._catalog.search(expr), self._parent)

    def reset(self):
        """
        Reset the catalog to its parent catalog if it exists.

        If self._parent is None, this method does nothing.
        """
        if self._parent is not None:
            self._catalog = self._parent._catalog


class BlueskyCatalog(CatalogBase):
    RUN_WRAPPER = BlueskyRun

    def filter_by_time(self, since=None, until=None):
        """
        Return a new catalog filtered to include only scans between the specified times.

        Parameters
        ----------
        since : str, optional
            The start time for the filter, formatted as "YYYY-MM-DD". If not provided, no lower time bound is applied.
        until : str, optional
            The end time for the filter, formatted as "YYYY-MM-DD". If not provided, no upper time bound is applied.

        Returns
        -------
        WrappedDatabroker
            A new instance of the catalog filtered by the specified time range.
        """
        return self.search(TimeRange(since=since, until=until))


class NBSCatalog(BlueskyCatalog):
    RUN_WRAPPER = NBSRun
