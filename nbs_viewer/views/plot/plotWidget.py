import matplotlib

matplotlib.use("Qt5Agg")
import numpy as np
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT as NavigationToolbar2QT,
)
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from qtpy.QtCore import Qt, QSize, QTimer
from qtpy.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QSizePolicy,
    QSplitter,
    QPushButton,
    QMessageBox,
)

from ...models.plot.plotDataModel import PlotDataModel
from .plotDimensionWidget import PlotDimensionControl
from .plotControl import PlotControls
from functools import partial


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
            self.canvas._legend_visible = True
        else:
            legend.set_visible(False)
            self.canvas._legend_visible = False
            self.canvas.draw()


class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, plotModel, parent=None, width=5, height=4, dpi=100):
        # Create figure with tight layout and proper spacing
        self.fig = Figure(figsize=(width, height), dpi=dpi, constrained_layout=True)

        # Create axes with explicit spacing from edges
        self.axes = self.fig.add_subplot(111)

        # Initialize canvas
        super().__init__(self.fig)
        self.setParent(parent)

        # Store plot model
        self.plotModel = plotModel
        self.plotArtists = {}

        # Initialize properties
        self._artist_count = 0
        self._autoscale = True
        self._draw_pending = False
        self._dimension = 1  # Default to 1D plotting
        self._slice = None
        self._legend_visible = True

        self.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))
        self.aspect_ratio = width / height

        # Connect signals
        self.plotModel.request_plot_update.connect(self.updatePlot)

    def sizeHint(self):
        width = self.width()
        height = int(width / self.aspect_ratio)
        return QSize(width, height)

    def heightForWidth(self, width):
        return int(width / self.aspect_ratio)

    def update_view_state(self, indices, dimension, validate=False):
        """Update the plot dimension and validate the change."""
        # print("Update_view_state")
        if dimension == 2 and validate:
            visible_count = 0
            for model in self.plotArtists.values():
                if model.artist is not None and model.artist.get_visible():
                    visible_count += 1

            # print(f"Visible count: {visible_count}")
            if visible_count > 1:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Warning)
                msg.setText("Cannot switch to 2D mode with multiple datasets")
                msg.setInformativeText(
                    "Please select only one dataset for 2D plotting."
                )
                msg.setWindowTitle("Invalid Plot Configuration")
                msg.exec_()
                return False

        if self._dimension != dimension or self._slice != indices:
            self.clear()
            self._dimension = dimension
            self._slice = indices
            self.updatePlot()
            # Force autoscale and legend update after dimension change

        return True

    def updatePlotData(self, runModel, xkey, ykey, norm_keys=None):
        key = (xkey, ykey, runModel.uid)
        if key not in self.plotArtists:
            plotData = PlotDataModel(
                runModel,
                xkey,
                ykey,
                norm_keys=norm_keys,
                indices=self._slice,
                dimension=self._dimension,
            )
            plotData.data_changed.connect(self.plot_data)
            plotData.draw_requested.connect(self.draw)
            plotData.autoscale_requested.connect(self.autoscale)
            plotData.visibility_changed.connect(lambda visible: self.updateLegend())
            self.plotArtists[key] = plotData
            self.plot_data(plotData)
        else:
            self.plotArtists[key].update_data_info(
                norm_keys=norm_keys, indices=self._slice, dimension=self._dimension
            )

    def updatePlot(self):
        """
        Update the plot with current data, using a timer to batch rapid updates.
        """
        if hasattr(self, "_update_timer_active") and self._update_timer_active:
            return

        self._update_timer_active = True
        QTimer.singleShot(100, self._do_update_plot)

    def _do_update_plot(self):
        """
        Actually perform the plot update.
        """
        if self._dimension > 1:
            self.clear()
        try:
            xkeys, ykeys, normkeys = self.plotModel.get_selected_keys()
            visible_keys = set()
            for runModel in self.plotModel.visible_models:
                for xkey in xkeys:
                    for ykey in ykeys:
                        visible_keys.add((xkey, ykey, runModel.uid))
                        self.updatePlotData(runModel, xkey, ykey, normkeys)

            for key, plotDataModel in self.plotArtists.items():
                if key not in visible_keys:
                    plotDataModel.set_visible(False)
                else:
                    plotDataModel.set_visible(True)
            if self._autoscale:
                self.autoscale()
            self.draw()
        finally:
            self._update_timer_active = False

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

    def plot_data(self, plotData):
        """
        Plot data from a PlotDataModel on the canvas.

        Parameters
        ----------
        plotData : PlotDataModel
            The plot data model containing the data to plot

        Returns
        -------
        Artist
            The matplotlib artist representing the plotted data
        """
        x, y = plotData.get_plot_data(self._slice, self._dimension)
        artist = plotData.artist
        # print(f"Plotting data for {plotData.label}")
        # Handle 1D data (line plots)
        if len(y.shape) == 1:
            # print(f"Plotting 1D data for {plotData.label}")
            if isinstance(artist, Line2D):
                artist.set_data(x[0], y)
            else:
                artist = self.axes.plot(x[0], y, clip_on=True, label=plotData.label)[0]
                self._artist_count += 1

            # Set axis labels if we have them
            if len(x) > 0 and hasattr(plotData, "dimension_names"):
                self.axes.set_xlabel(plotData.dimension_names[0])

            self.fig.tight_layout()
            if self._autoscale:
                self.autoscale()
            self.updateLegend()
            self.currentDim = 1

        # Handle 2D data (heatmap/image plots)
        elif len(y.shape) == 2 and len(x) >= 2:
            # print(f"Plotting 2D data for {plotData.label}")
            try:
                if self.currentDim != 2:
                    # Clean up old colorbar if it exists
                    if hasattr(self, "colorbar") and self.colorbar is not None:
                        try:
                            self.colorbar.remove()
                        except Exception as e:
                            print(f"[MplCanvas.plot_data] Error removing colorbar: {e}")
                        self.colorbar = None

                    old_axes = self.axes
                    self.fig.delaxes(old_axes)
                    self.axes = self.fig.add_subplot(111)

                    # Transpose the data and create meshgrid with swapped coordinates
                    y = y.T  # Transpose the data
                    X, Y = np.meshgrid(x[-2], x[-1])  # Swap x[-1] and x[-2]

                    mesh = self.axes.pcolormesh(
                        X, Y, y, shading="nearest", label=plotData.label
                    )
                    self.colorbar = self.fig.colorbar(mesh, ax=self.axes)
                    self.colorbar.set_label(plotData.label)

                    # Set axis labels if we have them
                    if hasattr(plotData, "dimension_names"):
                        self.axes.set_xlabel(plotData.dimension_names[-2])
                        self.axes.set_ylabel(plotData.dimension_names[-1])

                    artist = mesh
                    self.currentDim = 2
                else:
                    if (
                        hasattr(self.axes, "collections")
                        and len(self.axes.collections) > 0
                    ):
                        y = y.T  # Transpose the data
                        X, Y = np.meshgrid(x[-2], x[-1])  # Swap x[-1] and x[-2]
                        self.axes.collections[0].set_array(y.ravel())
                        artist = self.axes.collections[0]
                    else:
                        y = y.T  # Transpose the data
                        X, Y = np.meshgrid(x[-2], x[-1])  # Swap x[-1] and x[-2]
                        mesh = self.axes.pcolormesh(
                            X, Y, y, shading="nearest", label=plotData.label
                        )
                        # Clean up old colorbar if it exists
                        if hasattr(self, "colorbar") and self.colorbar is not None:
                            try:
                                self.colorbar.remove()
                            except Exception as e:
                                print(
                                    f"[MplCanvas.plot_data] Error removing colorbar: {e}"
                                )
                            self.colorbar = None
                        self.colorbar = self.fig.colorbar(mesh, ax=self.axes)
                        self.colorbar.set_label(plotData.label)

                        # Set axis labels if we have them
                        if hasattr(plotData, "dimension_names"):
                            self.axes.set_xlabel(plotData.dimension_names[-2])
                            self.axes.set_ylabel(plotData.dimension_names[-1])

                        artist = mesh
            except Exception as e:
                print(f"[MplCanvas.plot_data] Error in 2D plotting: {e}")
                artist = None
        else:
            print(
                f"[MplCanvas.plot_data] Unsupported dimensionality! {y.shape}, {len(x)}"
            )
            artist = None
        plotData.set_artist(artist)
        self.draw()
        return artist

    def clear(self):
        """Clear all visual artists from the axes but keep plotDataModel references."""
        # Remove line artists
        for line in self.axes.get_lines():
            line.remove()

        # Remove mesh/collection artists (for 2D plots)
        for collection in self.axes.collections:
            try:
                collection.remove()
            except Exception as e:
                print(f"[MplCanvas.clear] Error cleaning up collection: {e}")

        # Remove colorbar if it exists
        if hasattr(self, "colorbar"):
            try:
                if self.colorbar is not None:
                    self.colorbar.remove()
            except Exception as e:
                print(f"[MplCanvas.clear] Error removing colorbar: {e}")
            self.colorbar = None

        # Clear the figure and axes
        self.axes.cla()
        self.fig.clear()
        self.axes = self.fig.add_subplot(111)

        # Reset states but keep plotArtists
        self.currentDim = 1
        self._artist_count = 0

        # Clear artist references in plotDataModels but keep the models
        for model in self.plotArtists.values():
            model.artist = None

        self.draw()

    def updateLegend(self):
        """Update the plot legend to show only visible lines."""
        # Clear existing legend first
        legend = self.axes.get_legend()
        if legend is None or not legend.get_visible():
            if not self._legend_visible:
                return

        if self.axes.get_legend():
            self.axes.get_legend().remove()
        # Get visible lines and their labels, filtering out empty labels
        visible_lines = [
            line
            for line in self.axes.get_lines()
            if line.get_visible()
            and line.get_label()
            and not line.get_label().startswith("_")
        ]

        if visible_lines:
            labels = [line.get_label() for line in visible_lines]
            self.axes.legend(visible_lines, labels)

        self.draw()

    def autoscale(self):
        """Autoscale the plot based on visible data."""
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
                # Filter out inf/nan values
                valid_y = ydata[np.isfinite(ydata)]
                valid_x = xdata[np.isfinite(xdata)]
                if len(valid_y) > 0 and len(valid_x) > 0:
                    y_min.append(np.min(valid_y))
                    y_max.append(np.max(valid_y))
                    x_min.append(np.min(valid_x))
                    x_max.append(np.max(valid_x))

        if len(y_min) > 0:
            y_min = min(y_min)
            y_max = max(y_max)
            x_min = min(x_min)
            x_max = max(x_max)
        else:
            print("No valid data to autoscale")
            return

        yspan = y_max - y_min
        if yspan > 0:
            self.axes.set_ylim(y_min - 0.05 * yspan, y_max + 0.05 * yspan)

        xspan = x_max - x_min
        if xspan > 0:
            self.axes.set_xlim(x_min - 0.05 * xspan, x_max + 0.05 * xspan)

        self.draw()

    def draw(self):
        """Draw the figure with throttling."""
        if not self._draw_pending:
            self._draw_pending = True
            QTimer.singleShot(16, self._do_draw)  # About 60fps

    def _do_draw(self):
        """Actually perform the draw operation."""
        self._draw_pending = False
        # print("Drawing MplCanvas")
        # Call parent class draw
        super().draw()

    def remove_run_data(self, run_uid):
        """
        Remove all PlotDataModels associated with a specific run.

        Parameters
        ----------
        run_uid : str
            The unique identifier of the run to remove
        """
        # print(f"Removing PlotDataModels for run {run_uid}")
        # Find all keys associated with this run
        keys_to_remove = [key for key in self.plotArtists.keys() if key[2] == run_uid]

        # Remove each PlotDataModel
        for key in keys_to_remove:
            # print(f"  Removing PlotDataModel for {key}")
            plot_data = self.plotArtists[key]

            # Disconnect signals
            plot_data.data_changed.disconnect(self.plot_data)
            plot_data.draw_requested.disconnect(self.draw)
            plot_data.autoscale_requested.disconnect(self.autoscale)

            # Remove the artist from the axes
            plot_data.clear()

            # Remove from our dictionary
            del self.plotArtists[key]

        # Update legend and redraw if we removed anything
        if keys_to_remove:
            self.updateLegend()
            self.draw()

    def _debug_plot_state(self):
        """Print debug information about canvas state."""
        print("\n=== MplCanvas Debug Info ===")
        print(f"Current Dimension: {self._dimension}")
        print(f"Current Slice: {self._slice}")
        print(f"Artist Count: {self._artist_count}")
        print(f"Autoscale Enabled: {self._autoscale}")
        print("\nPlot Data Models:")
        for key, model in self.plotArtists.items():
            print(f"\n  Model: {key}")
            print(f"    Label: {model.label}")
            print(f"    Has Artist: {model.artist is not None}")
            if model.artist is not None:
                print(f"    Artist Type: {type(model.artist).__name__}")
                print(f"    Artist Visible: {model.artist.get_visible()}")

                # Matplotlib State
        print("\nMatplotlib State:")
        print(f"  Number of Lines: {len(self.axes.get_lines())}")
        print(f"  Number of Collections: {len(self.axes.collections)}")
        print("  Artists:")
        for artist in self.axes.get_lines():
            print(f"    - Line: {artist.get_label()} (visible: {artist.get_visible()})")
        for artist in self.axes.collections:
            print(
                f"    - Collection: {artist.get_label()} (visible: {artist.get_visible()})"
            )
        if hasattr(self, "colorbar"):
            print("  Colorbar: Present")
        else:
            print("  Colorbar: None")

        print("\n=== End MplCanvas Debug Info ===")


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
        self.debug_button = QPushButton("Debug Plot State")
        self.debug_button.clicked.connect(self._debug_plot_state)
        self.plot_layout.addWidget(self.debug_button)

        # Add dimension control widget
        self.dimension_control = PlotDimensionControl(self.plotModel, self.plot, self)
        self.plot_layout.addWidget(self.dimension_control)

        # Create plot controls
        self.plotControls = PlotControls(self.plotModel)

        # Add widgets to splitter
        self.layout.addWidget(self.plot_container)
        self.layout.addWidget(self.plotControls)

        # Create main layout and add splitter
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.layout)

        # Connect to model signals for cleanup
        self.plotModel.run_removed.connect(self._on_run_removed)

    def _on_run_removed(self, run):
        """Handle run removal by cleaning up associated PlotDataModels."""
        self.plot.remove_run_data(run.uid)

    def _debug_plot_state(self):
        """Print debug information about plot state."""
        print("\n=== Plot State Debug Info ===")

        # Canvas State
        print("\nMplCanvas State:")
        self.plot._debug_plot_state()

        # Plot Model State
        print("\nPlot Model State:")
        print("  Available Runs:")
        for run_model in self.plotModel._run_models.values():
            print(f"    - {run_model._run.display_name} (uid: {run_model._run.uid})")

        print("\n  Visible Runs:")
        for uid in self.plotModel._visible_runs:
            if uid in self.plotModel._run_models:
                run = self.plotModel._run_models[uid]._run
                print(f"    - {run.display_name} (uid: {uid})")
            else:
                print(f"    - WARNING: Visible uid {uid} not in run models!")

        print("\n  Current Selection:")
        print(f"    X keys: {self.plotModel._current_x_keys}")
        print(f"    Y keys: {self.plotModel._current_y_keys}")
        print(f"    Norm keys: {self.plotModel._current_norm_keys}")

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
