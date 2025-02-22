from typing import Dict, List, Tuple, Any, Optional
from qtpy.QtCore import QObject, Signal
import numpy as np
from asteval import Interpreter


class CatalogRun(QObject):
    """
    Base class for catalog run implementations.

    Provides data access, caching, and transformation services for a run.
    Can be shared between multiple models that need access to the same
    transformed data.

    Parameters
    ----------
    run : object
        The underlying run object
    key : str
        The key/identifier for this run
    catalog : object, optional
        The catalog containing this run
    dynamic : bool, optional
        Whether to enable dynamic updates, by default False
    """

    data_changed = Signal()
    transform_changed = Signal()

    def __init__(self, run, key, catalog=None, dynamic=False, parent=None):
        super().__init__(parent)
        self._run = run
        self._key = key
        self._catalog = catalog

        # Caching
        self._plot_data_cache = {}
        self._dimensions_cache = {}

        # Transform state
        self._transform_text = ""
        self._transform = Interpreter()

        # Dynamic updates
        self._dynamic = False

        # Initialize empty key list - subclasses can update later
        self._available_keys = []

        # Connect data_changed to cache clearing
        self.data_changed.connect(self._on_data_changed)

        # Set dynamic state last since it may trigger signals
        self.set_dynamic(dynamic)

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

    def to_row(self) -> List[Any]:
        """
        Returns a tuple of values corresponding to the METADATA_KEYS.

        Returns
        -------
        tuple
            Values for each metadata key
        """
        return tuple(getattr(self, attr, None) for attr in self.METADATA_KEYS)

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
        # print("Getting Default Selection")
        return ([], [], [])

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

    def _get_flattened_fields(self, fields: list) -> List[str]:
        """
        Get flattened list of fields from hints.

        Parameters
        ----------
        fields : list
            List of fields from hints

        Returns
        -------
        List[str]
            Flattened list of field names
        """
        flattened = []
        for field in fields:
            if isinstance(field, dict):
                if "signal" in field:
                    signal = field["signal"]
                    if isinstance(signal, list):
                        flattened.extend(signal)
                    else:
                        flattened.append(signal)
            else:
                flattened.append(field)
        return flattened

    def get_hinted_keys(self) -> Dict[int, List[str]]:
        """
        Get filtered keys based on NBS run's hints.

        Uses plot hints to filter keys, focusing on primary signals
        and their dimensions.

        Returns
        -------
        Dict[int, List[str]]
            Keys filtered by hints, organized by dimension
        """
        hints = self.getPlotHints()
        _, all_keys = self.getRunKeys()

        # Collect hinted fields
        hinted = []
        for fields in hints.values():
            for field in fields:
                if isinstance(field, dict):
                    if "signal" in field:
                        signal = field["signal"]
                        if isinstance(signal, list):
                            hinted.extend(signal)
                        else:
                            hinted.append(signal)
                else:
                    hinted.append(field)

        # Filter keys by dimension
        filtered = {}
        for dim, key_list in all_keys.items():
            filtered[dim] = [key for key in key_list if key in hinted]

        return filtered

    def get_plot_data(self, xkeys, ykeys, norm_keys=None):
        """
        Get transformed and cached plot data.

        Parameters
        ----------
        xkeys : List[str]
            Keys for x-axis data
        ykeys : List[str]
            Keys for y-axis data
        norm_keys : Optional[List[str]]
            Keys for normalization data

        Returns
        -------
        Tuple[List[np.ndarray], List[np.ndarray], List[str]]
            Tuple of (x_data_list, y_data_list, x_keys_list)
        """
        try:
            if not xkeys or not ykeys:
                return [], [], []
            # Cache key includes all input keys
            cache_key = (tuple(xkeys), tuple(ykeys), tuple(norm_keys or []))

            # Try to get raw data from cache
            if not self._dynamic and cache_key in self._plot_data_cache:
                xlist, ylist, norm = self._plot_data_cache[cache_key]
            else:
                # Get raw data
                xlist = [self.getData(key) for key in xkeys]
                ylist = [self.getData(key) for key in ykeys]

                # Handle normalization
                if norm_keys:
                    norm = self.getData(norm_keys[0])
                    for key in norm_keys[1:]:
                        norm = norm * self.getData(key)
                else:
                    norm = None

                # Cache raw data if not dynamic
                if not self._dynamic:
                    self._plot_data_cache[cache_key] = (xlist, ylist, norm)

            # Transform data
            xplotlist = []
            yplotlist = []
            xkeylist = []

            for key, y in zip(ykeys, ylist):
                # Apply transformations
                x_transformed, y_transformed = self.transform_data(xlist, y, norm)

                # Handle axis hints and reordering
                x_reordered, xkeys, y_reordered = self._reorder_dimensions(
                    key, x_transformed, y_transformed, xkeys
                )

                xplotlist.append(x_reordered)
                yplotlist.append(y_reordered)
                xkeylist.append(xkeys)

            return xplotlist, yplotlist, xkeylist
        except Exception as e:
            print(f"Error getting plot data: {e}")
            return [], [], []  # Return empty data on error

    def set_dynamic(self, enabled):
        """Enable/disable dynamic updates."""
        if enabled != self._dynamic:
            self._dynamic = enabled
            if enabled:
                # Connect to data update signals
                pass  # Implementation depends on data source
            else:
                # Disconnect signals
                pass
            self.clear_caches()

    def _on_data_changed(self):
        """Clear caches when data changes without re-emitting signal."""
        self._plot_data_cache.clear()
        self._dimensions_cache.clear()

    def clear_caches(self):
        """Clear all data caches and notify of change."""
        self._plot_data_cache.clear()
        self._dimensions_cache.clear()
        self.data_changed.emit()

    def transform_data(
        self, xlist: List[np.ndarray], y: np.ndarray, norm: Optional[np.ndarray] = None
    ) -> Tuple[List[np.ndarray], np.ndarray]:
        """
        Transform data using normalization and custom transformations.

        Parameters
        ----------
        xlist : List[np.ndarray]
            List of x-axis data arrays
        y : np.ndarray
            Y-axis data array
        norm : Optional[np.ndarray]
            Optional normalization data

        Returns
        -------
        Tuple[List[np.ndarray], np.ndarray]
            Transformed (x_data_list, y_data)
        """
        # Apply normalization if provided
        if norm is None:
            yfinal = y
        elif np.isscalar(norm):
            yfinal = y / norm
        else:
            temp_norm = norm
            while temp_norm.ndim < y.ndim:
                temp_norm = np.expand_dims(temp_norm, axis=-1)
            yfinal = y / temp_norm

        # Apply custom transformation
        if self._transform_text:
            self._transform.symtable["y"] = yfinal
            self._transform.symtable["x"] = xlist
            self._transform.symtable["norm"] = norm
            yfinal = self._transform(self._transform_text)

        return xlist, yfinal

    def _reorder_dimensions(
        self, key: str, xlist: List[np.ndarray], y: np.ndarray, xkeys: List[str]
    ) -> Tuple[List[np.ndarray], List[str], np.ndarray]:
        """
        Reorder dimensions based on axis hints and data shape.

        Parameters
        ----------
        key : str
            The data key being processed
        xlist : List[np.ndarray]
            List of x-axis data arrays
        y : np.ndarray
            Y-axis data array
        xkeys : List[str]
            List of x-axis keys

        Returns
        -------
        Tuple[List[np.ndarray], List[str], np.ndarray]
            Reordered (x_data_list, x_keys_list, y_data)
        """
        # Get dimension info
        xdim = len(xlist)
        axis_hints = self.getAxisHints()

        # Get axis additions from hints
        if key in axis_hints:
            xadditions = [self.getAxis(axkey) for axkey in axis_hints[key]]
            xadditional_keys = [axkey[-1] for axkey in axis_hints[key]]
        else:
            xadditions = []
            xadditional_keys = []

        # Add dimensions if needed
        current_dim = xdim + len(xadditions)
        if current_dim < len(y.shape):
            for n in range(current_dim, len(y.shape)):
                xadditions.append(np.arange(y.shape[n]))
                xadditional_keys.append(f"Dimension {n}")

        # Reorder based on number of additions
        if len(xadditions) == 1:
            xlist_reordered = xlist[:-1] + xadditions + [xlist[-1]]
            xkeys_reordered = xkeys[:-1] + xadditional_keys + [xkeys[-1]]
            y_reordered = np.swapaxes(y, -2, -1)
        else:
            xlist_reordered = xlist + xadditions
            xkeys_reordered = xkeys + xadditional_keys
            y_reordered = y

        return xlist_reordered, xkeys_reordered, y_reordered

    def set_transform(self, transform_state: Dict[str, Any]) -> None:
        """
        Set the transformation expression.

        Parameters
        ----------
        transform_state : Dict[str, Any]
            Dictionary with transform settings:
            - enabled: bool, whether transform is enabled
            - text: str, Python expression for data transformation
        """
        if transform_state["enabled"]:
            transform_text = transform_state["text"]
        else:
            transform_text = ""

        if transform_text != self._transform_text:
            self._transform_text = transform_text
            self.transform_changed.emit()

    def _initialize_keys(self):
        """Initialize available keys safely."""
        try:
            # Get all keys from run
            xkeys, ykeys = self.getRunKeys()

            # Collect all keys from both dictionaries while preserving order
            all_keys = []
            for keys in xkeys.values():
                for key in keys:
                    if key not in all_keys:
                        all_keys.append(key)
            for keys in ykeys.values():
                for key in keys:
                    if key not in all_keys:
                        all_keys.append(key)

            self._available_keys = all_keys
        except Exception as e:
            print(f"Error initializing keys: {e}")
            self._available_keys = []
        finally:
            self.data_changed.emit()  # Always notify of key changes

    @property
    def available_keys(self) -> List[str]:
        """Get the list of available keys."""
        return self._available_keys

    @property
    def display_name(self) -> str:
        """Get the display name of the run."""
        return str(self)
