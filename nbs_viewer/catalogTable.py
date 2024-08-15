from qtpy.QtCore import QTimer, Qt, QVariant, QAbstractTableModel
from bluesky_widgets.qt.threading import create_worker

import collections

LOADING_PLACEHOLDER = "..."
LOADING_LATENCY = 100  # ms


def _load_chunk(get_chunk, indexes):
    fetched_ranges = []
    for index in indexes:
        # print(index)
        # Check if index[0] is within any previously fetched range
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
    def __init__(self, catalog, chunk_size=50):
        """
        Initialize the table model with data from a Tiled catalog.

        Parameters
        ----------
        catalog : Tiled catalog
            A Tiled catalog containing Bluesky runs to be displayed in the table.
        chunk_size : int, optional
            The number of rows to fetch per chunk, by default 50.
        """
        super().__init__()
        self.catalog = catalog
        self._catalog_length = len(self.catalog)
        self._invert = False
        self._current_num_rows = 0
        self._chunk_size = chunk_size
        self._data = {}
        self._keys = {}  # Change this to a dictionary
        self._fetched_rows = 0
        self.columns = self.catalog.columns

        self._work_queue = collections.deque()
        # Set of active workers
        self._active_workers = set()

        # Start a timer that will periodically load any data queued up to be loaded.
        self._data_loading_timer = QTimer(self)
        # We run this once to initialize it. The _process_work_queue schedules
        # it to be run again when it completes. This is better than a strictly
        # periodic timer because it ensures that requests do not pile up if
        # _process_work_queue takes longer than LOADING_LATENCY to complete.
        self._data_loading_timer.singleShot(LOADING_LATENCY, self._process_work_queue)

    def _process_work_queue(self):
        if self._work_queue:
            worker = create_worker(_load_chunk, self.get_chunk, tuple(self._work_queue))
            self._work_queue.clear()
            # Track this worker in case we need to ignore it and cancel due to
            # model reset.
            self._active_workers.add(worker)
            worker.finished.connect(lambda: self._active_workers.discard(worker))
            worker.yielded.connect(self.on_row_loaded)
            worker.start()
        # Else, no work to do.
        # Schedule the next processing.
        self._data_loading_timer.singleShot(LOADING_LATENCY, self._process_work_queue)

    def on_item_loaded(self, payload):
        # Update state and trigger Qt to run data() to update its internal model.
        index, item = payload
        self._data[index] = item
        # print("Loaded Item")
        self.dataChanged.emit(index, index, [])

    def on_row_loaded(self, payload):
        rowNum, (key, row) = payload
        self._keys[rowNum] = key  # Store the key
        for i, item in enumerate(row):
            self._data[self.createIndex(rowNum, i)] = item
        self.dataChanged.emit(
            self.createIndex(rowNum, 0), self.createIndex(rowNum, len(row) - 1), []
        )

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.columns[section]

    def get_chunk(self, start, stop):
        chunk = list(self.catalog.items_slice(slice(start, stop + 1)))
        return [(key, run.to_row()) for key, run in chunk]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():  # does > 0 bounds check
            # print(f"Invalid index row: {index.row()}, column: {index.column()}")
            return QVariant()
        if index.column() >= self.columnCount() or index.row() >= self.rowCount():
            # print(f"Out of bounds index row: {index.row()}, column: {index.column()}")
            return QVariant()
        if role == Qt.DisplayRole:
            # print(f"Data requested for row: {index.row()}, column: {index.column()}")
            if index in self._data:
                return self._data[index]
            else:
                # print("Data not found")
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
        else:
            # Return QVariant() for unsupported roles
            return QVariant()

    def rowCount(self, index=None):
        return self._catalog_length

    def columnCount(self, index=None):
        return len(self.columns)

    def updateCatalog(self):
        self._catalog_length = len(self.catalog)
        if self.canFetchMore():
            self.fetchMore()

    def get_key(self, row):
        if row not in self._keys:
            # If the key for this row hasn't been loaded yet, trigger a load
            self.data(self.createIndex(row, 0))
            return None  # Return None to indicate the key isn't available yet
        return self._keys[row]
