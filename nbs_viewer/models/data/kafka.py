from collections import defaultdict
import numpy as np
from .base import CatalogRun
from typing import List, Tuple, Dict


class KafkaRun(CatalogRun):
    """
    Implementation of CatalogRun for Kafka streams.

    This class provides a CatalogRun interface for data received over Kafka,
    allowing it to be used with existing plotting infrastructure.

    Parameters
    ----------
    start_doc : dict
        The start document containing metadata about the stream
    key : str
        Unique identifier for this run
    catalog : object, optional
        Not used for Kafka runs, by default None
    """

    _METADATA_MAP = {
        "scan_id": ["start", "scan_id"],
        "uid": ["start", "uid"],
        "time": ["start", "time"],
        "num_points": ["start", "num_points"],
        "plan_name": ["start", "plan_name"],
        "group_name": ["start", "group_name"],
        "sample_name": ["start", "sample_name"],
        "motors": ["start", "motors"],
    }

    DISPLAY_KEYS = {
        "scan_id": "Scan ID",
        "uid": "UID",
        "time": "Time",
        "num_points": "Points",
        "plan_name": "Plan",
        "group_name": "Group",
        "sample_name": "Sample",
    }

    METADATA_KEYS = [
        "scan_id",
        "uid",
        "time",
        "num_points",
        "plan_name",
        "group_name",
        "sample_name",
    ]

    @classmethod
    def to_header(cls):
        """
        Get list of display names for metadata keys.

        Returns
        -------
        list
            List of display names for metadata columns
        """
        return [cls.DISPLAY_KEYS.get(attr, attr) for attr in cls.METADATA_KEYS]

    def __init__(
        self,
        start_doc,
        key=None,
        catalog=None,
    ):
        super().__init__(None, key, catalog, parent=None)
        self.start = start_doc
        self.setup()
        self._stop_doc = {}
        self._data_buffer = defaultdict(list)
        self._descriptors = {}
        self._plot_hints = {}
        # Initialize with basic keys, will update when descriptors arrive
        # print("New KafkaRun")

    def setup(self):
        """Set up the run object by extracting metadata from start document."""
        self.metadata = self.start

        for key, keylist in self._METADATA_MAP.items():
            setattr(self, key, self.get_md_value(keylist))

        self._plot_hints = self.start.get("plot_hints", {})
        self.hints = self.start.get("hints", {})

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

    def get_md_value(self, path, default=None):
        """
        Get a metadata value from the start document.
        """
        doc_name = path[0]
        if doc_name == "start":
            doc = self.start
        elif doc_name == "stop":
            doc = self._stop_doc
        else:
            raise ValueError(f"Invalid document name: {doc_name}")

        for key in path[1:]:
            doc = doc.get(key, {})
        if doc == {}:
            doc = default
        return doc

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
        data = np.array(self._data_buffer.get(key, []))
        if slice_info is not None:
            return data[slice_info]
        else:
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
        data = self.getData(key)
        return data.shape

    def getPlotHints(self):
        """
        Get plot hints from the descriptor documents.

        Returns
        -------
        dict
            Dictionary of plot hints
        """
        return self._plot_hints

    def process_descriptor(self, doc):
        """
        Process a descriptor document.

        Parameters
        ----------
        doc : dict
            The descriptor document
        """
        if doc.get("name") == "primary":
            self._descriptors[doc.get("uid")] = doc
            # Update available keys when we get new descriptors
            self._initialize_keys()

    def process_event(self, doc):
        """
        Process an event document and update data buffers.

        Parameters
        ----------
        doc : dict
            The event document containing:
            time : float
                Timestamp of the event
            data : dict
                Mapping names to values
            descriptor : str
                UID of the descriptor for this event
            uid : str
                Unique identifier for this event
            seq_num : int
                Sequence number of this event
        """
        # print("KafkaRun process_event")
        descriptor_uid = doc.get("descriptor")
        if descriptor_uid not in self._descriptors:
            return

        descriptor = self._descriptors[descriptor_uid]
        if descriptor.get("name") != "primary":
            return

        data = doc.get("data", {})
        if "time" not in data:
            val = doc.get("time", 0.0)
            self._data_buffer["time"].append(val)

        for key, value in data.items():
            self._data_buffer[key].append(value)
        # print("KafkaRun process_event done")
        self.data_changed.emit()

    def process_event_page(self, doc):
        """
        Process an event page document and update data buffers.

        Parameters
        ----------
        doc : dict
            The event page document containing:
            time : list
                List of timestamps for each event
            data : dict
                Mapping names to lists of values
            descriptor : str
                UID of the descriptor for these events
            uid : list
                List of unique identifiers for each event
            seq_num : list
                List of sequence numbers for each event
        """
        # print("KafkaRun process_event_page")
        descriptor_uid = doc.get("descriptor")
        if descriptor_uid not in self._descriptors:
            return

        descriptor = self._descriptors[descriptor_uid]
        if descriptor.get("name") != "primary":
            return

        data = doc.get("data", {})

        if "time" not in data:
            timestamps = doc.get("time", [])
            self._data_buffer["time"].extend(timestamps)

        for key, values in data.items():
            self._data_buffer[key].extend(values)
        # print("KafkaRun process_event_page done")
        self.data_changed.emit()

    def process_stop(self, doc):
        """
        Process a stop document.

        Parameters
        ----------
        doc : dict
            The stop document containing:
            time : float
                Time the run stopped
            exit_status : str
                'success' or 'failure' or 'abort'
            reason : str
                Why the run ended
            num_events : dict
                Number of events per stream
            run_start : str
                UID of the start document
        """
        self._stop_doc = doc
        self.data_changed.emit()

    def scanFinished(self):
        """
        Check if the scan is finished.

        Returns
        -------
        bool
            True if we have received a stop document or reached expected points
        """
        if hasattr(self, "_stop_doc"):
            return True

        if not self.num_points:
            return False

        for data in self._data_buffer.values():
            if len(data) >= self.num_points:
                return True
        return False

    def scanSucceeded(self):
        """
        Check if the scan completed successfully.

        Returns
        -------
        bool
            True if we have a stop document with 'success' status
        """
        if not hasattr(self, "_stop_doc"):
            return False

        return self._stop_doc.get("exit_status") == "success"

    def getRunKeys(self):
        """
        Get the x and y keys for this run, grouping related motor signals together.

        Returns
        -------
        tuple
            (xkeys, ykeys) where each is a dict mapping dimensions to lists
        """
        xkeys = defaultdict(list)
        ykeys = defaultdict(list)

        # Get dimension hints from start doc
        dimensions = self.hints.get("dimensions", [])
        if not dimensions and self.motors:
            dimensions = [([motor], "primary") for motor in self.motors]
        elif not dimensions:
            dimensions = [(["time"], "primary")]

        # Try to get object keys from descriptors
        object_keys = {}
        try:
            for desc in self._descriptors.values():
                if desc.get("name") == "primary":
                    object_keys = desc.get("object_keys", {})
                    break
        except Exception as e:
            print(f"Could not get object_keys from descriptors: {e}")

        # Process dimension hints and add related motor signals
        for fields, stream in dimensions:
            if fields:
                main_key = fields[0]
                xkeys[1].append(main_key)

                # Add related keys from object_keys
                if object_keys and main_key in object_keys:
                    for related_key in object_keys[main_key]:
                        if related_key != main_key:
                            xkeys[1].append(related_key)

        # Always include time in dimension 0
        if "time" not in xkeys[0]:
            xkeys[0].append("time")

        # Add remaining keys as y values
        for desc in self._descriptors.values():
            if desc.get("name") == "primary":
                data_keys = desc.get("data_keys", {})
                for key in data_keys:
                    if not any(key in xlist for xlist in xkeys.values()):
                        ykeys[1].append(key)

        # print(f"xkeys: {dict(xkeys)}")
        # print(f"ykeys: {dict(ykeys)}")
        return dict(xkeys), dict(ykeys)

    def getAxis(self, keys):
        """
        Get axis data for the given keys.

        Parameters
        ----------
        keys : list
            List of keys defining the axis. For Kafka streams, this is typically
            a single key, but we follow the bluesky convention of accepting a list

        Returns
        -------
        np.ndarray
            The axis data
        """
        if not keys:
            return np.array([])

        key = keys[-1]
        if key == "time":
            return np.array(self._data_buffer.get("time", []))

        return np.array(self._data_buffer.get(key, []))

    def refresh(self):
        """
        Refresh the run data.

        For Kafka runs, this is a no-op as data is updated via process_event.
        """
        pass

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

    def get_dims(
        self, ykey: str, xkeys: List[str]
    ) -> Tuple[Tuple[str, ...], Dict[str, Tuple[str, ...]]]:
        """
        Get dimension names from the data buffer.

        For Kafka runs, we generate dimension names based on the shape of the data
        since we don't have access to the underlying data object's dimension names.

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
        # For Kafka runs, we generate dimension names based on shape
        yshape = list(self.getShape(ykey))
        y_dims = ("time",) + tuple(f"dim_{i}" for i in range(1, len(yshape)))

        x_dims = {}
        for key in xkeys:
            shape = list(self.getShape(key))
            x_dims[key] = ("time",) + tuple(f"dim_{i}" for i in range(1, len(shape)))

        print(f"Kafka get_dims with xkeys: {xkeys}, ykey: {ykey}")
        print(f"y_dims: {y_dims}")
        print(f"x_dims: {x_dims}")
        return y_dims, x_dims
