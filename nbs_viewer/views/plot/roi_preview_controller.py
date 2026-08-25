"""
Manage the ROI workbench window and debounced preview updates.
"""

from __future__ import annotations

from qtpy.QtCore import QObject, QTimer

from nbs_viewer.models.plot.derived_fetch import _profile_uses_nd_load
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.plotModel import PlotModel
from nbs_viewer.models.plot.region import expand_region_for_profile

from .mpl_canvas import MplCanvas
from .plotDimensionWidget import PlotDimensionControl
from .roi_panel import RoiPanel
from .roi_preview_canvas import RoiPreviewWorker
from .roi_window import RoiWindow


class RoiPreviewController(QObject):
    """
    Open the ROI window and run debounced preview fetches for the selected ROI.

    Preview fetch and frozen-spectrum construction live on :class:`PlotModel`
    / :class:`PlotDataModel`. This controller handles window wiring, debounce,
    worker threads, and status text.
    """

    def __init__(
        self,
        canvas: MplCanvas,
        dimension_control: PlotDimensionControl,
        panel: RoiPanel,
        plot_model: PlotModel,
        parent=None,
    ):
        super().__init__(parent)
        self.canvas = canvas
        self.dimension_control = dimension_control
        self.panel = panel
        self.plot_model = plot_model
        self.roi_set = plot_model.roi_set
        self._window = None
        self._active_worker = None
        self._commit_worker = None
        self._pending_workers = set()
        self._generation = 0
        self._commit_generation = 0
        self._pending_commit_request = None
        self._pending_commit_entry_id = None
        self._pending_commit_plot_data = None
        self._save_all_queue = []

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.timeout.connect(self._run_preview)

        panel.roi_window_requested.connect(self._open_or_raise_window)
        panel.crop_draw_toggled.connect(self._on_panel_crop_draw_toggled)
        canvas.roi_region_changed.connect(self._on_roi_or_view_changed)
        canvas.plot_view_updated.connect(self._on_parent_plot_updated)
        dimension_control.indicesUpdated.connect(self._on_roi_or_view_changed)
        dimension_control.cubeViewChanged.connect(self._on_roi_or_view_changed)
        self.roi_set.selection_changed.connect(self._on_selection_changed)
        self.roi_set.entry_changed.connect(self._on_entry_changed)
        self.roi_set.entries_changed.connect(self._on_roi_or_view_changed)

        self._update_launcher_enabled()

    def _parent_spec(self):
        spec = self.dimension_control._cube_view_spec
        if spec is not None:
            return spec
        if self.plot_model.cube_view_spec is not None:
            return self.plot_model.cube_view_spec
        return self.canvas._cube_view_spec

    def _axis_names(self):
        names = self.dimension_control._dim_names
        return names if names is not None else ()

    def _parent_frame(self, plot_data):
        if plot_data is None or plot_data.last_bundle is None:
            return None
        try:
            return frame_from_bundle(plot_data.last_bundle)
        except ValueError:
            return None

    def _open_or_raise_window(self):
        if self._window is None:
            parent_window = self.panel.window()
            self._window = RoiWindow(self.roi_set, parent_window)
            self._window.draw_toggled.connect(self._on_window_draw_toggled)
            self._window.clear_requested.connect(self._on_window_clear)
            self._window.delete_requested.connect(self._on_window_delete)
            self._window.remove_stale_requested.connect(self._on_window_remove_stale)
            self._window.add_roi_requested.connect(self._on_add_roi)
            self._window.operation_changed.connect(self._schedule_preview)
            self._window.preview_enabled_changed.connect(self._schedule_preview)
            self._window.save_selected_requested.connect(self._on_save_selected)
            self._window.save_all_requested.connect(self._on_save_all)
            self._window.full_height_requested.connect(self._apply_roi_full_height)
            self._window.full_width_requested.connect(self._apply_roi_full_width)
            self._window.ellipse_circle_lock_changed.connect(
                self.canvas.set_ellipse_circle_locked
            )
            self._window.finished.connect(self._on_window_finished)
        self._update_window_context()
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        self._trigger_initial_preview()

    def _on_window_finished(self):
        self._cancel_preview_worker()
        self._cancel_commit_worker()
        self._save_all_queue.clear()
        if self._window is not None:
            self.canvas.set_roi_draw_enabled(False)
            self.canvas.set_ellipse_circle_locked(False)
            self._window.set_draw_checked(False)
        self._window = None

    def _on_window_draw_toggled(self, enabled: bool):
        if enabled:
            self.panel.set_crop_draw_checked(False)
            if self.canvas.is_crop_draw_enabled():
                self.canvas.set_crop_draw_enabled(False)
        self.canvas.set_roi_draw_enabled(enabled)

    def _on_panel_crop_draw_toggled(self, enabled: bool):
        if enabled and self._window is not None:
            self._window.set_draw_checked(False)

    def _on_window_clear(self):
        self.canvas.set_roi_draw_enabled(False)
        if self._window is not None:
            self._window.set_draw_checked(False)
        self.roi_set.clear()
        if self._window is not None:
            self._window.set_status("Cleared all ROIs")
            self._window.show_preview_message("No ROI selected")

    def _on_window_delete(self):
        entry = self.roi_set.selected_entry()
        if entry is None:
            return
        self.roi_set.remove(entry.id)
        if self._window is not None:
            self._window.set_status(f"Deleted {entry.display_label}")

    def _on_window_remove_stale(self):
        removed = self.roi_set.remove_stale()
        if self._window is not None:
            if removed:
                self._window.set_status(f"Removed {removed} stale ROI(s)")
            else:
                self._window.set_status("No stale ROIs")

    def _on_add_roi(self, region_type: str):
        try:
            entry_id = self.roi_set.add_placeholder(region_type)
        except ValueError:
            if self._window is not None:
                self._window.set_status(f"ROI type {region_type!r} is not available")
            return
        if self._window is not None:
            self._window.set_draw_checked(True)
            self.canvas.set_roi_draw_enabled(True)
            entry = self.roi_set.get(entry_id)
            label = entry.display_label if entry is not None else "ROI"
            kind = region_type
            if region_type == "polygon":
                self._window.set_status(
                    f"Draw {label}: click vertices on the parent plot, "
                    "click the first vertex to close"
                )
            else:
                self._window.set_status(f"Draw {label} ({kind}) on the parent plot")

    def _on_parent_plot_updated(self):
        if self._window is None or not self._window.isVisible():
            return
        if not self._window.is_preview_enabled():
            return
        self._schedule_preview()

    def _cached_parent_bundle(self, plot_data, request=None):
        """
        Return the parent :class:`PlotBundle` only when it matches the canvas view.
        """
        if plot_data is None or plot_data.last_bundle is None:
            return None
        if plot_data._cube_view_spec != self.canvas._cube_view_spec:
            return None
        if plot_data._indices != self.canvas._slice:
            return None
        if self.canvas._active_workers.get(plot_data._key) is not None:
            return None
        if request is not None and _profile_uses_nd_load(
            request, self._parent_spec()
        ):
            return None
        return plot_data.last_bundle

    def _on_roi_or_view_changed(self, *_args):
        self._update_launcher_enabled()
        if self._window is None or not self._window.isVisible():
            return
        self._update_window_context()
        self._schedule_preview()

    def _on_selection_changed(self, *_args):
        if self._window is None or not self._window.isVisible():
            return
        self._update_window_context()
        self._schedule_preview()

    def _on_entry_changed(self, *_args):
        if self._window is None or not self._window.isVisible():
            return
        self._schedule_preview()

    def _update_launcher_enabled(self):
        self.panel.set_roi_window_enabled(self.canvas.region_controls_enabled())

    def _update_window_context(self):
        if self._window is None:
            return
        plot_data = self.canvas.get_single_visible_2d_model()
        if plot_data is None:
            source = "No single 2D dataset selected"
        else:
            source = f"{plot_data.label} · {plot_data._ykey}"
        self._window.set_context(source)

        self._window.set_profile_context(
            self._parent_spec(),
            self._axis_names(),
            self._parent_frame(plot_data),
        )
        if self.canvas.is_roi_draw_enabled() != self._window.draw_button.isChecked():
            self._window.set_draw_checked(self.canvas.is_roi_draw_enabled())

    def _schedule_preview(self, *_args):
        if self._window is None:
            return
        self._debounce_timer.stop()
        self._debounce_timer.start()

    def _trigger_initial_preview(self):
        """
        Run preview once the window is shown and laid out.
        """
        if self._window is None:
            return
        self._debounce_timer.stop()
        if not self._window.is_preview_enabled():
            return
        self._window.show_preview_message("Updating preview…")
        QTimer.singleShot(0, self._run_preview)

    def _start_preview_worker(
        self,
        generation: int,
        entry,
        span_full_override=None,
    ):
        plot_data = self.canvas.get_single_visible_2d_model()
        if plot_data is None:
            raise ValueError("Select a single 2D dataset")

        parent_spec = self._parent_spec()
        request = self.plot_model.build_roi_profile_request(
            entry,
            parent_spec=parent_spec,
            parent_frame=self._parent_frame(plot_data),
            span_full_override=span_full_override,
            default_profile_axis=(
                None
                if self._window is None
                else self._window.get_profile_storage_axis()
            ),
        )

        worker = RoiPreviewWorker(
            plot_data,
            request,
            generation,
            self,
            parent_spec=parent_spec,
            parent_bundle=self._cached_parent_bundle(plot_data, request),
            view_crop=self.canvas.get_view_crop(),
        )
        return worker

    def _run_preview(self):
        if self._window is None:
            return
        if not self._window.is_preview_enabled():
            self._cancel_preview_worker()
            self._window.show_preview_message("Preview disabled")
            return

        try:
            entry = self.plot_model.resolve_roi_entry()
        except ValueError as exc:
            self._window.show_preview_message(str(exc))
            self._window.set_status("")
            return

        plot_data = self.canvas.get_single_visible_2d_model()
        if plot_data is None:
            self._window.show_preview_message("Select a single 2D dataset")
            self._window.set_status("")
            return

        self._cancel_preview_worker()
        self._generation += 1
        generation = self._generation

        try:
            worker = self._start_preview_worker(generation, entry)
        except ValueError as exc:
            self._window.show_preview_message("Preview unavailable")
            self._window.set_status(str(exc))
            return

        worker.preview_ready.connect(self._on_preview_ready)
        worker.error_occurred.connect(self._on_preview_error)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self._active_worker = worker
        self._pending_workers.add(worker)
        self._window.set_status("Updating preview…")
        worker.start()

    def _cancel_preview_worker(self):
        worker = self._active_worker
        self._active_worker = None
        if worker is None:
            return
        try:
            worker.preview_ready.disconnect(self._on_preview_ready)
            worker.error_occurred.disconnect(self._on_preview_error)
        except (TypeError, RuntimeError):
            pass
        worker.requestInterruption()
        if worker.isRunning():

            def _cleanup():
                self._pending_workers.discard(worker)
                worker.deleteLater()

            worker.finished.connect(_cleanup)
        else:
            self._pending_workers.discard(worker)
            worker.deleteLater()

    def _cancel_commit_worker(self):
        worker = self._commit_worker
        self._commit_worker = None
        if worker is None:
            return
        try:
            worker.preview_ready.disconnect(self._on_commit_ready)
            worker.error_occurred.disconnect(self._on_commit_error)
        except (TypeError, RuntimeError):
            pass
        worker.requestInterruption()
        if worker.isRunning():

            def _cleanup():
                self._pending_workers.discard(worker)
                worker.deleteLater()

            worker.finished.connect(_cleanup)
        else:
            self._pending_workers.discard(worker)
            worker.deleteLater()

    def _on_worker_finished(self, worker):
        self._pending_workers.discard(worker)
        if self._active_worker is worker:
            self._active_worker = None
        if self._commit_worker is worker:
            self._commit_worker = None

    def _on_preview_ready(self, bundle, generation):
        if self._window is None or generation != self._generation:
            return
        if not self._window.is_preview_enabled():
            return
        self._window.show_preview_bundle(bundle)
        self._window.set_status("")

    def _on_preview_error(self, message, generation):
        if self._window is None or generation != self._generation:
            return
        self._window.show_preview_message("Preview unavailable")
        self._window.set_status(message)

    def _on_save_selected(self):
        self._save_all_queue.clear()
        self._start_commit(self.roi_set.selected_id)

    def _on_save_all(self):
        self._save_all_queue = [
            entry.id
            for entry in self.roi_set.entries()
            if not entry.stale and entry.region.has_area()
        ]
        if not self._save_all_queue:
            if self._window is not None:
                self._window.set_status("No drawable ROIs to save")
            return
        self._start_commit(self._save_all_queue.pop(0))

    def _start_commit(self, entry_id):
        if self._window is None or entry_id is None:
            return

        try:
            entry = self.plot_model.resolve_roi_entry(entry_id)
        except ValueError as exc:
            self._window.set_status(str(exc))
            self._save_all_queue.clear()
            return

        plot_data = self.canvas.get_single_visible_2d_model()
        if plot_data is None:
            self._window.set_status("Select a single 2D dataset")
            return

        parent_spec = self._parent_spec()
        default_axis = self._window.get_profile_storage_axis()
        try:
            span_full, request = self.plot_model.prepare_roi_commit(
                entry,
                parent_spec=parent_spec,
                parent_frame=self._parent_frame(plot_data),
                axis_names=self._axis_names(),
                default_profile_axis=default_axis,
            )
        except ValueError as exc:
            self._window.set_status(str(exc))
            self._save_all_queue.clear()
            return

        self._cancel_commit_worker()
        self._commit_generation += 1
        generation = self._commit_generation
        self._pending_commit_request = request
        self._pending_commit_entry_id = entry_id
        self._pending_commit_plot_data = plot_data
        self._window.set_status(f"Saving {entry.display_label}…")

        try:
            worker = self._start_preview_worker(
                generation,
                entry,
                span_full_override=span_full,
            )
        except ValueError as exc:
            self._window.set_status(str(exc))
            self._save_all_queue.clear()
            return

        worker.preview_ready.connect(self._on_commit_ready)
        worker.error_occurred.connect(self._on_commit_error)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self._commit_worker = worker
        self._pending_workers.add(worker)
        worker.start()

    def _on_commit_ready(self, bundle, generation):
        if self._window is None or generation != self._commit_generation:
            return

        entry = self.roi_set.get(self._pending_commit_entry_id)
        plot_data = self._pending_commit_plot_data
        request = self._pending_commit_request
        if entry is None or plot_data is None or request is None:
            return

        try:
            frozen = self.plot_model.finalize_roi_commit(
                entry,
                bundle,
                request,
                parent_plot_data=plot_data,
                parent_spec=self._parent_spec(),
                axis_names=self._axis_names(),
                cube_fingerprint=(
                    tuple(self.canvas._slice) if self.canvas._slice else None,
                    str(self.canvas._cube_view_spec),
                ),
            )
        except ValueError as exc:
            self._window.set_status(str(exc))
            self._save_all_queue.clear()
            return

        self._window.set_status(f"Saved: {frozen.label}")

        if self._save_all_queue:
            next_id = self._save_all_queue.pop(0)
            QTimer.singleShot(0, lambda: self._start_commit(next_id))

    def _on_commit_error(self, message, generation):
        if self._window is None or generation != self._commit_generation:
            return
        self._window.set_status(message)
        self._save_all_queue.clear()

    def _apply_roi_full_height(self):
        self._apply_roi_full_span("plot_y")

    def _apply_roi_full_width(self):
        self._apply_roi_full_span("plot_x")

    def _apply_roi_full_span(self, profile_axis: str):
        region = self.canvas.get_roi_region()
        if region is None or not region.has_area():
            if self._window is not None:
                self._window.set_status("Draw an ROI on the parent plot first")
            return
        try:
            frame = self.canvas.get_view_frame()
        except ValueError as exc:
            if self._window is not None:
                self._window.set_status(str(exc))
            return
        if self._window is not None:
            selected = self._window.profile_axis_for_roi_span()
            if selected is not None:
                profile_axis = selected
        expanded = expand_region_for_profile(frame, region, profile_axis)
        self.canvas.apply_roi_from_region(expanded)
        if self._window is not None:
            self._schedule_preview()
