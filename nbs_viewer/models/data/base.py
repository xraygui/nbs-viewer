from typing import Dict, List, Tuple, Any
from qtpy.QtCore import QObject, Signal
import numpy as np


class CatalogRun(QObject):
    """
    Abstract base class for catalog run implementations.

    This class defines the interface that all run implementations must follow,
    whether they are reading from a catalog, Kafka stream, or other source.

    Parameters
    ----------
    run : object
        The underlying run object
    key : str
        The key/identifier for this run
    catalog : object, optional
        The catalog containing this run, by default None
    """

    @classmethod
    def METADATA_KEYS(cls):
        """
        Abstract class method that subclasses must define.
        Should return a list of metadata keys.

        Returns
        -------
        list
            List of metadata keys required by this run type
        """
        pass

    data_updated = Signal()

    def __init__(self, run, key, catalog, parent=None):
        super().__init__(parent)
        self._run = run
        self._key = key
        self._catalog = catalog

    def __repr__(self):
        """
        Returns a string representation of the CatalogRun object.

        Returns
        -------
        str
            String representation including class name and run info
        """
        return f"{self.__class__.__name__}({self._run!r})"

    def setup(self):
        """
        Set up the run object.

        This method should initialize all attributes defined in METADATA_KEYS
        and any other required state.
        """
        pass

    def refresh(self):
        """
        Refresh the run data from its source.

        Default implementation reloads from catalog. Subclasses may override
        for different refresh behavior.
        """
        self._run = self._catalog[self._key]
        self.setup()

    def getData(self, key: str) -> np.ndarray:
        """
        Get data for a given key.

        Parameters
        ----------
        key : str
            The key to get data for

        Returns
        -------
        np.ndarray
            The data for the given key
        """
        pass

    def getShape(self, key: str) -> Tuple[int, ...]:
        """
        Get the shape of data for a given key.

        Parameters
        ----------
        key : str
            The key to get shape for

        Returns
        -------
        tuple
            The shape of the data
        """
        pass

    def getPlotHints(self) -> Dict[str, Any]:
        """
        Get plot hints for this run.

        Returns
        -------
        dict
            Plot hints dictionary. Default implementation returns empty dict.
        """
        return {}

    def to_header(self) -> Dict[str, Any]:
        """
        Get a dictionary of metadata suitable for display in a header.

        Returns
        -------
        dict
            Dictionary of metadata key-value pairs
        """
        pass

    def getRunKeys(self) -> Tuple[Dict[int, List[str]], Dict[int, List[str]]]:
        """
        Get organized x and y keys for plotting.

        Returns
        -------
        Tuple[Dict[int, List[str]], Dict[int, List[str]]]
            A tuple of (xkeys, ykeys) where each is a dictionary mapping
            dimension (int) to list of keys (str)
        """
        pass

    def getAxis(self, keys: List[str]) -> np.ndarray:
        """
        Get axis data for a sequence of keys.

        Parameters
        ----------
        keys : List[str]
            Sequence of keys to traverse

        Returns
        -------
        np.ndarray
            The axis data
        """
        pass

    def get_hinted_keys(self) -> Dict[int, List[str]]:
        """
        Get filtered keys based on run's hints.

        Each run type may have different hint structures and filtering logic.
        This method encapsulates that run-specific logic.

        Returns
        -------
        Dict[int, List[str]]
            Keys filtered by hints, organized by dimension
        """
        pass

    def get_default_selection(self) -> Tuple[List[str], List[str], List[str]]:
        """
        Get default key selection for this run type.

        Each run type may have different conventions for what should be
        plotted by default. This method encapsulates that run-specific logic.

        Returns
        -------
        Tuple[List[str], List[str], List[str]]
            Default (x_keys, y_keys, norm_keys) for this run
        """
        pass

    def getDimensions(self, key: str) -> int:
        """
        Get number of dimensions for a key.

        Parameters
        ----------
        key : str
            The key to get dimensions for

        Returns
        -------
        int
            Number of dimensions
        """
        return len(self.getShape(key))

    def getAvailableKeys(self) -> List[str]:
        """
        Get list of all available data keys.

        Returns
        -------
        List[str]
            List of available keys
        """
        pass

    def getAxisHints(self) -> Dict[str, List[List[str]]]:
        """
        Get axis hints from plot hints.

        Returns
        -------
        Dict[str, List[List[str]]]
            Dictionary mapping signal names to lists of axis key sequences
        """
        hints = {}
        for dlist in self.getPlotHints().values():
            for d in dlist:
                if isinstance(d, dict) and "axes" in d:
                    signal = d["signal"]
                    if isinstance(signal, list):
                        signal = signal[-1]
                    hints[signal] = d["axes"]
        return hints
