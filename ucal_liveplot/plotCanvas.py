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
    A class to create control widgets for DataPlotter based on the dimensions of the y data.

    Attributes
    ----------
    data_plotter : DataPlotter
        The DataPlotter instance to control.
    sliders : list
        A list of QSlider widgets for controlling the dimensions of the y data.
    """

    indicesUpdated = Signal(tuple)

    def __init__(self, data_plotter):
        """
        Initializes the DataPlotterControl with a DataPlotter instance and creates sliders.

        Parameters
        ----------
        data_plotter : DataPlotter
            The DataPlotter instance to control.
        """
        super().__init__()
        self.data_plotter = data_plotter
        # self.indicesUpdated.connect(print)
        self.indicesUpdated.connect(self.data_plotter.update_data)

        self.init_ui()

    def init_ui(self):
        """
        Initializes the user interface, creating sliders based on the dimensions of the y data.
        """
        self.layout = QVBoxLayout()

        self.dimension_spinbox = QSpinBox()
        self.dimension_spinbox.setMinimum(1)
        self.dimension_spinbox.setMaximum(2)
        self.dimension_spinbox.setValue(self.data_plotter.dimension)
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
        y_shape = self.data_plotter._y.shape

        def create_slider_callback(slider, label, dim):
            def callback(value):
                label.setText(f"Dimension {dim+1}: {value}")
                # Here you can also add the logic to update the plotted data based on the slider's value

            return callback

        # Create a slider for each dimension of y, except the last one
        for dim in range(len(y_shape) - self.data_plotter.dimension):
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
        self.data_plotter.dimension = self.dimension_spinbox.value()
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

    def __init__(self, canvas, x, y, dimension=1):
        """
        Initializes the DataPlotter with data and a canvas, and plots the data.

        Parameters
        ----------
        canvas : MplCanvas
            The MplCanvas instance where the data will be plotted.
        x : list of array_like
            The x data to plot.
        y : list of array_like
            The y data to plot.
        """
        super().__init__()
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
        x : array_like
            The x data to plot. If x is multidimensional, only the last axis is plotted.
        y : array_like
            The y data to plot. If y is multidimensional, only the last axis is plotted.

        Returns
        -------
        list
            A list of Line2D objects representing the plotted data.
        """
        xlistmod = []
        if indices is None:
            indices = tuple([0 for n in range(len(self._x) - self.dimension)])
        for x in self._x:
            if len(x.shape) > 1:
                xlistmod.append(x[indices])
            else:
                xlistmod.append(x)
        y = self._y[indices]
        artist = self.canvas.plot(xlistmod[-self.dimension :], y, self.artist)
        return artist

    @Slot(tuple)
    def update_data(self, indices):
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

        # Redraw the canvas to reflect the updated data
        self.canvas.draw()


class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        super(MplCanvas, self).__init__(fig)

    def plot(self, xlist, y, artist=None, **kwargs):
        if len(xlist) == 1:
            if not isinstance(artist, Line2D):
                self.axes.clear()
                artist = self.axes.plot(xlist[0], y, **kwargs)[0]
            else:
                artist.set_data(xlist[0], y)
        elif len(xlist) == 2:
            self.axes.clear()
            # artist = self.axes.contourf(xlist[-1], xlist[-2], y)
            artist = self.axes.imshow(y)
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
        self.plot_layout.addWidget(self.toolbar)
        self.plot_layout.addWidget(self.plot)
        self.layout.addLayout(self.plot_layout)

    def addPlotItem(self, x, y, dimension=1):
        self.dataWidget = DataPlotter(self.plot, x, y, dimension)
        self.dataControls = DataPlotterControl(self.dataWidget)

        self.plot_layout.addWidget(self.dataControls)


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
    widget.addPlotItem([phase2, phase, x], y, dimension=1)
    app.exec_()
