from qtpy.QtWidgets import (
    QHeaderView,
    QMenu,
    QAction,
    QTableView,
    QWidget,
    QVBoxLayout,
    QPushButton,
)
from qtpy.QtCore import Qt, Signal, QSortFilterProxyModel
from .catalogTable import CatalogTableModel
from .plotItem import PlotItem
from .search import DateSearchWidget, ScantypeSearch


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
        self.invert = True
        super().__init__(*args, **kwargs)

    def mapFromSource(self, index):
        if self.invert:
            model = self.sourceModel()
            newRow = model.rowCount() - index.row()
            newIndex = model.createIndex(newRow, index.column())
            return newIndex
        else:
            return index

    def mapToSource(self, index):
        if self.invert:
            model = self.sourceModel()
            newRow = model.rowCount() - index.row()
            newIndex = model.createIndex(newRow, index.column())
            return newIndex
        else:
            return index


class CatalogTableView(QWidget):
    add_rows_current_plot = Signal(object)
    add_rows_new_plot = Signal(object)

    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.parent_catalog = catalog
        self.filter_list = []
        self.filter_list.append(DateSearchWidget(self))
        self.filter_list.append(ScantypeSearch(self))
        self.display_button = QPushButton("Display Selection", self)
        self.display_button.clicked.connect(self.refresh_filters)
        self.plot_button1 = QPushButton("Add Data to Current Plot", self)
        self.plot_button1.clicked.connect(self.emit_add_rows)

        self.data_view = QTableView(self)
        data_header = CustomHeaderView(Qt.Horizontal, self.data_view)
        self.data_view.setHorizontalHeader(data_header)
        self.data_view.setSelectionBehavior(QTableView.SelectRows)

        layout = QVBoxLayout()
        for widget in self.filter_list:
            layout.addWidget(widget)
        layout.addWidget(self.display_button)
        layout.addWidget(self.data_view)
        layout.addWidget(self.plot_button1)
        self.setLayout(layout)

    def rows_selected(self, selected, deselected):
        selected_rows = selected.indexes()
        if len(selected_rows) > 0:
            self.plot_button1.setEnabled(True)
        else:
            self.plot_button1.setEnabled(False)

    def emit_add_rows(self):
        selected_rows = self.data_view.selectionModel().selectedRows()
        selected_data = []
        for index in selected_rows:
            if index.column() == 0:  # Check if the column is 0
                key = index.data()  # Get the key from the cell data
                data = self.parent_catalog[key]  # Fetch the data using the key
                selected_data.append(PlotItem(data))
        self.add_rows_current_plot.emit(selected_data)

    def refresh_filters(self):
        catalog = self.parent_catalog
        for f in self.filter_list:
            catalog = f.filter_catalog(catalog)
        # add some intelligent cache via UIDs?
        table_model = CatalogTableModel(catalog)
        self.data_view.setModel(table_model)
        # reverse = ReverseModel()
        # reverse.setSourceModel(table_model)
        # self.data_view.setModel(reverse)
        self.data_view.selectionModel().selectionChanged.connect(self.rows_selected)
