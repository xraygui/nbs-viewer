from collections import defaultdict
import numpy as np
from .base import CatalogRun
from typing import List, Tuple, Dict

class MemoryRun(CatalogRun):
    """
    Implementation of CatalogRun for a totally static in-memory run

    Parameters
    ----------
    metadata: dict
        Document containing metadata about the run. Should contain, minimally, the following keys:
        - scan_id
        - uid
        - time
        - plan_name
        - exit_status 
    data: dict
        Dictionary containing data keys. For sanity's sake, all should be of the same length   
    """

    DISPLAY_KEYS = {
        "scan_id": "Scan ID",
        "uid": "UID",
        "date": "Date",
        "num_points": "Scan Points",
        "plan_name": "Plan Name",
        "exit_status": "Status",
    }

    METADATA_KEYS = [
        "scan_id",
        "plan_name",
        "num_points",
        "date",
        "exit_status",
        "uid",
    ]

    def __init__(self, metadata, data):
        self.metadata = metadata
        self._data = data
        self._dim_cache = {}
        self.setup()

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

    def __repr__(self):
        """
        Returns a string representation of the CatalogRun object.

        Returns
        -------
        str
            String representation including class name and run info
        """
        return f"{self.__class__.__name__}"
        
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


    def setup(self):
        """Set up the run object by extracting metadata from start document."""
        
        for key in self.METADATA_KEYS:
            if not hasattr(self.__class__, key):
                value = self.metadata.get(key, None)
                setattr(self, key, value)

        self._plot_hints = self.metadata.get("plot_hints", {})
        self._hints = self.metadata.get("hints", {})

    @property
    def num_points(self):
        if 'time' in self._data:
            return len(self._data['time'])
        else:
            data = list(self._data.values())[0]
            return len(data)
        


    def get_md_value(self, keys, default=None):
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


    def getRunKeys(self):
        xkeys = defaultdict(list)
        ykeys = defaultdict(list)

        # Get dimension hints from start doc
        dimensions = self.hints.get("dimensions", [])
        if not dimensions and self.motors:
            dimensions = [motor for motor in self.motors]
        elif not dimensions:
            dimensions = ["time"]

        xkeys[0].append("time")
        for field in dimensions:
            if field != "time":
                xkeys[1].append(field)

        # Add remaining keys as y values
        
        for key in self._data.keys():
            if not any(key in xlist for xlist in xkeys.values()):
                ykeys[1].append(key)
        return dict(xkeys), dict(ykeys)

    def getData(self, key, slice_info=None):
        """
        Get data for a specific key from the buffer.

        Parameters
        ----------
        key : str
            The data key to retrieve

        Returns
        -------
        np.ndarray
            Array of values for the key
        """
        # print(f"Getting data for key: {key}")
        data = np.array(self._data.get(key, []))
        if slice_info is not None:
            return data[slice_info]
        else:
            return data

    def getAxis(self, keys):
        if not keys:
            return np.array([])

        key = keys[-1]
        if key == "time":
            return np.array(self._data.get("time", []))

        return np.array(self._data.get(key, []))

    def getPlotHints(self):
        return self._plot_hints

    def refresh(self):
        pass

    def _infer_dims_from_shape(self, key: str, shape: Tuple[int, ...]) -> Tuple[str, ...]:
        """
        Infer dimension names when Tiled structure metadata has no dims.

        Stacked Bluesky primary arrays typically use a leading event axis named
        ``time`` when a ``time`` data key exists in the stream.

        Parameters
        ----------
        key : str
            Data key name.
        shape : tuple of int
            Array shape for the key.

        Returns
        -------
        tuple of str
            Inferred dimension names.
        """

    def _resolve_dims(self, key: str) -> Tuple[str, ...]:
        """
        Resolve dimension names for a data key, with shape-based inference as fallback.

        Parameters
        ----------
        key : str
            Data key name.

        Returns
        -------
        tuple of str
            Dimension names for the key.
        """
        shape = tuple(self.getShape(key))
        ndim = len(shape)
        if ndim == 0:
            return ()

        if key == "time":
            return ("time",)

        has_time_key = False
        try:
            has_time_key = "time" in self._data.keys()
        except Exception:
            has_time_key = False

        if has_time_key:
            if ndim == 1:
                return ("time",)
            return ("time",) + tuple(f"dim_{i}" for i in range(0, ndim))

        inferred = tuple(f"dim_{i}" for i in range(ndim))

        return inferred

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
        if ykey not in self._dim_cache:
            self._dim_cache[ykey] = self._resolve_dims(ykey)

        y_dims = self._dim_cache[ykey]

        x_dims = {}
        for key in xkeys:
            if key not in self._dim_cache:
                self._dim_cache[key] = self._resolve_dims(key)
            x_dims[key] = self._dim_cache[key]

        return y_dims, x_dims        