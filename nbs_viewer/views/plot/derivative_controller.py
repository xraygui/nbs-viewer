"""
Manage the derivative plot dialog and debounced preview updates.
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
from nbs_viewer.models.plot.region import expand_rect_for_profile

from .derivative_plot_dialog import DerivativePlotDialog
from .derivative_preview_canvas import DerivativePreviewWorker
from .mpl_canvas import MplCanvas
from .plotDimensionWidget import PlotDimensionControl
from .roi_panel import RoiPanel


class DerivativeController(QObject):
    """
    Open the modeless derivative dialog and run debounced preview fetches.
    """

    def __init__(
        self,
        canvas: MplCanvas,
        dimension_control: PlotDimensionControl,
        panel: RoiPanel,
        parent=None,
    ):
        super().__init__(parent)
        self.canvas = canvas
        self.dimension_control = dimension_control
        self.panel = panel
        self._dialog = None
        self._active_worker = None
        self._commit_worker = None
        self._pending_workers = set()
        self._generation = 0
        self._commit_generation = 0
        self._pending_commit_span_full = None

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.timeout.connect(self._run_preview)

        panel.create_derivative_requested.connect(self._open_or_raise_dialog)
        canvas.roi_region_changed.connect(self._on_roi_or_view_changed)
        canvas.plot_view_updated.connect(self._on_parent_plot_updated)
        dimension_control.indicesUpdated.connect(self._on_roi_or_view_changed)
        dimension_control.cubeViewChanged.connect(self._on_roi_or_view_changed)

        self._update_create_button_enabled()

    def _parent_spec(self):
        spec = self.dimension_control._cube_view_spec
        if spec is not None:
            return spec
        return self.canvas._cube_view_spec

    def _axis_names(self):
        names = self.dimension_control._dim_names
        return names if names is not None else ()

    def _open_or_raise_dialog(self):
        if self._dialog is None:
            parent_window = self.panel.window()
            self._dialog = DerivativePlotDialog(parent_window)
            self._dialog.request_changed.connect(self._schedule_preview)
            self._dialog.preview_enabled_changed.connect(
                self._schedule_preview
            )
            self._dialog.save_requested.connect(self._on_save_requested)
            self._dialog.full_height_requested.connect(
                self._apply_roi_full_height
            )
            self._dialog.full_width_requested.connect(
                self._apply_roi_full_width
            )
            self._dialog.finished.connect(self._on_dialog_finished)
        self._update_dialog_context()
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
        self._trigger_initial_preview()

    def _on_dialog_finished(self):
        self._cancel_preview_worker()
        self._cancel_commit_worker()
        self._dialog = None

    def _on_parent_plot_updated(self):
        if self._dialog is None or not self._dialog.isVisible():
            return
        if not self._dialog.is_preview_enabled():
            return
        if self.canvas.get_roi_region() is None:
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
        self._update_create_button_enabled()
        if self._dialog is None or not self._dialog.isVisible():
            return
        self._update_dialog_context()
        self._schedule_preview()

    def _update_create_button_enabled(self):
        enabled = (
            self.canvas.region_controls_enabled()
            and self.canvas.get_roi_region() is not None
        )
        self.panel.set_create_derivative_enabled(enabled)

    def _update_dialog_context(self):
        if self._dialog is None:
            return
        model = self.canvas.get_single_visible_2d_model()
        region = self.canvas.get_roi_region()
        if model is None:
            source = "No single 2D dataset selected"
        else:
            source = f"{model.label} · {model._ykey}"
        if region is None:
            roi_text = "ROI: —"
        else:
            region = region.normalized()
            roi_text = (
                f"ROI: ({region.x0:g}, {region.y0:g}) — "
                f"({region.x1:g}, {region.y1:g})"
            )
        self._dialog.set_context(source, roi_text)

        parent_spec = self._parent_spec()
        parent_frame = None
        if model is not None and model.last_bundle is not None:
            try:
                parent_frame = frame_from_bundle(model.last_bundle)
            except ValueError:
                parent_frame = None
        self._dialog.set_profile_context(
            parent_spec,
            self._axis_names(),
            parent_frame,
        )

    def _schedule_preview(self, *_args):
        if self._dialog is None:
            return
        self._debounce_timer.stop()
        self._debounce_timer.start()

    def _trigger_initial_preview(self):
        """
        Run preview once the dialog is shown and laid out.

        A direct call from ``show()`` can run before Qt reports the dialog
        visible, so the first fetch is deferred to the next event-loop tick.
        """
        if self._dialog is None:
            return
        self._debounce_timer.stop()
        if not self._dialog.is_preview_enabled():
            return
        self._dialog.show_preview_message("Updating preview…")
        QTimer.singleShot(0, self._run_preview)

    def _commit_span_full(self, parent_spec, profile_storage_axis: int) -> bool:
        """
        Return whether stack-spectrum save should span the full profile axis.
        """
        if classify_profile_kind(parent_spec, profile_storage_axis) != "stack_spectrum":
            return self._dialog.span_full_profile_axis()
        if is_plot_plane_storage_axis(parent_spec, profile_storage_axis):
            return True
        return self._dialog.span_full_profile_axis()

    def _start_preview_worker(
        self,
        generation: int,
        for_commit: bool,
        span_full_override=None,
    ):
        region = self.canvas.get_roi_region()
        if region is None:
            raise ValueError("Draw an ROI on the parent plot")

        plot_model = self.canvas.get_single_visible_2d_model()
        if plot_model is None:
            raise ValueError("Select a single 2D dataset")

        parent_spec = self._parent_spec()
        if self._dialog.is_profile_output():
            span_full = (
                span_full_override
                if span_full_override is not None
                else self._dialog.span_full_profile_axis()
            )
            request = self._dialog.build_profile_request(
                region,
                parent_spec=parent_spec,
                span_full_profile_axis=span_full,
            )
        else:
            request = self._dialog.build_plane_request(
                region,
                parent_spec=parent_spec,
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
        )
        return worker

    def _run_preview(self):
        if self._dialog is None:
            return
        if not self._dialog.is_preview_enabled():
            self._cancel_preview_worker()
            self._dialog.show_preview_message("Preview disabled")
            return

        region = self.canvas.get_roi_region()
        if region is None:
            self._dialog.show_preview_message(
                "Draw an ROI on the parent plot"
            )
            self._dialog.set_status("")
            return

        plot_model = self.canvas.get_single_visible_2d_model()
        if plot_model is None:
            self._dialog.show_preview_message(
                "Select a single 2D dataset"
            )
            self._dialog.set_status("")
            return

        self._cancel_preview_worker()
        self._generation += 1
        generation = self._generation

        try:
            worker = self._start_preview_worker(generation, for_commit=False)
        except ValueError as exc:
            self._dialog.show_preview_message("Preview unavailable")
            self._dialog.set_status(str(exc))
            return

        worker.preview_ready.connect(self._on_preview_ready)
        worker.error_occurred.connect(self._on_preview_error)
        worker.finished.connect(
            lambda w=worker: self._on_worker_finished(w)
        )
        self._active_worker = worker
        self._pending_workers.add(worker)
        self._dialog.set_status("Updating preview…")
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
        if self._dialog is None or generation != self._generation:
            return
        if not self._dialog.is_preview_enabled():
            return
        self._dialog.show_preview_bundle(bundle)
        self._dialog.set_status("")

    def _on_preview_error(self, message, generation):
        if self._dialog is None or generation != self._generation:
            return
        self._dialog.show_preview_message("Preview unavailable")
        self._dialog.set_status(message)

    def _on_save_requested(self):
        self._start_commit()

    def _start_commit(self):
        if self._dialog is None:
            return
        if not self._dialog.is_profile_output():
            self._dialog.set_status(
                "Committed 2D planes are not supported yet; "
                "use preview or switch to 1D profile"
            )
            return

        region = self.canvas.get_roi_region()
        if region is None:
            self._dialog.set_status("Draw an ROI on the parent plot")
            return

        plot_model = self.canvas.get_single_visible_2d_model()
        if plot_model is None:
            self._dialog.set_status("Select a single 2D dataset")
            return

        width = region.normalized().x1 - region.normalized().x0
        height = region.normalized().y1 - region.normalized().y0
        if width == 0.0 or height == 0.0:
            self._dialog.set_status("ROI has zero width or height")
            return

        parent_spec = self._parent_spec()
        if parent_spec is None:
            self._dialog.set_status("Parent cube view is unavailable")
            return

        profile_axis = self._dialog.get_profile_storage_axis()
        profile_kind = classify_profile_kind(parent_spec, profile_axis)
        if profile_kind == "local_profile":
            scan_axis = scan_profile_storage_axis(parent_spec)
            names = self._axis_names()
            if scan_axis is not None and scan_axis < len(names):
                hint = names[scan_axis]
            else:
                hint = "the leading scan axis"
            self._dialog.set_status(
                f"Select a profile along {hint} to save to Run Display"
            )
            return

        span_full = self._commit_span_full(parent_spec, profile_axis)
        request = self._dialog.build_profile_request(
            region,
            parent_spec=parent_spec,
            span_full_profile_axis=span_full,
        )
        if request is None:
            self._dialog.set_status("Parent cube view is unavailable")
            return

        self._cancel_commit_worker()
        self._commit_generation += 1
        generation = self._commit_generation
        self._pending_commit_span_full = span_full
        self._dialog.set_status("Saving…")

        try:
            worker = self._start_preview_worker(
                generation,
                for_commit=True,
                span_full_override=span_full,
            )
        except ValueError as exc:
            self._dialog.set_status(str(exc))
            return

        worker.preview_ready.connect(self._on_commit_ready)
        worker.error_occurred.connect(self._on_commit_error)
        worker.finished.connect(
            lambda w=worker: self._on_worker_finished(w)
        )
        self._commit_worker = worker
        self._pending_workers.add(worker)
        worker.start()

    def _on_commit_ready(self, bundle, generation):
        if self._dialog is None or generation != self._commit_generation:
            return
        if bundle.render_mode != "line" or bundle.ndim != 1:
            self._dialog.set_status(
                "Saved derivatives must be 1D line profiles"
            )
            return

        plot_model = self.canvas.get_single_visible_2d_model()
        region = self.canvas.get_roi_region()
        if plot_model is None or region is None:
            return

        parent_spec = self._parent_spec()
        span_full = self._pending_commit_span_full
        request = self._dialog.build_profile_request(
            region,
            parent_spec=parent_spec,
            span_full_profile_axis=span_full,
        )
        if request is None:
            return

        label = self._dialog.get_label() or default_profile_label(
            request,
            self._axis_names(),
            parent_spec=parent_spec,
        )
        x_keys, _, _ = plot_model._run.get_selected_keys()
        committed_xkey = x_keys[0] if x_keys else ""

        profile_axis = self._dialog.get_profile_storage_axis()
        profile_kind = classify_profile_kind(parent_spec, profile_axis)

        entry = FrozenSpectrum(
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
        plot_model._run.register_frozen_spectrum(entry)
        self._dialog.set_status(f"Saved: {label}")

    def _on_commit_error(self, message, generation):
        if self._dialog is None or generation != self._commit_generation:
            return
        self._dialog.set_status(message)

    def _apply_roi_full_height(self):
        self._apply_roi_full_span("plot_y")

    def _apply_roi_full_width(self):
        self._apply_roi_full_span("plot_x")

    def _apply_roi_full_span(self, profile_axis: str):
        region = self.canvas.get_roi_region()
        if region is None:
            if self._dialog is not None:
                self._dialog.set_status("Draw an ROI on the parent plot first")
            return
        try:
            frame = self.canvas.get_view_frame()
        except ValueError as exc:
            if self._dialog is not None:
                self._dialog.set_status(str(exc))
            return
        if self._dialog is not None:
            selected = self._dialog.profile_axis_for_roi_span()
            if selected is not None:
                profile_axis = selected
        expanded = expand_rect_for_profile(frame, region, profile_axis)
        self.canvas.apply_roi_from_region(expanded)
        if self._dialog is not None:
            self._schedule_preview()
