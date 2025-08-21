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


class FilterModel(QSortFilterProxyModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDynamicSortFilter(True)

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        source_index = model.index(source_row, self.filterKeyColumn(), source_parent)

        # Get data directly from source model - don't map through proxy
        data = model.data(source_index, Qt.DisplayRole)
        if data is None:
            return False

        data_str = str(data)
        regex = self.filterRegExp()
        return regex.indexIn(data_str) != -1


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
                last_visible = min(
                    first_visible + self._buffer_size, self.model().rowCount() - 1
                )
            else:
                last_visible = 0

        # Add a buffer of rows above and below for smoother scrolling
        first_visible = max(0, first_visible - self._buffer_size)
        last_visible = min(
            self.model().rowCount() - 1, last_visible + self._buffer_size
        )

        # Find the source model (CatalogTableModel)
        source_model = self.model()
        while hasattr(source_model, "sourceModel") and source_model.sourceModel():
            source_model = source_model.sourceModel()

        # If the source model has a set_visible_rows method, call it
        if hasattr(source_model, "set_visible_rows"):
            source_model.set_visible_rows(first_visible, last_visible)


class CatalogTableView(QWidget):
    """A widget for displaying and managing catalog data in a table view."""

    add_runs_to_display = Signal(list, str)

    def __init__(self, catalog, display_id, parent=None):
        """Initialize the CatalogTableView."""
        super().__init__(parent)
        self._catalog = catalog
        self.display_id = display_id
        self._handling_selection = False  # Flag to prevent circular updates
        self._is_inverted = False  # Track inversion state
        self._setup_ui()
        self.setup_context_menu()
        self.refresh_filters()

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

        self.display_button = QPushButton("Display Selection", self)
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

        scrollLayout = QHBoxLayout()
        scrollLayout.addWidget(self.scrollToTopButton)
        scrollLayout.addWidget(self.scrollToBottomButton)

        layout = QVBoxLayout()
        for widget in self.filter_list:
            layout.addWidget(widget)
        layout.addWidget(self.display_button)
        layout.addLayout(filterLayout)
        layout.addLayout(scrollLayout)
        layout.addWidget(self.invertButton)
        layout.addWidget(self.data_view)
        self.setLayout(layout)

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

        # Handle newly selected items
        for index in selected.indexes():
            if index.column() == 0:  # Only process first column
                # Map through all proxy models to get source index
                source_index = self.map_to_source(index)
                key = source_model.get_key(source_index.row())
                if key is not None:
                    self._catalog.select_run(key)

        # Handle deselected items similarly
        for index in deselected.indexes():
            if index.column() == 0:
                source_index = self.map_to_source(index)
                key = source_model.get_key(source_index.row())
                if key is not None:
                    self._catalog.deselect_run(key)

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
        filter_model = self.data_view.model()
        reverse_model = filter_model.sourceModel()
        reverse_model.toggleInvert()
        filter_model.invalidateFilter()
        self.data_view._update_visible_rows()

    def setupModelAndView(self, catalog):
        """
        Set up the table model and view with the given catalog.

        Parameters
        ----------
        catalog : Catalog
            The catalog to display in the table
        """
        # Create model chain: source -> reverse -> filter
        table_model = CatalogTableModel(catalog)
        reverse_model = ReverseModel(parent=self.data_view)
        filter_model = FilterModel(parent=self.data_view)

        # Connect models
        reverse_model.setSourceModel(table_model)
        filter_model.setSourceModel(reverse_model)

        # Disconnect existing selection model if it exists
        if self.data_view.model() is not None:
            self.data_view.selectionModel().selectionChanged.disconnect()

        # Set the filter model as the view's model
        self.data_view.setModel(filter_model)
        self.data_view.selectionModel().selectionChanged.connect(
            self.on_selection_changed
        )

        # Connect filter controls to filter model
        self.filterLineEdit.textChanged.connect(filter_model.setFilterRegExp)
        self.filterComboBox.clear()
        self.filterComboBox.addItems([col for col in table_model.columns])
        self.filterComboBox.currentIndexChanged.connect(
            lambda index: filter_model.setFilterKeyColumn(index)
        )

        # Connect invert button to our handler instead
        self.invertButton.setEnabled(True)

        # Apply inversion state if needed
        if self._is_inverted:
            # Set the invert property on the reverse model
            reverse_model.toggleInvert()
            filter_model.invalidateFilter()
            self.data_view._update_visible_rows()

    def refresh_filters(self):
        catalog = self._catalog
        for f in self.filter_list:
            catalog = f.filter_catalog(catalog)

        self.setupModelAndView(catalog)

        # Reconnect the selection model's signal after setting up the new model
        self.data_view.selectionModel().selectionChanged.connect(
            self.on_selection_changed
        )

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
