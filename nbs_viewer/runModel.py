from datetime import datetime
from abc import ABC, abstractmethod


class CatalogRun(ABC):
    @classmethod
    @property
    @abstractmethod
    def METADATA_KEYS(cls):
        """
        Abstract property that subclasses must define.
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
    def getShape(self):
        """
        Generic method to get the shape of the run.
        Should return the shape of the X-axis data.
        """
        pass

    def getPlotHints(self):
        """
        Generic method to get plot hints.
        Subclasses should override this with a dictionary of plot hints,
        if applicable/desired.
        """
        return {}


class BlueskyRun(CatalogRun):
    METADATA_KEYS = [
        "uid",
        "date",
        "scan_id",
        "plan_name",
        "num_points",
    ]

    def __init__(self, run, key, catalog):
        self._catalog = catalog
        self._key = key
        self._run = run
        self.setup()

    def setup(self):
        self.metadata = self._run.metadata["start"]

        self._date = datetime.fromtimestamp(self.metadata.get("time", 0)).isoformat()

        for key in self.METADATA_KEYS:
            if not hasattr(self.__class__, key):
                value = self.metadata.get(key, None)
                setattr(self, key, value)

        if self._key is None:
            self._key = self.uid

    @property
    def num_points(self):
        """
        Returns the number of points in the run.

        Returns -1 if not defined in the metadata.
        """
        if "num_points" in self.metadata:
            return self.metadata.get("num_points")
        else:
            return (
                self._run.metadata.get("stop", {})
                .get("num_events", {})
                .get("primary", -1)
            )

    @property
    def date(self):
        return self._date

    def to_row(self):
        """
        Returns a tuple of values corresponding to the METADATA_KEYS.
        """
        return tuple(getattr(self, key, None) for key in self.METADATA_KEYS)

    def getShape(self):
        return self.metadata.get("shape", [self.num_points])

    def getPlotHints(self):
        plotHints = self.metadata.get("plot_hints", {})
        return plotHints

    def getData(self, key):
        return self._run["primary", "data", key].read()

    def getAxis(self, keys):
        data = self._run["primary"]
        for key in keys:
            data = data[key]
        return data.read().squeeze()

    def getRunKeys(self):
        allData = {key: arr.shape for key, arr in self._run["primary", "data"].items()}
        xkeyhints = self.metadata.get("dimensions", [])
        keys1d = []
        keysnd = []

        xkeys = {}
        ykeys = {}
        for key in list(allData.keys()):
            if len(allData[key]) == 1:
                keys1d.append(key)
            elif len(allData[key]) > 1:
                keysnd.append(key)
        if "time" in keys1d:
            xkeys[0] = ["time"]
            keys1d.pop(keys1d.index("time"))
        for i, dimension in enumerate(xkeyhints):
            axlist = dimension[0]
            xkeys[i + 1] = []
            for ax in axlist:
                if ax in keys1d:
                    keys1d.pop(keys1d.index(ax))
                    xkeys[i + 1].append(ax)
            if len(xkeys[i + 1]) == 0:
                xkeys.pop(i + 1)
        ykeys[1] = keys1d
        ykeys[2] = keysnd
        return xkeys, ykeys

    def __str__(self):
        scan_desc = ["Scan", str(self.scan_id)]

        if self.plan_name:
            scan_desc.append(self.plan_name)

        return " ".join(scan_desc)

    def scanFinished(self):
        return bool(self._run.metadata.get("stop", False))

    def scanSucceeded(self):
        status = self._run.metadata.get("stop", {}).get("exit_status", "")
        return status == "success"


class NBSRun(BlueskyRun):
    METADATA_KEYS = [
        "uid",
        "date",
        "scan_id",
        "scantype",
        "plan_name",
        "edge",
        "sample_name",
        "sample_id",
        "num_points",
    ]

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
        elif hasattr(self.metadata, "sample_md"):
            scan_desc.append("of")
            scan_desc.append(self.metadata["sample_md"].get("name", "Unknown"))
        return " ".join(scan_desc)
