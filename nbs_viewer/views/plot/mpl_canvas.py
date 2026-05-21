import matplotlib

matplotlib.use("qtagg")

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
from matplotlib.lines import Line2D
from qtpy.QtCore import QSize, QTimer, Signal
from qtpy.QtWidgets import QMessageBox, QSizePolicy

from ...models.plot.plotDataModel import PlotDataModel
from ...models.plot.plot_geometry import PlotBundle, RenderMode
from nbs_viewer.utils import print_debug, time_function, DEBUG_VARIABLES
from .mpl_renderers import ImageRenderer, LineRenderer, MeshRenderer, remove_2d_artists
from .plot_worker import PlotWorker, retire_plot_worker


class NavigationToolbar(NavigationToolbar2QT):
    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent)
        self.addAction("Autoscale", self.autoscale)
        self.addAction("Autolegend", self.autolegend)

    def autoscale(self):
        self.canvas.autoscale()
        self.canvas.draw()

    def autolegend(self):
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
        self.fig = Figure(figsize=(width, height), dpi=dpi, constrained_layout=True)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)

        self.run_list_model = run_list_model
        self.plotArtists = {}
        self._worker_generations = {}
        self._active_workers = {}
        self._pending_workers = set()
        self._last_2d_plot_key = None

        self._artist_count = 0
        self._autoscale = True
        self._draw_pending = False
        self._dimension = 1
        self._slice = None
        self._legend_visible = True
        self._active_render_mode = None
        self._colorbar_state = {}
        self.currentDim = 1

        self.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))
        self.aspect_ratio = width / height

        self.run_list_model.run_removed.connect(self._on_run_removed)
        self.run_list_model.request_plot_update.connect(self.updatePlot)

    def sizeHint(self):
        width = self.width()
        height = int(width / self.aspect_ratio)
        return QSize(width, height)

    def heightForWidth(self, width):
        return int(width / self.aspect_ratio)

    def update_view_state(self, indices, dimension, validate=False):
        print_debug(
            "MplCanvas.update_view_state",
            f"indices={indices}, dimension={dimension}, validate={validate}",
        )
        if dimension == 2 and validate:
            visible_count = sum(
                1
                for model in self.plotArtists.values()
                if model.artist is not None and model.artist.get_visible()
            )
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

        if self._dimension != dimension:
            self.clear()
            self._dimension = dimension

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
            plotData.visibility_changed.connect(lambda _v: self.updateLegend())
            plotData.render_mode_changed.connect(self._on_render_mode_changed)
            self.plotArtists[key] = plotData
            self.plot_data(plotData)
        else:
            self.plotArtists[key].update_data_info(
                norm_keys=norm_keys, indices=self._slice, dimension=self._dimension
            )

    def _on_render_mode_changed(self, plot_data, mode):
        print_debug(
            "MplCanvas",
            f"Render mode changed to {mode} for {plot_data.label}",
            category="DEBUG_PLOTS",
        )
        if plot_data.artist is not None:
            plot_data.clear()
        self._reset_plot_axes()

    def _on_run_removed(self, run):
        self.remove_run_data(run.uid)

    def updatePlot(self):
        self._update_timer = getattr(self, "_update_timer", None)
        if self._update_timer is not None:
            self._update_timer.stop()
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._do_update_plot)
        self._update_timer.start(100)

    def _do_update_plot(self):
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
                    plotDataModel.clear()
                else:
                    plotDataModel.set_visible(True)
            if self._autoscale:
                self.autoscale()
            self.draw()
        except Exception as e:
            print_debug("MplCanvas._do_update_plot", str(e), category="DEBUG_PLOTS")

    def plot_data(self, plotData):
        model_key = plotData._key
        generation = self._worker_generations.get(model_key, 0) + 1
        self._worker_generations[model_key] = generation

        old_worker = self._active_workers.pop(model_key, None)
        retire_plot_worker(old_worker, self._pending_workers)

        print_debug(
            "MplCanvas.plot_data",
            f"Worker gen={generation} for {plotData.label}",
            category="DEBUG_PLOTS",
        )
        worker = PlotWorker(
            plotData, self._slice, self._dimension, generation, plotData.artist
        )
        worker.data_ready.connect(self._handle_plot_data)
        worker.error_occurred.connect(self._handle_plot_error)
        worker.finished.connect(
            lambda mk=model_key, w=worker: self._on_plot_worker_finished(mk, w)
        )
        self._active_workers[model_key] = worker
        worker.start()

    def _on_plot_worker_finished(self, model_key, worker):
        if self._active_workers.get(model_key) is worker:
            self._active_workers.pop(model_key, None)

    @time_function(function_name="MplCanvas._handle_plot_data", category="DEBUG_PLOTS")
    def _handle_plot_data(self, bundle, plotData, artist, generation):
        model_key = plotData._key
        if generation != self._worker_generations.get(model_key):
            print_debug(
                "MplCanvas._handle_plot_data",
                f"Stale worker gen={generation}, skipping",
                category="DEBUG_PLOTS",
            )
            return

        if artist is None:
            artist = plotData.artist

        print_debug(
            "MplCanvas._handle_plot_data",
            f"Plotting {plotData.label} mode={bundle.render_mode}",
            category="DEBUG_PLOTS",
        )

        try:
            if bundle.render_mode == "line":
                self._last_2d_plot_key = None
                artist = self._render_line(bundle, plotData, artist)
                self.currentDim = 1
                self._active_render_mode = "line"
            elif bundle.render_mode == "image":
                self._prepare_2d_axes(plotData._key)
                artist = self._render_image(bundle, plotData, artist)
                self.currentDim = 2
                self._active_render_mode = "image"
            elif bundle.render_mode == "mesh":
                self._prepare_2d_axes(plotData._key)
                artist = self._render_mesh(bundle, plotData, artist)
                self.currentDim = 2
                self._active_render_mode = "mesh"
        except Exception as e:
            print(f"[MplCanvas._handle_plot_data] Error: {e}")
            artist = None

        plotData.set_artist(artist)
        self.draw()

    def _render_line(self, bundle: PlotBundle, plotData, artist):
        if isinstance(artist, Line2D):
            LineRenderer.update(artist, bundle)
        else:
            artist = LineRenderer.create(self.axes, bundle, plotData.label)
            self._artist_count += 1
        LineRenderer.set_labels(self.axes, bundle)
        if self._autoscale:
            self.autoscale()
        self.updateLegend()
        return artist

    def _render_image(self, bundle: PlotBundle, plotData, artist):
        if isinstance(artist, AxesImage):
            ImageRenderer.update(
                artist, bundle, self._autoscale, self._colorbar_state
            )
        else:
            artist, _cbar = ImageRenderer.create(
                self.axes,
                self.fig,
                bundle,
                plotData.label,
                self._colorbar_state,
            )
        return artist

    def _render_mesh(self, bundle: PlotBundle, plotData, artist):
        artist, _cbar = MeshRenderer.create(
            self.axes,
            self.fig,
            bundle,
            plotData.label,
            self._colorbar_state,
        )
        return artist

    def _prepare_2d_axes(self, plot_key):
        if (
            self._last_2d_plot_key != plot_key
            or self._active_render_mode not in ("image", "mesh")
            or self.currentDim != 2
        ):
            self._reset_plot_axes()
        self._last_2d_plot_key = plot_key

    def _reset_plot_axes(self):
        remove_2d_artists(self.axes, self._colorbar_state, self.fig)
        while self.axes.lines:
            try:
                self.axes.lines[0].remove()
            except Exception:
                break
        self._active_render_mode = None

    def _handle_plot_error(self, error_msg):
        print(f"[MplCanvas] Plot error: {error_msg}")

    def clear(self):
        print_debug("MplCanvas.clear", "Starting Clear", category="DEBUG_PLOTS")

        for model_key in list(self._active_workers.keys()):
            worker = self._active_workers.pop(model_key, None)
            retire_plot_worker(worker, self._pending_workers)
        self._worker_generations.clear()

        old_axes = self.axes
        self.axes = self.fig.add_subplot(111)
        if old_axes in self.fig.axes:
            try:
                self.fig.delaxes(old_axes)
            except Exception as e:
                print(f"[MplCanvas.clear] Error removing old axes: {e}")

        self._colorbar_state.clear()
        self._last_2d_plot_key = None
        self.currentDim = 1
        self._active_render_mode = None
        self._artist_count = 0

        for model in self.plotArtists.values():
            model.artist = None

        self.draw()

    def updateLegend(self):
        legend = self.axes.get_legend()
        if legend is None or not legend.get_visible():
            if not self._legend_visible:
                return

        if self.axes.get_legend():
            self.axes.get_legend().remove()

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
        if self._active_render_mode == "image":
            for image in self.axes.images:
                if image.get_visible():
                    data = image.get_array()
                    if data is not None and data.size > 0:
                        finite = data[np.isfinite(data)]
                        if finite.size > 0:
                            image.set_clim(
                                float(np.min(finite)), float(np.max(finite))
                            )
            cbar = self._colorbar_state.get("colorbar")
            if cbar is not None:
                cbar.update_ticks()
            self.draw()
            return

        if self._active_render_mode == "mesh":
            for collection in self.axes.collections:
                if collection.get_visible() and hasattr(collection, "get_array"):
                    arr = np.asarray(collection.get_array())
                    if arr.size > 0:
                        finite = arr[np.isfinite(arr)]
                        if finite.size > 0:
                            collection.set_clim(
                                float(np.min(finite)), float(np.max(finite))
                            )
            self.draw()
            return

        visible_lines = [
            line for line in self.axes.get_lines() if line.get_visible()
        ]
        if not visible_lines:
            return

        y_min, y_max, x_min, x_max = [], [], [], []
        for line in visible_lines:
            ydata = line.get_ydata()
            xdata = line.get_xdata()
            if len(ydata) > 0 and len(xdata) > 0:
                valid_y = ydata[np.isfinite(ydata)]
                valid_x = xdata[np.isfinite(xdata)]
                if len(valid_y) > 0 and len(valid_x) > 0:
                    y_min.append(np.min(valid_y))
                    y_max.append(np.max(valid_y))
                    x_min.append(np.min(valid_x))
                    x_max.append(np.max(valid_x))

        if not y_min:
            return

        y_min, y_max = min(y_min), max(y_max)
        x_min, x_max = min(x_min), max(x_max)
        yspan = y_max - y_min
        if yspan > 0:
            self.axes.set_ylim(y_min - 0.05 * yspan, y_max + 0.05 * yspan)
        xspan = x_max - x_min
        if xspan > 0:
            self.axes.set_xlim(x_min - 0.05 * xspan, x_max + 0.05 * xspan)
        self.draw()

    def draw(self):
        if not self._draw_pending:
            self._draw_pending = True
            QTimer.singleShot(16, self._do_draw)

    def _do_draw(self):
        self._draw_pending = False
        print_debug("MplCanvas._do_draw", "Drawing", category="DEBUG_PLOTS")
        super().draw()

    def remove_run_data(self, run_uid):
        print_debug(
            "MplCanvas.remove_run_data",
            f"Removing run {run_uid}",
            category="DEBUG_PLOTS",
        )
        keys_to_remove = [key for key in self.plotArtists if key[2] == run_uid]

        for key in keys_to_remove:
            self._worker_generations.pop(key, None)
            worker = self._active_workers.pop(key, None)
            retire_plot_worker(worker, self._pending_workers)

        for key in keys_to_remove:
            plot_data = self.plotArtists[key]
            plot_data.data_changed.disconnect(self.plot_data)
            plot_data.draw_requested.disconnect(self.draw)
            plot_data.autoscale_requested.disconnect(self.autoscale)
            try:
                plot_data.render_mode_changed.disconnect(
                    self._on_render_mode_changed
                )
            except Exception:
                pass
            plot_data.visibility_changed.disconnect()
            del self.plotArtists[key]
            plot_data.clear()

        if keys_to_remove:
            self._reset_plot_axes()
            self.updateLegend()
            self.draw()

    def _debug_plot_state(self):
        if not DEBUG_VARIABLES.get("PRINT_DEBUG"):
            return
        print("\n=== MplCanvas Debug Info ===")
        print(f"Current Dimension: {self._dimension}")
        print(f"Active Render Mode: {self._active_render_mode}")
        print(f"Current Slice: {self._slice}")
        for key, model in self.plotArtists.items():
            print(f"  {key}: mode={model.render_mode}, bundle={model.last_bundle}")
        print("=== End MplCanvas Debug Info ===\n")
