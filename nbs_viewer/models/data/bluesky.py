from datetime import datetime
import time
import logging
from .base import CatalogRun
from typing import Dict, List, Tuple
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
        self._axis_cache = {}
        self._shape_cache = {}
        self._has_data = False  # Track if run has valid data

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
        self._shape_cache.clear()
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
        for key in keys:
            value = value.get(key, {})
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
                shape = self._run["primary", "data", key].metadata["shape"]
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

    def getData(self, key):
        """
        Get data for a given key, using cache if available.

        Parameters
        ----------
        key : str
            The key to get data for

        Returns
        -------
        array-like
            The data for the given key
        """
        if not self._has_data:
            return np.array([])  # Return empty array if no data

        if key not in self._data_cache:
            try:
                self._data_cache[key] = self._run["primary", "data", key].read()
            except Exception as e:
                print(f"Error reading data for key {key}: {e}")
                return np.array([])
        return self._data_cache[key]

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
        Get the run keys without shape information initially.

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

            t1 = time.time()
            xkeyhints = self.get_md_value(["start", "hints", "dimensions"], [])
            logging.debug(f"Getting dimension hints took: {time.time() - t1:.3f}s")

            # Initialize dictionaries
            xkeys = {}
            ykeys = {1: [], 2: []}  # We'll determine actual dimensions later

            # Handle time key if present
            if "time" in all_keys:
                xkeys[0] = ["time"]
                all_keys.remove("time")

            # Process dimension hints
            t2 = time.time()
            for i, dimension in enumerate(xkeyhints):
                axlist = dimension[0]
                xkeys[i + 1] = []
                for ax in axlist:
                    if ax in all_keys:
                        all_keys.remove(ax)
                        xkeys[i + 1].append(ax)
                if len(xkeys[i + 1]) == 0:
                    xkeys.pop(i + 1)
            logging.debug(f"Processing hints took: {time.time() - t2:.3f}s")

            # All remaining keys go to ykeys[1] initially
            ykeys[1] = all_keys

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

    def getAvailableKeys(self) -> List[str]:
        """
        Get list of all available data keys.

        Returns
        -------
        List[str]
            List of available keys
        """
        return list(self._run["primary", "data"].keys())
