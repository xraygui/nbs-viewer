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
)
from qtpy.QtCore import Qt, Signal, QObject

# from pyqtgraph import PlotWidget
from tiled.client import show_logs

import matplotlib

matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure

# show_logs()


class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        super(MplCanvas, self).__init__(fig)

    def plot(self, *args, **kwargs):
        self.axes.plot(*args, **kwargs)
        self.draw()

    def clear(self):
        print("Clearing Axes")
        self.axes.cla()
        self.draw()


def blueskyrun_to_string(blueskyrun):
    # Replace this with your actual function
    start = blueskyrun.metadata["start"]
    scan_id = str(start["scan_id"])
    scan_desc = ["Scan", scan_id]
    if hasattr(start, "edge"):
        scan_desc.append(start.get("edge"))
        scan_desc.append("edge")
    if hasattr(start, "scantype"):
        scan_desc.append(start.get("scantype"))
    else:
        scan_desc.append(start.get("plan_name"))
    if hasattr(start, "sample_md"):
        scan_desc.append("of")
        scan_desc.append(start["sample_md"].get("name", "Unknown"))
    elif hasattr(start, "sample_name"):
        scan_desc.append("of")
        scan_desc.append(start["sample_name"])
    str_desc = " ".join(scan_desc)
    return str_desc


class PlotItem(QObject):
    def __init__(self, run, dynamic=False):
        super(PlotItem, self).__init__()
        self._run = run
        self._dynamic = dynamic
        self._rows = get1dKeys(self._run)
        self._data = get1dData(self._run["primary", "data"])
        self._description = blueskyrun_to_string(self._run)
        self._uid = self._run.metadata["start"]["scan_id"]
        # self._description = str(self._run.metadata["start"]["scan_id"])

    @property
    def description(self):
        return self._description

    @property
    def rows(self):
        return self._rows

    @property
    def uid(self):
        return self._uid

    def get_data(self, key):
        return self._data[key]

    def update(self):
        # TODO: Implement this method to update the plot
        pass


class BlueskyListWidget(QListWidget):
    """
    A widget for displaying Bluesky Runs in a list.

    Signals
    -------
    selectedDataChanged : Signal
        Emitted when the selected data in the list changes. Emits a list of
        (text, BlueskyRun) tuples based on the selected list items.
    """

    selectedDataChanged = Signal(list)

    def __init__(self, parent=None):
        """
        Initialize the BlueskyListWidget.

        Parameters
        ----------
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.itemSelectionChanged.connect(self.emit_selected_data)
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

    def selectedData(self):
        print("Selecting Data")
        selected_items = self.selectedItems()
        print("Got Selected items")
        print(selected_items)
        first_item = selected_items[0]
        print(f"First item text: {first_item.text()}")
        items_for_emission = [
            self._plotItems[item.data(Qt.UserRole)] for item in selected_items
        ]
        print("Created items for emission")
        return items_for_emission

    def emit_selected_data(self):
        print("Preparing to Emit Data")
        self.selectedDataChanged.emit(self.selectedData())
        print("Emitted")


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
        self.plot_layout = QVBoxLayout()
        # self.plot = PlotWidget()
        self.plot = MplCanvas(self, 5, 4, 100)
        self.toolbar = NavigationToolbar(self.plot, self)
        self.plot_layout.addWidget(self.toolbar)
        self.plot_layout.addWidget(self.plot)
        self.controls = PlotControls(self.plot)
        self.runlist = BlueskyListWidget()
        self.runlist.selectedDataChanged.connect(self.controls.update_display)
        self.layout.addLayout(self.plot_layout)
        self.layout.addWidget(self.runlist)
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
        self.layout = QVBoxLayout(self)
        self.grid = QGridLayout()
        self.layout.addLayout(self.grid)

        self.add_data_button = QPushButton("Plot Data")
        self.add_data_button.clicked.connect(self.addData)
        self.add_data_button.setEnabled(False)

        self.clear_data_button = QPushButton("Clear Plot")
        self.clear_data_button.clicked.connect(self.plot.clear)
        self.layout.addWidget(self.add_data_button)
        self.layout.addWidget(self.clear_data_button)

    def test_update(self, data_list):
        print("Updating controls")
        data = data_list[0]
        header = str(data.metadata["start"]["scan_id"])
        data_dict = get1dData(data["primary", "data"])
        self.update_display(header, data_dict)

    # def update_display(self, data_list):
    #    header, data_dict = data_list[0]
    def update_display(self, plotItem):
        print("Updating Display")
        self.plotItem = plotItem[0]
        header = self.plotItem.description
        # Clear the current display
        for i in reversed(range(self.grid.count())):
            self.grid.itemAt(i).widget().setParent(None)

        # Clear the header from the layout
        for i in reversed(range(self.layout.count())):
            widget = self.layout.itemAt(i).widget()
            if isinstance(widget, QLabel):
                widget.setParent(None)

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
        x_group = ExclusiveCheckBoxGroup(self)
        y_group = QButtonGroup(self)
        y_group.setExclusive(False)

        for i, key in enumerate(self.plotItem.rows):
            key_label = QLabel(key)
            self.grid.addWidget(key_label, i + 1, 0)
            xbox = QCheckBox()
            self.grid.addWidget(xbox, i + 1, 1)
            x_group.addButton(xbox, i)
            ybox = QCheckBox()
            y_group.addButton(ybox, i)
            self.grid.addWidget(ybox, i + 1, 2)
            vertical_line = QFrame()
            vertical_line.setFrameShape(QFrame.VLine)
            self.grid.addWidget(vertical_line, i + 1, 3)
            normbox = QCheckBox()
            self.grid.addWidget(normbox, i + 1, 4)
            norm_group.addButton(normbox, i)

        self.norm_group = norm_group
        self.y_group = y_group
        self.x_group = x_group
        self.add_data_button.setEnabled(True)

    def checkedButtons(self):
        x_checked_ids = [
            self.plotItem.rows[self.x_group.id(button)]
            for button in self.x_group.buttons()
            if button.isChecked()
        ]
        y_checked_ids = [
            self.plotItem.rows[self.y_group.id(button)]
            for button in self.y_group.buttons()
            if button.isChecked()
        ]
        norm_checked_ids = [
            self.plotItem.rows[self.norm_group.id(button)]
            for button in self.norm_group.buttons()
            if button.isChecked()
        ]
        if len(norm_checked_ids) > 0:
            norm = norm_checked_ids[0]
        else:
            norm = None
        return x_checked_ids[0], y_checked_ids, norm

    def addData(self):
        checked_x, checked_y, checked_norm = self.checkedButtons()

        x = self.plotItem.get_data(checked_x)
        if checked_norm is not None:
            norm = self.plotItem.get_data(checked_norm)
        else:
            norm = 1
        # y_dict = {k: self.data[k].read() for k in checked_y}
        for k in checked_y:
            self.plot.plot(x, self.plotItem.get_data(k) / norm, label=k)


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


if __name__ == "__main__":
    from tiled.client import from_uri

    c = from_uri("https://tiled.nsls2.bnl.gov")["ucal", "raw"]
    # run = c["ucal"]["raw"].items_indexer[-10][-1]
    app = QApplication([])
    widget = DataDisplayWidget()
    widget.show()
    widget.addPlotItem([PlotItem(run) for run in c.values()[len(c) - 5 :]])
    app.exec_()
