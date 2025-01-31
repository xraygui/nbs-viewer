from datetime import datetime
from abc import ABC, abstractmethod
import time
import logging

# logging.basicConfig(level=logging.DEBUG)


class CatalogRun(ABC):
    @classmethod
    @abstractmethod
    def METADATA_KEYS(cls):
        """
        Abstract class method that subclasses must define.
        Should return a list of metadata keys.
        """
        pass

    def __init__(self, run, key, catalog):
        self._run = run
        self._key = key
        self._catalog = catalog

    def __repr__(self):
        """
        Returns a string representation of the CatalogRun object.

        This representation includes the class name and the repr of the wrapped _run object.
        """
        return f"{self.__class__.__name__}({self._run!r})"

    @abstractmethod
    def setup(self):
        """
        Abstract method that subclasses must implement.
        Should set up the run object by defining attributes for every
        key in METADATA_KEYS.
        """
        pass

    def refresh(self):
        self._run = self._catalog[self._key]
        self.setup()

    @abstractmethod
    def getData(self, key):
        """
        Abstract method that subclasses must implement.
        Should return the data for a given key.
        """
        pass

    @abstractmethod
    def getShape(self, key):
        """
        Abstract method that subclasses must implement.
        Should return the shape of the data for a given key.
        """
        pass

    def getPlotHints(self):
        """
        Generic method to get plot hints.
        Subclasses should override this with a dictionary of plot hints,
        if applicable/desired.
        """
        return {}

    @abstractmethod
    def to_header(self):
        """
        Get a dictionary of metadata suitable for display in a header.

        Returns
        -------
        dict
            Dictionary of metadata key-value pairs
        """
        pass


class BlueskyRun(CatalogRun):
    """
    A class representing a Bluesky run with data caching capabilities.
    """

    METADATA_KEYS = {
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

    def __init__(self, run, key, catalog):
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
        self._catalog = catalog
        self._key = key
        self._run = run
        self._data_cache = {}
        self._axis_cache = {}
        self._shape_cache = {}
        self.setup()

    def refresh(self):
        """
        Refresh the run data and clear caches.
        """
        self._data_cache.clear()
        self._axis_cache.clear()
        self._shape_cache.clear()
        super().refresh()

    def setup(self):
        self.metadata = self._run.metadata

        self._date = datetime.fromtimestamp(
            self.get_md_value(["start", "time"], 0)
        ).isoformat()

        for attr, keys in self.METADATA_KEYS.items():
            if not hasattr(self.__class__, attr):
                value = self.get_md_value(keys)
                setattr(self, attr, value)

        if self._key is None:
            self._key = self.uid

    def get_md_value(self, keys, default=None):
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

        Returns -1 if not defined in the metadata.
        """
        value = self.get_md_value(["stop", "num_events", "primary"], None)
        if value is None:
            value = self.get_md_value(["start", "num_points"], -1)
        return value

    @property
    def date(self):
        return self._date

    def to_row(self):
        """
        Returns a tuple of values corresponding to the METADATA_KEYS.
        """
        return tuple(getattr(self, attr, None) for attr in self.METADATA_KEYS)

    @classmethod
    def to_header(cls):
        attrs = cls.METADATA_KEYS.keys()
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

    def getPlotHints(self):
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
        t_start = time.time()
        if key not in self._data_cache:
            logging.debug(f"Fetching data for key {key}")
            self._data_cache[key] = self._run["primary", "data", key].read()
            logging.debug(f"Fetching data for {key} took: {time.time() - t_start:.3f}s")
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

    def __str__(self):
        scan_desc = ["Scan", str(self.scan_id)]

        if self.plan_name:
            scan_desc.append(self.plan_name)

        return " ".join(scan_desc)

    def scanFinished(self):
        return bool(self.metadata.get("stop", False))

    def scanSucceeded(self):
        status = self.get_md_value(["stop", "exit_status"], "")
        return status == "success"


class NBSRun(BlueskyRun):
    METADATA_KEYS = {
        "uid": ["start", "uid"],
        "date": [],
        "scan_id": ["start", "scan_id"],
        "scantype": ["start", "scantype"],
        "plan_name": ["start", "plan_name"],
        "edge": ["start", "edge"],
        "sample_name": ["start", "sample_name"],
        "sample_id": ["start", "sample_id"],
        "num_points": [],
    }

    DISPLAY_KEYS = {
        "uid": "UID",
        "date": "Date",
        "scan_id": "Scan ID",
        "scantype": "Scan Type",
        "plan_name": "Plan Name",
        "edge": "Edge",
        "sample_name": "Sample Name",
        "sample_id": "Sample ID",
        "num_points": "Scan Points",
    }

    def __str__(self):
        scan_desc = ["Scan", str(self.scan_id)]
        if self.edge:
            scan_desc.extend([self.edge, "edge"])
        if self.scantype:
            scan_desc.append(self.scantype)
        elif self.plan_name:
            scan_desc.append(self.plan_name)
        if self.sample_name:
            scan_desc.extend(["of", self.sample_name])
        else:
            scan_desc.append("of")
            scan_desc.append(
                self.get_md_value(["start", "sample_md", "name"], "Unknown")
            )
        return " ".join(scan_desc)
