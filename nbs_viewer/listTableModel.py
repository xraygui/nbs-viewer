from qtpy.QtCore import QTimer, Qt, QVariant, QAbstractTableModel
from bluesky_widgets.qt.threading import create_worker
from datetime import datetime

import collections

LOADING_PLACEHOLDER = "..."
LOADING_LATENCY = 100  # ms


def _run_to_row(run):
    start = run.metadata["start"]
    uid = start["uid"]
    date = datetime.fromtimestamp(start.get("time", 0)).isoformat()
    scan_id = start["scan_id"]
    scantype = start.get("scantype", start.get("plan_name", "None"))
    return (uid, scan_id, scantype, date)


def _load_one(get_chunk, indexes):
    for index in indexes:
        print(index)
        try:
            row = get_chunk(index)
        except Exception as ex:
            print(ex)
            continue
        yield index, row


class RunListTableModel(QAbstractTableModel):
    def __init__(self, catalog):
        """
        Initialize the table model with data from a list of Runs.

        Parameters
        ----------
        catalog : Tiled catalog
            A Tiled catalog containing Bluesky runs to be displayed in the table.
        """
        super().__init__()
        self._current_num_rows = 0
        self.catalog = catalog
        self._catalog_length = len(self.catalog)
        self._data = {}
        self._uids = []
        self._fetched_rows = 0
        self.columns = ["uid", "scantype", "scan_id", "date"]

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
            print("work queue populated")
            # worker = create_worker(_load_data, self.get_data, tuple(self._work_queue))
            worker = create_worker(_load_one, self.get_data, tuple(self._work_queue))
            self._work_queue.clear()
            # Track this worker in case we need to ignore it and cancel due to
            # model reset.
            self._active_workers.add(worker)
            worker.finished.connect(lambda: self._active_workers.discard(worker))
            # worker.yielded.connect(self.on_item_loaded)
            worker.yielded.connect(self.on_row_loaded)
            worker.start()
        # Else, no work to do.
        # Schedule the next processing.
        self._data_loading_timer.singleShot(LOADING_LATENCY, self._process_work_queue)

    def on_item_loaded(self, payload):
        # Update state and trigger Qt to run data() to update its internal model.
        index, item = payload
        self._data[index] = item
        print("Loaded Item")
        self.dataChanged.emit(index, index, [])

    def on_row_loaded(self, payload):
        rowNum, row = payload
        for i, item in enumerate(row):
            self._data[self.createIndex(rowNum, i)] = item
        self.dataChanged.emit(
            self.createIndex(rowNum, 0), self.createIndex(rowNum, self.columnCount())
        )

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.columns[section]

    def get_data(self, index):
        return _run_to_row(self.catalog[index])

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():  # does > 0 bounds check
            return QVariant()
        if index.column() >= self.columnCount() or index.row() >= self.rowCount():
            return QVariant()
        if role == Qt.DisplayRole:
            if index in self._data:
                return self._data[index]
            else:
                self._data[index] = LOADING_PLACEHOLDER
                return LOADING_PLACEHOLDER
        else:
            return QVariant()

    def canFetchMore(self, parent=None):
        if parent.isValid():
            return False
        return self._current_num_rows < self._catalog_length

    def fetchMore(self, parent=None):
        if parent.isValid():
            return
        rows_to_add = self._catalog_length - self._current_num_rows
        if rows_to_add <= 0:
            return
        self.beginInsertRows(
            parent, self._current_num_rows, self._current_num_rows + rows_to_add - 1
        )
        print(
            f"Fetching {self._current_num_rows} to {self._current_num_rows + rows_to_add - 1}"
        )
        for i in range(self._current_num_rows, self._current_num_rows + rows_to_add):
            self._work_queue.append(i)

        self._current_num_rows += rows_to_add
        self.endInsertRows()

    def rowCount(self, index=None):
        return self._current_num_rows

    def columnCount(self, index=None):
        return len(self.columns)

    def updateCatalog(self):
        self._catalog_length = len(self.catalog)
