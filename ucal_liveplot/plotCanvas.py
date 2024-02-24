from qtpy.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QSlider,
    QLabel,
    QSpinBox,
)
from qtpy.QtCore import Qt, Signal, QObject, QTimer, Slot

import matplotlib
import numpy as np

matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure
from matplotlib.lines import Line2D


class DataPlotterControl(QWidget):
    """
    Must be updated to be able to hold a list of DataPlotters! Most Key thing.
    A class to create control widgets for DataPlotter based on the dimensions of the y data.

    Attributes
    ----------
    data_plotter : DataPlotter
        The DataPlotter instance to control.
    sliders : list
        A list of QSlider widgets for controlling the dimensions of the y data.
    """

    indicesUpdated = Signal(tuple)

    def __init__(self, data_plotter=None, parent=None):
        """
        Initializes the DataPlotterControl with a DataPlotter instance and creates sliders.

        Parameters
        ----------
        data_plotter : DataPlotter
            The DataPlotter instance to control.
        """
        super().__init__(parent)
        self.data_list = []
        if data_plotter is not None:
            self.add_data(data_plotter)
        self.init_ui()

    def add_data(self, data_plotter):
        self.data_list.append(data_plotter)
        self.indicesUpdated.connect(data_plotter.update_indices)

    def remove_data(self, data_plotter):
        if data_plotter in self.data_list:
            idx = self.data_list.index(data_plotter)
            self.data_list.pop(idx)
        data_plotter.clear()

    def init_ui(self):
        """
        Initializes the user interface, creating sliders based on the dimensions of the y data.
        """
        self.layout = QVBoxLayout()

        self.dimension_spinbox = QSpinBox()
        self.dimension_spinbox.setMinimum(1)
        self.dimension_spinbox.setMaximum(2)
        self.dimension_spinbox.setValue(1)
        self.dimension_spinbox.valueChanged.connect(self.dimension_changed)
        self.layout.addWidget(self.dimension_spinbox)
        self.create_sliders()

        self.setLayout(self.layout)

    def create_sliders(self):
        for slider in getattr(self, "sliders", []):
            slider.deleteLater()
        self.sliders = []

        for label in getattr(self, "labels", []):
            label.deleteLater()
        self.labels = []

        # Assuming _y is accessible and is a numpy array
        # Need to have the data_plotter report the shape itself!!
        if len(self.data_list) == 0:
            return

        y_shape = self.data_list[0]._y.shape

        def create_slider_callback(slider, label, dim):
            def callback(value):
                label.setText(f"Dimension {dim+1}: {value}")
                # Here you can also add the logic to update the plotted data based on the slider's value

            return callback

        # Create a slider for each dimension of y, except the last one
        for dim in range(len(y_shape) - self.dimension_spinbox.value()):
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(y_shape[dim] - 1)
            label = QLabel(f"Dimension {dim+1}: {slider.value()}")
            slider.valueChanged.connect(create_slider_callback(slider, label, dim))
            slider.valueChanged.connect(self.sliders_changed)
            self.layout.addWidget(label)
            self.layout.addWidget(slider)
            self.sliders.append(slider)
            self.labels.append(label)

    def dimension_changed(self):
        # Update the dimension in DataPlotter
        for data_plotter in self.data_list:
            data_plotter.dimension = self.dimension_spinbox.value()
        # Recreate the sliders
        self.create_sliders()
        self.sliders_changed()
        # You might need to update the plot here as well

    def sliders_changed(self):
        """
        Creates a callback function for a slider that updates the plotted data based on the slider's value.

        Parameters
        ----------
        dim : int
            The dimension that the slider controls.

        Returns
        -------
        function
            A callback function to be connected to the slider's valueChanged signal.
        """
        indices = []
        for s in self.sliders:
            value = s.value()
            indices.append(value)
        indices = tuple(indices)
        # print(indices)
        self.indicesUpdated.emit(indices)


class DataPlotter(QWidget):
    """
    A class to plot x, y data on a given MplCanvas instance and hold the resulting lines object.

    Attributes
    ----------
    canvas : MplCanvas
        The MplCanvas instance where the data will be plotted.
    lines : list
        A list of Line2D objects representing the plotted data.
    """

    def __init__(self, parent, canvas, x, y, dimension=1):
        """
        Initializes the DataPlotter with data and a canvas, and plots the data.

        Parameters
        ----------
        canvas : MplCanvas
            The MplCanvas instance where the data will be plotted.
        x : list of array_like
            The x data to plot.
        y : array_like
            The y data to plot.
        """
        super().__init__(parent)
        self.canvas = canvas
        self._x = x
        self._y = y
        self.dimension = dimension
        self.artist = None
        self.artist = self.plot_data()

    def plot_data(self, indices=None):
        """
        Plots the given x, y data on the associated MplCanvas instance. If x and y have more than one dimension,
        only the last axis is plotted.

        Parameters
        ----------
        x : list of array_like
            The x data to plot. If x is multidimensional, only the last axis is plotted.
        y : array_like
            The y data to plot. If y is multidimensional, only the last axis is plotted.

        Returns
        -------
        list
            A list of Line2D objects representing the plotted data.
        """
        xlistmod = []
        # self.dimension needs to be set better?
        # indices need to account for extra axes from detector
        if indices is None:
            indices = tuple([0 for n in range(len(self._x) - self.dimension)])
        for x in self._x:
            print(f"Original x shape: {x.shape}")
            if len(x.shape) > 1:
                xlistmod.append(x[indices])
            else:
                xlistmod.append(x)
        y = self._y[indices]
        for x in xlistmod:
            print(f"xlistmod shape: {x.shape}")
        x = xlistmod[-self.dimension :]
        print(len(x))
        print(y.shape)
        artist = self.canvas.plot(x, y, self.artist)
        return artist

    def update_data(self, x, y):
        self._x = x
        self._y = y
        self.plot_data()

    @Slot(tuple)
    def update_indices(self, indices):
        """
        Updates the plotted data based on the provided indices into the first N-1 dimensions of the data.

        Parameters
        ----------
        indices : tuple
            Indices into the first N-1 dimensions of the data arrays.
        """
        # Clear the current lines from the plot
        # Index into the first N-1 dimensions of the data arrays
        self.artist = self.plot_data(indices)

    def clear(self):
        if self.artist is not None:
            if hasattr(self.artist, "remove"):
                self.artist.remove()
            else:
                self.canvas.clear()
            self.canvas.draw()
        self.artist = None

    def remove(self):
        self.parent().remove_data(self)


class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        self.currentDim = 1
        super(MplCanvas, self).__init__(self.fig)

    def plot(self, xlist, y, artist=None, **kwargs):
        print(f"plot x list {len(xlist)}")
        print(f"plot y shape {y.shape}")
        if len(y.shape) == 1:
            print(f"plot x shape {xlist[0].shape}")
            if self.currentDim != 1:
                self.axes.cla()
                self.axes.remove()
                self.axes = self.fig.add_subplot(111)
            if not isinstance(artist, Line2D):
                artist = self.axes.plot(xlist[0], y, **kwargs)[0]
            else:
                artist.set_data(xlist[0], y)
            self.currentDim = 1
            self.autoscale()
        elif len(y.shape) == 2:
            self.axes.cla()
            artist = self.axes.contourf(xlist[-1], xlist[-2], y)
            # artist = self.axes.imshow(y)
            self.currentDim = 2
        else:
            print(f"Unsupported dimensionality! {y.shape}")
        self.draw()
        return artist

    def clear(self):
        print("Clearing Axes")
        self.axes.cla()
        self.draw()

    def autoscale(self):
        """
        Adjusts the y scale of the plot based on the maximum and minimum of the y data in lines
        """
        lines = self.axes.get_lines()
        y_min = min([line.get_ydata().min() for line in lines])
        y_max = max([line.get_ydata().max() for line in lines])
        span = y_max - y_min
        self.axes.set_ylim(y_min - 0.05 * span, y_max + 0.05 * span)

        x_min = min([line.get_xdata().min() for line in lines])
        x_max = max([line.get_xdata().max() for line in lines])
        xspan = x_max - x_min
        self.axes.set_xlim(x_min - 0.05 * xspan, x_max + 0.05 * xspan)


class PlotWidget(QWidget):
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
        self.dataControls = DataPlotterControl()

        self.plot_layout.addWidget(self.toolbar)
        self.plot_layout.addWidget(self.plot)
        self.plot_layout.addWidget(self.dataControls)

        self.layout.addLayout(self.plot_layout)

    def addPlotData(self, x, y, dimension=1):
        # Needs to just create and return a DataPlotter
        data_plotter = DataPlotter(self.dataControls, self.plot, x, y, dimension)
        self.dataControls.add_data(data_plotter)
        return data_plotter


if __name__ == "__main__":
    from tiled.client import from_uri

    c = from_uri("https://tiled.nsls2.bnl.gov")["ucal", "raw"]
    # run = c["ucal"]["raw"].items_indexer[-10][-1]
    app = QApplication([])
    widget = PlotWidget()
    widget.show()
    d1 = 1000
    d2 = 1000
    d3 = 20
    x = np.zeros((d3, d2, d1))
    phase = np.zeros((d3, d2, d1))
    phase2 = np.zeros((d3, d2, d1))
    for n in range(d2):
        for m in range(d3):
            x[m, n, :] = np.linspace(0, 2 * np.pi, d1)
            phase[m, n, :] = n * 2 * np.pi / (2 * d2)
            phase2[m, n, :] = m * 2 * np.pi / d3
    y = np.sin(x + phase + phase2)
    widget.addPlotData([phase2, phase, x], y, dimension=1)
    app.exec_()
