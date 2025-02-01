from typing import Dict, List, Tuple, Optional, Any
import numpy as np
from qtpy.QtCore import QObject, Signal
from asteval import Interpreter


class PlotData(QObject):
    """
    Core data management for plotting.

    Manages data access, caching, transformations, and state for plot data.
    Provides an interface between the raw data source (CatalogRun) and the plot views.

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

    def __init__(self, run, dynamic: bool = False):
        super().__init__()
        self._run = run
        self._dynamic = dynamic

        # Caching
        self._plot_data_cache: Dict[Tuple, Tuple] = {}
        self._dimensions_cache: Dict[str, int] = {}

        # State
        self._transform_text = ""
        self._checked_x: List[str] = []
        self._checked_y: List[str] = []
        self._checked_norm: List[str] = []

        # Transform engine
        self._transform = Interpreter()

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
                key, x_transformed, y_transformed
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
        self, key: str, xlist: List[np.ndarray], y: np.ndarray
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
            xkeys = self._checked_x[:-1] + xadditional_keys + [self._checked_x[-1]]
            y_reordered = np.swapaxes(y, -2, -1)
        else:
            xlist_reordered = xlist + xadditions
            xkeys = self._checked_x + xadditional_keys
            y_reordered = y

        return xlist_reordered, xkeys, y_reordered

    def set_transform(self, transform_text: str) -> None:
        """
        Set the transformation expression.

        Parameters
        ----------
        transform_text : str
            Python expression for data transformation
        """
        if transform_text != self._transform_text:
            self._transform_text = transform_text
            self.transform_changed.emit()

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

    def update_checked_data(
        self,
        checked_x: List[str],
        checked_y: List[str],
        checked_norm: Optional[List[str]] = None,
    ) -> None:
        """
        Update which data keys are selected for plotting.

        Parameters
        ----------
        checked_x : List[str]
            Selected x-axis keys
        checked_y : List[str]
            Selected y-axis keys
        checked_norm : Optional[List[str]], optional
            Selected normalization keys, by default None
        """
        self._checked_x = checked_x
        self._checked_y = checked_y
        self._checked_norm = checked_norm or []
        self.data_changed.emit()
