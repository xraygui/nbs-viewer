from datetime import datetime
import time
import logging
from .base import CatalogRun
from typing import Dict, List, Tuple, Any, Optional, Union
import numpy as np


class BlueskyRun(CatalogRun):
    """
    A class representing a Bluesky run with data caching capabilities.

    This class implements the CatalogRun interface for Bluesky data,
    providing caching for data, axes, and shapes.

    Parameters
    ----------
    run : BlueskyRun
        The run object
    key : str
        The key for this run
    catalog : Catalog
        The catalog containing the run
    """

    _METADATA_MAP = {
        "scan_id": ["start", "scan_id"],
        "uid": ["start", "uid"],
        "plan_name": ["start", "plan_name"],
        "date": [],
        "num_points": [],
    }

    DISPLAY_KEYS = {
        "scan_id": "Scan ID",
        "uid": "UID",
        "plan_name": "Plan Name",
        "date": "Date",
        "num_points": "Scan Points",
    }

    METADATA_KEYS = ["scan_id", "plan_name", "num_points", "date", "uid"]

    def __init__(self, run, key, catalog, parent=None):
        """
        Initialize the BlueskyRun.

        Parameters
        ----------
        run : BlueskyRun
            The run object
        key : str
            The key for this run
        catalog : Catalog
            The catalog containing the run
        """
        super().__init__(run, key, catalog, parent)
        self._data_cache = {}
        self._nd_data_cache = {}
        self._axis_cache = {}
        self._shape_cache = {}
        self._has_data = False
        self._metadata = None
        self._start_doc = None
        self._stop_doc = None
        self._descriptors = None
        self._stream = "primary"
        self._max_1d_cache_items = 100
        self._max_nd_cache_items = 10

        # Setup metadata first since it's always available
        self.setup()

        # Try to initialize data access, but don't fail if unavailable
        try:
            self._check_data_access()
            self._initialize_keys()
        except Exception as e:
            print(f"Warning: Could not initialize data for run {key}: {e}")
            self._available_keys = []

    def _check_data_access(self):
        """Check if run has accessible data."""
        try:
            # Check if primary stream exists and has data
            if ("primary", "data") in self._run:
                self._has_data = True
            else:
                print(f"Warning: Run {self._key} has no primary data stream")
                self._has_data = False
        except Exception as e:
            print(f"Error checking data access for run {self._key}: {e}")
            self._has_data = False

    def refresh(self):
        """
        Refresh the run data and clear caches.
        """
        self._data_cache.clear()
        self._axis_cache.clear()
        self._nd_data_cache.clear()
        self._shape_cache.clear()
        self._start_doc = None
        self._stop_doc = None
        self._descriptors = None
        super().refresh()

    def setup(self):
        """
        Set up the run object by extracting metadata from the run.
        """
        self.metadata = self._run.metadata

        self._date = datetime.fromtimestamp(
            self.get_md_value(["start", "time"], 0)
        ).isoformat()

        for attr, keys in self._METADATA_MAP.items():
            if not hasattr(self.__class__, attr):
                value = self.get_md_value(keys)
                setattr(self, attr, value)

        if self._key is None:
            self._key = self.uid

    def get_md_value(self, keys, default=None):
        """
        Get a value from nested metadata.

        Parameters
        ----------
        keys : str or list
            Key or list of keys to traverse
        default : Any, optional
            Default value if key not found, by default None

        Returns
        -------
        Any
            The value found in metadata or default
        """
        if not isinstance(keys, (list, tuple)):
            keys = [keys]
        value = self.metadata
        if value is None:
            return default

        if not hasattr(value, "get"):
            print(f"Got bad metadata in get_md_value {value}")
            return default

        for key in keys:
            value = value.get(key, {})
            if not value:
                value = default
                break
        if value == {}:
            value = default
        return value

    @property
    def num_points(self):
        """
        Returns the number of points in the run.

        Returns
        -------
        int
            Number of points, or -1 if not defined in metadata
        """
        value = self.get_md_value(["stop", "num_events", "primary"], None)
        if value is None:
            value = self.get_md_value(["start", "num_points"], -1)
        return value

    @property
    def date(self):
        """
        Get the run date.

        Returns
        -------
        str
            ISO format date string
        """
        return self._date

    def to_row(self):
        """
        Returns a tuple of values corresponding to the METADATA_KEYS.

        Returns
        -------
        tuple
            Values for each metadata key
        """
        return tuple(getattr(self, attr, None) for attr in self.METADATA_KEYS)

    @classmethod
    def to_header(cls):
        """
        Get list of display names for metadata keys.

        Returns
        -------
        list
            Display names for metadata columns
        """
        attrs = cls.METADATA_KEYS
        header_names = [cls.DISPLAY_KEYS.get(attr, attr) for attr in attrs]
        return header_names

    def getShape(self, key):
        """
        Get the shape of data for a given key using metadata.

        Parameters
        ----------
        key : str
            The key to get shape for

        Returns
        -------
        tuple
            The shape of the data
        """
        t_start = time.time()
        if key not in self._shape_cache:
            logging.debug(f"Getting shape for key {key}")
            try:
                # Try to get shape from metadata first
                shape = self._run["primary", "data", key].shape
                self._shape_cache[key] = shape
                logging.debug("Got shape from metadata")
            except (KeyError, AttributeError):
                # If metadata doesn't have shape, get it from data
                logging.debug("Falling back to getting shape from data")
                self._shape_cache[key] = self.getData(key).shape
            logging.debug(f"Getting shape for {key} took: {time.time() - t_start:.3f}s")
        return self._shape_cache[key]

    def get_default_selection(self) -> Tuple[List[str], List[str], List[str]]:
        """
        Get default key selection for NBS run.

        For NBS data, typically selects:
        - First non-zero dimension x key
        - Primary signals from hints for y
        - Normalization signals from hints for norm

        Returns
        -------
        Tuple[List[str], List[str], List[str]]
            Default (x_keys, y_keys, norm_keys) for this run
        """
        x_keys, _ = self.getRunKeys()
        hints = self.getPlotHints()

        # Select x keys
        selected_x = []
        selected_y = []
        selected_norm = []

        if 1 in x_keys:
            for n in x_keys.keys():
                if n != 0:
                    selected_x.append(x_keys[n][0])
        elif 0 in x_keys:
            selected_x = [x_keys[0][0]]

        # Get y keys from primary hints
        if hints.get("primary", []):
            selected_y = self._get_flattened_fields(hints.get("primary", []))
            # Get normalization keys from hints
            selected_norm = self._get_flattened_fields(hints.get("normalization", []))
        else:
            detectors = self.get_md_value(["start", "detectors"], [])
            if detectors:
                selected_y = [detectors[0]]
            else:
                selected_y = []
            selected_norm = []
        return selected_x, selected_y, selected_norm

    def getPlotHints(self):
        """
        Get plot hints from the run metadata.

        Returns
        -------
        dict
            Dictionary of plot hints
        """
        plotHints = self.get_md_value(["start", "plot_hints"], {})
        return plotHints

    def getData(self, key, slice_info=None):
        """
        Get data for a given key, using cache if available.

        Parameters
        ----------
        key : str
            The key to get data for
        slice_info : tuple, optional
            Tuple of slice objects or indices for each dimension

        Returns
        -------
        array-like
            The data for the given key, potentially sliced
        """
        if not self._has_data:
            return np.array([])  # Return empty array if no data

        # First check if we have the full data in the regular cache
        if key in self._data_cache:
            if slice_info is not None:
                # If we have full data, just slice it directly
                return self._data_cache[key][slice_info]
            return self._data_cache[key]

        # Determine dimensionality from shape
        shape = self.getShape(key)
        is_1d = len(shape) == 1

        # For 1D data, always fetch the full dataset
        if is_1d:
            try:
                data_accessor = self._run["primary", "data", key]
                data = data_accessor.read()
                self._data_cache[key] = data
                self._manage_cache(self._data_cache, self._max_1d_cache_items)

                # Return sliced data if requested
                if slice_info is not None:
                    return np.array(data[slice_info])
                return data
            except Exception as e:
                logging.error(f"Error reading 1D data for key {key}: {e}")
                return np.array([])

        # For N-D data, proceed with slice-aware fetching
        if slice_info is not None:
            # Use N-D data cache for sliced data
            cache = self._nd_data_cache
            # Convert slice objects to tuples of (start, stop, step)
            slice_key = tuple(
                (s.start, s.stop, s.step) if isinstance(s, slice) else s
                for s in slice_info
            )
            cache_key = (key, slice_key)
            max_cache_items = self._max_nd_cache_items

            if cache_key in cache:
                return cache[cache_key]
        else:
            # Use regular data cache for full data
            cache = self._data_cache
            cache_key = key
            max_cache_items = self._max_1d_cache_items

        try:
            # Get the data accessor
            data_accessor = self._run["primary", "data", key]

            if slice_info is not None:
                # Request only the slice we need from Tiled
                # This avoids calling read() on the entire dataset
                data = data_accessor[slice_info]
                if not np.isscalar(data):
                    cache[cache_key] = data
                else:
                    data = np.array(data)
            else:
                # For full data requests
                data = data_accessor.read()
                cache[cache_key] = data

            # Manage cache size
            self._manage_cache(cache, max_cache_items)

        except Exception as e:
            logging.error(f"Error reading data for key {key}: {e}")
            return np.array([])

        return data

    def _manage_cache(self, cache, max_items):
        """
        Limit cache size by removing least recently used items.

        Parameters
        ----------
        cache : dict
            The cache to manage
        max_items : int
            Maximum number of items to keep in cache
        """
        if len(cache) > max_items:
            # Simple LRU implementation - remove oldest items first
            keys_to_remove = list(cache.keys())[:-max_items]
            for key in keys_to_remove:
                del cache[key]

    def getAxis(self, keys):
        """
        Get axis data for given keys, using cache if available.

        Parameters
        ----------
        keys : list
            The keys to get axis data for

        Returns
        -------
        array-like
            The axis data for the given keys
        """
        cache_key = tuple(keys)
        if cache_key not in self._axis_cache:
            data = self._run["primary"]
            for key in keys:
                data = data[key]
            self._axis_cache[cache_key] = data.read().squeeze()
        return self._axis_cache[cache_key]

    def getRunKeys(self):
        """
        Get the run keys, grouping related motor signals together.

        Returns
        -------
        tuple
            A tuple of (xkeys, ykeys) dictionaries
        """
        if not self._has_data:
            return {}, {}  # Return empty key sets if no data

        try:
            t_start = time.time()

            # Get all available keys
            logging.debug("Getting available keys")
            all_keys = list(self._run["primary", "data"].keys())
            t0 = time.time()
            logging.debug(f"Got {len(all_keys)} keys in {t0 - t_start:.3f}s")

            # Initialize dictionaries
            xkeys = {}
            ykeys = {1: [], 2: []}

            # Handle time key if present
            if "time" in all_keys:
                xkeys[0] = ["time"]
                all_keys.remove("time")

            # Get dimension hints and try to get object keys from descriptors
            t1 = time.time()
            xkeyhints = self.get_md_value(["start", "hints", "dimensions"], [])

            # Try to get object keys from descriptors
            object_keys = {}
            try:
                descriptors = self._run.primary.descriptors
                if descriptors:
                    object_keys = descriptors[0].get("object_keys", {})
            except Exception as e:
                logging.debug(f"Could not get object_keys from descriptors: {e}")
                object_keys = {}

            logging.debug(f"Getting dimension hints took: {time.time() - t1:.3f}s")

            # Process dimension hints
            t2 = time.time()
            for i, dimension in enumerate(xkeyhints):
                axlist = dimension[0]
                xkeys[i + 1] = []
                for ax in axlist:
                    # Add the main key
                    if ax in all_keys:
                        all_keys.remove(ax)
                        xkeys[i + 1].append(ax)

                        # Add related keys from object_keys
                        if object_keys and ax in object_keys:
                            for related_key in object_keys[ax]:
                                if related_key != ax and related_key in all_keys:
                                    all_keys.remove(related_key)
                                    xkeys[i + 1].append(related_key)

                if len(xkeys[i + 1]) == 0:
                    xkeys.pop(i + 1)

            logging.debug(f"Processing hints took: {time.time() - t2:.3f}s")

            # All remaining keys go to ykeys[1] initially
            ykeys[1] = all_keys
            # print(f"xkeys: {xkeys}")
            # print(f"ykeys: {ykeys}")
            logging.debug(f"Total getRunKeys took: {time.time() - t_start:.3f}s")
            return xkeys, ykeys
        except Exception as e:
            print(f"Error getting run keys for {self._key}: {e}")
            return {}, {}

    def __str__(self):
        """
        Get a string representation of the run.

        Returns
        -------
        str
            Human-readable description of the run
        """
        scan_desc = ["Scan", str(self.scan_id)]

        if self.plan_name:
            scan_desc.append(self.plan_name)

        return " ".join(scan_desc)

    def scanFinished(self):
        """
        Check if the scan is finished.

        Returns
        -------
        bool
            True if the run has a stop document
        """
        return bool(self.metadata.get("stop", False))

    def scanSucceeded(self):
        """
        Check if the scan completed successfully.

        Returns
        -------
        bool
            True if the run has a successful exit status
        """
        status = self.get_md_value(["stop", "exit_status"], "")
        return status == "success"

    @property
    def start(self):
        """Get the run's start document."""
        if self._start_doc is None:
            try:
                self._start_doc = self._run.metadata["start"]
            except (KeyError, AttributeError):
                try:
                    self._start_doc = self._run.start
                except AttributeError:
                    self._start_doc = {}
        return self._start_doc

    @property
    def stop(self):
        """Get the run's stop document."""
        if self._stop_doc is None:
            try:
                self._stop_doc = self._run.metadata["stop"]
            except (KeyError, AttributeError):
                try:
                    self._stop_doc = self._run.stop
                except AttributeError:
                    self._stop_doc = {}
        return self._stop_doc

    @property
    def descriptors(self):
        """Get the run's descriptors."""
        if self._descriptors is None:
            try:
                self._descriptors = list(self._run.metadata["descriptors"])
            except (KeyError, AttributeError):
                try:
                    self._descriptors = list(self._run.descriptors)
                except AttributeError:
                    self._descriptors = []
        return self._descriptors

    def get_dimension_data(self, key, indices, plot_dims):
        """
        Get data for a specific key, sliced according to indices and plot dimensions.

        Parameters
        ----------
        key : str
            The data key
        indices : tuple
            Indices for non-plotted dimensions
        plot_dims : int or tuple
            Dimensions to include in the plot (1 for line plot, 2 for 2D plot)

        Returns
        -------
        array-like
            The sliced data ready for plotting
        """
        # Get the full shape
        shape = self.getShape(key)
        if not shape:
            return np.array([])

        # Prepare slice information
        slice_info = [slice(None)] * len(shape)

        # Handle 1D plotting
        if plot_dims == 1:
            # Set all non-plotted dimensions to the specified indices
            for i, idx in enumerate(indices):
                if i < len(shape) - 1:  # All except the last dimension
                    slice_info[i] = idx

        # Handle 2D plotting
        elif plot_dims == 2:
            # Set all dimensions except the last two to the specified indices
            for i, idx in enumerate(indices):
                if i < len(shape) - 2:  # All except the last two dimensions
                    slice_info[i] = idx

        # Get the sliced data
        return self.getData(key, tuple(slice_info))

    def clear_cache(self, clear_1d=True, clear_nd=True):
        """
        Clear the data caches.

        Parameters
        ----------
        clear_1d : bool, optional
            Whether to clear the 1D data cache, by default True
        clear_nd : bool, optional
            Whether to clear the N-D data cache, by default True
        """
        if clear_1d:
            self._data_cache.clear()
        if clear_nd:
            self._nd_data_cache.clear()

    def get_cache_size(self):
        """
        Get the approximate size of the data caches in bytes.

        Returns
        -------
        dict
            Dictionary with sizes of 1D and N-D caches
        """
        size_1d = 0
        for data in self._data_cache.values():
            if hasattr(data, "nbytes"):
                size_1d += data.nbytes

        size_nd = 0
        for data in self._nd_data_cache.values():
            if hasattr(data, "nbytes"):
                size_nd += data.nbytes

        return {"1d_cache": size_1d, "nd_cache": size_nd, "total": size_1d + size_nd}

    def get_dims(
        self, ykey: str, xkeys: List[str]
    ) -> Tuple[Tuple[str, ...], Dict[str, Tuple[str, ...]]]:
        """
        Get dimension names from the data object.

        Parameters
        ----------
        ykey : str
            The key for the y-data
        xkeys : List[str]
            List of keys for x-axes

        Returns
        -------
        Tuple[Tuple[str, ...], Dict[str, Tuple[str, ...]]]
            A tuple containing:
            - y_dims: Tuple of dimension names for y-data
            - x_dims: Dict mapping xkeys to their dimension names
        """
        try:
            # Try to get dimension names from the data object
            y_dims = self._run["primary", "data", ykey].dims
            x_dims = {}
            for key in xkeys:
                x_dims[key] = self._run["primary", "data", key].dims
            return y_dims, x_dims
        except Exception as e:
            print(f"Could not get dimension names from data: {e}")
            # Fall back to generic names
            yshape = list(self.getShape(ykey))
            y_dims = tuple(f"dim_{i}" for i in range(len(yshape)))
            x_dims = {}
            for key in xkeys:
                shape = list(self.getShape(key))
                x_dims[key] = tuple(f"dim_{i}" for i in range(len(shape)))
            return y_dims, x_dims
