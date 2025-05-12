"""Base table model for catalog data display."""

from qtpy.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant, QTimer, Signal
from bluesky_widgets.qt.threading import create_worker
import collections
from nbs_viewer.utils import print_debug


LOADING_PLACEHOLDER = "..."
LOADING_LATENCY = 100  # ms


def _load_chunk(get_chunk, indexes):
    """
    Load chunks of data from the catalog, avoiding overlapping requests.

    Parameters
    ----------
    get_chunk : callable
        Function to get a chunk of data
    indexes : list of tuple
        List of (start, stop) index ranges to load

    Yields
    ------
    tuple
        (row_index, row_data) for each loaded row
    """
    # Track which ranges we've already fetched in this batch
    fetched_ranges = []

    for start, end in indexes:
        # Skip if this range overlaps with any already fetched range
        if any(
            start <= fetched_end and end >= fetched_start
            for fetched_start, fetched_end in fetched_ranges
        ):
            continue

        try:
            rows = get_chunk(start, end)
            fetched_ranges.append((start, end))

            for row, i in zip(rows, range(start, end + 1)):
                yield i, row

        except Exception as ex:
            print_debug(
                "CatalogTableModel",
                f"Error loading chunk {start}-{end}: {ex}",
                category="DEBUG_RUNLIST",
            )


class CatalogTableModel(QAbstractTableModel):
    """
    Base table model for displaying catalog data.

    This model implements lazy loading of data in chunks to handle large
    catalogs efficiently.
    """

    new_run_available = Signal(str)  # emits run uid

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
        super().__init__()
        # print("CatalogTableModel init")
        self._catalog = catalog
        self._catalog.data_updated.connect(self.updateCatalog)
        self._catalog.new_run_available.connect(self.new_run_available)
        self._catalog_length = len(self._catalog)
        # print("Catalog length: ", self._catalog_length)
        self._current_num_rows = 0
        self._fetched_rows = 0
        self._chunk_size = chunk_size
        self._data = {}
        self._keys = {}
        self._invert = False

        # Track which chunks are being loaded or have been requested
        self._loading_chunks = set()  # Set of (start, end) tuples

        self._work_queue = collections.deque()
        self._active_workers = set()

        # Track visible rows for prioritization
        self._visible_rows = set()

        self._data_loading_timer = QTimer(self)
        self._data_loading_timer.singleShot(LOADING_LATENCY, self._process_work_queue)

    def _process_work_queue(self):
        """Process any pending data loading requests."""
        if (
            not self._work_queue or len(self._active_workers) >= 3
        ):  # Limit to 3 concurrent workers
            # Schedule the next processing
            self._data_loading_timer.singleShot(
                LOADING_LATENCY, self._process_work_queue
            )
            return

        # Create a copy of the work queue for processing
        chunks_to_load = list(self._work_queue)
        self._work_queue.clear()

        # Filter out chunks that are already being loaded
        non_overlapping_chunks = []
        for chunk in chunks_to_load:
            # Skip if this chunk is already being loaded
            if chunk in self._loading_chunks:
                continue

            # Skip if this chunk overlaps with any already loading chunk
            if any(
                chunk[0] <= loading_end and chunk[1] >= loading_start
                for loading_start, loading_end in self._loading_chunks
            ):
                continue

            non_overlapping_chunks.append(chunk)
            # Mark this chunk as loading
            self._loading_chunks.add(chunk)

        if non_overlapping_chunks:
            # Debug info
            # print(f"Processing {len(non_overlapping_chunks)} chunks")

            # Prioritize chunks that contain visible rows
            if self._visible_rows:
                # Sort chunks by whether they contain visible rows
                def chunk_priority(chunk):
                    chunk_start, chunk_end = chunk
                    # Check if any visible row is in this chunk
                    for row in self._visible_rows:
                        if chunk_start <= row <= chunk_end:
                            return 0  # Highest priority
                    return 1  # Lower priority

                non_overlapping_chunks.sort(key=chunk_priority)
                # print(f"Prioritized chunks containing visible rows")

            # Process chunks in smaller batches (max 5 chunks per worker)
            max_chunks_per_worker = 5
            for i in range(0, len(non_overlapping_chunks), max_chunks_per_worker):
                batch = non_overlapping_chunks[i : i + max_chunks_per_worker]

                worker = create_worker(_load_chunk, self.get_chunk, tuple(batch))
                self._active_workers.add(worker)
                worker.finished.connect(
                    lambda w=worker, b=batch: self._handle_worker_finished(w, b)
                )
                worker.yielded.connect(self.on_row_loaded)
                worker.start()

                # If we've reached the worker limit, break
                if len(self._active_workers) >= 3:
                    # Put remaining chunks back in the queue
                    for remaining_chunk in non_overlapping_chunks[
                        i + max_chunks_per_worker :
                    ]:
                        print_debug(
                            "CatalogTableModel._process_work_queue",
                            f"Adding remaining chunk to work queue: {remaining_chunk}",
                            category="DEBUG_RUNLIST",
                        )
                        self._work_queue.append(remaining_chunk)
                        self._loading_chunks.remove(remaining_chunk)
                    break

        elif chunks_to_load:
            # If we had chunks but none were processed, log this
            print_debug(
                "CatalogTableModel._process_work_queue",
                f"All {len(chunks_to_load)} chunks were already being loaded",
                category="DEBUG_RUNLIST",
            )

        # Schedule the next processing
        self._data_loading_timer.singleShot(LOADING_LATENCY, self._process_work_queue)

    def _handle_worker_finished(self, worker, chunks):
        """
        Handle worker completion by removing it from active workers
        and marking chunks as no longer loading.

        Parameters
        ----------
        worker : Worker
            The worker that finished
        chunks : list
            List of chunks that were being loaded
        """
        self._active_workers.discard(worker)

        # Remove chunks from loading set
        for chunk in chunks:
            print_debug(
                "CatalogTableModel._handle_worker_finished",
                f"Removing chunk from loading set: {chunk}",
                category="DEBUG_RUNLIST",
            )
            self._loading_chunks.discard(chunk)

    def on_item_loaded(self, payload):
        # Update state and trigger Qt to run data() to update its internal model.
        index, item = payload
        self._data[index] = item
        # print("Loaded Item")
        self.dataChanged.emit(index, index, [])

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
        print_debug(
            "CatalogTableModel.get_chunk",
            f"Getting chunk {start} to {stop}",
            category="DEBUG_RUNLIST",
        )

        # Determine if we need a forward or reverse slice
        is_reversed = start > stop

        if is_reversed:
            # For inverted mode, we need to swap start and stop
            # to get a valid slice (start <= stop)
            chunk_start = stop
            chunk_stop = start
        else:
            chunk_start = start
            chunk_stop = stop

        # Get the chunk from the catalog
        chunk = self._catalog.items_slice(slice(chunk_start, chunk_stop + 1))

        def chunk_generator(chunk):
            # Convert to list if we're in inverted mode
            items = list(chunk) if is_reversed else chunk

            # Reverse the items if we're in inverted mode
            if is_reversed:
                # print("Reversing items")
                items.reverse()

            count = 0
            for key, run in items:
                count += 1
                try:
                    row = run.to_row()
                except Exception as ex:
                    print_debug(
                        "CatalogTableModel.get_chunk",
                        f"Error in chunk_generator: {ex}",
                        category="DEBUG_RUNLIST",
                    )
                    row = ["x"] * len(self._catalog.columns)
                yield key, row

            # print(f"Generated {count} rows from chunk {start}-{stop}")

        loaded_chunk = chunk_generator(chunk)
        return loaded_chunk

    def data(self, index, role=Qt.DisplayRole):
        """Get data for display."""
        if not index.isValid():
            return QVariant()

        if index.column() >= self.columnCount() or index.row() >= self.rowCount():
            return QVariant()

        if role == Qt.DisplayRole:
            if index in self._data:
                if self._data[index] != LOADING_PLACEHOLDER:
                    return self._data[index]

            row = index.row()

            # If no visible rows have been set yet, don't load any data
            # This prevents loading all chunks on startup
            if not self._visible_rows:
                self._data[index] = LOADING_PLACEHOLDER
                return LOADING_PLACEHOLDER

            # Only load data if this row is in the visible set
            if row not in self._visible_rows:
                # For non-visible rows, just return the placeholder without requesting data
                self._data[index] = LOADING_PLACEHOLDER
                return LOADING_PLACEHOLDER

            # For visible rows, proceed with loading
            self._data[index] = LOADING_PLACEHOLDER

            # Calculate chunk boundaries based on the chunk size
            # The row is already in the correct space (original or inverted)
            # because _visible_rows has been mapped in set_visible_rows
            chunk_start = (row // self._chunk_size) * self._chunk_size
            chunk_end = min(
                chunk_start + self._chunk_size - 1, self._catalog_length - 1
            )

            # Check if this chunk is already in the work queue or is being loaded
            chunk = (chunk_start, chunk_end)
            if chunk in self._loading_chunks:
                print_debug(
                    "CatalogTableModel.data",
                    f"Chunk {chunk} is already being loaded",
                    category="DEBUG_RUNLIST",
                )
                # This chunk is already being loaded, no need to request it again
                return LOADING_PLACEHOLDER

            # Check if this chunk is already in the work queue
            if any(
                start == chunk_start and end == chunk_end
                for start, end in self._work_queue
            ):
                print_debug(
                    "CatalogTableModel.data",
                    f"Chunk {chunk} is already in the work queue",
                    category="DEBUG_RUNLIST",
                )
                # This chunk is already in the work queue, no need to add it again
                return LOADING_PLACEHOLDER

            # Add the chunk to the work queue
            print_debug(
                "CatalogTableModel.data",
                f"Requesting chunk for row {row}: {chunk_start}-{chunk_end}",
                category="DEBUG_RUNLIST",
            )
            self._work_queue.append(chunk)

            return LOADING_PLACEHOLDER

        return QVariant()

    def rowCount(self, index=None):
        """Get total number of rows."""
        return self._catalog_length

    def columnCount(self, index=None):
        """Get total number of columns."""
        return len(self._catalog.columns)

    @property
    def columns(self):
        """Get columns."""
        return self._catalog.columns

    def updateCatalog(self):
        """Update catalog data when new data arrives or rows are removed."""
        new_length = len(self._catalog)

        if new_length != self._catalog_length:
            # Clear cached data since indices will change
            self._data.clear()
            self._keys.clear()
            self._loading_chunks.clear()
            self._work_queue.clear()

            if new_length < self._catalog_length:
                # Rows were removed
                self.beginRemoveRows(
                    QModelIndex(), new_length, self._catalog_length - 1
                )
                self._catalog_length = new_length
                self.endRemoveRows()
            else:
                # Rows were added
                self.beginInsertRows(
                    QModelIndex(), self._catalog_length, new_length - 1
                )
                self._catalog_length = new_length
                self.endInsertRows()

            # Update visible rows if they were set
            if self._visible_rows:
                # Recalculate visible rows based on current view
                # This will trigger loading of visible data
                visible_rows = list(self._visible_rows)
                if visible_rows:
                    start_row = min(visible_rows)
                    end_row = min(max(visible_rows), new_length - 1)
                    self.set_visible_rows(start_row, end_row)
        else:
            # If length hasn't changed, just emit dataChanged for visible rows
            if self._visible_rows:
                visible_rows = list(self._visible_rows)
                if visible_rows:
                    start_row = min(visible_rows)
                    end_row = min(max(visible_rows), new_length - 1)

                    # Only emit dataChanged for visible rows
                    start_idx = self.createIndex(start_row, 0)
                    end_idx = self.createIndex(end_row, len(self.columns) - 1)
                    self.dataChanged.emit(start_idx, end_idx, [])
                    return

            # If no visible rows, emit dataChanged for all rows
            start_idx = self.createIndex(0, 0)
            end_idx = self.createIndex(self._catalog_length - 1, len(self.columns) - 1)
            self.dataChanged.emit(start_idx, end_idx, [])

    def get_key(self, row):
        """Get key for given row."""
        if row not in self._keys:
            self.data(self.createIndex(row, 0))
            return None
        return self._keys[row]

    def set_visible_rows(self, start_row, end_row):
        """
        Set the range of rows that are currently visible in the view.

        Parameters
        ----------
        start_row : int
            First visible row
        end_row : int
            Last visible row
        """
        # Calculate the new visible rows set
        new_visible_rows = set(range(start_row, end_row + 1))
        if new_visible_rows:
            print_debug(
                "CatalogTableModel.set_visible_rows",
                f"Visible rows updated: {min(new_visible_rows)} to {max(new_visible_rows)}",
                category="DEBUG_RUNLIST",
            )
        else:
            print_debug(
                "CatalogTableModel.set_visible_rows",
                "No visible rows",
                category="DEBUG_RUNLIST",
            )

        # If we're in inverted mode, we need to translate the visible rows
        if self._invert:
            # Map the visible rows to their inverted positions
            inverted_rows = set()
            for row in new_visible_rows:
                # Calculate the inverted row index
                inverted_row = self._catalog_length - 1 - row
                inverted_rows.add(inverted_row)
            new_visible_rows = inverted_rows
            # print(
            #     f"Mapped visible rows to inverted positions: {start_row}-{end_row} -> {min(inverted_rows)}-{max(inverted_rows)}"
            # )

        # If the visible rows haven't changed, don't do anything
        if new_visible_rows == self._visible_rows:
            print_debug(
                "CatalogTableModel.set_visible_rows",
                "Visible rows haven't changed",
                category="DEBUG_RUNLIST",
            )
            return

        # Update the set of visible rows
        self._visible_rows = new_visible_rows

        # Clear the work queue to prioritize visible rows
        self._work_queue.clear()

        # Request data for visible rows if not already loaded
        for row in self._visible_rows:
            # Only request the first column to trigger loading the entire row
            index = self.createIndex(row, 0)
            if index not in self._data or self._data[index] == LOADING_PLACEHOLDER:
                self.data(index)

        # Immediately process the work queue to start loading visible rows
        self._data_loading_timer.stop()
        self._process_work_queue()
