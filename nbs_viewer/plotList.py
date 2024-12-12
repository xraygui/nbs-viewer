from qtpy.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QAbstractItemView,
    QInputDialog,
)
from qtpy.QtCore import Qt, Signal
from .plotItem import CompoundPlotItem


class BlueskyListWidget(QWidget):
    """
    A widget for displaying Bluesky Runs in a list.

    Signals
    -------
    itemsSelected : Signal
        Emitted when items are selected in the list.
    itemsDeselected : Signal
        Emitted when items are deselected in the list.
    itemsRemoved : Signal
        Emitted when items are removed from the list.
    itemVisibilityChanged : Signal
        Emitted when an item's visibility is toggled.
    """

    itemsSelected = Signal(list)
    itemsDeselected = Signal(list)
    itemsRemoved = Signal(list)
    itemVisibilityChanged = Signal(object, bool)

    def __init__(self, parent=None):
        """
        Initialize the BlueskyListWidget.

        Parameters
        ----------
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)

        self.list_widget = QListWidget(self)
        size_policy = self.list_widget.sizePolicy()
        size_policy.setHorizontalPolicy(QSizePolicy.Minimum)
        self.list_widget.setSizePolicy(size_policy)
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.selectionModel().selectionChanged.connect(
            self.handle_selection_change
        )
        self.list_widget.itemChanged.connect(self.handle_item_changed)

        self._plotItems = {}
        self._temp_plotItems = {}  # New temporary dictionary for selected items

        self.remove_items_button = QPushButton("Remove Items")
        self.remove_items_button.clicked.connect(self.removeSelectedItems)

        self.combine_items_button = QPushButton("Combine Items")
        self.combine_items_button.clicked.connect(self.combineSelectedItems)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.remove_items_button)
        button_layout.addWidget(self.combine_items_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list_widget)
        layout.addLayout(button_layout)

    def addPlotItem(self, plotItem):
        """
        Add a run or multiple runs to the list widget.

        Parameters
        ----------
        plotItem : PlotItem or list of PlotItem
            The plot item(s) to be added to the list widget.
        """
        if isinstance(plotItem, (list, tuple)):
            for p in plotItem:
                self._addSinglePlotItem(p)
        else:
            self._addSinglePlotItem(plotItem)

    def _addSinglePlotItem(self, plotItem):
        # print("Adding bluesky plot item")
        item = QListWidgetItem(plotItem.description)
        item.setData(Qt.UserRole, plotItem.uid)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self._plotItems[plotItem.uid] = plotItem
        self.list_widget.addItem(item)
        # print("Done adding bluesky plot item")

    def removePlotItem(self, plotItem):
        """
        Remove a plot item from the list widget based on its UID.

        Parameters
        ----------
        plotItem : PlotItem
            The plot item to be removed from the list widget.
        """
        # print("Removing Plot Item from BlueskyList")
        plotItem.clear()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == plotItem.uid:
                self.list_widget.takeItem(i)
                if plotItem.uid in self._plotItems:
                    del self._plotItems[plotItem.uid]
                break

    def handle_selection_change(self, selected, deselected):
        items_for_selection = self.selectedData()
        items_for_deselection = [
            self._plotItems[self.list_widget.itemFromIndex(index).data(Qt.UserRole)]
            for index in deselected.indexes()
        ]
        self.itemsSelected.emit(items_for_selection)
        self.itemsDeselected.emit(items_for_deselection)

    def selectedData(self):
        selected_items = self.list_widget.selectedItems()
        return [self._plotItems[item.data(Qt.UserRole)] for item in selected_items]

    def removeSelectedItems(self):
        items = self.selectedData()
        for plotItem in items:
            self.removePlotItem(plotItem)
        self.itemsRemoved.emit(items)
        return items

    def combineSelectedItems(self):
        selected_items = self.selectedData()
        if len(selected_items) < 2:
            # Optionally, show a message to the user that at least 2 items must be selected
            return

        label, ok = QInputDialog.getText(
            self, "Combine Items", "Enter a label for the combined item:"
        )
        if ok and label:
            compound_item = CompoundPlotItem(selected_items, label)
            self.addPlotItem(compound_item)

    def handle_item_changed(self, item):
        """
        Handle changes to list items, specifically checkbox state changes.

        Parameters
        ----------
        item : QListWidgetItem
            The item that changed
        """
        plot_item = self._plotItems[item.data(Qt.UserRole)]
        is_visible = item.checkState() == Qt.Checked
        plot_item.setVisible(is_visible)
        self.itemVisibilityChanged.emit(plot_item, is_visible)
