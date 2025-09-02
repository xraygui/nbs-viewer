import matplotlib
import time as ttime

matplotlib.use("qtagg")
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from qtpy.QtCore import Qt, QSize, QTimer, QThread, Signal, Slot
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
from nbs_viewer.utils import print_debug, time_function, DEBUG_VARIABLES
import uuid


class PlotWorker(QThread):
    """Worker thread for fetching and preparing plot data."""

    data_ready = Signal(object, object, object, object)  # (x, y, plotData, artist)
    error_occurred = Signal(str)

    def __init__(self, plotData, slice_info, dimension, artist=None):
        super().__init__()
        self.plotData = plotData
        self.slice_info = slice_info
        self.dimension = dimension
        self.artist = artist
        print_debug("PlotWorker", "Created new worker", category="DEBUG_PLOTS")

    @time_function(function_name="PlotWorker.run", category="DEBUG_PLOTS")
    def run(self):
        """Fetch and prepare the plot data."""
        try:
            print_debug("PlotWorker", "Starting data fetch", category="DEBUG_PLOTS")
            t1 = ttime.time()
            x, y = self.plotData.get_plot_data(self.slice_info, self.dimension)
            t2 = ttime.time()
            print_debug(
                "PlotWorker",
                f"Data fetch complete - x shape: {[xi.shape for xi in x]}, y shape: {y.shape}, time: {t2 - t1:.2f} seconds",
                category="DEBUG_PLOTS",
            )
            self.data_ready.emit(x, y, self.plotData, self.artist)
        except Exception as e:
            error_msg = f"Error fetching plot data: {str(e)}"
            print_debug("PlotWorker", error_msg, category="DEBUG_PLOTS")
            self.error_occurred.emit(error_msg)


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
    def __init__(self, run_list_model, parent=None, width=5, height=4, dpi=100):
        # Create figure with tight layout and proper spacing
        self.fig = Figure(figsize=(width, height), dpi=dpi, constrained_layout=True)

        # Create axes with explicit spacing from edges
        self.axes = self.fig.add_subplot(111)

        # Initialize canvas
        super().__init__(self.fig)
        self.setParent(parent)

        # Store plot model
        self.run_list_model = run_list_model
        self.plotArtists = {}
        self.workers = {}  # Store active workers

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
        # self.run_list_model.selected_keys_changed.connect(self._on_selected_keys_changed)
        self.run_list_model.run_removed.connect(self._on_run_removed)
        self.run_list_model.request_plot_update.connect(self.updatePlot)

    def sizeHint(self):
        width = self.width()
        height = int(width / self.aspect_ratio)
        return QSize(width, height)

    def heightForWidth(self, width):
        return int(width / self.aspect_ratio)

    def update_view_state(self, indices, dimension, validate=False):
        """Update the plot dimension and validate the change."""
        print_debug(
            "MplCanvas.update_view_state",
            f"indices={indices}, dimension={dimension}, validate={validate}",
        )
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

        # Only clear if dimension changes
        if self._dimension != dimension:
            self.clear()
            self._dimension = dimension

        # Always update slice indices
        if self._slice != indices:
            self._slice = indices
            self.updatePlot()

        return True

    def updatePlotData(self, runModel, xkey, ykey, norm_keys=None):
        key = (xkey, ykey, runModel.uid)
        print_debug(
            "MplCanvas.updatePlotData",
            f"Updating plot with {xkey} and {ykey}",
            category="DEBUG_PLOTS",
        )
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
            print_debug(
                "MplCanvas.updatePlotData",
                f"Adding plotData {plotData.label} to plotArtists",
                category="DEBUG_PLOTS",
            )
            self.plotArtists[key] = plotData
            self.plot_data(plotData)
        else:
            print_debug(
                "MplCanvas.updatePlotData",
                f"Updating plotData {self.plotArtists[key].label}",
                category="DEBUG_PLOTS",
            )
            self.plotArtists[key].update_data_info(
                norm_keys=norm_keys, indices=self._slice, dimension=self._dimension
            )

    def _on_selected_keys_changed(self, xkeys, ykeys, normkeys):
        """Handle changes in selected keys."""
        self.updatePlot()

    def _on_run_removed(self, run):
        """Handle removal of a run."""
        self.remove_run_data(run.uid)

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
        try:
            visible_keys = set()

            for runModel in self.run_list_model.visible_models:
                xkeys, ykeys, normkeys = runModel.get_selected_keys()
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
        This now creates and starts a worker thread for data fetching.

        Parameters
        ----------
        plotData : PlotDataModel
            The plot data model containing the data to plot
        """
        # Create worker for this plot
        worker_key = str(uuid.uuid4())
        model_key = plotData._key
        worker = PlotWorker(plotData, self._slice, self._dimension)
        worker.data_ready.connect(self._handle_plot_data)
        worker.error_occurred.connect(self._handle_plot_error)
        worker.finished.connect(lambda: self._cleanup_worker((model_key, worker_key)))

        # Store worker reference and start it
        self.workers[(model_key, worker_key)] = worker
        worker.start()

    @time_function(function_name="MplCanvas._handle_plot_data", category="DEBUG_PLOTS")
    def _handle_plot_data(self, x, y, plotData, artist=None):
        """Handle the plotting once data is ready."""
        if artist is None:
            artist = plotData.artist
        print_debug(
            "MplCanvas._handle_plot_data",
            f"Plotting {plotData.label}",
            category="DEBUG_PLOTS",
        )
        # Handle 1D data (line plots)
        if len(y.shape) == 1:
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
            try:
                y = y.T  # Transpose the data
                X = x[-2].T
                Y = x[-1].T  # Swap x[-1] and x[-2]

                if self.currentDim != 2:
                    # First time showing 2D plot, need full setup
                    if hasattr(self, "colorbar") and self.colorbar is not None:
                        self.colorbar.remove()
                        self.colorbar = None

                    old_axes = self.axes
                    self.fig.delaxes(old_axes)
                    self.axes = self.fig.add_subplot(111)

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
                    # Update existing 2D plot
                    if (
                        hasattr(self.axes, "collections")
                        and len(self.axes.collections) > 0
                    ):
                        # Update existing mesh
                        mesh = self.axes.collections[0]
                        mesh.set_array(y.ravel())
                        mesh.set_clim(vmin=y.min(), vmax=y.max())
                        if self.colorbar is not None:
                            self.colorbar.update_normal(mesh)
                        artist = mesh
                    else:
                        # Create new mesh if none exists
                        mesh = self.axes.pcolormesh(
                            X, Y, y, shading="nearest", label=plotData.label
                        )
                        if self.colorbar is None:
                            self.colorbar = self.fig.colorbar(mesh, ax=self.axes)
                            self.colorbar.set_label(plotData.label)
                        artist = mesh

                    # Update axis limits if needed
                    self.axes.set_xlim(X.min(), X.max())
                    self.axes.set_ylim(Y.min(), Y.max())

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

    def _handle_plot_error(self, error_msg):
        """Handle errors that occur during plotting."""
        print(f"[MplCanvas] Plot error: {error_msg}")

    def _cleanup_worker(self, key):
        """Clean up the worker thread."""
        if key in self.workers:
            worker = self.workers.pop(key)
            try:
                # Disconnect all signals
                worker.data_ready.disconnect()
                worker.error_occurred.disconnect()
                worker.quit()
                worker.wait()
                worker.deleteLater()
            except Exception as e:
                print(f"[MplCanvas._cleanup_worker] Error: {e}")

    def clear(self):
        """Clear all visual artists from the axes but keep plotDataModel references."""
        # Stop any active workers
        print_debug("MplCanvas.clear", "Starting Clear", category="DEBUG_PLOTS")
        for key in list(self.workers.keys()):
            # Disconnect all signals
            self._cleanup_worker(key)

        # First remove the colorbar if it exists
        if hasattr(self, "colorbar") and self.colorbar is not None:
            try:
                self.colorbar.remove()
            except Exception as e:
                print(f"[MplCanvas.clear] Error removing colorbar: {e}")
            self.colorbar = None

        # Store reference to old axes
        old_axes = self.axes

        # Create new axes
        self.axes = self.fig.add_subplot(111)

        # Remove old axes from figure
        if old_axes in self.fig.axes:
            try:
                self.fig.delaxes(old_axes)
            except Exception as e:
                print(f"[MplCanvas.clear] Error removing old axes: {e}")

        # Clear all collections and lines from new axes
        while self.axes.collections:
            try:
                self.axes.collections[0].remove()
            except Exception as e:
                print(f"[MplCanvas.clear] Error removing collection: {e}")
                break

        while self.axes.lines:
            try:
                self.axes.lines[0].remove()
            except Exception as e:
                print(f"[MplCanvas.clear] Error removing line: {e}")
                break

        # Reset states but keep plotArtists
        self.currentDim = 1
        self._artist_count = 0

        # Clear artist references in plotDataModels but keep the models
        for model in self.plotArtists.values():
            model.artist = None

        # Force a redraw to ensure clean state
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
        print_debug("MplCanvas._do_draw", "Drawing", category="DEBUG_PLOTS")
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
        print_debug(
            "MplCanvas.remove_run_data",
            f"Removing run {run_uid}",
            category="DEBUG_PLOTS",
        )

        # First find all keys associated with this run
        keys_to_remove = [key for key in self.plotArtists.keys() if key[2] == run_uid]

        # Stop any active workers for this run
        worker_keys = [key for key in self.workers.keys() if key[0][2] == run_uid]
        for key in worker_keys:
            self._cleanup_worker(key)

        # Remove each PlotDataModel
        for key in keys_to_remove:
            plot_data = self.plotArtists[key]

            # First disconnect all signals to prevent any callbacks during cleanup
            plot_data.data_changed.disconnect(self.plot_data)
            plot_data.draw_requested.disconnect(self.draw)
            plot_data.autoscale_requested.disconnect(self.autoscale)
            plot_data.visibility_changed.disconnect()

            # Remove from our dictionary before clearing the artist
            # to prevent any redraw attempts during cleanup
            del self.plotArtists[key]

            # Now clear the artist
            plot_data.clear()

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

        print("\nActive Workers:")
        print(f"  Total Active Workers: {len(self.workers)}")
        for key, worker in self.workers.items():
            plotData = self.plotArtists[key[0]]
            print(f"  Worker for {plotData.label}:")
            print(f"    Thread ID: {worker.currentThreadId()}")
            print(f"    Is Running: {worker.isRunning()}")
            print(f"    Is Finished: {worker.isFinished()}")

        print("\nPlot Data Models:")
        for key, model in self.plotArtists.items():
            print(f"\n  Model: {key}")
            print(f"    Label: {model.label}")
            print(f"    Has Artist: {model.artist is not None}")
            hasWorker = False
            for worker_key in self.workers.keys():
                if worker_key[0] == key:
                    hasWorker = True
                    break
            print(f"    Has Active Worker: {hasWorker}")
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

    def __init__(self, run_list_model, parent=None):
        super().__init__(parent)
        self.run_list_model = run_list_model

        # Create plot canvas
        self.plot_canvas = MplCanvas(self.run_list_model, self, 5, 4, 100)

        # Create toolbar
        self.plot_toolbar = NavigationToolbar(self.plot_canvas, self)

        # Create dimension control widget
        self.dimension_control = PlotDimensionControl(
            self.run_list_model, self.plot_canvas, self
        )

        # Create plot controls (for data selection)
        self.plot_controls = PlotControls(self.run_list_model)

        # Add debug button if needed
        if DEBUG_VARIABLES["PRINT_DEBUG"]:
            self.debug_button = QPushButton("Debug Plot State")
            self.debug_button.clicked.connect(self._debug_plot_state)
        else:
            self.debug_button = None

        # Create plot-specific layout (canvas + toolbar + dimension controls)
        plot_layout = QVBoxLayout(self)
        plot_layout.setContentsMargins(0, 0, 0, 0)

        # Add toolbar
        plot_layout.addWidget(self.plot_toolbar)

        # Add canvas
        plot_layout.addWidget(self.plot_canvas)

        # Add dimension control
        plot_layout.addWidget(self.dimension_control)

        # Add debug button if available
        if self.debug_button:
            plot_layout.addWidget(self.debug_button)

        # Connect to model signals for cleanup
        self.run_list_model.run_removed.connect(self._on_run_removed)

    def _on_run_removed(self, run):
        """Handle run removal by cleaning up associated PlotDataModels."""
        self.plot_canvas.remove_run_data(run.uid)

    def _debug_plot_state(self):
        """Print debug information about plot state."""
        print("\n=== Plot State Debug Info ===")

        # Canvas State
        print("\nMplCanvas State:")
        self.plot_canvas._debug_plot_state()

        # Plot Model State
        print("\nPlot Model State:")
        print("  Available Runs:")
        for run_model in self.run_list_model._run_models.values():
            print(f"    - {run_model._run.display_name} (uid: {run_model._run.uid})")

        print("\n  Visible Runs:")
        for uid in self.run_list_model._visible_runs:
            if uid in self.run_list_model._run_models:
                run = self.run_list_model._run_models[uid]._run
                print(f"    - {run.display_name} (uid: {uid})")
            else:
                print(f"    - WARNING: Visible uid {uid} not in run models!")

        print("\n  Current Selection:")
        print(f"    X keys: {self.run_list_model._current_x_keys}")
        print(f"    Y keys: {self.run_list_model._current_y_keys}")
        print(f"    Norm keys: {self.run_list_model._current_norm_keys}")

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
