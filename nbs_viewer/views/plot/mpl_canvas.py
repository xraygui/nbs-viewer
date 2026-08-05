import matplotlib

matplotlib.use("qtagg")

from typing import Optional

import time as ttime
import traceback

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.widgets import RectangleSelector
from qtpy.QtCore import QSize, QTimer, Signal
from qtpy.QtWidgets import QMessageBox, QSizePolicy

from ...models.plot.cube_view import CubeViewSpec
from ...models.plot.plotDataModel import PlotDataModel
from ...models.plot.plot_geometry import PlotBundle, RenderMode
from ...models.plot.plot_view_frame import (
    PlotViewFrame,
    frame_from_bundle,
    view_fingerprint_from_bundle,
)
from ...models.plot.region import RectRegion
from ...models.plot.roi_set import RoiSetModel
from ...models.plot.view_crop import ViewCrop
from nbs_viewer.utils import print_debug, time_function, DEBUG_VARIABLES
from .mpl_renderers import ImageRenderer, LineRenderer, MeshRenderer, remove_2d_artists
from .plot_worker import PlotWorker, retire_plot_worker

_ROI_EDGE_WIDTH = 2.5
_ROI_HALO_WIDTH = 4.5
_ROI_FILL_ALPHA = 0.12
_ROI_STALE_FILL_ALPHA = 0.08
_CROP_SELECTOR_PROPS = dict(
    facecolor=to_rgba("#ff7f0e", 0.12),
    edgecolor="#ff7f0e",
    fill=True,
    linewidth=_ROI_EDGE_WIDTH,
    linestyle="--",
)
_CROP_OVERLAY_PROPS = dict(
    linewidth=_ROI_EDGE_WIDTH,
    edgecolor="#ff7f0e",
    facecolor=to_rgba("#ff7f0e", 0.10),
    fill=True,
    linestyle="--",
)


def _draw_caller_summary(skip=2, limit=6):
    """
    Return a compact caller chain for temporary draw instrumentation.

    Parameters
    ----------
    skip : int, optional
        Number of leading frames to omit (this helper and its caller).
    limit : int, optional
        Maximum number of frames to include.

    Returns
    -------
    str
        Compact ``file:line:func`` frames joined by `` <- ``.
    """
    frames = traceback.extract_stack(limit=skip + limit)[:-skip]
    parts = []
    for frame in frames[-limit:]:
        filename = frame.filename.rsplit("/", 1)[-1]
        parts.append(f"{filename}:{frame.lineno}:{frame.name}")
    return " <- ".join(parts) if parts else "?"


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
            self.canvas.draw()
        else:
            legend.set_visible(False)
            self.canvas._legend_visible = False
            self.canvas.draw()


class MplCanvas(FigureCanvasQTAgg):
    """
    Matplotlib canvas for run list plots.

    ``autoscale`` and ``updateLegend`` mutate axes state only; callers that
    need a paint must call :meth:`draw` (coalesced) themselves.

    Signals
    -------
    roi_region_changed : object
        Emitted with the selected ROI geometry or ``None``.
    crop_region_changed : object
        Emitted with the draft crop :class:`RectRegion` or ``None``.
    view_crop_changed : object
        Emitted with a :class:`ViewCrop` or ``None`` when the view crop changes.
    plot_view_updated : Signal
        Emitted after the visible plot view is updated.
    """

    roi_region_changed = Signal(object)
    crop_region_changed = Signal(object)
    view_crop_changed = Signal(object)
    plot_view_updated = Signal()

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
        self._last_2d_cube_view_spec = None
        self._last_view_frame: Optional[PlotViewFrame] = None

        self._artist_count = 0
        self._autoscale = True
        self._lock_aspect = True
        self._nbs_draw_pending = False
        self._nbs_draw_coalesce_count = 0
        self._nbs_in_do_draw = False
        self._dimension = 1
        self._slice = None
        self._cube_view_spec = None
        self._legend_visible = True
        self._active_render_mode = None
        self._colorbar_state = {}
        self.currentDim = 1
        self._roi_set: Optional[RoiSetModel] = None
        self._roi_selector = None
        self._roi_overlays = {}
        self._roi_draw_enabled = False
        self._crop_draft_region = None
        self._crop_selector = None
        self._crop_overlay = None
        self._crop_draw_enabled = False
        self._view_crop: Optional[ViewCrop] = None
        self._last_2d_view_crop = None

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

    def update_view_state(
        self, indices, dimension, validate=False, cube_view_spec=None
    ):
        print_debug(
            "MplCanvas.update_view_state",
            f"indices={indices}, dimension={dimension}, validate={validate}",
            category="plots",
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

        view_changed = self._slice != indices or self._cube_view_spec != cube_view_spec
        if view_changed:
            self._slice = indices
            self._cube_view_spec = cube_view_spec
            self.updatePlot()

        return True

    def updatePlotData(self, runModel, xkey, ykey, norm_keys=None):
        """
        Create or refresh a plot model for one x/y key pair.

        List-owned path: updates metadata without emitting ``data_changed`` and
        starts at most one worker when a refetch is needed.
        """
        key = (xkey, ykey, runModel.uid)
        if key not in self.plotArtists:
            print_debug(
                "MplCanvas.updatePlotData",
                f"create {xkey}/{ykey}",
                category="plots",
            )
            plotData = PlotDataModel(
                runModel,
                xkey,
                ykey,
                norm_keys=norm_keys,
                indices=self._slice,
                cube_view_spec=self._cube_view_spec,
                dimension=self._dimension,
            )
            plotData.data_changed.connect(self.plot_data)
            plotData.draw_requested.connect(self.draw)
            plotData.autoscale_requested.connect(self.autoscale)
            plotData.visibility_changed.connect(self._on_artist_visibility_changed)
            plotData.render_mode_changed.connect(self._on_render_mode_changed)
            self.plotArtists[key] = plotData
            self.plot_data(plotData)
        else:
            changed = self.plotArtists[key].update_data_info(
                norm_keys=norm_keys,
                indices=self._slice,
                cube_view_spec=self._cube_view_spec,
                dimension=self._dimension,
                emit=False,
            )
            if changed:
                self.plot_data(self.plotArtists[key])

    def _canvas_is_2d(self):
        """
        Return whether the canvas is currently showing 2D image or mesh data.

        Returns
        -------
        bool
            True if active render mode or dimension indicates 2D plotting.
        """
        return (
            self._active_render_mode in ("image", "mesh") or self.currentDim == 2
        )

    def _mode_is_2d(self, mode):
        """
        Return whether a render mode string describes 2D plotting.

        Parameters
        ----------
        mode : str
            Render mode name from :class:`PlotBundle`.

        Returns
        -------
        bool
            True for image or mesh modes.
        """
        return mode in ("image", "mesh")

    @property
    def lock_aspect(self) -> bool:
        """
        Whether image plots should use equal data aspect.

        Returns
        -------
        bool
            True when image aspect should be locked.
        """
        return self._lock_aspect

    def set_lock_aspect(self, locked: bool) -> None:
        """
        Set whether image plots use equal data aspect.

        Mesh and line plots always use automatic aspect. Changing this
        preference redraws when an image is currently shown.

        Parameters
        ----------
        locked : bool
            If True, image plots use ``aspect="equal"``.
        """
        locked = bool(locked)
        if locked == self._lock_aspect:
            return
        self._lock_aspect = locked
        self._apply_aspect()
        if self._active_render_mode == "image":
            self.draw()

    def _image_aspect(self) -> str:
        """
        Return the matplotlib aspect string for the current image preference.

        Returns
        -------
        str
            ``"equal"`` when locked, otherwise ``"auto"``.
        """
        return "equal" if self._lock_aspect else "auto"

    def _apply_aspect(self) -> None:
        """
        Apply axis aspect for the active render mode.

        Image mode respects :attr:`lock_aspect`. Mesh and line modes always
        use ``aspect="auto"``.
        """
        if self._active_render_mode == "image":
            self.axes.set_aspect(self._image_aspect())
        else:
            self.axes.set_aspect("auto")

    def _on_render_mode_changed(self, plot_data, mode):
        """
        Prepare axes when switching between 1D and 2D render modes.

        Does not schedule ``updatePlot``; the in-flight worker applies data via
        ``_handle_plot_data``.
        """
        print_debug(
            "MplCanvas",
            f"Render mode changed to {mode} for {plot_data.label}",
            category="plots",
        )
        was_2d = self._canvas_is_2d()
        will_be_2d = self._mode_is_2d(mode)
        if was_2d == will_be_2d:
            return

        if plot_data.artist is not None:
            plot_data.clear()
        self._reset_plot_axes()
        self.plot_view_updated.emit()

    def _on_artist_visibility_changed(self, _plot_data, _visible):
        """
        Refresh the legend after an artist show/hide.

        Paint is requested separately via ``draw_requested``.
        """
        self.updateLegend()

    def _on_run_removed(self, run):
        self.remove_run_data(run.uid)

    def updatePlot(self):
        self._update_timer = getattr(self, "_update_timer", None)
        rescheduled = (
            self._update_timer is not None and self._update_timer.isActive()
        )
        if self._update_timer is not None:
            self._update_timer.stop()
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._do_update_plot)
        self._update_timer.start(100)
        print_debug(
            "MplCanvas.updatePlot",
            f"{'rescheduled' if rescheduled else 'scheduled'} (100ms)",
            category="plots",
        )

    def _do_update_plot(self):
        t0 = ttime.time()
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
                    artist = plotDataModel.artist
                    needs_artist = artist is None or (
                        isinstance(artist, Line2D)
                        and not self._line_artist_on_axes(artist)
                    )
                    if needs_artist and key not in self._active_workers:
                        self.plot_data(plotDataModel)

            workers_pending = len(self._active_workers) > 0
            if workers_pending:
                print_debug(
                    "MplCanvas._do_update_plot",
                    f"visible={len(visible_keys)} artists={len(self.plotArtists)} "
                    f"active_workers={len(self._active_workers)} "
                    f"skip_paint (workers pending) {ttime.time() - t0:.4f}s",
                    category="plots",
                )
                return

            if self._autoscale:
                self.autoscale()
            self.draw()
            print_debug(
                "MplCanvas._do_update_plot",
                f"visible={len(visible_keys)} artists={len(self.plotArtists)} "
                f"active_workers=0 {ttime.time() - t0:.4f}s",
                category="plots",
            )
        except Exception as e:
            print_debug("MplCanvas._do_update_plot", str(e), category="plots")

    def plot_data(self, plotData):
        model_key = plotData._key
        generation = self._worker_generations.get(model_key, 0) + 1
        self._worker_generations[model_key] = generation

        old_worker = self._active_workers.pop(model_key, None)
        retired = old_worker is not None
        retire_plot_worker(old_worker, self._pending_workers)

        worker = PlotWorker(
            plotData,
            self._slice,
            self._dimension,
            generation,
            plotData.artist,
            cube_view_spec=self._cube_view_spec,
            view_crop=self._view_crop_for_model(plotData),
        )
        worker.data_ready.connect(self._handle_plot_data)
        worker.error_occurred.connect(self._handle_plot_error)
        worker.finished.connect(
            lambda mk=model_key, w=worker: self._on_plot_worker_finished(mk, w)
        )
        self._active_workers[model_key] = worker
        print_debug(
            "MplCanvas.plot_data",
            f"start gen={generation} label={plotData.label} "
            f"retired_prior={retired} "
            f"active_workers={len(self._active_workers)}",
            category="plots",
        )
        worker.start()

    def _on_plot_worker_finished(self, model_key, worker):
        if self._active_workers.get(model_key) is worker:
            self._active_workers.pop(model_key, None)

    @time_function(function_name="MplCanvas._handle_plot_data", category="plots")
    def _handle_plot_data(self, bundle, plotData, artist, generation):
        model_key = plotData._key
        if generation != self._worker_generations.get(model_key):
            print_debug(
                "MplCanvas._handle_plot_data",
                f"Stale worker gen={generation}, skipping",
                category="plots",
            )
            return

        if artist is None:
            artist = plotData.artist

        print_debug(
            "MplCanvas._handle_plot_data",
            f"apply {plotData.label} mode={bundle.render_mode} "
            f"y.shape={getattr(bundle.y, 'shape', None)} "
            f"active_workers={len(self._active_workers)}",
            category="plots",
        )

        try:
            if bundle.render_mode == "line":
                self._last_2d_plot_key = None
                self._last_view_frame = None
                artist = self._render_line(bundle, plotData, artist)
                self.currentDim = 1
                self._active_render_mode = "line"
                self._apply_aspect()
            elif bundle.render_mode == "image":
                self._prepare_2d_axes(plotData._key)
                artist = self._render_image(bundle, plotData, artist)
                self.currentDim = 2
                self._active_render_mode = "image"
                self._last_view_frame = frame_from_bundle(bundle)
                self._apply_aspect()
            elif bundle.render_mode == "mesh":
                self._prepare_2d_axes(plotData._key)
                artist = self._render_mesh(bundle, plotData, artist)
                self.currentDim = 2
                self._active_render_mode = "mesh"
                self._last_view_frame = frame_from_bundle(bundle)
                self._apply_aspect()
        except Exception as e:
            print(f"[MplCanvas._handle_plot_data] Error: {e}")
            artist = None

        plotData.set_artist(artist)
        if bundle.render_mode == "line":
            self._ensure_sibling_lines_on_axes(except_key=plotData._key)
        self._sync_roi_display()
        self.plot_view_updated.emit()
        self.draw()

    def _ensure_sibling_lines_on_axes(self, except_key=None):
        """
        Re-queue plot workers for visible line series not on the axes.

        Covers races where another handler cleared lines but left plot models.
        """
        for key, model in self.plotArtists.items():
            if key == except_key or not getattr(model, "_visible", False):
                continue
            if model.render_mode != "line":
                continue
            artist = model.artist
            if artist is None or (
                isinstance(artist, Line2D) and not self._line_artist_on_axes(artist)
            ):
                print_debug(
                    "MplCanvas._ensure_sibling_lines_on_axes",
                    f"Re-plotting {model.label}",
                    category="plots",
                )
                self.plot_data(model)

    def _line_artist_on_axes(self, artist):
        """
        Return whether a line artist is attached to this canvas's axes.

        Parameters
        ----------
        artist : Artist or None
            Candidate matplotlib line artist.

        Returns
        -------
        bool
            True if artist is a Line2D on ``self.axes``.
        """
        return isinstance(artist, Line2D) and artist.axes is self.axes

    def _render_line(self, bundle: PlotBundle, plotData, artist):
        label = plotData.label
        if self._line_artist_on_axes(artist):
            LineRenderer.update(artist, bundle)
            artist.set_label(label)
        else:
            if isinstance(artist, Line2D):
                try:
                    artist.remove()
                except Exception:
                    pass
            artist = LineRenderer.create(self.axes, bundle, label)
            self._artist_count += 1
        LineRenderer.set_labels(self.axes, bundle)
        if self._autoscale:
            self.autoscale()
        self.updateLegend()
        return artist

    def _image_artist_on_axes(self, artist):
        """
        Return whether an image artist is attached to this canvas's axes.

        Parameters
        ----------
        artist : Artist or None
            Candidate matplotlib image artist.

        Returns
        -------
        bool
            True if artist is an AxesImage on ``self.axes``.
        """
        return isinstance(artist, AxesImage) and artist.axes is self.axes

    def _mesh_artist_on_axes(self, artist):
        """
        Return whether a mesh artist is attached to this canvas's axes.

        Parameters
        ----------
        artist : Artist or None
            Candidate matplotlib collection artist.

        Returns
        -------
        bool
            True if artist is a collection on ``self.axes`` with mesh data.
        """
        return (
            artist is not None
            and artist.axes is self.axes
            and hasattr(artist, "set_array")
            and not isinstance(artist, (Line2D, AxesImage))
        )

    def _remove_figure_colorbars(self):
        """
        Remove the tracked colorbar and any extra axes on the figure.

        Matplotlib keeps colorbar axes on the figure even when the
        colorbar object is dropped from application state.
        """
        remove_2d_artists(self.axes, self._colorbar_state, self.fig)

    def _render_image(self, bundle: PlotBundle, plotData, artist):
        if self._image_artist_on_axes(artist):
            ImageRenderer.update(
                artist, bundle, self._autoscale, self._colorbar_state
            )
        else:
            if artist is not None:
                try:
                    artist.remove()
                except Exception:
                    pass
            self._remove_figure_colorbars()
            artist, _cbar = ImageRenderer.create(
                self.axes,
                self.fig,
                bundle,
                plotData.label,
                self._colorbar_state,
                aspect=self._image_aspect(),
            )
        return artist

    def _render_mesh(self, bundle: PlotBundle, plotData, artist):
        if self._mesh_artist_on_axes(artist):
            MeshRenderer.update(
                artist, bundle, self._autoscale, self._colorbar_state
            )
        else:
            if artist is not None:
                try:
                    artist.remove()
                except Exception:
                    pass
            self._remove_figure_colorbars()
            artist, _cbar = MeshRenderer.create(
                self.axes,
                self.fig,
                bundle,
                plotData.label,
                self._colorbar_state,
            )
        return artist

    def _prepare_2d_axes(self, plot_key):
        crop = self._view_crop
        crop_key = crop.storage_bbox if crop is not None else None
        spec_changed = self._cube_view_spec != self._last_2d_cube_view_spec
        crop_changed = crop_key != self._last_2d_view_crop
        if (
            self._last_2d_plot_key != plot_key
            or self._active_render_mode not in ("image", "mesh")
            or self.currentDim != 2
            or spec_changed
            or crop_changed
        ):
            self._reset_plot_axes()
        self._last_2d_plot_key = plot_key
        self._last_2d_cube_view_spec = self._cube_view_spec
        self._last_2d_view_crop = crop_key

    def _reset_plot_axes(self):
        remove_2d_artists(self.axes, self._colorbar_state, self.fig)
        while self.axes.lines:
            try:
                self.axes.lines[0].remove()
            except Exception:
                break
        for model in self.plotArtists.values():
            model.artist = None
        self._destroy_roi_selector()
        self._destroy_crop_selector()
        self._remove_roi_overlays()
        self._remove_crop_overlay()
        self._active_render_mode = None
        self.axes.set_aspect("auto")

    def set_roi_set_model(self, roi_set: RoiSetModel) -> None:
        """
        Attach the ROI set model that owns geometry and selection.
        """
        if self._roi_set is not None:
            try:
                self._roi_set.entries_changed.disconnect(self._on_roi_set_changed)
                self._roi_set.entry_changed.disconnect(self._on_roi_entry_changed)
                self._roi_set.selection_changed.disconnect(
                    self._on_roi_selection_changed
                )
            except (TypeError, RuntimeError):
                pass
        self._roi_set = roi_set
        roi_set.entries_changed.connect(self._on_roi_set_changed)
        roi_set.entry_changed.connect(self._on_roi_entry_changed)
        roi_set.selection_changed.connect(self._on_roi_selection_changed)
        self._sync_roi_display()
        self.roi_region_changed.emit(self.get_roi_region())

    def get_roi_set_model(self) -> Optional[RoiSetModel]:
        """
        Return the attached ROI set model, if any.
        """
        return self._roi_set

    def apply_roi_from_region(self, region) -> None:
        """
        Set the selected ROI from a :class:`RectRegion` in data coordinates.
        """
        if self._roi_set is None:
            return
        region = region.normalized()
        self._roi_set.set_or_replace_single(
            region,
            view_fingerprint=self.current_view_fingerprint(),
        )
        if self._roi_selector is not None:
            self._roi_selector.extents = (
                region.x0,
                region.x1,
                region.y0,
                region.y1,
            )

    def _handle_plot_error(self, error_msg):
        print(f"[MplCanvas] Plot error: {error_msg}")

    def get_single_visible_2d_model(self):
        """
        Return the sole visible 2D plot model, if exactly one exists.

        Returns
        -------
        PlotDataModel or None
        """
        models = []
        for model in self.plotArtists.values():
            if not getattr(model, "_visible", False):
                continue
            artist = model.artist
            if artist is None or not artist.get_visible():
                continue
            if model.render_mode in ("image", "mesh"):
                models.append(model)
        if len(models) == 1:
            return models[0]
        return None

    def get_active_plot_bundle(self):
        """
        Return the plot bundle for the single visible 2D trace.

        Returns
        -------
        PlotBundle or None
        """
        model = self.get_single_visible_2d_model()
        if model is None:
            return None
        if model.last_bundle is not None:
            return model.last_bundle
        return model.get_plot_bundle(
            self._slice, self._dimension, self._cube_view_spec
        )

    def get_view_frame(self) -> PlotViewFrame:
        """
        Return the view frame for the current 2D plot.

        Returns
        -------
        PlotViewFrame

        Raises
        ------
        ValueError
            If no 2D bundle is available.
        """
        bundle = self.get_active_plot_bundle()
        if bundle is None:
            raise ValueError("No active 2D plot bundle for ROI")
        return frame_from_bundle(bundle)

    def region_controls_enabled(self):
        """
        Return whether ROI controls should be enabled.

        Returns
        -------
        bool
        """
        return self._canvas_is_2d() and self.get_single_visible_2d_model() is not None

    def is_roi_draw_enabled(self):
        """
        Return whether interactive ROI drawing is active.
        """
        return self._roi_draw_enabled

    def is_crop_draw_enabled(self):
        """
        Return whether interactive crop drawing is active.
        """
        return self._crop_draw_enabled

    def get_roi_region(self):
        """
        Return the selected ROI geometry, if any.

        Returns
        -------
        RegionDefinition or None
        """
        if self._roi_set is None:
            return None
        return self._roi_set.selected_region()

    def get_selected_roi_entry(self):
        """
        Return the selected :class:`RoiEntry`, if any.
        """
        if self._roi_set is None:
            return None
        return self._roi_set.selected_entry()

    def is_selected_roi_stale(self) -> bool:
        """
        Return whether the selected ROI is marked stale.
        """
        entry = self.get_selected_roi_entry()
        return entry is not None and entry.stale

    def get_crop_region(self):
        """
        Return the draft crop rectangle, if any.

        Returns
        -------
        RectRegion or None
        """
        return self._crop_draft_region

    def get_view_crop(self) -> Optional[ViewCrop]:
        """
        Return the active persistent view crop, if any.

        Returns
        -------
        ViewCrop or None
        """
        return self._view_crop

    def set_view_crop(self, crop: Optional[ViewCrop]):
        """
        Set or clear the persistent view crop and refresh the plot.

        Parameters
        ----------
        crop : ViewCrop or None
            Crop state to apply to the main display fetch path.
        """
        self._view_crop = crop
        self.view_crop_changed.emit(crop)
        model = self.get_single_visible_2d_model()
        if model is not None and (
            crop is None or crop.source_key == model._key
        ):
            self.plot_data(model)
            return
        self.updatePlot()

    def clear_view_crop(self):
        """
        Remove the persistent view crop and refresh the plot.
        """
        if self._view_crop is None:
            return
        self.set_view_crop(None)

    def get_full_view_frame_for_crop(self) -> PlotViewFrame:
        """
        Return the full plot-plane frame used to commit a view crop.

        When a crop is already active, returns the stored pre-crop frame.
        Otherwise returns the frame for the current displayed bundle.

        Returns
        -------
        PlotViewFrame

        Raises
        ------
        ValueError
            If no 2D bundle is available.
        """
        if self._view_crop is not None:
            return self._view_crop.full_frame
        return self.get_view_frame()

    def _view_crop_for_model(self, plot_data: PlotDataModel) -> Optional[ViewCrop]:
        crop = self._view_crop
        if crop is None:
            return None
        if crop.source_key != plot_data._key:
            return None
        return crop

    def current_view_fingerprint(self):
        """
        Return a fingerprint for the active 2D plot coordinate frame.
        """
        bundle = self.get_active_plot_bundle()
        if bundle is None:
            return None
        try:
            return view_fingerprint_from_bundle(bundle)
        except ValueError:
            return None

    def get_roi_view_fingerprint(self):
        """
        Return the view fingerprint stored with the selected ROI.
        """
        entry = self.get_selected_roi_entry()
        if entry is None:
            return None
        return entry.view_fingerprint

    def set_roi_draw_enabled(self, enabled: bool):
        """
        Enable or disable interactive ROI rectangle drawing.
        """
        enabled = bool(enabled)
        if enabled and self._crop_draw_enabled:
            self.set_crop_draw_enabled(False)
        if enabled == self._roi_draw_enabled:
            return
        self._roi_draw_enabled = enabled
        if self._roi_draw_enabled:
            self._remove_roi_overlays()
            self._attach_roi_selector()
        else:
            if self._roi_selector is not None:
                region = self._region_from_selector(self._roi_selector)
                if region is not None:
                    self._commit_roi_region(region)
            self._detach_roi_selector()
            self._update_roi_overlays()

    def set_crop_draw_enabled(self, enabled: bool):
        """
        Enable or disable interactive crop rectangle drawing.
        """
        enabled = bool(enabled)
        if enabled and self._roi_draw_enabled:
            self.set_roi_draw_enabled(False)
        if enabled == self._crop_draw_enabled:
            return
        self._crop_draw_enabled = enabled
        if self._crop_draw_enabled:
            self._remove_crop_overlay()
            self._attach_crop_selector()
        else:
            if self._crop_selector is not None:
                region = self._region_from_selector(self._crop_selector)
                if region is not None:
                    self._set_crop_draft_region(region, update_overlay=True)
            self._detach_crop_selector()
            self._update_crop_overlay()

    def clear_roi(self, paint=True):
        """
        Clear ROI set entries and detach ROI artists.

        Parameters
        ----------
        paint : bool, optional
            If True, schedule a coalesced redraw. Pass False when the caller
            will paint later (for example during ``clear`` before a refetch).
        """
        if self._roi_set is not None:
            self._roi_set.clear()
        else:
            self._destroy_roi_selector()
            self._remove_roi_overlays()
            self.roi_region_changed.emit(None)
        if self._roi_draw_enabled:
            self._attach_roi_selector()
        if paint:
            self.draw()

    def clear_crop_draft(self, paint=True):
        """
        Clear the draft crop rectangle and detach its artists.
        """
        self._crop_draft_region = None
        self._destroy_crop_selector()
        self._remove_crop_overlay()
        self.crop_region_changed.emit(None)
        if self._crop_draw_enabled:
            self._attach_crop_selector()
        if paint:
            self.draw()

    def _region_from_selector(self, selector):
        """
        Read a rectangle from selector extents.
        """
        if selector is None:
            return None
        x0, x1, y0, y1 = selector.extents
        return RectRegion(x0=x0, x1=x1, y0=y0, y1=y1).normalized()

    def _commit_roi_region(self, region: RectRegion):
        if self._roi_set is None:
            return
        self._roi_set.set_or_replace_single(
            region.normalized(),
            view_fingerprint=self.current_view_fingerprint(),
        )

    def _set_crop_draft_region(self, region: RectRegion, update_overlay=None):
        self._crop_draft_region = region.normalized()
        if update_overlay is None:
            update_overlay = not self._crop_draw_enabled
        if update_overlay:
            self._update_crop_overlay()
        self.crop_region_changed.emit(self._crop_draft_region)

    def _on_roi_selected(self, _eclick, _erelease):
        if not self._roi_draw_enabled:
            return
        region = self._region_from_selector(self._roi_selector)
        if region is None:
            return
        self._commit_roi_region(region)

    def _on_crop_selected(self, _eclick, _erelease):
        if not self._crop_draw_enabled:
            return
        region = self._region_from_selector(self._crop_selector)
        if region is None:
            return
        self._set_crop_draft_region(region, update_overlay=False)

    def _destroy_selector(self, selector):
        """
        Fully remove a RectangleSelector and its artists from the axes.
        """
        if selector is None:
            return
        try:
            selector.disconnect_events()
        except Exception:
            pass
        try:
            selector.set_active(False)
        except Exception:
            pass
        try:
            selector.clear()
        except Exception:
            pass
        try:
            selector.set_visible(False)
        except Exception:
            pass
        for artist in tuple(getattr(selector, "artists", ())):
            try:
                artist.remove()
            except Exception:
                pass
        for handle_group in (
            getattr(selector, "_corner_handles", None),
            getattr(selector, "_edge_handles", None),
            getattr(selector, "_center_handle", None),
        ):
            if handle_group is not None and hasattr(handle_group, "remove"):
                try:
                    handle_group.remove()
                except Exception:
                    pass
        selection = getattr(selector, "_selection_artist", None)
        if selection is not None:
            try:
                selection.remove()
            except Exception:
                pass

    def _destroy_roi_selector(self):
        selector = self._roi_selector
        self._roi_selector = None
        self._destroy_selector(selector)

    def _destroy_crop_selector(self):
        selector = self._crop_selector
        self._crop_selector = None
        self._destroy_selector(selector)

    def _detach_roi_selector(self):
        self._destroy_roi_selector()

    def _detach_crop_selector(self):
        self._destroy_crop_selector()

    def _attach_roi_selector(self):
        if not self._roi_draw_enabled:
            return
        self._destroy_roi_selector()
        if not self.region_controls_enabled():
            return

        entry = self.get_selected_roi_entry()
        color = entry.color if entry is not None else "#00ffff"
        self._roi_selector = RectangleSelector(
            self.axes,
            self._on_roi_selected,
            useblit=False,
            button=[1],
            minspanx=0,
            minspany=0,
            spancoords="data",
            interactive=True,
            props=dict(
                facecolor=to_rgba(color, _ROI_FILL_ALPHA),
                edgecolor=color,
                fill=True,
                linewidth=_ROI_EDGE_WIDTH,
            ),
        )
        region = self.get_roi_region()
        if isinstance(region, RectRegion):
            region = region.normalized()
            self._roi_selector.extents = (
                region.x0,
                region.x1,
                region.y0,
                region.y1,
            )

    def _attach_crop_selector(self):
        if not self._crop_draw_enabled:
            return
        self._destroy_crop_selector()
        if not self.region_controls_enabled():
            return

        self._crop_selector = RectangleSelector(
            self.axes,
            self._on_crop_selected,
            useblit=False,
            button=[1],
            minspanx=0,
            minspany=0,
            spancoords="data",
            interactive=True,
            props=dict(**_CROP_SELECTOR_PROPS),
        )
        if self._crop_draft_region is not None:
            region = self._crop_draft_region.normalized()
            self._crop_selector.extents = (
                region.x0,
                region.x1,
                region.y0,
                region.y1,
            )

    def _remove_roi_overlays(self):
        for patches in self._roi_overlays.values():
            for patch in patches:
                try:
                    patch.remove()
                except Exception:
                    pass
        self._roi_overlays = {}

    def _remove_crop_overlay(self):
        if self._crop_overlay is not None:
            try:
                self._crop_overlay.remove()
            except Exception:
                pass
            self._crop_overlay = None

    def _rect_overlay_for_region(self, region: RectRegion, *, color: str, stale: bool):
        """
        Build ROI overlay patches with an opaque edge and light halo.

        A global patch alpha would fade the border into dark heatmaps, so fill
        alpha is applied only to the face color.
        """
        region = region.normalized()
        edge = "#bdbdbd" if stale else color
        face_alpha = _ROI_STALE_FILL_ALPHA if stale else _ROI_FILL_ALPHA
        xy = (region.x0, region.y0)
        width = region.x1 - region.x0
        height = region.y1 - region.y0
        halo = Rectangle(
            xy,
            width,
            height,
            linewidth=_ROI_HALO_WIDTH,
            edgecolor="white",
            facecolor="none",
            alpha=0.85 if not stale else 0.45,
            fill=False,
            zorder=20,
        )
        body = Rectangle(
            xy,
            width,
            height,
            linewidth=_ROI_EDGE_WIDTH,
            edgecolor=edge,
            facecolor=to_rgba(edge, face_alpha),
            fill=True,
            zorder=21,
        )
        return halo, body

    def _update_roi_overlays(self):
        self._remove_roi_overlays()
        if self._roi_set is None or self._roi_draw_enabled:
            return
        for entry in self._roi_set.entries():
            if not entry.visible or not isinstance(entry.region, RectRegion):
                continue
            if not entry.region.has_area():
                continue
            patches = self._rect_overlay_for_region(
                entry.region,
                color=entry.color,
                stale=entry.stale,
            )
            for patch in patches:
                self.axes.add_patch(patch)
            self._roi_overlays[entry.id] = patches

    def _update_crop_overlay(self):
        self._remove_crop_overlay()
        if self._crop_draft_region is None or self._crop_draw_enabled:
            return
        region = self._crop_draft_region.normalized()
        self._crop_overlay = Rectangle(
            (region.x0, region.y0),
            region.x1 - region.x0,
            region.y1 - region.y0,
            **_CROP_OVERLAY_PROPS,
        )
        self.axes.add_patch(self._crop_overlay)

    def _selector_is_live(self, selector) -> bool:
        """
        Return whether a rectangle selector is attached to the current axes.
        """
        if selector is None:
            return False
        ax = getattr(selector, "ax", None)
        if ax is not self.axes:
            return False
        selection = getattr(selector, "_selection_artist", None)
        return selection is not None and selection.axes is self.axes

    def _on_roi_set_changed(self):
        self._sync_roi_display()
        self.roi_region_changed.emit(self.get_roi_region())
        self.draw()

    def _on_roi_entry_changed(self, _entry_id: str):
        self._sync_roi_display()
        self.roi_region_changed.emit(self.get_roi_region())
        self.draw()

    def _on_roi_selection_changed(self, _entry_id):
        self._sync_roi_display()
        self.roi_region_changed.emit(self.get_roi_region())
        self.draw()

    def _sync_roi_display(self):
        if self._roi_draw_enabled:
            self._remove_roi_overlays()
            if not self._selector_is_live(self._roi_selector):
                self._attach_roi_selector()
            else:
                region = self.get_roi_region()
                if isinstance(region, RectRegion):
                    region = region.normalized()
                    self._roi_selector.extents = (
                        region.x0,
                        region.x1,
                        region.y0,
                        region.y1,
                    )
        else:
            self._update_roi_overlays()
        if self._crop_draw_enabled:
            self._remove_crop_overlay()
            if not self._selector_is_live(self._crop_selector):
                self._attach_crop_selector()
            elif self._crop_draft_region is not None:
                region = self._crop_draft_region.normalized()
                self._crop_selector.extents = (
                    region.x0,
                    region.x1,
                    region.y0,
                    region.y1,
                )
        else:
            self._update_crop_overlay()

    def clear(self):
        """
        Reset axes and artists for a dimension change without painting.

        The previous Agg frame stays on screen until the following refetch
        paints via ``_handle_plot_data`` or ``_do_update_plot``. ROI set
        geometry is kept and marked stale by the controller when the view
        fingerprint changes.
        """
        print_debug("MplCanvas.clear", "Starting Clear", category="plots")
        self._destroy_roi_selector()
        self._destroy_crop_selector()
        self._remove_roi_overlays()
        self._remove_crop_overlay()

        for model_key in list(self._active_workers.keys()):
            worker = self._active_workers.pop(model_key, None)
            retire_plot_worker(worker, self._pending_workers)
        self._worker_generations.clear()

        remove_2d_artists(self.axes, self._colorbar_state, self.fig)

        old_axes = self.axes
        self.axes = self.fig.add_subplot(111)
        if old_axes in self.fig.axes:
            try:
                self.fig.delaxes(old_axes)
            except Exception as e:
                print(f"[MplCanvas.clear] Error removing old axes: {e}")

        for ax in list(self.fig.axes):
            if ax is not self.axes:
                try:
                    ax.remove()
                except Exception:
                    pass

        self._colorbar_state.clear()
        self._last_2d_plot_key = None
        self._last_2d_cube_view_spec = None
        self.currentDim = 1
        self._active_render_mode = None
        self._artist_count = 0

        for model in self.plotArtists.values():
            model.artist = None

    def updateLegend(self):
        """
        Rebuild the axes legend from visible labeled lines.

        Does not paint; callers that need a refresh must call :meth:`draw`.
        """
        t0 = ttime.time()
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

        print_debug(
            "MplCanvas.updateLegend",
            f"lines={len(visible_lines)} {ttime.time() - t0:.4f}s",
            category="plots",
        )

    def autoscale(self):
        """
        Adjust clim or axis limits from currently visible artists.

        Does not paint; callers that need a refresh must call :meth:`draw`.
        """
        t0 = ttime.time()
        mode = self._active_render_mode
        if mode == "image":
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
            print_debug(
                "MplCanvas.autoscale",
                f"mode=image {ttime.time() - t0:.4f}s",
                category="plots",
            )
            return

        if mode == "mesh":
            for collection in self.axes.collections:
                if collection.get_visible() and hasattr(collection, "get_array"):
                    arr = np.asarray(collection.get_array())
                    if arr.size > 0:
                        finite = arr[np.isfinite(arr)]
                        if finite.size > 0:
                            collection.set_clim(
                                float(np.min(finite)), float(np.max(finite))
                            )
            print_debug(
                "MplCanvas.autoscale",
                f"mode=mesh {ttime.time() - t0:.4f}s",
                category="plots",
            )
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
        print_debug(
            "MplCanvas.autoscale",
            f"mode=line lines={len(visible_lines)} {ttime.time() - t0:.4f}s",
            category="plots",
        )

    def resizeEvent(self, event):
        print_debug(
            "MplCanvas.resizeEvent",
            f"id={id(self)} size={event.size().width()}x{event.size().height()} "
            f"nbs_pending={self._nbs_draw_pending} "
            f"mpl_pending={getattr(self, '_draw_pending', False)} "
            f"in_do_draw={self._nbs_in_do_draw}",
            category="plots",
        )
        super().resizeEvent(event)

    def draw_idle(self):
        print_debug(
            "MplCanvas.draw_idle",
            f"id={id(self)} nbs_pending={self._nbs_draw_pending} "
            f"mpl_pending={getattr(self, '_draw_pending', False)} "
            f"is_drawing={getattr(self, '_is_drawing', False)} "
            f"in_do_draw={self._nbs_in_do_draw} "
            f"via={_draw_caller_summary()}",
            category="plots",
        )
        super().draw_idle()

    def draw(self):
        caller = _draw_caller_summary()
        if not self._nbs_draw_pending:
            self._nbs_draw_pending = True
            self._nbs_draw_coalesce_count = 0
            print_debug(
                "MplCanvas.draw",
                f"scheduled (16ms) id={id(self)} "
                f"mpl_pending={getattr(self, '_draw_pending', False)} "
                f"is_drawing={getattr(self, '_is_drawing', False)} "
                f"in_do_draw={self._nbs_in_do_draw} via={caller}",
                category="plots",
            )
            QTimer.singleShot(16, self._do_draw)
        else:
            self._nbs_draw_coalesce_count += 1
            print_debug(
                "MplCanvas.draw",
                f"coalesced=#{self._nbs_draw_coalesce_count} id={id(self)} "
                f"in_do_draw={self._nbs_in_do_draw} via={caller}",
                category="plots",
            )

    def _do_draw(self):
        self._nbs_draw_pending = False
        coalesced = self._nbs_draw_coalesce_count
        self._nbs_draw_coalesce_count = 0
        t0 = ttime.time()
        self._nbs_in_do_draw = True
        try:
            super().draw()
        finally:
            self._nbs_in_do_draw = False
        print_debug(
            "MplCanvas._do_draw",
            f"FigureCanvas.draw {ttime.time() - t0:.4f}s "
            f"coalesced_calls={coalesced} "
            f"id={id(self)} "
            f"active_workers={len(self._active_workers)}",
            category="plots",
        )

    def remove_run_data(self, run_uid):
        print_debug(
            "MplCanvas.remove_run_data",
            f"Removing run {run_uid}",
            category="plots",
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
        print(f"plotArtists count: {len(self.plotArtists)}")
        print(f"active workers: {list(self._active_workers.keys())}")

        visible_keys = set()
        for runModel in self.run_list_model.visible_models:
            xkeys, ykeys, normkeys = runModel.get_selected_keys()
            print(
                f"  run {runModel.scan_id}: x={xkeys} y={ykeys} norm={normkeys}"
            )
            for xkey in xkeys:
                for ykey in ykeys:
                    visible_keys.add((xkey, ykey, runModel.uid))
        print(f"expected visible_keys ({len(visible_keys)}):")
        for key in sorted(visible_keys):
            print(f"    {key}")

        axes_line_ids = {id(line) for line in self.axes.get_lines()}

        def _on_axes(artist):
            return self._line_artist_on_axes(artist)
        print("plotArtists:")
        for key, model in self.plotArtists.items():
            artist = model.artist
            artist_visible = None
            mpl_label = None
            on_axes = _on_axes(artist)
            if artist is not None:
                artist_visible = artist.get_visible()
                mpl_label = artist.get_label() if hasattr(artist, "get_label") else None
                if on_axes and id(artist) not in axes_line_ids:
                    on_axes = False
            print(
                f"  {key}:"
                f" label={model.label!r}"
                f" mode={model.render_mode}"
                f" in_visible_keys={key in visible_keys}"
                f" model._visible={getattr(model, '_visible', '?')}"
                f" artist={artist is not None}"
                f" artist.get_visible()={artist_visible}"
                f" on_axes={on_axes}"
                f" mpl_label={mpl_label!r}"
            )

        lines = self.axes.get_lines()
        print(f"axes.get_lines() ({len(lines)}):")
        for i, line in enumerate(lines):
            print(
                f"  [{i}] label={line.get_label()!r}"
                f" visible={line.get_visible()}"
                f" id={id(line)}"
            )

        artist_ids = {
            id(m.artist) for m in self.plotArtists.values() if m.artist is not None
        }
        orphan_lines = [
            line
            for line in lines
            if id(line) not in artist_ids
            and line.get_label()
            and not line.get_label().startswith("_")
        ]
        if orphan_lines:
            print(f"lines on axes not tracked in plotArtists ({len(orphan_lines)}):")
            for line in orphan_lines:
                print(
                    f"  label={line.get_label()!r}"
                    f" visible={line.get_visible()}"
                    f" id={id(line)}"
                )

        missing_artists = [
            key for key in visible_keys if key not in self.plotArtists
        ]
        if missing_artists:
            print(f"visible_keys without plotArtists entry ({len(missing_artists)}):")
            for key in sorted(missing_artists):
                print(f"    {key}")

        stale_artists = [
            key
            for key, model in self.plotArtists.items()
            if key in visible_keys
            and not self._line_artist_on_axes(model.artist)
        ]
        if stale_artists:
            print(
                f"visible_keys without line on axes ({len(stale_artists)}):"
            )
            for key in sorted(stale_artists):
                model = self.plotArtists[key]
                axes_ref = (
                    None
                    if model.artist is None
                    else getattr(model.artist, "axes", None)
                )
                print(f"    {key} artist.axes={axes_ref}")

        legend = self.axes.get_legend()
        if legend is not None:
            print(f"legend visible={legend.get_visible()}")
        else:
            print("legend: None")
        print("=== End MplCanvas Debug Info ===\n")
