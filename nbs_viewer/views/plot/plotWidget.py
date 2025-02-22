from qtpy.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QSlider,
    QLabel,
    QSpinBox,
    QSizePolicy,
    QSplitter,
    QPushButton,
)
from qtpy.QtCore import Qt, Signal, Slot, QSize, QTimer

import matplotlib
import numpy as np

matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from .plotDimensionWidget import PlotDimensionControl
from .plotControl import PlotControls


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
        # Create figure with tight layout and proper spacing
        self.fig = Figure(figsize=(width, height), dpi=dpi, constrained_layout=True)

        # Create axes with explicit spacing from edges
        self.axes = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=0.15, right=0.95, top=0.95, bottom=0.15)

        # Initialize canvas
        super().__init__(self.fig)

        self.currentDim = 1
        self._autoscale = True
        self._artist_count = 0
        self._draw_pending = False

        self.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))
        self.aspect_ratio = width / height

        # Connect plot model signals
        self.plotModel = plotModel
        self.plotModel.artist_needed.connect(self.create_artist)
        self.plotModel.draw_requested.connect(self.draw)
        self.plotModel.autoscale_requested.connect(self.autoscale)
        self.plotModel.visibility_changed.connect(self._on_visibility_changed)
        self.plotModel.legend_update_requested.connect(self.updateLegend)

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
        try:
            artist = self.plot(x, y, None, label=plotData._label)
        except Exception as e:
            print(f"Error creating artist for {plotData._label}: {e}")
            artist = None
        plotData.set_artist(artist)
        return artist

    def resizeEvent(self, event):
        """Handle resize events to maintain proper layout."""
        super().resizeEvent(event)
        # Update figure size while maintaining margins
        width = event.size().width() / self.fig.dpi
        height = event.size().height() / self.fig.dpi
        self.fig.set_size_inches(width, height)
        # Ensure layout is updated
        self.fig.tight_layout()
        self.draw()

    def plot(self, xlist, y, artist=None, **kwargs):
        """Plot data on the canvas."""
        label = kwargs.get("label", "no label")

        if len(y.shape) == 1:
            if isinstance(artist, Line2D):
                # print(f"Updating existing artist: {label}")
                artist.set_data(xlist[0], y)
            else:
                # print(f"Creating new artist #{self._artist_count}: {label}")
                # Create artist with clipping enabled
                artist = self.axes.plot(xlist[0], y, clip_on=True, **kwargs)[0]
                self._artist_count += 1

            # Ensure proper layout after adding/updating artists
            self.fig.tight_layout()

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
        # print("\nClearing canvas...")
        # print(f"Before clear: {len(self.axes.get_lines())} artists")
        for line in self.axes.get_lines():
            # print(f"  Removing {line.get_label()}")
            line.remove()

        # Clear the figure and axes
        self.axes.cla()
        self.fig.clear()
        self.axes = self.fig.add_subplot(111)
        # print(f"After clear: {len(self.axes.get_lines())} artists")

        # Reset states
        self.currentDim = 1
        self._artist_count = 0
        self.draw()

    def autoscale(self):
        # Get only visible lines
        visible_lines = [line for line in self.axes.get_lines() if line.get_visible()]
        if not visible_lines:
            return

        y_min = []
        y_max = []
        x_min = []
        x_max = []
        for line in visible_lines:
            ydata = line.get_ydata()
            xdata = line.get_xdata()
            if len(ydata) > 0 and len(xdata) > 0:
                y_min.append(ydata.min())
                y_max.append(ydata.max())
                x_min.append(xdata.min())
                x_max.append(xdata.max())

        if len(y_min) > 0:
            y_min = min(y_min)
            y_max = max(y_max)
            x_min = min(x_min)
            x_max = max(x_max)
        else:
            print("No visible lines to autoscale")
            return

        yspan = y_max - y_min
        if yspan > 0:
            self.axes.set_ylim(y_min - 0.05 * yspan, y_max + 0.05 * yspan)

        xspan = x_max - x_min
        if xspan > 0:
            self.axes.set_xlim(x_min - 0.05 * xspan, x_max + 0.05 * xspan)

    def updateLegend(self):
        """Update the plot legend to show only visible lines."""
        # Clear existing legend first
        if self.axes.get_legend():
            self.axes.get_legend().remove()

        # Get visible lines and their labels
        visible_lines = [line for line in self.axes.get_lines() if line.get_visible()]
        if visible_lines:
            labels = [line.get_label() for line in visible_lines]
            self.axes.legend(visible_lines, labels)

        self.draw()

    def draw(self):
        """Draw the figure with throttling."""
        if not self._draw_pending:
            self._draw_pending = True
            QTimer.singleShot(16, self._do_draw)  # About 60fps

    def _do_draw(self):
        """Actually perform the draw operation."""
        self._draw_pending = False
        # Call parent class draw
        super().draw()


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

        # Create main splitter
        self.layout = QSplitter(Qt.Horizontal)

        # Create and setup plot container widget
        self.plot_container = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_container)

        # Add plot widgets to container
        self.plot = MplCanvas(self.plotModel, self, 5, 4, 100)
        self.toolbar = NavigationToolbar(self.plot, self)
        self.plot_layout.addWidget(self.toolbar)
        self.plot_layout.addWidget(self.plot)

        # Add debug button
        # self.debug_button = QPushButton("Debug Plot State")
        # self.debug_button.clicked.connect(self._debug_plot_state)
        # self.plot_layout.addWidget(self.debug_button)

        # Create plot controls
        self.plotControls = PlotControls(self.plotModel)

        # Add widgets to splitter
        self.layout.addWidget(self.plot_container)
        self.layout.addWidget(self.plotControls)

        # Create main layout and add splitter
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.layout)

    def _debug_plot_state(self):
        """Print debug information about plot state."""
        print("\n=== Plot State Debug Info ===")

        # Plot Model Runs
        print("\nPlot Model Available Runs:")
        for run_model in self.plotModel._run_models.values():
            print(f"  - {run_model._run.display_name} (uid: {run_model._run.uid})")

        print("\nPlot Model Visible Runs:")
        for uid in self.plotModel._visible_runs:
            if uid in self.plotModel._run_models:
                run = self.plotModel._run_models[uid]._run
                print(f"  - {run.display_name} (uid: {uid})")
            else:
                print(f"  - WARNING: Visible uid {uid} not in run models!")

        # Canvas Artists
        print("\nMplCanvas Artists:")
        for artist in self.plot.axes.get_lines():
            print(f"  - {artist.get_label()} (visible: {artist.get_visible()})")

        print("\nCurrent Selection:")
        print(f"  X keys: {self.plotModel._current_x_keys}")
        print(f"  Y keys: {self.plotModel._current_y_keys}")
        print(f"  Norm keys: {self.plotModel._current_norm_keys}")

        print("\n=== End Debug Info ===\n")


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
