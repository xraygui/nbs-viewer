from qtpy.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QSplitter,
)
from qtpy.QtCore import Signal, Qt

# from pyqtgraph import PlotWidget

from .plotItem import PlotItem
from .plotCanvas import PlotWidget
from .plotControl import PlotControls
from .plotList import BlueskyListWidget
from .dataList import DataList


class PlotManagerBase(QWidget):
    """
    Base class for PlotManager that combines a plot and controls.

    Parameters
    ----------
    parent : QWidget, optional
        The parent widget, by default None.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Horizontal)
        self.layout.addWidget(self.splitter)

        # Create widgets
        self.plot_widget = PlotWidget()
        self.controls = PlotControls(self.plot_widget)

        self.clear_plot_button = QPushButton("Clear Plot")
        self.clear_plot_button.clicked.connect(self.plot_widget.clearPlot)

        # Create a widget for controls
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        control_layout.addWidget(self.controls)
        control_layout.addWidget(self.clear_plot_button)

        # Add widgets to splitter
        self.splitter.addWidget(self.plot_widget)
        self.splitter.addWidget(control_widget)

        self.setLayout(self.layout)

    def setup_list_widget(self, list_widget):
        """
        Set up the list widget and connect its signals.

        Parameters
        ----------
        list_widget : QWidget
            The list widget to set up.
        """
        self.list_widget = list_widget
        self.splitter.insertWidget(0, self.list_widget)

        # Connect signals
        self.list_widget.itemsSelected.connect(self.controls.addPlotItems)

        # Set initial sizes (adjust as needed)
        self.splitter.setSizes([200, 400, 200])  # list, plot, controls


class PlotManagerWithBlueskyList(PlotManagerBase):
    """
    PlotManager that uses BlueskyListWidget.

    Parameters
    ----------
    parent : QWidget, optional
        The parent widget, by default None.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_list_widget(BlueskyListWidget(self))


class PlotManagerWithDataList(PlotManagerBase):
    """
    PlotManager that uses DataList.

    Parameters
    ----------
    config_file : str, optional
        Path to the configuration file, by default None.
    parent : QWidget, optional
        The parent widget, by default None.
    """

    addToPlot = Signal(list)

    def __init__(self, config_file=None, parent=None):
        super().__init__(parent)
        self.setup_list_widget(DataList(config_file, self))
        self.list_widget.itemsAdded.connect(self.addToPlot)


if __name__ == "__main__":
    from tiled.client import from_uri

    # c = from_uri("https://tiled.nsls2.bnl.gov")["ucal", "raw"]
    c = from_uri("http://localhost:8000")
    # run = c["ucal"]["raw"].items_indexer[-10][-1]
    app = QApplication([])
    widget = PlotManager()
    widget.show()
    widget.addPlotItem([PlotItem(run) for run in c.values()])
    app.exec_()
