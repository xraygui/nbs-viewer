from qtpy.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QFrame,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QLineEdit,
    QAbstractItemView,
)
from qtpy.QtCore import Qt, Signal

# from pyqtgraph import PlotWidget

from .plotItem import PlotItem
from .plotCanvas import PlotWidget


class BlueskyListWidget(QListWidget):
    """
    A widget for displaying Bluesky Runs in a list.

    Signals
    -------
    selectedDataChanged : Signal
        Emitted when the selected data in the list changes. Emits a list of
        (text, BlueskyRun) tuples based on the selected list items.
    """

    itemsSelected = Signal(list)
    itemsDeselected = Signal(list)

    def __init__(self, parent=None):
        """
        Initialize the BlueskyListWidget.

        Parameters
        ----------
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)

        sizePolicy = self.sizePolicy()
        sizePolicy.setHorizontalPolicy(QSizePolicy.Minimum)
        # sizePolicy.setVerticalPolicy(QSizePolicy.Minimum)
        self.setSizePolicy(sizePolicy)
        self.selectionModel().selectionChanged.connect(self.handle_selection_change)
        self.setSelectionMode(
            QAbstractItemView.ExtendedSelection
        )  # Enable multiple item selection

        # self.itemSelectionChanged.connect(self.emit_selected_data)
        self._plotItems = {}

    def addPlotItem(self, plotItem):
        """
        Add a run or multiple runs to the list widget.

        Parameters
        ----------
        blueskyrun : BlueskyRun or list/tuple of BlueskyRun
            The run(s) to be added to the list widget.
        """
        if isinstance(plotItem, (list, tuple)):
            for p in plotItem:
                self.addPlotItem(p)
        else:
            item = QListWidgetItem(plotItem.description)
            item.setData(Qt.UserRole, plotItem.uid)
            # item.setData(Qt.UserRole, blueskyrun)
            self._plotItems[plotItem.uid] = plotItem
            self.addItem(item)

    def removePlotItem(self, plotItem):
        """
        Remove a plot item from the list widget based on its UID.

        Parameters
        ----------
        plotItem : PlotItem
            The plot item to be removed from the list widget.
        """
        plotItem.clear()
        # Iterate over all items in the list
        for i in range(self.count()):
            item = self.item(i)
            # Check if the item's UID matches the plotItem's UID
            if item.data(Qt.UserRole) == plotItem.uid:
                # Remove the item from the list
                self.takeItem(i)
                # Optionally, delete the plotItem from the internal dictionary if it's being tracked
                if plotItem.uid in self._plotItems:
                    del self._plotItems[plotItem.uid]
                break  # Exit the loop once the item is found and removed

    def handle_selection_change(self, selected, deselected):
        items_for_selection = self.selectedData()

        items_for_deselection = []
        for index in deselected.indexes():
            item = self.itemFromIndex(index)
            plotItem = self._plotItems[item.data(Qt.UserRole)]
            items_for_deselection.append(plotItem)
        self.itemsSelected.emit(items_for_selection)
        self.itemsDeselected.emit(items_for_deselection)

    def selectedData(self):
        # print("Selecting Data")
        selected_items = self.selectedItems()
        items_for_emission = [
            self._plotItems[item.data(Qt.UserRole)] for item in selected_items
        ]
        return items_for_emission

    def removeSelectedItems(self):
        items = self.selectedData()
        for plotItem in items:
            self.removePlotItem(plotItem)


class ExclusiveCheckBoxGroup(QButtonGroup):
    def __init__(self, parent=None):
        super(ExclusiveCheckBoxGroup, self).__init__(parent)
        self.setExclusive(False)  # This allows checkboxes to be unchecked

    def addButton(self, checkbox, id=-1):
        super().addButton(checkbox, id)
        checkbox.clicked.connect(self.enforce_exclusivity)

    def enforce_exclusivity(self, checked):
        if checked:
            clicked_checkbox = self.sender()
            for checkbox in self.buttons():
                if checkbox is not clicked_checkbox:
                    checkbox.setChecked(False)


class MutuallyExclusiveCheckBoxGroups(QWidget):
    buttonsChanged = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(**kwargs)
        self.buttonGroups = args
        for group in self.buttonGroups:
            group.buttonClicked.connect(self.uncheckOtherGroups)

    def addGroup(self, buttonGroup):
        self.buttonGroups.append(buttonGroup)
        buttonGroup.buttonClicked.connect(self.uncheckOtherGroups)

    def uncheckOtherGroups(self, clickedButton):
        for group in self.buttonGroups:
            if clickedButton not in group.buttons():
                defaultExclusivity = group.exclusive()
                group.setExclusive(False)
                for button in group.buttons():
                    button.setChecked(False)
                group.setExclusive(defaultExclusivity)
        self.buttonsChanged.emit()


class DataDisplayWidget(QWidget):
    """
    The main organizing widget that combines a plot, a list of Bluesky runs,
    and controls to add runs to the plot.

    Parameters
    ----------
    parent : QWidget, optional
        The parent widget, by default None.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.plot_widget = PlotWidget()
        self.controls = PlotControls(self.plot_widget)
        vlayout = QVBoxLayout()

        self.runlist = BlueskyListWidget()
        self.runlist.itemsSelected.connect(self.controls.addPlotItems)

        self.remove_plot_items = QPushButton("Remove Items")
        self.clear_plot_button = QPushButton("Clear Plot")

        self.remove_plot_items.clicked.connect(self.runlist.removeSelectedItems)
        self.clear_plot_button.clicked.connect(self.plot_widget.clearPlot)

        vlayout.addWidget(self.runlist)
        vlayout.addWidget(self.remove_plot_items)
        vlayout.addWidget(self.clear_plot_button)

        self.layout.addWidget(self.plot_widget)
        self.layout.addLayout(vlayout)
        self.layout.addWidget(self.controls)

    # def addRun(self, blueskyruns):
    #     self.runlist.addRun(blueskyruns)

    def addPlotItem(self, plotItem):
        self.runlist.addPlotItem(plotItem)


class PlotControls(QWidget):
    """
    A widget for interactive plotting controls, including a grid of checkboxes
    for selecting X data, Y data, and normalization options. It is designed to
    work with an MPLCanvas or a similar object acting as a Matplotlib FigureCanvas.

    Parameters
    ----------
    plot : MPLCanvas or similar
        The plotting canvas where the data will be displayed.
    parent : QWidget, optional
        The parent widget, by default None.
    """

    def __init__(self, plot, parent=None):
        super().__init__(parent)
        self.plot = plot
        self.data = None
        self.allkeylist = []
        self.plotItemList = []
        self.layout = QVBoxLayout(self)

        auto_add_layout = QHBoxLayout()
        auto_add_layout.addWidget(QLabel("Auto Add"))
        self.auto_add_box = QCheckBox()
        self.auto_add_box.setChecked(True)
        self.auto_add_box.clicked.connect(self.checked_changed)
        auto_add_layout.addWidget(self.auto_add_box)
        self.layout.addLayout(auto_add_layout)

        dynamic_update_layout = QHBoxLayout()
        dynamic_update_layout.addWidget(QLabel("Dynamic Update"))
        self.dynamic_update_box = QCheckBox()
        self.dynamic_update_box.setChecked(False)

        dynamic_update_layout.addWidget(self.dynamic_update_box)
        self.layout.addLayout(dynamic_update_layout)

        show_all_layout = QHBoxLayout()
        show_all_layout.addWidget(QLabel("Show all rows"))
        self.show_all = QCheckBox()
        self.show_all.setChecked(False)
        self.show_all.clicked.connect(self.update_display)
        show_all_layout.addWidget(self.show_all)
        self.layout.addLayout(show_all_layout)

        transform_layout = QHBoxLayout()
        transform_layout.addWidget(QLabel("Transform"))
        self.transform_box = QCheckBox()
        self.transform_box.setChecked(False)
        self.transform_box.clicked.connect(self.checked_changed)
        transform_layout.addWidget(self.transform_box)
        self.layout.addLayout(transform_layout)

        self.transform_text_edit = QLineEdit()
        self.layout.addWidget(self.transform_text_edit)

        self.grid = QGridLayout()
        self.layout.addLayout(self.grid)

        self.update_plot_button = QPushButton("Update Plot")
        self.update_plot_button.clicked.connect(self.update_plot)
        self.update_plot_button.setEnabled(False)

        self.clear_data_button = QPushButton("Uncheck All")
        self.clear_data_button.clicked.connect(self.uncheck_all)
        self.clear_data_button.setEnabled(False)
        self.layout.addWidget(self.update_plot_button)
        self.layout.addWidget(self.clear_data_button)

    @property
    def auto_add(self):
        t = self.auto_add_box.isChecked()
        # print(f"Auto add {t}")
        return t

    def addPlotItems(self, plotItemList):
        # print("Add Plot Item")
        # print(f"Adding {len(plotItemList)} items")
        for plotItem in plotItemList:
            if not plotItem._connected:
                plotItem.attach_plot(self.plot)
                self.dynamic_update_box.clicked.connect(plotItem.setDynamic)
                plotItem._connected = True

        self.plotItemList = plotItemList
        self.update_display()
        self.checked_changed()

    def clear_display(self):
        for i in reversed(range(self.grid.count())):
            self.grid.itemAt(i).widget().setParent(None)

        # Clear the header from the layout
        for i in reversed(range(self.layout.count())):
            widget = self.layout.itemAt(i).widget()
            if isinstance(widget, QLabel):
                widget.setParent(None)
        self.update_plot_button.setEnabled(False)
        self.clear_data_button.setEnabled(False)

    def update_display(self):
        self.clear_display()
        if len(self.plotItemList) == 0:
            return

        if len(self.plotItemList) == 1:
            header = self.plotItemList[0].description
        else:
            header = "Multiple Selected Scans"
        # header = self.plotItem.description
        for plotItem in self.plotItemList:
            plotItem.set_row_visibility(self.show_all.isChecked())
        # Clear the current display

        # self.data = data_dict
        # Add the header
        header_label = QLabel(header)
        self.layout.insertWidget(0, header_label)

        # Add column labels
        for i, label in enumerate(["X", "Y"]):
            label_widget = QLabel(label)
            self.grid.addWidget(label_widget, 0, i + 1)
        self.grid.addWidget(QLabel("Normalize"), 0, 4)

        # Add the data
        norm_group = ExclusiveCheckBoxGroup(self)
        silly_x_group = ExclusiveCheckBoxGroup(self)
        y_group1d = QButtonGroup(self)
        y_group2d = ExclusiveCheckBoxGroup(self)
        y_group1d.setExclusive(False)

        checked_norm = getCommonAttr(self.plotItemList, "_checked_norm")
        checked_x = getCommonAttr(self.plotItemList, "_checked_x")
        checked_y = getCommonAttr(self.plotItemList, "_checked_y")

        any_y_checked = False

        def add_xyn_buttons(key, i):

            key_label = QLabel(key)
            self.grid.addWidget(key_label, i + 1, 0)
            xbox = QCheckBox()
            self.grid.addWidget(xbox, i + 1, 1)
            ybox = QCheckBox()
            self.grid.addWidget(ybox, i + 1, 2)
            vertical_line = QFrame()
            vertical_line.setFrameShape(QFrame.VLine)
            self.grid.addWidget(vertical_line, i + 1, 3)
            normbox = QCheckBox()
            self.grid.addWidget(normbox, i + 1, 4)

            if key in checked_norm:
                normbox.setChecked(True)
            if key in checked_x:
                xbox.setChecked(True)

            return xbox, ybox, normbox

        i = 0
        xgroups = {}
        allkeylist = []

        rows = getCommonRows(self.plotItemList)
        xkeyDict = getCommonXKeyDict(self.plotItemList)
        ykeyDict = getCommonYKeyDict(self.plotItemList)

        for xdim, xlist in xkeyDict.items():
            if not any([x in rows for x in xlist]):
                continue
            else:
                xgroups[xdim] = ExclusiveCheckBoxGroup()
                for x in xlist:
                    if x in rows:
                        allkeylist.append(x)
                        xbox, ybox, nbox = add_xyn_buttons(x, i)
                        xgroups[xdim].addButton(xbox, i)
                        y_group1d.addButton(ybox, i)
                        norm_group.addButton(nbox, i)
                        i += 1

        for ydim, ylist in ykeyDict.items():
            for y in ylist:
                if y in rows:
                    allkeylist.append(y)
                    xbox, ybox, nbox = add_xyn_buttons(y, i)
                    silly_x_group.addButton(xbox, i)
                    if ydim == 1:
                        if y in checked_y:
                            ybox.setChecked(True)
                            any_y_checked = True
                        y_group1d.addButton(ybox, i)
                    else:
                        y_group2d.addButton(ybox, i)
                        if y in checked_y and not any_y_checked:
                            ybox.setChecked(True)
                            any_y_checked = True
                    norm_group.addButton(nbox, i)
                    i += 1

        self.norm_group = norm_group
        self.y_group1d = y_group1d
        self.y_group2d = y_group2d
        self.extra_x_group = silly_x_group
        self.x_groups = xgroups
        self.allkeylist = allkeylist
        for group in [
            self.norm_group,
            self.extra_x_group,
        ]:
            for button in group.buttons():
                button.clicked.connect(self.checked_changed)
        for group in self.x_groups.values():
            for button in group.buttons():
                button.clicked.connect(self.checked_changed)
        self._exclusionary_y_group = MutuallyExclusiveCheckBoxGroups(
            self.y_group1d, self.y_group2d
        )
        self._exclusionary_y_group.buttonsChanged.connect(self.checked_changed)
        self.update_plot_button.setEnabled(True)
        self.clear_data_button.setEnabled(True)

    def checkedButtons(self):
        x_checked_ids = []
        y_checked_ids = []
        for group in list(self.x_groups.values()) + [self.extra_x_group]:
            for button in group.buttons():
                if button.isChecked():
                    x_checked_ids.append(self.allkeylist[group.id(button)])
        for group in [self.y_group1d, self.y_group2d]:
            for button in group.buttons():
                if button.isChecked():
                    y_checked_ids.append(self.allkeylist[group.id(button)])
        norm_checked_ids = [
            self.allkeylist[self.norm_group.id(button)]
            for button in self.norm_group.buttons()
            if button.isChecked()
        ]

        return x_checked_ids, y_checked_ids, norm_checked_ids

    def uncheck_all(self):
        for plotItem in self.plotItemList:
            plotItem.update_plot_settings([], [], [], "")
        self.update_display()

    def checked_changed(self):
        for plotItem in self.plotItemList:
            checked_x, checked_y, checked_norm = self.checkedButtons()
            transform_text = (
                self.transform_text_edit.text()
                if self.transform_box.isChecked()
                else ""
            )
            # print(f"Checked Changed, transform_text: {transform_text}")
            # print(checked_x, checked_y, checked_norm)
            plotItem.update_plot_settings(
                checked_x, checked_y, checked_norm, transform_text
            )
            if self.auto_add:
                plotItem.updatePlot()

    def update_plot(self):
        self.checked_changed()
        if not self.auto_add:
            for plotItem in self.plotItemList:
                plotItem.updatePlot()


def getCommonAttr(plotItemList, attr):
    if len(plotItemList) == 0:
        return set()
    first_attr = getattr(plotItemList[0], attr)
    try:
        rows = set(first_attr)
    except TypeError:
        rows = set([first_attr])

    for plotItem in plotItemList:
        rows &= set(getattr(plotItem, attr))
    return rows


def getCommonRows(plotItemList):
    return getCommonAttr(plotItemList, "rows")


def getCommonXKeyDict(plotItemList):
    if len(plotItemList) == 0:
        return dict()

    xdims = set(plotItemList[0].xkeyDict.keys())
    for plotItem in plotItemList:
        xdims &= set(plotItem.xkeyDict.keys())
    xdims = sorted(list(xdims))
    xkeyDict = {}
    for dim in xdims:
        xlist = set(plotItemList[0].xkeyDict[dim])
        for plotItem in plotItemList:
            xlist &= set(plotItem.xkeyDict[dim])
        xkeyDict[dim] = sorted(list(xlist))
    return xkeyDict


def getCommonYKeyDict(plotItemList):
    if len(plotItemList) == 0:
        return dict()
    ydims = set(plotItemList[0].all_ykeyDict.keys())
    for plotItem in plotItemList:
        ydims &= set(plotItem.all_ykeyDict.keys())
    ydims = sorted(list(ydims))

    ykeyDict = {}
    for dim in ydims:
        ylist = set(plotItemList[0].all_ykeyDict[dim])
        for plotItem in plotItemList:
            ylist &= set(plotItem.all_ykeyDict[dim])
        ykeyDict[dim] = sorted(list(ylist))
    return ykeyDict


def get1dDataFromRun(blueskyrun):
    if isinstance(blueskyrun, BlueskyRun):
        return get1dData(blueskyrun.primary)
    return get1dData(blueskyrun["primary", "data"])


def get1dData(data):
    allData = {key: arr.shape for key, arr in data.items()}
    for key in list(allData.keys()):
        if len(allData[key]) != 1:
            del allData[key]
    return {k: d.data for k, d in data.read(variables=list(allData.keys())).items()}


def get1dKeys(run):
    allData = {key: arr.shape for key, arr in run["primary", "data"].items()}
    keys1d = []
    for key in list(allData.keys()):
        if len(allData[key]) == 1:
            keys1d.append(key)
    return keys1d


def separateKeys(run):
    allData = {key: arr.shape for key, arr in run["primary", "data"].items()}
    keys1d = []
    keysnd = []
    for key in list(allData.keys()):
        if len(allData[key]) == 1:
            keys1d.append(key)
        elif len(allData[key]) > 1:
            keysnd.append(key)
    return keys1d, keysnd


def getPlotKey(key_or_dict):
    if isinstance(key_or_dict, dict):
        return key_or_dict["signal"]
    else:
        return key_or_dict


def getPlotHints(run, all1dkeys):
    """
    So far only works for 1-d scans
    """
    xkey = run.start["hints"]["dimensions"][0][0][0]
    yhints = run.start["plot_hints"]
    ykeys_tmp = []
    for keys in yhints.values():
        ykeys_tmp += keys
    ykeys = [y for y in ykeys_tmp if y in all1dkeys]
    return xkey, ykeys, yhints


if __name__ == "__main__":
    from tiled.client import from_uri

    # c = from_uri("https://tiled.nsls2.bnl.gov")["ucal", "raw"]
    c = from_uri("http://localhost:8000")
    # run = c["ucal"]["raw"].items_indexer[-10][-1]
    app = QApplication([])
    widget = DataDisplayWidget()
    widget.show()
    widget.addPlotItem([PlotItem(run) for run in c.values()])
    app.exec_()
