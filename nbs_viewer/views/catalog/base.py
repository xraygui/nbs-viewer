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
    Signal,
    QSortFilterProxyModel,
    QItemSelectionModel,
    QModelIndex,
)

from ...models.catalog.table import CatalogTableModel
from ...models.plot.runModel import RunModel
from ...search import DateSearchWidget
from ...models.plot.runData import RunData


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
        Returns the name of the column at the specified index in the given QTableView.

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

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        index = model.index(source_row, self.filterKeyColumn(), source_parent)
        data = model.data(index, Qt.DisplayRole)
        if data is None:
            return False

        # Convert data to string if it's not already one
        data_str = str(data)
        regex = self.filterRegExp()
        match = regex.indexIn(data_str) != -1
        # print(f"Row {source_row}, Data: {data_str}, Match: {match}")
        return match

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
        self.invalidateFilter()  # Use invalidateFilter instead of invalidate
        self.layoutChanged.emit()  # Notify views that layout has changed


class CatalogTableView(QWidget):
    """A widget for displaying and managing catalog data in a table view."""

    # Update signals to handle individual selections
    itemSelected = Signal(object)  # (RunData)
    itemDeselected = Signal(object)  # (RunData)
    selectionChanged = Signal(list)  # (List[RunData])

    def __init__(self, catalog, parent=None):
        """Initialize the CatalogTableView."""
        super().__init__(parent)
        self._catalog = catalog
        self._run_data = {}  # uid -> RunData
        self._dynamic = False
        self._setup_ui()
        self.refresh_filters()

    def _setup_ui(self):
        """
        Set up the user interface components.
        """
        self.data_view = QTableView(self)
        data_header = CustomHeaderView(Qt.Horizontal, self.data_view)
        self.data_view.setHorizontalHeader(data_header)
        self.data_view.setSelectionBehavior(QTableView.SelectRows)
        self.data_view.setSelectionMode(QTableView.ExtendedSelection)

        self.filter_list = []
        self.filter_list.append(DateSearchWidget(self))

        self.display_button = QPushButton("Display Selection", self)
        self.display_button.clicked.connect(self.refresh_filters)

        self.invertButton = QPushButton("Reverse Data", self)
        self.invertButton.setEnabled(False)

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
        proxy_model = self.data_view.model()
        source_model = proxy_model.sourceModel()

        selected_runs = []
        # Handle newly selected items
        for index in selected.indexes():
            if index.column() == 0:  # Only process first column
                source_index = proxy_model.mapToSource(index)
                key = source_model.get_key(source_index.row())
                if key is not None:
                    if key not in self._run_data:
                        data = self._catalog.get_run(key)
                        self._run_data[key] = RunData(data, dynamic=self._dynamic)
                    selected_runs.append(self._run_data[key])
                    self.itemSelected.emit(self._run_data[key])
        self.selectionChanged.emit(selected_runs)

        # Handle newly deselected items
        for index in deselected.indexes():
            if index.column() == 0:  # Only process first column
                source_index = proxy_model.mapToSource(index)
                key = source_model.get_key(source_index.row())
                if key is not None and key in self._run_data:
                    self.itemDeselected.emit(self._run_data[key])

    def setupModelAndView(self, catalog):
        """
        Set up the table model and view with the given catalog.

        Parameters
        ----------
        catalog : Catalog
            The catalog to display in the table
        """
        table_model = CatalogTableModel(catalog)
        reverse = ReverseModel()
        reverse.setSourceModel(table_model)

        # Disconnect existing selection model if it exists
        if self.data_view.model() is not None:
            self.data_view.selectionModel().selectionChanged.disconnect()

        self.data_view.setModel(reverse)
        self.data_view.selectionModel().selectionChanged.connect(
            self.on_selection_changed
        )

        self.filterLineEdit.textChanged.connect(reverse.setFilterRegExp)

        self.filterComboBox.clear()
        self.filterComboBox.addItems([col for col in table_model.columns])
        self.filterComboBox.currentIndexChanged.connect(
            lambda index: reverse.setFilterKeyColumn(index)
        )

        self.invertButton.clicked.connect(reverse.toggleInvert)
        self.invertButton.setEnabled(True)

    def refresh_filters(self):
        catalog = self._catalog
        for f in self.filter_list:
            catalog = f.filter_catalog(catalog)
        self.setupModelAndView(catalog)
        # Reconnect the selection model's signal after setting up the new model
        self.data_view.selectionModel().selectionChanged.connect(
            self.on_selection_changed
        )
        print("Reconnected selectionChanged signal after refresh")

    def get_selected_items(self):
        """
        Get the currently selected RunData instances.

        Returns
        -------
        list
            List of currently selected RunData instances
        """
        proxy_model = self.data_view.model()
        if proxy_model is None:
            return []

        source_model = proxy_model.sourceModel()
        selected_data = []

        for index in self.data_view.selectedIndexes():
            if index.column() == 0:
                source_index = proxy_model.mapToSource(index)
                key = source_model.get_key(source_index.row())
                if key is not None:
                    if key not in self._run_data:
                        data = self._catalog.get_run(key)
                        self._run_data[key] = RunData(data, dynamic=self._dynamic)
                    selected_data.append(self._run_data[key])

        return selected_data

    def deselect_items(self, items):
        """
        Deselect specific items from the view.

        Parameters
        ----------
        items : list
            List of RunData instances to deselect
        """
        selection_model = self.data_view.selectionModel()
        if selection_model is None:
            return

        item_uids = [item.run.uid for item in items]

        for index in self.data_view.selectedIndexes():
            if index.column() == 0:
                source_index = self.data_view.model().mapToSource(index)
                key = source_index.model().get_key(source_index.row())
                if key in item_uids:
                    selection_model.select(
                        index, QItemSelectionModel.Deselect | QItemSelectionModel.Rows
                    )
