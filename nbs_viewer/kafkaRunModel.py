from collections import defaultdict
import numpy as np
from .models.data import KafkaRun
from qtpy.QtCore import Qt, QAbstractTableModel, QVariant
from qtpy.QtWidgets import QWidget


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
