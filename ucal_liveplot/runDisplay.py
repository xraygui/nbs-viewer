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
from qtpy.QtCore import Qt, Signal, QObject, QTimer

# from pyqtgraph import PlotWidget
from tiled.client import show_logs

import matplotlib
import numpy as np

matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure

# show_logs()


class PlotItem(QObject):
    update_plot_signal = Signal()

    def __init__(self, run, catalog=None, dynamic=False):
        super(PlotItem, self).__init__()
        self._run = run
        self._catalog = catalog
        self._dynamic = dynamic
        allkeys = get1dKeys(self._run)
        xkey, ykeys, hints = getPlotHints(self._run, allkeys)
        self._rows = [xkey]
        for y in ykeys:
            if y in allkeys:
                self._rows.append(y)
        if not self._dynamic:
            self._data = get1dData(self._run["primary", "data"])
        else:
            self._data = None
        self._description = blueskyrun_to_string(self._run)
        self._uid = self._run.metadata["start"]["scan_id"]
        self._checked_x = xkey
        self._checked_y = hints.get("primary", None)
        self._checked_norm = hints.get("normalization", [None])[0]
        self._plot = None
        self._lines = {}
        if self._dynamic:
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._dynamic_update)
            self.timer.start(1000)
            self._expected_points = None
        else:
            self.timer = None
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

    def attach_plot(self, plot):
        self._plot = plot
        self.update_plot_signal.connect(self.plot_checked)

    def get_data(self, key):
        if not self._dynamic:
            return self._data[key]
        else:
            return self._run["primary", "data", key].read()

    def _dynamic_update(self):
        if self._expected_points is None:
            self._expected_points = self._run.start.get("num_points", -1)

        if self._run.metadata.get("stop", None) is not None:
            print("Converting from dynamic to static")
            print(self._run.metadata["stop"])
            self._dynamic = False
            self._data = get1dData(self._run["primary", "data"])
            if self.timer is not None:
                self.timer.stop()
                self.timer = None
        elif self._catalog is not None:
            self._run = self._catalog[self.uid]

        self.update_plot_signal.emit()
        print(self._run.metadata["stop"])

    def update_checkboxes(self, checked_x, checked_y, checked_norm):
        self._checked_x = checked_x
        self._checked_y = checked_y
        self._checked_norm = checked_norm
        if checked_x is not None and checked_y is not None:
            self.update_plot_signal.emit()

    def plot_checked(self):
        if self._checked_x is None or self._checked_y is None:
            for line in self._lines.values():
                line.remove()
            self._lines = {}
            return

        x = self.get_data(self._checked_x)
        if self._checked_norm is not None:
            norm = self.get_data(self._checked_norm)
        else:
            norm = np.ones_like(x)
        # y_dict = {k: self.data[k].read() for k in checked_y}
        all_line_ids = list(self._lines.keys())
        plotted_line_ids = []
        for k in self._checked_y:
            line_id = f"{self._checked_x};{k};{str(self._checked_norm)}"
            plotted_line_ids.append(line_id)
            if line_id not in self._lines:
                y = self.get_data(k)
                minlen = min(len(y), len(x), len(norm))
                self._lines[line_id] = self._plot.plot(
                    x[:minlen], y[:minlen] / norm[:minlen], label=k
                )[0]
            elif self._dynamic:
                y = self.get_data(k)
                minlen = min(len(y), len(x), len(norm))
                self._lines[line_id].set_data(x[:minlen], y[:minlen] / norm[:minlen])
                if minlen == self._expected_points:
                    print("Converting from dynamic to static")
                    print(self._run.metadata["stop"])
                    self._dynamic = False
                    self._data = get1dData(self._run["primary", "data"])
                    if self.timer is not None:
                        self.timer.stop()
                        self.timer = None
        for line_id in all_line_ids:
            if line_id not in plotted_line_ids:
                line = self._lines.pop(line_id)
                line.remove()
        self._plot.autoscale()
        self._plot.draw()


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
        items_for_emission = [
            self._plotItems[item.data(Qt.UserRole)] for item in selected_items
        ]
        return items_for_emission

    def emit_selected_data(self):
        self.selectedDataChanged.emit(self.selectedData())


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

    checked_changed = Signal(list)

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
        if isinstance(plotItem, (list, tuple)):
            plotItem = plotItem[0]
        self.plotItem = plotItem
        self.plotItem.attach_plot(self.plot)
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

        checked_norm = self.plotItem._checked_norm
        checked_x = self.plotItem._checked_x
        checked_y = self.plotItem._checked_y

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

            if key == checked_norm:
                normbox.setChecked(True)
            if key == checked_x:
                xbox.setChecked(True)
            if checked_y is not None and key in checked_y:
                ybox.setChecked(True)

        self.norm_group = norm_group
        self.y_group = y_group
        self.x_group = x_group
        for group in [self.norm_group, self.x_group, self.y_group]:
            for button in group.buttons():
                button.clicked.connect(self.emit_checked_changed)
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
        if len(x_checked_ids) > 0:
            x = x_checked_ids[0]
        else:
            x = None
        if len(y_checked_ids) == 0:
            y_checked_ids = None
        return x, y_checked_ids, norm

    def emit_checked_changed(self):
        checked_x, checked_y, checked_norm = self.checkedButtons()
        self.plotItem.update_checkboxes(checked_x, checked_y, checked_norm)

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

    c = from_uri("https://tiled.nsls2.bnl.gov")["ucal", "raw"]
    # run = c["ucal"]["raw"].items_indexer[-10][-1]
    app = QApplication([])
    widget = DataDisplayWidget()
    widget.show()
    widget.addPlotItem([PlotItem(run) for run in c.values()[len(c) - 5 :]])
    app.exec_()
