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
from qtpy.QtCore import Qt, Signal, QSortFilterProxyModel, QItemSelectionModel

from .catalogTable import CatalogTableModel
from .plotItem import PlotItem
from .search import DateSearchWidget


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
            # print(f"Row {source_row} has None data, skipping.")
            return False  # Optionally, decide how to handle None data

        # Convert data to string if it's not already one
        data_str = str(data)
        regex = self.filterRegExp()
        match = regex.indexIn(data_str) != -1
        # print(f"Row {source_row}, Data: {data_str}, Match: {match}")
        return match

    def mapFromSource(self, index):
        if not self.invert:
            filteredIndex = super().mapFromSource(index)
            # if index.column() == 0:
            #    print(f"Mapping {index.row()}")
            #    print(f"From {filteredIndex.row()}")
            return filteredIndex
        else:
            # print("Calling mapFromSource inverted... not sure why")
            model = self.sourceModel()
            newRow = model._catalog_length - index.row() - 1
            newIndex = model.index(newRow, index.column())
            return newIndex

    def mapToSource(self, index):
        if not self.invert:
            filteredIndex = super().mapToSource(index)
            # if index.column() == 0:
            #     print(f"Mapping {index.row()}")
            #     print(f"To {filteredIndex.row()}")
            #     print(f"Total rows: {self.rowCount()}")
            return filteredIndex
        else:
            if index.row() == -1:
                return super().mapToSource(index)
            newRow = self.rowCount() - index.row() - 1
            newIndex = self.index(newRow, index.column())
            filteredIndex = super().mapToSource(newIndex)
            return filteredIndex

    def toggleInvert(self):
        """
        Toggle the inversion of row order and refresh the view.
        """
        self.invert = not self.invert
        self.sourceModel()._invert = self.invert
        self.invalidate()  # This will refresh the view


class CatalogTableView(QWidget):
    itemsSelected = Signal(list)
    itemsDeselected = Signal(list)

    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        print("Creating CatalogTableView")
        self.parent_catalog = catalog
        self.plot_items = {}
        self.data_view = QTableView(self)
        data_header = CustomHeaderView(Qt.Horizontal, self.data_view)
        self.data_view.setHorizontalHeader(data_header)
        self.data_view.setSelectionBehavior(QTableView.SelectRows)

        self.filter_list = []
        self.filter_list.append(DateSearchWidget(self))
        # self.filter_list.append(ScantypeSearch(self))
        self.display_button = QPushButton("Display Selection", self)
        self.display_button.clicked.connect(self.refresh_filters)
        self.invertButton = QPushButton("Reverse Data", self)
        self.invertButton.setEnabled(False)  # Enable the invertButton

        self.scrollToBottomButton = QPushButton("Scroll to Bottom", self)
        self.scrollToBottomButton.clicked.connect(self.data_view.scrollToBottom)

        self.scrollToTopButton = QPushButton("Scroll to Top", self)
        self.scrollToTopButton.clicked.connect(self.data_view.scrollToTop)

        # Add filter text box and drop-down
        self.filterLineEdit = QLineEdit(self)
        self.filterComboBox = QComboBox(self)

        # Create a horizontal layout for the filter widgets
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

        # Setup the model and filtering
        self.refresh_filters()
        print("Setting up selectionModel")
        self.data_view.selectionModel().selectionChanged.connect(
            self.on_selection_changed
        )

    def on_selection_changed(self, selected, deselected):
        print("Selection Changed!")
        print("Selected indices:", selected.indexes())
        print("Deselected indices:", deselected.indexes())
        new_plot_keys = []
        # for index in deselected.indexes():
        #     if index.column() == 0:
        #         model = self.data_view.model().sourceModel()
        #         key = model.get_key(index.row())
        #         print(f"Deselecting {key}")
        #         if key is not None and key in self.plot_items:
        #             plot_item = self.plot_items.pop(key)
        #             print(f"Removing Data {key} from inside catalogView, {plot_item}")
        #             plot_item.removeData()

        proxy_model = self.data_view.model()
        source_model = proxy_model.sourceModel()

        for index in selected.indexes():
            if index.column() == 0:  # We still check for column 0 to avoid duplicates
                source_index = proxy_model.mapToSource(index)
                key = source_model.get_key(source_index.row())
                if key is not None and key not in self.plot_items:
                    new_plot_keys.append(key)
                    data = self.parent_catalog[key]
                    self.plot_items[key] = PlotItem(data)
                elif key in self.plot_items:
                    new_plot_keys.append(key)

        oldkeys = list(self.plot_items.keys())
        for key in oldkeys:
            if key not in new_plot_keys:
                plot_item = self.plot_items.pop(key)
                plot_item.removeData()

        items_selected = list(self.plot_items.values())
        print(items_selected)
        self.itemsSelected.emit(items_selected)

    def deselect_items(self, items):
        selection_model = self.data_view.selectionModel()
        for index in self.data_view.selectedIndexes():
            if index.column() == 0:
                model = self.data_view.model().sourceModel()
                key = model.get_key(index.row())
                if key in [item.uid for item in items]:
                    selection_model.select(index, QItemSelectionModel.Deselect)

    def get_selected_items(self):
        return list(self.plot_items.values())

    def setupModelAndView(self, catalog):
        table_model = CatalogTableModel(catalog)
        reverse = ReverseModel()
        reverse.setSourceModel(table_model)
        self.data_view.setModel(reverse)

        # Connect filter line edit to set filter regexp
        self.filterLineEdit.textChanged.connect(reverse.setFilterRegExp)

        # Populate and connect the combo box for selecting filter column
        self.filterComboBox.clear()  # Clear the filterComboBox of any items
        self.filterComboBox.addItems([col for col in table_model.columns])
        self.filterComboBox.currentIndexChanged.connect(
            lambda index: reverse.setFilterKeyColumn(index)
        )
        self.invertButton.clicked.connect(reverse.toggleInvert)
        self.invertButton.setEnabled(True)

    def refresh_filters(self):
        catalog = self.parent_catalog
        for f in self.filter_list:
            catalog = f.filter_catalog(catalog)
        self.setupModelAndView(catalog)
        # Reconnect the selection model's signal after setting up the new model
        self.data_view.selectionModel().selectionChanged.connect(
            self.on_selection_changed
        )
        print("Reconnected selectionChanged signal after refresh")
