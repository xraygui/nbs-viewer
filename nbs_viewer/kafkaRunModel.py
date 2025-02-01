from collections import defaultdict
import numpy as np
from .runModel import CatalogRun
from qtpy.QtCore import Qt, QAbstractTableModel, QVariant
from qtpy.QtWidgets import QWidget


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
        "scan_id": ["scan_id"],
        "uid": ["uid"],
        "time": ["time"],
        "num_points": ["num_points"],
        "plan_name": ["plan_name"],
        "sample_name": ["sample_name"],
    }

    DISPLAY_KEYS = {
        "scan_id": "Scan ID",
        "uid": "UID",
        "time": "Time",
        "num_points": "Points",
        "plan_name": "Plan",
        "sample_name": "Sample",
    }

    @classmethod
    def METADATA_KEYS(cls):
        """
        Define required metadata keys.

        Returns
        -------
        list
            List of required metadata keys
        """
        return list(cls._METADATA_MAP.keys())

    @classmethod
    def to_header(cls):
        """
        Get list of display names for metadata keys.

        Returns
        -------
        list
            List of display names for metadata columns
        """
        return [cls.DISPLAY_KEYS.get(attr, attr) for attr in cls._METADATA_MAP]

    def __init__(self, start_doc, key, catalog=None):
        super().__init__(None, key, catalog)
        self._start_doc = start_doc
        self._data_buffer = defaultdict(list)
        self._descriptors = {}
        self._plot_hints = {}
        self.setup()

    def setup(self):
        """
        Set up the run object by extracting metadata from start document.
        """
        self.time = self._start_doc.get("time")
        self.uid = self._start_doc.get("uid")
        self.scan_id = self._start_doc.get("scan_id")
        self._plot_hints = self._start_doc.get("plot_hints", {})
        self.hints = self._start_doc.get("hints", {})
        self.motors = self._start_doc.get("motors", [])
        self.num_points = self._start_doc.get("num_points")
        self.metadata = self._start_doc

    def getData(self, key):
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
        return np.array(self._data_buffer.get(key, []))

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
        # Only store descriptors for the primary stream
        if doc.get("name") == "primary":
            self._descriptors[doc.get("uid")] = doc

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
        # Store event metadata
        descriptor_uid = doc.get("descriptor")
        if descriptor_uid not in self._descriptors:
            # Skip events for unknown descriptors
            return

        # Skip if not from primary stream (descriptor was filtered)
        descriptor = self._descriptors[descriptor_uid]
        if descriptor.get("name") != "primary":
            return

        # Store event timestamp in time buffer if not in data
        data = doc.get("data", {})
        if "time" not in data:
            val = doc.get("time", 0.0)
            self._data_buffer["time"].append(val)
            # print(f"Event time: {val}")

        # Update data buffers
        for key, value in data.items():
            self._data_buffer[key].append(value)
            # print(f"Event {key}: {value}")

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
        # Store event metadata
        descriptor_uid = doc.get("descriptor")
        if descriptor_uid not in self._descriptors:
            # Skip event pages for unknown descriptors
            return

        # Skip if not from primary stream (descriptor was filtered)
        descriptor = self._descriptors[descriptor_uid]
        if descriptor.get("name") != "primary":
            return

        # Update data buffers
        data = doc.get("data", {})

        # Store event timestamps in time buffer if not in data
        if "time" not in data:
            timestamps = doc.get("time", [])
            self._data_buffer["time"].extend(timestamps)
            # print(f"Event page time: {timestamps}")

        # Update data buffers
        for key, values in data.items():
            self._data_buffer[key].extend(values)
            # print(f"Event page {key}: {values}")

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

    def scanFinished(self):
        """
        Check if the scan is finished.

        Returns
        -------
        bool
            True if we have received a stop document or reached expected points
        """
        # If we have a stop document, we're definitely done
        if hasattr(self, "_stop_doc"):
            return True

        # Otherwise check if we've reached expected points
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
        Get the x and y keys for this run.

        This method organizes keys from the descriptor into x and y axes,
        using hints from the start document to determine dimensions.

        Returns
        -------
        tuple
            (xkeys, ykeys) where each is a dict mapping dimensions to lists of keys
        """
        # Initialize dimension dictionaries
        xkeys = defaultdict(list)
        ykeys = defaultdict(list)

        # Get dimensions from hints
        dimensions = self.hints.get("dimensions", [])
        if not dimensions and self.motors:
            # If no dimensions in hints, use motors as dimension 1
            dimensions = [([motor], "primary") for motor in self.motors]
        elif not dimensions:
            # If no motors either, use time as dimension 0
            dimensions = [(["time"], "primary")]

        # Add x keys based on dimensions
        for fields, stream in dimensions:
            # First field in each dimension group is the x axis
            if fields:
                xkeys[1].append(fields[0])

        # Add time to dimension 0 if we have it
        # Always add time to dimension 0
        if "time" not in xkeys[0]:
            xkeys[0].append("time")

        # Get y keys from descriptors
        for desc in self._descriptors.values():
            if desc.get("name") == "primary":
                # Get all data keys
                data_keys = desc.get("data_keys", {})

                # Add to y keys, excluding those used as x axes
                for key in data_keys:
                    if not any(key in xlist for xlist in xkeys.values()):
                        # For now, put all y keys in dimension 1
                        ykeys[1].append(key)

        return dict(xkeys), dict(ykeys)

    def getAxis(self, keys):
        """
        Get axis data for the given keys.

        Parameters
        ----------
        keys : list
            List of keys defining the axis. For Kafka streams, this is typically
            a single key, but we follow the bluesky convention of accepting a list.

        Returns
        -------
        np.ndarray
            The axis data

        Notes
        -----
        For time axes, returns the timestamps from the data buffer.
        For other axes, returns the data values for that key.
        """
        if not keys:
            return np.array([])

        # Use the last key in the list (following bluesky convention)
        key = keys[-1]

        # Special handling for time axis
        if key == "time":
            return np.array(self._data_buffer.get("time", []))

        # For other axes, return the data values
        return np.array(self._data_buffer.get(key, []))

    def refresh(self):
        """
        Refresh the run data.

        For Kafka runs, this is a no-op as data is updated via process_event.
        """
        pass


class KafkaRunTableModel(QAbstractTableModel):
    """
    Table model for displaying KafkaRuns.

    Parameters
    ----------
    runs : list
        List of KafkaRun instances
    parent : QWidget, optional
        Parent widget, by default None
    """

    def __init__(self, runs=None, parent=None):
        super().__init__(parent)
        self._runs = runs or []
        self._headers = KafkaRun.to_header()
        self.columns = self._headers  # For compatibility with CatalogTableModel
        self._catalog_length = len(self._runs)  # For compatibility

    def rowCount(self, parent=None):
        return self._catalog_length

    def columnCount(self, parent=None):
        return len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return QVariant()
        if index.column() >= self.columnCount() or index.row() >= self.rowCount():
            return QVariant()

        if role == Qt.DisplayRole:
            run = self._runs[index.row()]
            attr = KafkaRun.METADATA_KEYS()[index.column()]
            return str(getattr(run, attr, ""))

        return QVariant()

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return QVariant()

        if orientation == Qt.Horizontal:
            return self.columns[section]

        return str(section + 1)

    def addRun(self, run):
        """
        Add a new run to the model.

        Parameters
        ----------
        run : KafkaRun
            The run to add
        """
        self.beginInsertRows(
            self.index(0, 0).parent(), len(self._runs), len(self._runs)
        )
        self._runs.append(run)
        self._catalog_length = len(self._runs)
        self.endInsertRows()

    def getRun(self, row):
        """
        Get the run at the specified row.

        Parameters
        ----------
        row : int
            The row index

        Returns
        -------
        KafkaRun
            The run at that row
        """
        return self._runs[row]

    def get_key(self, row):
        """
        Get the unique key for a row.

        Parameters
        ----------
        row : int
            The row index

        Returns
        -------
        str
            The run's unique identifier
        """
        run = self.getRun(row)
        return run.uid if run is not None else None


class KafkaRunManager:
    """
    Manager class for creating and updating KafkaRuns from documents.

    This class handles the creation of new runs when start documents are
    received and dispatches subsequent documents to the appropriate run.

    Parameters
    ----------
    model : KafkaRunTableModel
        The model to update with new runs
    """

    def __init__(self, model):
        self._model = model
        self._active_runs = {}  # uid -> KafkaRun
        self._desc_to_run = {}  # descriptor_uid -> run_uid

    def dispatch(self, name, doc):
        """
        Dispatch a document to the appropriate handler.

        Parameters
        ----------
        name : str
            Document name (start, descriptor, event, etc.)
        doc : dict
            The document itself
        """
        handler = getattr(self, f"_handle_{name}", None)
        if handler is not None:
            handler(doc)

    def _handle_start(self, doc):
        """Handle a start document by creating a new run."""
        uid = doc.get("uid")
        if uid in self._active_runs:
            return

        run = KafkaRun(doc, uid)
        self._active_runs[uid] = run
        self._model.addRun(run)

    def _handle_descriptor(self, doc):
        """
        Handle a descriptor document.

        Maps the descriptor UID to its run UID for event routing.
        """
        run_uid = doc.get("run_start")
        desc_uid = doc.get("uid")

        if run_uid in self._active_runs:
            self._desc_to_run[desc_uid] = run_uid
            self._active_runs[run_uid].process_descriptor(doc)

    def _handle_event(self, doc):
        """Handle an event document."""
        desc_uid = doc.get("descriptor")
        if desc_uid in self._desc_to_run:
            run_uid = self._desc_to_run[desc_uid]
            if run_uid in self._active_runs:
                self._active_runs[run_uid].process_event(doc)

    def _handle_event_page(self, doc):
        """Handle an event page document."""
        desc_uid = doc.get("descriptor")
        if desc_uid in self._desc_to_run:
            run_uid = self._desc_to_run[desc_uid]
            if run_uid in self._active_runs:
                self._active_runs[run_uid].process_event_page(doc)

    def _handle_stop(self, doc):
        """
        Handle a stop document.

        Process the stop document and remove the run from active runs.
        """
        run_uid = doc.get("run_start")
        if run_uid in self._active_runs:
            self._active_runs[run_uid].process_stop(doc)
            # Clean up descriptor mappings for this run
            desc_uids = [
                desc_uid
                for desc_uid, run in self._desc_to_run.items()
                if run == run_uid
            ]
            for desc_uid in desc_uids:
                del self._desc_to_run[desc_uid]
            # Remove from active runs
            del self._active_runs[run_uid]
