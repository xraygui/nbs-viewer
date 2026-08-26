from collections import defaultdict
import numpy as np
from .base import CatalogRun
from typing import List, Tuple, Dict


class MemoryRun(CatalogRun):
    """
    Implementation of CatalogRun for a totally static in-memory run.

    Parameters
    ----------
    metadata : dict
        Document containing metadata about the run. Should contain, minimally,
        the following keys:

        - scan_id
        - uid
        - date or time
        - plan_name
        - exit_status
    data : dict
        Dictionary containing data keys. All arrays should be the same length.
    key : str, optional
        Unique identifier for this run. Defaults to ``metadata["uid"]``.
    catalog : object, optional
        Parent catalog, by default None.
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

    def __init__(self, metadata, data, key=None, catalog=None):
        uid = key if key is not None else metadata.get("uid")
        super().__init__(None, uid, catalog, parent=None)
        self.metadata = metadata
        self._data = data
        self._dim_cache = {}
        self.setup()
        self._initialize_keys()

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
        return f"{self.__class__.__name__}({self.uid!r})"

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
        """Set up the run object by extracting metadata from the start document."""
        self.start = self.metadata

        for key in self.METADATA_KEYS:
            if not hasattr(self.__class__, key):
                value = self.metadata.get(key, None)
                setattr(self, key, value)

        if not hasattr(self.__class__, "motors"):
            self.motors = self.metadata.get("motors", None)

        self._plot_hints = self.metadata.get("plot_hints", {})
        self.hints = self.metadata.get("hints", {})

        if self._key is None:
            self._key = self.uid

    @property
    def num_points(self):
        if "time" in self._data:
            return len(self._data["time"])
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

        dimensions = self.hints.get("dimensions", [])
        if not dimensions and self.motors:
            dimensions = [motor for motor in self.motors]
        elif not dimensions:
            dimensions = ["time"]

        xkeys[0].append("time")
        for field in dimensions:
            if isinstance(field, (list, tuple)) and field:
                field = field[0]
                if isinstance(field, (list, tuple)) and field:
                    field = field[0]
            if field != "time" and field not in xkeys[0] and field not in xkeys[1]:
                xkeys[1].append(field)

        for key in self._data.keys():
            if not any(key in xlist for xlist in xkeys.values()):
                ndim = len(np.asarray(self._data[key]).shape)
                ykeys[max(ndim, 1)].append(key)
        return dict(xkeys), dict(ykeys)

    def getData(self, key, slice_info=None):
        """
        Get data for a specific key from the buffer.

        Parameters
        ----------
        key : str
            The data key to retrieve
        slice_info : tuple, optional
            Per-axis slice tuple. Truncated to the key's dimensionality so
            1-D axes/norms can be loaded alongside N-D plot slices.

        Returns
        -------
        np.ndarray
            Array of values for the key
        """
        data = np.asarray(self._data.get(key, []))
        if slice_info is not None:
            slice_info = tuple(slice_info[: data.ndim])
            return data[slice_info]
        return data

    def getShape(self, key):
        """
        Get the shape of data for a specific key.

        Parameters
        ----------
        key : str
            The data key to get shape for

        Returns
        -------
        tuple
            Shape of the data array
        """
        return np.asarray(self._data.get(key, [])).shape

    def getAxis(self, keys, slice_info=None):
        """
        Get axis data for the given keys.

        Parameters
        ----------
        keys : list
            Key path; the last entry is the data key.
        slice_info : tuple, optional
            Per-axis slice tuple, truncated to the axis dimensionality.

        Returns
        -------
        np.ndarray
            Axis values for the key.
        """
        if not keys:
            return np.array([])

        key = keys[-1]
        data = np.asarray(self._data.get(key, []))
        if slice_info is not None and data.ndim > 0:
            data = data[tuple(slice_info[-data.ndim :])]
        return data
    def getPlotHints(self):
        return self._plot_hints

    def get_default_selection(self) -> Tuple[List[str], List[str], List[str]]:
        """
        Get default key selection for a memory run.

        Returns
        -------
        Tuple[List[str], List[str], List[str]]
            Default (x_keys, y_keys, norm_keys) for this run
        """
        x_keys, y_keys = self.getRunKeys()
        selected_x = []
        selected_y = []

        if 1 in x_keys and x_keys[1]:
            selected_x.append(x_keys[1][0])
        elif 0 in x_keys and x_keys[0]:
            selected_x.append(x_keys[0][0])

        for dim in sorted(y_keys.keys()):
            if y_keys[dim]:
                selected_y.append(y_keys[dim][0])
                break

        return selected_x, selected_y, []

    def refresh(self):
        pass

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

        has_time_key = "time" in self._data

        if has_time_key:
            if ndim == 1:
                return ("time",)
            return ("time",) + tuple(f"dim_{i}" for i in range(1, ndim))

        return tuple(f"dim_{i}" for i in range(ndim))

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
