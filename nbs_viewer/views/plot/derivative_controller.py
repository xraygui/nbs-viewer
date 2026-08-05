"""
Manage the ROI workbench window and debounced preview updates.
"""

from __future__ import annotations

from uuid import uuid4

from qtpy.QtCore import QObject, QTimer

from nbs_viewer.models.plot.cube_view import (
    classify_profile_kind,
    default_profile_label,
    is_plot_plane_storage_axis,
    scan_profile_storage_axis,
)
from nbs_viewer.models.plot.derived_fetch import _profile_uses_nd_load
from nbs_viewer.models.plot.frozen_spectrum import (
    SYNTHETIC_KEY_PREFIX,
    FrozenSpectrum,
    copy_plot_bundle,
)
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.region import RectRegion, expand_region_for_profile
from nbs_viewer.models.plot.roi_set import RoiSetModel

from .derivative_preview_canvas import DerivativePreviewWorker
from .mpl_canvas import MplCanvas
from .plotDimensionWidget import PlotDimensionControl
from .roi_panel import RoiPanel
from .roi_window import RoiWindow


class DerivativeController(QObject):
    """
    Open the ROI window and run debounced preview fetches for the selected ROI.
    """

    def __init__(
        self,
        canvas: MplCanvas,
        dimension_control: PlotDimensionControl,
        panel: RoiPanel,
        roi_set: RoiSetModel,
        parent=None,
    ):
        super().__init__(parent)
        self.canvas = canvas
        self.dimension_control = dimension_control
        self.panel = panel
        self.roi_set = roi_set
        self._window = None
        self._active_worker = None
        self._commit_worker = None
        self._pending_workers = set()
        self._generation = 0
        self._commit_generation = 0
        self._pending_commit_span_full = None
        self._pending_commit_entry_id = None
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
        roi_set.selection_changed.connect(self._on_selection_changed)
        roi_set.entry_changed.connect(self._on_entry_changed)
        roi_set.entries_changed.connect(self._on_roi_or_view_changed)

        self._update_launcher_enabled()

    def _parent_spec(self):
        spec = self.dimension_control._cube_view_spec
        if spec is not None:
            return spec
        return self.canvas._cube_view_spec

    def _axis_names(self):
        names = self.dimension_control._dim_names
        return names if names is not None else ()

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
        if region_type != "rect":
            if self._window is not None:
                self._window.set_status(f"ROI type {region_type!r} is not available yet")
            return
        entry_id = self.roi_set.add_placeholder_rect()
        if self._window is not None:
            self._window.set_draw_checked(True)
            self.canvas.set_roi_draw_enabled(True)
            entry = self.roi_set.get(entry_id)
            label = entry.display_label if entry is not None else "ROI"
            self._window.set_status(f"Draw {label} on the parent plot")

    def _on_parent_plot_updated(self):
        if self._window is None or not self._window.isVisible():
            return
        if not self._window.is_preview_enabled():
            return
        self._schedule_preview()

    def _cached_parent_bundle(self, plot_model, request=None):
        """
        Return the parent :class:`PlotBundle` only when it matches the canvas view.
        """
        if plot_model is None or plot_model.last_bundle is None:
            return None
        if plot_model._cube_view_spec != self.canvas._cube_view_spec:
            return None
        if plot_model._indices != self.canvas._slice:
            return None
        if self.canvas._active_workers.get(plot_model._key) is not None:
            return None
        if request is not None and _profile_uses_nd_load(
            request, self._parent_spec()
        ):
            return None
        return plot_model.last_bundle

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
        model = self.canvas.get_single_visible_2d_model()
        if model is None:
            source = "No single 2D dataset selected"
        else:
            source = f"{model.label} · {model._ykey}"
        self._window.set_context(source)

        parent_spec = self._parent_spec()
        parent_frame = None
        if model is not None and model.last_bundle is not None:
            try:
                parent_frame = frame_from_bundle(model.last_bundle)
            except ValueError:
                parent_frame = None
        self._window.set_profile_context(
            parent_spec,
            self._axis_names(),
            parent_frame,
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

    def _commit_span_full(self, parent_spec, profile_storage_axis: int, span_full: bool) -> bool:
        """
        Return whether stack-spectrum save should span the full profile axis.
        """
        if classify_profile_kind(parent_spec, profile_storage_axis) != "stack_spectrum":
            return span_full
        if is_plot_plane_storage_axis(parent_spec, profile_storage_axis):
            return True
        return span_full

    def _selected_entry_for_preview(self):
        entry = self.roi_set.selected_entry()
        if entry is None:
            raise ValueError("Select an ROI")
        if entry.stale:
            raise ValueError("Selected ROI is stale; redraw it before previewing")
        if not entry.region.has_area():
            raise ValueError("Draw the selected ROI on the parent plot")
        return entry

    def _start_preview_worker(
        self,
        generation: int,
        entry,
        span_full_override=None,
    ):
        plot_model = self.canvas.get_single_visible_2d_model()
        if plot_model is None:
            raise ValueError("Select a single 2D dataset")

        parent_spec = self._parent_spec()
        span_full = (
            span_full_override
            if span_full_override is not None
            else entry.operation.span_full_profile_axis
        )
        request = self._window.build_profile_request(
            entry.region,
            parent_spec=parent_spec,
            span_full_profile_axis=span_full,
            operation=entry.operation,
        )
        if request is None:
            raise ValueError("Parent cube view is unavailable")

        worker = DerivativePreviewWorker(
            plot_model,
            request,
            generation,
            self,
            parent_spec=parent_spec,
            parent_bundle=self._cached_parent_bundle(plot_model, request),
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
            entry = self._selected_entry_for_preview()
        except ValueError as exc:
            self._window.show_preview_message(str(exc))
            self._window.set_status("")
            return

        plot_model = self.canvas.get_single_visible_2d_model()
        if plot_model is None:
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

        entry = self.roi_set.get(entry_id)
        if entry is None:
            self._window.set_status("Selected ROI is unavailable")
            return
        if entry.stale:
            self._window.set_status("Selected ROI is stale; redraw it before saving")
            return
        if not entry.region.has_area():
            self._window.set_status("Draw the selected ROI on the parent plot")
            return

        plot_model = self.canvas.get_single_visible_2d_model()
        if plot_model is None:
            self._window.set_status("Select a single 2D dataset")
            return

        if isinstance(entry.region, RectRegion):
            region = entry.region.normalized()
            if region.x1 - region.x0 == 0.0 or region.y1 - region.y0 == 0.0:
                self._window.set_status("ROI has zero width or height")
                return

        parent_spec = self._parent_spec()
        if parent_spec is None:
            self._window.set_status("Parent cube view is unavailable")
            return

        profile_axis = entry.operation.profile_storage_axis
        if profile_axis is None:
            profile_axis = self._window.get_profile_storage_axis()
        profile_kind = classify_profile_kind(parent_spec, profile_axis)
        if profile_kind == "local_profile":
            scan_axis = scan_profile_storage_axis(parent_spec)
            names = self._axis_names()
            if scan_axis is not None and scan_axis < len(names):
                hint = names[scan_axis]
            else:
                hint = "the leading scan axis"
            self._window.set_status(
                f"Select a profile along {hint} to save to Run Display"
            )
            self._save_all_queue.clear()
            return

        span_full = self._commit_span_full(
            parent_spec,
            profile_axis,
            entry.operation.span_full_profile_axis,
        )
        self._cancel_commit_worker()
        self._commit_generation += 1
        generation = self._commit_generation
        self._pending_commit_span_full = span_full
        self._pending_commit_entry_id = entry_id
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
        if bundle.render_mode != "line" or bundle.ndim != 1:
            self._window.set_status("Saved derivatives must be 1D line profiles")
            self._save_all_queue.clear()
            return

        plot_model = self.canvas.get_single_visible_2d_model()
        entry = self.roi_set.get(self._pending_commit_entry_id)
        if plot_model is None or entry is None:
            return

        parent_spec = self._parent_spec()
        span_full = self._pending_commit_span_full
        request = self._window.build_profile_request(
            entry.region,
            parent_spec=parent_spec,
            span_full_profile_axis=span_full,
            operation=entry.operation,
        )
        if request is None:
            return

        label = (
            entry.operation.label
            or entry.display_label
            or default_profile_label(
                request,
                self._axis_names(),
                parent_spec=parent_spec,
            )
        )
        x_keys, _, _ = plot_model._run.get_selected_keys()
        committed_xkey = x_keys[0] if x_keys else ""

        profile_axis = entry.operation.profile_storage_axis
        if profile_axis is None:
            profile_axis = self._window.get_profile_storage_axis()
        profile_kind = classify_profile_kind(parent_spec, profile_axis)

        frozen = FrozenSpectrum(
            key=f"{SYNTHETIC_KEY_PREFIX}{uuid4()}",
            label=label,
            bundle=copy_plot_bundle(bundle),
            kind=profile_kind,
            source_ykey=plot_model._ykey,
            committed_xkey=committed_xkey,
            request=request,
            source_key=plot_model._key,
            cube_fingerprint=(
                tuple(self.canvas._slice) if self.canvas._slice else None,
                str(self.canvas._cube_view_spec),
            ),
        )
        plot_model._run.register_frozen_spectrum(frozen)
        self._window.set_status(f"Saved: {label}")

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
