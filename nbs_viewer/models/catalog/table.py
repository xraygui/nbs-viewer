"""Base table model for catalog data display."""

from typing import Any, List, Optional
from qtpy.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QTimer
from bluesky_widgets.qt.threading import create_worker
import collections

LOADING_PLACEHOLDER = "..."
LOADING_LATENCY = 100  # ms


def _load_chunk(get_chunk, indexes):
    """Load a chunk of data from the catalog."""
    fetched_ranges = []
    for index in indexes:
        if any(start <= index[0] <= end for start, end in fetched_ranges):
            continue
        try:
            rows = get_chunk(index[0], index[1])
        except Exception as ex:
            print("Something went wrong loading chunk", ex)
            continue
        fetched_ranges.append((index[0], index[1]))
        for row, i in zip(rows, range(index[0], index[1] + 1)):
            yield i, row


class CatalogTableModel(QAbstractTableModel):
    """
    Base table model for displaying catalog data.

    This model implements lazy loading of data in chunks to handle large
    catalogs efficiently.
    """

    def __init__(self, catalog, chunk_size=50, parent=None):
        """
        Initialize the table model.

        Parameters
        ----------
        catalog : CatalogBase
            The catalog containing the data to display.
        chunk_size : int, optional
            Number of rows to fetch per chunk.
        parent : QObject, optional
            Parent object.
        """
        super().__init__(parent)
        self._catalog = catalog
        self._catalog_length = len(self._catalog)
        self._chunk_size = chunk_size
        self._data = {}
        self._keys = {}
        self._invert = False

        self._work_queue = collections.deque()
        self._active_workers = set()

        self._data_loading_timer = QTimer(self)
        self._data_loading_timer.singleShot(LOADING_LATENCY, self._process_work_queue)

    def _process_work_queue(self):
        """Process any pending data loading requests."""
        if self._work_queue:
            worker = create_worker(_load_chunk, self.get_chunk, tuple(self._work_queue))
            self._work_queue.clear()
            self._active_workers.add(worker)
            worker.finished.connect(lambda: self._active_workers.discard(worker))
            worker.yielded.connect(self.on_row_loaded)
            worker.start()

        self._data_loading_timer.singleShot(LOADING_LATENCY, self._process_work_queue)

    def on_row_loaded(self, payload):
        """Handle loaded row data."""
        rowNum, (key, row) = payload
        self._keys[rowNum] = key
        for i, item in enumerate(row):
            self._data[self.createIndex(rowNum, i)] = item
        self.dataChanged.emit(
            self.createIndex(rowNum, 0), self.createIndex(rowNum, len(row) - 1), []
        )

    def headerData(self, section, orientation, role):
        """Get header data for display."""
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._catalog.columns[section]

    def get_chunk(self, start, stop):
        """
        Get a chunk of data from the catalog.

        Parameters
        ----------
        start : int
            Start index.
        stop : int
            Stop index.

        Returns
        -------
        list
            List of (key, row) tuples.
        """
        return list(self._catalog.items_slice(slice(start, stop + 1)))

    def data(self, index, role=Qt.DisplayRole):
        """Get data for display."""
        if not index.isValid():
            return QVariant()

        if index.column() >= self.columnCount() or index.row() >= self.rowCount():
            return QVariant()

        if role == Qt.DisplayRole:
            if index in self._data:
                return self._data[index]

            self._data[index] = LOADING_PLACEHOLDER

            if self._invert:
                minrow = max(0, index.row() - self._chunk_size - 1)
                self._work_queue.append((minrow, index.row()))
            else:
                maxrow = min(
                    index.row() + self._chunk_size - 1, self._catalog_length - 1
                )
                self._work_queue.append((index.row(), maxrow))
            return LOADING_PLACEHOLDER

        return QVariant()

    def rowCount(self, index=None):
        """Get total number of rows."""
        return self._catalog_length

    def columnCount(self, index=None):
        """Get total number of columns."""
        return len(self._catalog.columns)

    def updateCatalog(self):
        """Update catalog data."""
        self._catalog_length = len(self._catalog)
        self.layoutChanged.emit()

    def get_key(self, row):
        """Get key for given row."""
        if row not in self._keys:
            self.data(self.createIndex(row, 0))
            return None
        return self._keys[row]
