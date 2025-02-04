from typing import Dict, List, Tuple, Optional
import numpy as np
from qtpy.QtCore import QObject, Signal
from asteval import Interpreter

from ..data.base import CatalogRun


class RunData(QObject):
    """
    Service for run data transformation and caching.

    Provides data access, caching, and transformation services for a run.
    Can be shared between multiple models that need access to the same
    transformed data.

    Parameters
    ----------
    run : CatalogRun
        The run object providing the data
    dynamic : bool, optional
        Whether to enable dynamic updates, by default False

    Signals
    -------
    data_changed : Signal
        Emitted when underlying data changes
    transform_changed : Signal
        Emitted when transformation settings change
    """

    data_changed = Signal()
    transform_changed = Signal()

    def __init__(self, run: CatalogRun, dynamic: bool = False):
        super().__init__()
        self._run = run
        self._dynamic = dynamic

        # Caching
        self._plot_data_cache: Dict[Tuple, Tuple] = {}
        self._dimensions_cache: Dict[str, int] = {}

        # Transform state
        self._transform_text = ""
        self._transform = Interpreter()

    @property
    def run(self) -> CatalogRun:
        """Get the underlying run object."""
        return self._run

    def clear_caches(self) -> None:
        """Clear all data caches."""
        self._plot_data_cache.clear()
        self._dimensions_cache.clear()
        self.data_changed.emit()

    def get_plot_data(
        self, xkeys: List[str], ykeys: List[str], norm_keys: Optional[List[str]] = None
    ) -> Tuple[List[np.ndarray], List[np.ndarray], List[str]]:
        """
        Get transformed and cached plot data.

        Parameters
        ----------
        xkeys : List[str]
            Keys for x-axis data
        ykeys : List[str]
            Keys for y-axis data
        norm_keys : Optional[List[str]], optional
            Keys for normalization data, by default None

        Returns
        -------
        Tuple[List[np.ndarray], List[np.ndarray], List[str]]
            Tuple of (x_data_list, y_data_list, x_keys_list)
        """
        print("RunData get_plot_data")
        print(xkeys, ykeys, norm_keys)
        if not xkeys or not ykeys:
            return [], [], []
        # Cache key includes all input keys
        cache_key = (tuple(xkeys), tuple(ykeys), tuple(norm_keys or []))

        # Try to get raw data from cache
        if not self._dynamic and cache_key in self._plot_data_cache:
            xlist, ylist, norm = self._plot_data_cache[cache_key]
        else:
            # Get raw data
            xlist = [self._run.getData(key) for key in xkeys]
            ylist = [self._run.getData(key) for key in ykeys]

            # Handle normalization
            if norm_keys:
                norm = self._run.getData(norm_keys[0])
                for key in norm_keys[1:]:
                    norm = norm * self._run.getData(key)
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

    def transform_data(
        self, xlist: List[np.ndarray], y: np.ndarray, norm: Optional[np.ndarray] = None
    ) -> Tuple[List[np.ndarray], np.ndarray]:
        """
        Transform data using normalization and custom transformations.

        Parameters
        ----------
        xlist : List[np.ndarray]
            List of x data arrays
        y : np.ndarray
            Y data array
        norm : Optional[np.ndarray], optional
            Normalization data, by default None

        Returns
        -------
        Tuple[List[np.ndarray], np.ndarray]
            Transformed x and y data
        """
        # Apply normalization
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
            Data key
        xlist : List[np.ndarray]
            List of x data arrays
        y : np.ndarray
            Y data array
        xkeys : List[str]
            List of x-axis keys

        Returns
        -------
        Tuple[List[np.ndarray], List[str], np.ndarray]
            Reordered x data, x keys, and y data
        """
        xdim = len(xlist)
        axis_hints = self._run.getAxisHints()

        # Get axis additions from hints
        if key in axis_hints:
            xadditions = [self._run.getAxis(axkey) for axkey in axis_hints[key]]
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

    def set_transform(self, transform_state) -> None:
        """
        Set the transformation expression.

        Parameters
        ----------
        transform_text : str
            Python expression for data transformation
        """
        if transform_state["enabled"]:
            transform_text = transform_state["text"]
        else:
            transform_text = ""

        if transform_text != self._transform_text:
            self._transform_text = transform_text
            self.data_changed.emit()

    def set_dynamic(self, enabled: bool) -> None:
        """
        Enable/disable dynamic updates.

        Parameters
        ----------
        enabled : bool
            Whether to enable dynamic updates
        """
        if enabled != self._dynamic:
            self._dynamic = enabled
            if enabled:
                self.clear_caches()
