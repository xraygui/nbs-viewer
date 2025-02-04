from qtpy.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QSlider,
    QLabel,
    QSpinBox,
    QSizePolicy,
)
from qtpy.QtCore import Qt, Signal, Slot, QSize

import matplotlib
import numpy as np

matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from .plotDimensionWidget import PlotDimensionControl


class NavigationToolbar(NavigationToolbar2QT):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent)

        # Add custom buttons after initialization
        self.addAction("Autoscale", self.autoscale)
        self.addAction("Autolegend", self.autolegend)

    def autoscale(self):
        self.canvas.autoscale()
        self.canvas.draw()

    def autolegend(self):
        """Toggle legend visibility and update with current visible lines."""
        legend = self.canvas.axes.get_legend()
        if legend is None or not legend.get_visible():
            self.canvas.updateLegend()
        else:
            legend.set_visible(False)
            self.canvas.draw()


class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, plotModel, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.add_subplot(111)
        self.currentDim = 1
        self._autoscale = True
        super().__init__(self.fig)
        self.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))
        self.aspect_ratio = width / height

        self.plotModel = plotModel
        self.plotModel.artist_needed.connect(self.create_artist)
        self.plotModel.draw_requested.connect(self.draw)
        self.plotModel.autoscale_requested.connect(self.autoscale)
        self.plotModel.visibility_changed.connect(self._on_visibility_changed)

    def _on_visibility_changed(self, plot_data, is_visible):
        """Handle visibility changes by updating the legend."""
        self.updateLegend()
        self.autoscale()

    def sizeHint(self):
        width = self.width()
        height = int(width / self.aspect_ratio)
        return QSize(width, height)

    def heightForWidth(self, width):
        return int(width / self.aspect_ratio)

    def create_artist(self, plotData):
        x = plotData._xplot
        y = plotData._yplot
        artist = self.plot(x, y, None, label=plotData._label)
        plotData.set_artist(artist)
        return artist

    def plot(self, xlist, y, artist=None, **kwargs):
        """
        Plot data on the canvas.

        Parameters
        ----------
        xlist : list
            List of x data arrays
        y : array_like
            Y data array
        artist : Artist, optional
            Existing artist to update, by default None
        **kwargs
            Additional keyword arguments passed to plot

        Returns
        -------
        Artist
            The matplotlib artist created or updated
        """
        if len(y.shape) == 1:
            # Only clear axes if switching from 2D to 1D
            if self.currentDim != 1:
                # Properly clean up old axes
                old_axes = self.axes
                self.fig.delaxes(old_axes)
                self.axes = self.fig.add_subplot(111)
                self.currentDim = 1

            if isinstance(artist, Line2D):
                artist.set_data(xlist[0], y)
            else:
                artist = self.axes.plot(xlist[0], y, **kwargs)[0]

            if self._autoscale:
                self.autoscale()
            self.updateLegend()

        elif len(y.shape) == 2 and len(xlist) > 1:
            # Only clear for 2D plots or dimension changes
            if self.currentDim != 2:
                # Properly clean up old axes
                old_axes = self.axes
                self.fig.delaxes(old_axes)
                self.axes = self.fig.add_subplot(111)
                artist = self.axes.contourf(xlist[-1], xlist[-2], y)
                self.currentDim = 2
        else:
            print(f"Unsupported dimensionality! {y.shape}, {len(xlist)}")
            artist = None

        self.draw()
        return artist

    def clear(self):
        """Clear all artists from the axes and reset state."""
        # Clear the figure and axes
        self.axes.cla()
        self.fig.clear()
        self.axes = self.fig.add_subplot(111)

        # Reset dimension state
        self.currentDim = 1

        # Redraw the canvas
        self.draw()

    def autoscale(self):
        # Get only visible lines
        visible_lines = [line for line in self.axes.get_lines() if line.get_visible()]
        if not visible_lines:
            return

        y_min = min(line.get_ydata().min() for line in visible_lines)
        y_max = max(line.get_ydata().max() for line in visible_lines)
        span = y_max - y_min
        if span > 0:
            self.axes.set_ylim(y_min - 0.05 * span, y_max + 0.05 * span)

        x_min = min(line.get_xdata().min() for line in visible_lines)
        x_max = max(line.get_xdata().max() for line in visible_lines)
        xspan = x_max - x_min
        if xspan > 0:
            self.axes.set_xlim(x_min - 0.05 * xspan, x_max + 0.05 * xspan)

    def updateLegend(self):
        """Update the plot legend to show only visible lines."""
        # Get visible lines and their labels
        visible_lines = [line for line in self.axes.get_lines() if line.get_visible()]
        if visible_lines:
            labels = [line.get_label() for line in visible_lines]
            self.axes.legend(visible_lines, labels)
        else:
            # Remove legend if no visible lines
            legend = self.axes.get_legend()
            if legend is not None:
                legend.remove()
        self.draw()


class PlotWidget(QWidget):
    """
    The main organizing widget that combines a plot, a list of Bluesky runs,
    and controls to add runs to the plot.

    Parameters
    ----------
    parent : QWidget, optional
        The parent widget, by default None.
    """

    def __init__(self, plotModel, parent=None):
        super().__init__(parent)
        self.plotModel = plotModel
        self.layout = QHBoxLayout(self)
        self.plot_layout = QVBoxLayout()
        # self.plot = PlotWidget()
        self.plot = MplCanvas(self.plotModel, self, 5, 4, 100)
        self.toolbar = NavigationToolbar(self.plot, self)
        # self.dimensionControls = PlotDimensionControl(self.plotModel)

        self.plot_layout.addWidget(self.toolbar)
        self.plot_layout.addWidget(self.plot)
        # self.plot_layout.addWidget(self.dimensionControls)

        self.layout.addLayout(self.plot_layout)

    """
    def addPlotData(self, x, y, xkeys, ykey, dimension=1):
        # Needs to just create and return a DataPlotter
        data_plotter = DataPlotter(
            self.dimensionControls, self.plot, x, y, xkeys, ykey, dimension
        )
        return data_plotter

    def clearPlot(self):
        self.dimensionControls.clear_data()
        self.plot.clear()
    """


if __name__ == "__main__":

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
