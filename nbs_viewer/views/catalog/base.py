from qtpy.QtWidgets import (
    QHeaderView,
    QMenu,
    QAction,
    QTableView,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLineEdit,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QCheckBox,
)
from qtpy.QtCore import (
    Qt,
    QSortFilterProxyModel,
    QItemSelectionModel,
    QModelIndex,
    QTimer,
    Signal,
)

from ...models.catalog.table import CatalogTableModel
from ...search import DateSearchWidget
from ..plot.metadataView import FullMetadataBrowser
from nbs_viewer.utils import print_debug, get_top_level_model


class CustomHeaderView(QHeaderView):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.showContextMenu)

    def showContextMenu(self, pos):
        # Get the column index based on the position of the mouse click
        index = self.logicalIndexAt(pos)
        if index < 0:
            return  # No column was clicked

        menu = QMenu(self)
        hidden_columns = self.getHiddenColumns()
        numcol = self.count()
        if len(hidden_columns) < numcol - 1:
            col_name = self.getColumnName(index)
            action1 = QAction(f"Hide {col_name}", self)

            def _hideThisColumn():
                self.hideColumn(index)

            action1.triggered.connect(_hideThisColumn)

            menu.addAction(action1)

        for col in hidden_columns:
            col_name = self.getColumnName(col)
            action = QAction(f"Show {col_name}", self)

            def _showCol():
                self.showColumn(col)

            action.triggered.connect(_showCol)
            menu.addAction(action)

        menu.exec_(self.mapToGlobal(pos))

    def hideColumn(self, index):
        self.parent().hideColumn(index)  # Assuming the parent is a QTableView

    def showColumn(self, index):
        self.parent().showColumn(index)

    def getHiddenColumns(self):
        """
        Returns a list of indices of hidden columns in the given QTableView.

        Parameters
        ----------
        table_view : QTableView
            The table view to check for hidden columns.

        Returns
        -------
        list of int
            The list of hidden column indices.
        """
        table_view = self.parent()

        hidden_columns = []
        model = table_view.model()
        if model:  # Ensure there is a model
            column_count = model.columnCount()
            for column in range(column_count):
                if table_view.isColumnHidden(column):
                    hidden_columns.append(column)
        return hidden_columns

    def getColumnName(self, column_index):
        """
        Returns the name of the column at the specified index in the given
        QTableView.

        Parameters
        ----------
        table_view : QTableView
            The table view containing the column.
        column_index : int
            The index of the column.

        Returns
        -------
        str
            The name of the column.
        """
        table_view = self.parent()
        model = table_view.model()
        if model is not None:
            # Qt.DisplayRole returns the data used for display purposes
            return model.headerData(column_index, Qt.Horizontal, Qt.DisplayRole)
        return None


class ReverseModel(QSortFilterProxyModel):
    def __init__(self, *args, **kwargs):
        self.invert = False
        super().__init__(*args, **kwargs)
        self.setDynamicSortFilter(True)

    def mapFromSource(self, sourceIndex):
        if not sourceIndex.isValid():
            return QModelIndex()

        if not self.invert:
            return super().mapFromSource(sourceIndex)

        sourceModel = self.sourceModel()
        if sourceIndex.model() is not sourceModel:
            return QModelIndex()

        row = sourceModel.rowCount() - sourceIndex.row() - 1
        return self.createIndex(row, sourceIndex.column())

    def mapToSource(self, proxyIndex):
        if not proxyIndex.isValid():
            return QModelIndex()

        if not self.invert:
            return super().mapToSource(proxyIndex)

        if proxyIndex.model() is not self:
            return QModelIndex()

        row = self.rowCount() - proxyIndex.row() - 1
        return self.sourceModel().createIndex(row, proxyIndex.column())

    def toggleInvert(self):
        """Toggle the inversion of row order and refresh the view."""
        self.invert = not self.invert
        self.sourceModel()._invert = self.invert

        # Just handle layout change
        self.layoutAboutToBeChanged.emit()
        self.layoutChanged.emit()

    def set_visible_rows(self, start_row, end_row):
        """
        Forward set_visible_rows call to the source model.

        This allows the LazyLoadingTableView to properly trigger
        data loading through the proxy chain.
        """
        source_model = self.sourceModel()
        if hasattr(source_model, "set_visible_rows"):
            source_model.set_visible_rows(start_row, end_row)


class FilterModel(QSortFilterProxyModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDynamicSortFilter(True)
        self.saved_start_row = 0
        self.saved_end_row = 0
        self._filter_target_rows = 0
        self._filter_loaded_end = 0
        self._filter_chunk_size = 50

    def filterAcceptsRow(self, source_row, source_parent):
        regex = self.filterRegularExpression()
        if not regex.pattern() or not regex.isValid():
            return True

        model = self.sourceModel()
        source_index = model.index(source_row, self.filterKeyColumn(), source_parent)

        data = model.data(source_index, Qt.DisplayRole)
        if data is None:
            return False

        data_str = str(data)
        return regex.match(data_str).hasMatch()

    def set_visible_rows(self, start_row, end_row):
        """
        Forward set_visible_rows call to the source model.

        This allows the LazyLoadingTableView to properly trigger
        data loading through the proxy chain.
        """
        # If we're currently filtering, update our target based on what the view needs
        # The view needs to display rows start_row to end_row
        # So we need at least (end_row + 1) total filtered matches
        self._filter_target_rows = end_row + 1
        # print(
        #    f"Updated filter target to {self._filter_target_rows} rows (view needs {start_row}-{end_row})"
        # )

        current_matches = self.rowCount()
        if current_matches < self._filter_target_rows:
            source_model = self.sourceModel()
            while hasattr(source_model, "sourceModel") and source_model.sourceModel():
                source_model = source_model.sourceModel()
            self._load_next_filter_chunk(source_model)

    def setFilterRegularExpression(self, pattern):
        """
        Override to trigger intelligent data loading for filtering.

        When a filter is applied, we need to ensure that data is loaded
        for rows that might match the filter, not just currently visible rows.
        """
        # Convert string pattern to QRegularExpression if needed

        # Call the parent method with the QRegularExpression
        super().setFilterRegularExpression(pattern)

        # If we have a filter pattern, trigger intelligent data loading
        if pattern and pattern.strip():
            self._filter_loaded_end = 0
            self._check_filter_sufficiency()
        else:
            # If filter is cleared, the normal lazy loading will handle it
            pass

    def _trigger_intelligent_filtering(self):
        """
        Trigger intelligent data loading for filtering.

        This loads data in chunks until we have enough filtered results
        to display (target: 50 visible rows).
        """
        # Get the source model (CatalogTableModel)
        source_model = self.sourceModel()
        while hasattr(source_model, "sourceModel") and source_model.sourceModel():
            source_model = source_model.sourceModel()

        self._filter_loaded_end = 0  # Track how much data we've loaded

        # Start loading the first chunk
        self._load_next_filter_chunk(source_model)

    def _load_next_filter_chunk(self, source_model):
        """
        Load the next chunk of data for filtering.
        """
        total_rows = source_model.rowCount()
        if total_rows == 0:
            return

        start_row = self._filter_loaded_end
        if start_row >= total_rows:
            return

        end_row = min(start_row + self._filter_chunk_size - 1, total_rows - 1)

        if hasattr(source_model, "request_chunk_load"):
            source_model.request_chunk_load(start_row, end_row)
        elif hasattr(source_model, "set_visible_rows"):
            source_model.set_visible_rows(start_row, end_row)

        self._filter_loaded_end = end_row + 1
        print_debug(
            "FilterModel._load_next_filter_chunk",
            f"Loaded chunk {start_row}-{end_row}, "
            f"proxy rowCount={self.rowCount()} target={self._filter_target_rows}",
            category="DEBUG_RUNLIST",
        )

        # Schedule a check after the chunk loads

        QTimer.singleShot(1000, lambda: self._check_filter_sufficiency())

    def _check_filter_sufficiency(self):
        """
        Check if we have enough filter matches, and load more chunks if needed.
        This method will keep loading chunks until sufficient matches are found or
        we've exhausted the source model.
        """
        # Count current visible rows in the filtered model
        visible_count = self.rowCount()
        self._filter_loaded_end = max(self._filter_loaded_end, visible_count)
        pattern = self.filterRegularExpression().pattern()
        print_debug(
            "FilterModel._check_filter_sufficiency",
            f"proxy rowCount={visible_count} target={self._filter_target_rows} "
            f"loaded_end={self._filter_loaded_end} pattern={pattern!r}",
            category="DEBUG_RUNLIST",
        )

        if visible_count >= self._filter_target_rows:
            return

        # Get the source model
        source_model = self.sourceModel()
        while hasattr(source_model, "sourceModel") and source_model.sourceModel():
            source_model = source_model.sourceModel()

        total_rows = source_model.rowCount()
        # Check if we've loaded all available data
        if self._filter_loaded_end >= total_rows:
            # print(
            #    f"Filtering complete: loaded all {total_rows} rows, found {visible_count} matches"
            # )
            return

        # Load the next chunk
        # print(f"Need more data, loading next chunk from row {self._filter_loaded_end}")
        self._load_next_filter_chunk(source_model)


class LazyLoadingTableView(QTableView):
    """
    A custom QTableView that only loads data for visible rows.

    This view tracks which rows are visible and notifies the model
    to prioritize loading those rows.
    """

    def __init__(self, parent=None, buffer_size=50):
        """
        Initialize the lazy loading table view.

        Parameters
        ----------
        parent : QWidget, optional
            Parent widget
        """
        super().__init__(parent)
        self._buffer_size = buffer_size
        # Timer to avoid excessive updates during scrolling
        self._visible_rows_timer = QTimer(self)
        self._visible_rows_timer.setSingleShot(True)
        self._visible_rows_timer.timeout.connect(self._update_visible_rows)

        # Connect to scrolling signals
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # Update visible rows when the view becomes visible
        self._init_timer = QTimer(self)
        self._init_timer.setSingleShot(True)
        self._init_timer.timeout.connect(self._update_visible_rows)
        self._init_timer.start(500)  # Delay to ensure view is properly initialized

    def showEvent(self, event):
        """Handle show events to update visible rows when the view becomes visible."""
        super().showEvent(event)
        # Update visible rows when the view becomes visible
        self._update_visible_rows()

    def resizeEvent(self, event):
        """
        Handle resize events to update visible rows when the view is resized.

        Parameters
        ----------
        event : QResizeEvent
            The resize event
        """
        # Let the base class handle the resize first
        super().resizeEvent(event)

        # Update visible rows after resize
        self._update_visible_rows()

    def setModel(self, model):
        """
        Set the model for this view.

        Parameters
        ----------
        model : QAbstractItemModel
            The model to set
        """
        super().setModel(model)
        self._update_visible_rows()
        # Wait a bit for the view to be properly laid out before updating visible rows
        # QTimer.singleShot(100, self._update_visible_rows)

    def _on_scroll(self):
        """Handle scroll events by scheduling an update of visible rows."""
        # Delay the update to avoid excessive calls during rapid scrolling
        self._visible_rows_timer.start(100)  # 100ms delay

    def _update_visible_rows(self):
        """Update the model with the current visible row range."""
        if not self.model() or not self.isVisible():
            return

        # Get the visible row range
        first_visible = self.rowAt(0)
        if first_visible < 0:
            first_visible = 0

        # Get the last visible row
        viewport_height = self.viewport().height()
        last_visible = self.rowAt(viewport_height - 1)
        if last_visible < 0:
            if self.model().rowCount() > 0:
                last_visible = first_visible + self._buffer_size
            else:
                last_visible = 0

        first_visible = max(0, first_visible - self._buffer_size)
        last_visible = last_visible + self._buffer_size

        model = self.model()
        if not hasattr(model, "set_visible_rows"):
            return

        proxy_row_count = model.rowCount()
        if proxy_row_count > 0:
            last_visible = min(last_visible, proxy_row_count - 1)

        source_first = first_visible
        source_last = last_visible
        top_index = model.index(first_visible, 0)
        bottom_index = model.index(last_visible, 0)
        if top_index.isValid():
            source_top = top_index
            while hasattr(source_top.model(), "mapToSource"):
                source_top = source_top.model().mapToSource(source_top)
            source_first = source_top.row()
        if bottom_index.isValid():
            source_bottom = bottom_index
            while hasattr(source_bottom.model(), "mapToSource"):
                source_bottom = source_bottom.model().mapToSource(source_bottom)
            source_last = source_bottom.row()

        print_debug(
            "LazyLoadingTableView._update_visible_rows",
            f"proxy {first_visible}-{last_visible} -> source {source_first}-{source_last} "
            f"proxy rowCount={proxy_row_count}",
            category="DEBUG_RUNLIST",
        )

        model.set_visible_rows(first_visible, last_visible)

        source_model = model
        while hasattr(source_model, "sourceModel") and source_model.sourceModel():
            source_model = source_model.sourceModel()
        if source_model is not model:
            source_model.set_visible_rows(source_first, source_last)


class CatalogTableView(QWidget):
    """A widget for displaying and managing catalog data in a table view."""

    add_runs_to_display = Signal(list, str)

    def __init__(self, catalog, display_id, parent=None):
        """Initialize the CatalogTableView."""
        super().__init__(parent)
        self._catalog = catalog
        self.display_id = display_id
        self._metadata_browser_dialog = None
        self._handling_selection = False  # Flag to prevent circular updates
        self._is_inverted = False  # Track inversion state
        self._setup_ui()
        self.setup_context_menu()
        self.setupModelAndView()

    def setup_context_menu(self):
        self.data_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.data_view.customContextMenuRequested.connect(self.showContextMenu)

    def _setup_ui(self):
        """
        Set up the user interface components.
        """
        self.data_view = LazyLoadingTableView(self)
        data_header = CustomHeaderView(Qt.Horizontal, self.data_view)
        self.data_view.setHorizontalHeader(data_header)
        self.data_view.setSelectionBehavior(QTableView.SelectRows)
        self.data_view.setSelectionMode(QTableView.ExtendedSelection)

        # Enable context menu for the table view

        self.filter_list = []
        self.filter_list.append(DateSearchWidget(self))

        self.display_button = QPushButton("Update Catalog", self)
        self.display_button.clicked.connect(self.refresh_filters)

        self.invertButton = QPushButton("Reverse Data", self)
        self.invertButton.setEnabled(False)
        self.invertButton.clicked.connect(self._handle_invert)

        self.scrollToBottomButton = QPushButton("Scroll to Bottom", self)
        self.scrollToBottomButton.clicked.connect(self.data_view.scrollToBottom)

        self.scrollToTopButton = QPushButton("Scroll to Top", self)
        self.scrollToTopButton.clicked.connect(self.data_view.scrollToTop)

        self.filterLineEdit = QLineEdit(self)
        self.filterComboBox = QComboBox(self)

        filterLayout = QHBoxLayout()
        filterLayout.addWidget(QLabel("RegEx Filter"))
        filterLayout.addWidget(self.filterLineEdit)
        filterLayout.addWidget(self.filterComboBox)

        self.filterLineEdit2 = QLineEdit(self)
        self.filterComboBox2 = QComboBox(self)

        filterLayout2 = QHBoxLayout()
        filterLayout2.addWidget(QLabel("RegEx Filter 2"))
        filterLayout2.addWidget(self.filterLineEdit2)
        filterLayout2.addWidget(self.filterComboBox2)

        self.exitFilterCheckBox = QCheckBox(self)
        self.exitFilterCheckBox.setChecked(False)
        self.exitFilterCheckBox.stateChanged.connect(self.on_exit_filter_changed)
        exitFilterLayout = QHBoxLayout()
        exitFilterLayout.addWidget(QLabel("Exclude Unsuccessful Runs"))
        exitFilterLayout.addWidget(self.exitFilterCheckBox)

        scrollLayout = QHBoxLayout()
        scrollLayout.addWidget(self.scrollToTopButton)
        scrollLayout.addWidget(self.scrollToBottomButton)

        layout = QVBoxLayout()
        for widget in self.filter_list:
            layout.addWidget(widget)
        layout.addWidget(self.display_button)
        layout.addLayout(filterLayout)
        layout.addLayout(filterLayout2)
        layout.addLayout(exitFilterLayout)
        layout.addLayout(scrollLayout)
        layout.addWidget(self.invertButton)
        layout.addWidget(self.data_view)
        self.setLayout(layout)

    def on_exit_filter_changed(self, state):
        """
        Handle changes to the exit status filter checkbox.

        Parameters
        ----------
        state : int
            Checkbox state (0 = unchecked, 2 = checked)
        """
        # Get the third filter model (for exit status)
        filter_model3 = self.data_view.model()

        if state == 2:  # Checked - filter for successful runs only
            filter_model3.setFilterRegularExpression("success")
        else:  # Unchecked - clear the filter
            filter_model3.setFilterRegularExpression("")

    def on_selection_changed(self, selected, deselected):
        """Handle changes in the selection state of table rows."""
        print_debug(
            "CatalogTableView.on_selection_changed",
            f"Selection changed, selected: {len(selected.indexes())}, deselected: {len(deselected.indexes())}",
            "catalog",
        )
        if self._handling_selection:
            return

        # Get the source model using our utility method
        source_model = self.get_source_model()

        selected_keys = set()
        deselected_keys = set()
        # Handle newly selected items
        for index in selected.indexes():
            if index.column() == 0:  # Only process first column
                # Map through all proxy models to get source index
                source_index = self.map_to_source(index)
                key = source_model.get_key(source_index.row())
                if key is not None:
                    selected_keys.add(key)

        # Handle deselected items similarly
        for index in deselected.indexes():
            if index.column() == 0:
                source_index = self.map_to_source(index)
                key = source_model.get_key(source_index.row())
                if key is not None:
                    deselected_keys.add(key)
        self._catalog.update_selection(selected_keys, deselected_keys)

    def _handle_invert(self):
        """Handle inversion by clearing selection and toggling order."""
        # print("_handle_invert in CatalogTableView")
        # Clear any existing selection
        selection_model = self.data_view.selectionModel()
        if selection_model:
            selection_model.clearSelection()

        # Toggle inversion state
        self._is_inverted = not self._is_inverted

        # Get models
        filter_model3 = self.data_view.model()
        filter_model2 = filter_model3.sourceModel()
        filter_model = filter_model2.sourceModel()
        reverse_model = filter_model.sourceModel()
        reverse_model.toggleInvert()
        filter_model.invalidateFilter()
        filter_model2.invalidateFilter()
        filter_model3.invalidateFilter()
        self.data_view._update_visible_rows()

    def setupModelAndView(self):
        """
        Set up the table model and view with the given catalog.

        Parameters
        ----------
        catalog : Catalog
            The catalog to display in the table
        """
        # Create model chain: source -> reverse -> filter1 -> filter2 -> filter3
        catalog = self._catalog
        for f in self.filter_list:
            catalog = f.filter_catalog(catalog)
        table_model = CatalogTableModel(catalog)
        reverse_model = ReverseModel(parent=self.data_view)
        filter_model = FilterModel(parent=self.data_view)
        filter_model2 = FilterModel(parent=self.data_view)
        filter_model3 = FilterModel(parent=self.data_view)

        self.lowest_model = reverse_model
        # Connect models
        reverse_model.setSourceModel(table_model)
        filter_model.setSourceModel(reverse_model)
        filter_model2.setSourceModel(filter_model)
        filter_model3.setSourceModel(filter_model2)

        # Disconnect existing selection model if it exists
        if self.data_view.model() is not None:
            self.data_view.selectionModel().selectionChanged.disconnect()

        # Set the third filter model as the view's model
        self.data_view.setModel(filter_model3)
        self.data_view.selectionModel().selectionChanged.connect(
            self.on_selection_changed
        )

        # Connect filter controls to filter model
        self.filterLineEdit.textChanged.connect(filter_model.setFilterRegularExpression)
        self.filterLineEdit2.textChanged.connect(
            filter_model2.setFilterRegularExpression
        )
        self.filterComboBox.clear()
        self.filterComboBox.addItems([col for col in table_model.columns])
        self.filterComboBox.currentIndexChanged.connect(
            lambda index: filter_model.setFilterKeyColumn(index)
        )

        # Set default column for first filter to "Plan Name" if it exists
        if "Plan Name" in table_model.columns:
            plan_column_index = table_model.columns.index("Plan Name")
            self.filterComboBox.setCurrentIndex(plan_column_index)

        # Configure the second filter model (user-defined regex)
        self.filterComboBox2.clear()
        self.filterComboBox2.addItems([col for col in table_model.columns])
        self.filterComboBox2.currentIndexChanged.connect(
            lambda index: filter_model2.setFilterKeyColumn(index)
        )

        # Set default column for second filter to "Sample Name" if it exists
        if "Sample Name" in table_model.columns:
            sample_column_index = table_model.columns.index("Sample Name")
            self.filterComboBox2.setCurrentIndex(sample_column_index)

        # Configure the third filter model for exit status
        # Find the "Status" column index
        status_column_index = 0  # Default to first column
        if "Status" in table_model.columns:
            status_column_index = table_model.columns.index("Status")
        # Set the filter column to "Status" permanently
        filter_model3.setFilterKeyColumn(status_column_index)

        # Connect invert button to our handler instead
        self.invertButton.setEnabled(True)

        # Apply inversion state if needed
        if self._is_inverted:
            # Set the invert property on the reverse model
            reverse_model.toggleInvert()
            filter_model.invalidateFilter()
            filter_model2.invalidateFilter()
            filter_model3.invalidateFilter()
            self.data_view._update_visible_rows()

    def refresh_filters(self):
        selection_model = self.data_view.selectionModel()
        if selection_model:
            selection_model.clearSelection()
        catalog = self._catalog
        for f in self.filter_list:
            catalog = f.filter_catalog(catalog)

        # self.setupModelAndView(catalog)
        table_model = CatalogTableModel(catalog)
        self.lowest_model.setSourceModel(table_model)

        self.data_view._update_visible_rows()

        # Reconnect the selection model's signal after setting up the new model
        # self.data_view.selectionModel().selectionChanged.connect(
        #    self.on_selection_changed
        # )

    def get_selected_runs(self):
        """
        Get the currently selected runs.

        Returns
        -------
        list
            List of currently selected CatalogRun instances
        """
        print_debug(
            "CatalogTableView.get_selected_runs", "Getting selected items", "catalog"
        )
        return self._catalog.get_selected_runs()

    def deselect_items(self, items):
        """
        Deselect specific items from the view.

        Parameters
        ----------
        items : list
            List of CatalogRun instances to deselect
        """
        selection_model = self.data_view.selectionModel()
        if selection_model is None:
            return

        item_uids = [item.uid for item in items]
        source_model = self.get_source_model()

        try:
            self._handling_selection = True  # Set flag before making changes
            for index in self.data_view.selectedIndexes():
                if index.column() == 0:
                    # Map through all proxy models to get source index
                    source_index = self.map_to_source(index)

                    # Get key from source model
                    key = source_model.get_key(source_index.row())
                    if key in item_uids:
                        selection_model.select(
                            index,
                            QItemSelectionModel.Deselect | QItemSelectionModel.Rows,
                        )
        finally:
            self._handling_selection = False  # Always reset flag

    def deselect_all(self):
        """
        Deselect all items in both the view and catalog.

        This ensures synchronization between the view's selection state
        and the catalog's internal selection state.
        """
        # Clear the view's selection first
        all_items = self.get_selected_runs()
        self.deselect_items(all_items)
        # Then clear the catalog's selection
        # This will trigger item_deselected signals for each selected run
        self._catalog.clear_selection()

    def cleanup(self):
        """Clean up resources before removal."""
        # Clear all selections using our synchronized method
        self.deselect_all()

        # Disconnect signals
        if self.data_view.model() is not None:
            self.data_view.selectionModel().selectionChanged.disconnect()

        # Clear model
        self.data_view.setModel(None)

    def map_to_source(self, proxy_index):
        """
        Map an index from the view through all proxy models to the source model.

        Parameters
        ----------
        proxy_index : QModelIndex
            The index in the view's model

        Returns
        -------
        QModelIndex
            The corresponding index in the source model
        """
        if not proxy_index.isValid():
            return QModelIndex()

        source_index = proxy_index
        current_model = self.data_view.model()

        while hasattr(current_model, "mapToSource"):
            source_index = current_model.mapToSource(source_index)
            current_model = current_model.sourceModel()

        return source_index

    def map_from_source(self, source_index):
        """
        Map an index from the source model through all proxy models to the view.

        Parameters
        ----------
        source_index : QModelIndex
            The index in the source model

        Returns
        -------
        QModelIndex
            The corresponding index in the view's model
        """
        if not source_index.isValid():
            return QModelIndex()

        # Get the chain of models from view to source
        model_chain = []
        current_model = self.data_view.model()

        while hasattr(current_model, "sourceModel"):
            model_chain.append(current_model)
            current_model = current_model.sourceModel()

        # Map from source through each proxy model in reverse order
        proxy_index = source_index
        for model in reversed(model_chain):
            proxy_index = model.mapFromSource(proxy_index)

        return proxy_index

    def get_source_model(self):
        """
        Get the source model at the bottom of the proxy chain.

        Returns
        -------
        QAbstractItemModel
            The source model (typically CatalogTableModel)
        """
        model = self.data_view.model()

        while hasattr(model, "sourceModel"):
            source_model = model.sourceModel()
            if not hasattr(source_model, "sourceModel"):
                return source_model
            model = source_model

        return model

    def showContextMenu(self, pos):
        """
        Show context menu for run management.

        Parameters
        ----------
        pos : QPoint
            Position where the context menu should appear
        """
        # Get the index at the clicked position
        index = self.data_view.indexAt(pos)
        if not index.isValid():
            return

        # Get selected runs
        selected_runs = self.get_selected_runs()
        if not selected_runs:
            return
        clicked_run = self.get_run_at_index(index)
        if clicked_run is None:
            clicked_run = selected_runs[0]

        menu = QMenu(self)
        app_model = get_top_level_model()
        # Add to new display
        if self.display_id != "main":
            new_canvas_menu = QMenu("Move to New Display", self)
            display_types = app_model.display_manager.get_available_display_types()
            for display_type in display_types:
                metadata = app_model.display_manager.get_display_metadata(display_type)
                display_name = metadata.get("name", display_type)
                action = QAction(display_name, self)
                action.setToolTip(
                    f"Create a new {display_type} display and move selected runs to it"
                )
                action.triggered.connect(
                    lambda checked, name=display_type: self.move_selected_runs_to_new_display(
                        name
                    )
                )
                new_canvas_menu.addAction(action)
            menu.addMenu(new_canvas_menu)

        new_canvas_copy_menu = QMenu("Copy to New Display", self)
        display_types = app_model.display_manager.get_available_display_types()
        # Remove the current display from the list
        for display_type in display_types:
            metadata = app_model.display_manager.get_display_metadata(display_type)
            display_name = metadata.get("name", display_type)
            action = QAction(display_name, self)
            action.setToolTip(
                f"Create a new {display_type} display and copy selected runs to it"
            )
            action.triggered.connect(
                lambda checked, name=display_type: self.copy_selected_runs_to_new_display(
                    name
                )
            )
            new_canvas_copy_menu.addAction(action)
        menu.addMenu(new_canvas_copy_menu)
        browse_action = QAction("Browse Metadata", self)
        browse_action.setToolTip("Open metadata browser for this run")
        browse_action.triggered.connect(
            lambda checked=False, run=clicked_run, runs=selected_runs: self._browse_metadata_for_run(
                run, runs
            )
        )
        menu.addAction(browse_action)
        menu.addSeparator()
        # Add submenu for existing displays
        available_displays = app_model.display_manager.get_display_ids()
        # Remove the current display from the list
        available_displays = [
            d for d in available_displays if d not in [self.display_id, "main"]
        ]
        if available_displays:
            if self.display_id != "main":
                move_menu = QMenu("Move to Display", self)
                for display_name in available_displays:
                    action = QAction(display_name, self)
                    action.setToolTip(f"Move selected runs to {display_name}")
                    action.triggered.connect(
                        lambda checked, name=display_name: self.move_selected_runs_to_display(
                            name
                        )
                    )
                    move_menu.addAction(action)
                menu.addMenu(move_menu)

            move_menu = QMenu("Copy to Display", self)
            for display_name in available_displays:
                action = QAction(display_name, self)
                action.setToolTip(f"Copy selected runs to {display_name}")
                action.triggered.connect(
                    lambda checked, name=display_name: self.copy_selected_runs_to_display(
                        name
                    )
                )
                move_menu.addAction(action)
            menu.addMenu(move_menu)

        # Remove from current display
        remove_action = QAction("Clear Selection", self)
        remove_action.triggered.connect(self.deselect_all)
        menu.addAction(remove_action)

        menu.exec_(self.data_view.mapToGlobal(pos))
        # Deselect the runs (this will remove them from the current display)

    def get_run_at_index(self, index):
        """
        Get run object for a clicked table index.

        Parameters
        ----------
        index : QModelIndex
            View index from the table

        Returns
        -------
        CatalogRun or None
            Run for the clicked row, if available
        """
        if not index.isValid():
            return None
        source_model = self.get_source_model()
        source_index = self.map_to_source(index)
        if not source_index.isValid():
            return None
        key = source_model.get_key(source_index.row())
        if key is None:
            return None
        try:
            return self._catalog.get_run(key)
        except Exception:
            return None

    def _browse_metadata_for_run(self, run, runs):
        if run is None:
            return
        browse_runs = runs if runs else [run]
        self._metadata_browser_dialog = FullMetadataBrowser(
            browse_runs, selected_run=run, parent=self
        )
        self._metadata_browser_dialog.show()
        self._metadata_browser_dialog.raise_()
        self._metadata_browser_dialog.activateWindow()

    def move_selected_runs_to_new_display(self, display_type: str):
        self.copy_selected_runs_to_new_display(display_type)
        self.deselect_all()

    def copy_selected_runs_to_new_display(self, display_type: str):
        top_level_model = get_top_level_model()
        runs = self.get_selected_runs()
        top_level_model.display_manager.create_display_with_runs(runs, display_type)

    def move_selected_runs_to_display(self, display_id: str):
        self.copy_selected_runs_to_display(display_id)
        self.deselect_all()

    def copy_selected_runs_to_display(self, display_id: str):
        runs = self.get_selected_runs()
        top_level_model = get_top_level_model()
        top_level_model.display_manager.add_runs_to_display(runs, display_id)
