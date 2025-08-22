from datetime import datetime
import time
import logging
from .base import CatalogRun
from typing import Dict, List, Tuple, Any, Optional, Union
import numpy as np
from nbs_viewer.utils import print_debug, time_function


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
    chunk_cache : ChunkCache, optional
        Cache for chunked array data
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

    @time_function(function_name="BlueskyRun.__init__", category="DEBUG_CATALOG")
    def __init__(self, run, key, catalog, parent=None, chunk_cache=None):
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
        chunk_cache : ChunkCache, optional
            Cache for chunked array data
        """
        super().__init__(run, key, catalog, parent)
        self._data_cache = {}  # For 1D data only
        self._chunk_cache = chunk_cache
        self._axis_cache = {}
        self._shape_cache = {}
        self._dim_cache = {}  # New cache for dimensions
        self._run_keys_cache = None
        self._has_data = None
        self._metadata = None
        self._start_doc = None
        self._stop_doc = None
        self._descriptors = None
        self._stream = "primary"
        self._max_1d_cache_items = 100

        # Setup metadata first since it's always available
        self.setup()

        # Defer keys initialization; emit loading/ready/error via background pool
        # Caller (catalog UI) should schedule async key init using AppModel's pool

    @time_function(category="DEBUG_RUN")
    def _check_data_access(self):
        """Check if run has accessible data."""
        try:
            # Check if primary stream exists and has data
            if "/".join(["primary", "data"]) in self._run:
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
        if self._chunk_cache is not None:
            self._chunk_cache.clear_run(self.start["uid"])
        self._shape_cache.clear()
        self._dim_cache.clear()
        self._run_keys_cache = None
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
                shape = self._run["/".join(["primary", "data", key])].shape
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
        print_debug(
            "BlueskyRun.getData",
            f"getting data for {key}, slice_info={slice_info}",
            category="DEBUG_CATALOG",
        )
        if not self._has_data:
            return np.array([])  # Return empty array if no data

        # Determine dimensionality from shape
        shape = self.getShape(key)
        is_1d = len(shape) == 1
        if slice_info is not None:
            slice_info = slice_info[: len(shape)]
        # For 1D data, use simple caching
        if is_1d:
            if key in self._data_cache:
                if slice_info is not None:
                    return self._data_cache[key][slice_info]
                return self._data_cache[key]

            try:
                data_accessor = self._run["/".join(["primary", "data", key])]
                data = data_accessor.read()
                self._data_cache[key] = data
                self._manage_cache(self._data_cache, self._max_1d_cache_items)

                if slice_info is not None:
                    return np.array(data[slice_info])
                return data
            except Exception as e:
                print(f"Error reading 1D data for key {key}: {e}")
                return np.array([])

        # For N-D data, use chunk-aware caching
        if self._chunk_cache is None:
            # Fallback to loading full data if no chunk cache available
            try:
                data_accessor = self._run["/".join(["primary", "data", key])]
                data = data_accessor.read()
                if slice_info is not None:
                    return data[slice_info]
                return data
            except Exception as e:
                print(f"Error reading N-D data for key {key}: {e}")
                return np.array([])

        # Use chunk-aware caching
        try:
            print_debug(
                "BlueskyRun.getData", "Loading from chunk cache", category="cache"
            )
            return self._chunk_cache.get_data(self._run, key, slice_info)
        except Exception as e:
            print(f"Error reading chunked data for key {key}: {e}")
            return np.array([])

    # @time_function(category="DEBUG_CATALOG")
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

    def getAxis(self, keys, slice_info=None):
        """
        Get axis data for given keys, using cache if available.

        Parameters
        ----------
        keys : list
            The keys to get axis data for
        slice_info : tuple, optional
            Tuple of slice objects or indices for each dimension.
            If provided, the axis data will be sliced using the last n indices
            of slice_info, where n is the number of dimensions in the data.

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
            # Config data always comes with a dummy time axis, squeeze it
            data = data.read().squeeze()
            #
            if slice_info is not None:
                data = data[slice_info[-len(data.shape) :]]
            self._axis_cache[cache_key] = data
        return self._axis_cache[cache_key]

    def getRunKeys(self):
        """
        Get the run keys, grouping related motor signals together.

        Returns
        -------
        tuple
            A tuple of (xkeys, ykeys) dictionaries
        """
        # Return cached result if available
        if self._run_keys_cache is not None:
            return self._run_keys_cache

        if self._has_data is False:
            return {}, {}  # Return empty key sets if no data

        t_start = time.time()

        # Get all available keys
        print_debug(
            "BlueskyRun.getRunKeys",
            "Getting run['/'.join(['primary', 'data'])].keys()",
            category="DEBUG_CATALOG",
        )
        try:
            all_keys = list(self._run["/".join(["primary", "data"])].keys())
            self._has_data = True
        except Exception as e:
            print(
                f"[BlueskyRun.getRunKeys] Could not get keys from run['primary', 'data']: {e}"
            )
            self._has_data = False
            return {}, {}
        t0 = time.time()
        print_debug(
            "BlueskyRun.getRunKeys",
            f"Got {len(all_keys)} keys in {t0 - t_start:.3f}s",
            category="DEBUG_CATALOG",
        )

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
        print_debug(
            "BlueskyRun.getRunKeys",
            f"Getting dimension hints took: {time.time() - t1:.3f}s",
            category="DEBUG_CATALOG",
        )
        t2 = time.time()
        # Try to get object keys from descriptors
        object_keys = {}
        try:
            descriptors = self._run.primary.descriptors
            if descriptors:
                object_keys = descriptors[0].get("object_keys", {})
        except Exception as e:
            print(
                f"[BlueskyRun.getRunKeys] Could not get object_keys from descriptors: {e}"
            )
            object_keys = {}

        print_debug(
            "BlueskyRun.getRunKeys",
            f"Getting dimension hints from descriptors took: {time.time() - t1:.3f}s",
            category="DEBUG_CATALOG",
        )

        # Process dimension hints
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

        # All remaining keys go to ykeys[1] initially
        ykeys[1] = all_keys
        # print(f"xkeys: {xkeys}")
        # print(f"ykeys: {ykeys}")
        print_debug(
            "BlueskyRun.getRunKeys",
            f"Total getRunKeys took: {time.time() - t_start:.3f}s",
            category="DEBUG_CATALOG",
        )
        self._run_keys_cache = (xkeys, ykeys)
        return self._run_keys_cache

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
            self._shape_cache.clear()
            self._dim_cache.clear()  # Clear dimension cache as well
            self._run_keys_cache = None
        if clear_nd:
            self._chunk_cache.clear_run(self.start["uid"])

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
        if self._chunk_cache is not None:
            size_nd = self._chunk_cache.get_size()

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
        # Get y dimensions from cache or fetch
        if ykey not in self._dim_cache:
            try:
                self._dim_cache[ykey] = self._run[
                    "/".join(["primary", "data", ykey])
                ].dims
            except Exception as e:
                print(f"Could not get dimension names for {ykey}: {e}")
                # Fallback to generating dimension names from shape
                shape = self.getShape(ykey)
                self._dim_cache[ykey] = tuple(f"dim_{i}" for i in range(len(shape)))

        y_dims = self._dim_cache[ykey]

        # Get x dimensions from cache or fetch
        x_dims = {}
        for key in xkeys:
            if key not in self._dim_cache:
                try:
                    self._dim_cache[key] = self._run[
                        "/".join(["primary", "data", key])
                    ].dims
                except Exception as e:
                    print(f"Could not get dimension names for {key}: {e}")
                    # Fallback to generating dimension names from shape
                    shape = self.getShape(key)
                    self._dim_cache[key] = tuple(f"dim_{i}" for i in range(len(shape)))
            x_dims[key] = self._dim_cache[key]

        return y_dims, x_dims
