"""
Manage the derivative plot dialog and debounced preview updates.
"""

from __future__ import annotations

from qtpy.QtCore import QObject, QTimer

from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle

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
        self._pending_workers = set()
        self._generation = 0

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.timeout.connect(self._run_preview)

        panel.create_derivative_requested.connect(self._open_or_raise_dialog)
        canvas.roi_region_changed.connect(self._on_roi_or_view_changed)
        dimension_control.indicesUpdated.connect(self._on_roi_or_view_changed)
        dimension_control.cubeViewChanged.connect(self._on_roi_or_view_changed)

        self._update_create_button_enabled()

    def _open_or_raise_dialog(self):
        if self._dialog is None:
            parent_window = self.panel.window()
            self._dialog = DerivativePlotDialog(parent_window)
            self._dialog.spec_changed.connect(self._schedule_preview)
            self._dialog.preview_enabled_changed.connect(
                self._schedule_preview
            )
            self._dialog.finished.connect(self._on_dialog_finished)
        self._update_dialog_context()
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
        self._trigger_initial_preview()

    def _on_dialog_finished(self):
        self._cancel_preview_worker()
        self._dialog = None

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
        bundle = None
        if model is not None:
            bundle = model.last_bundle
        if bundle is not None:
            try:
                frame = frame_from_bundle(bundle)
                self._dialog.set_profile_axis_choices(
                    frame.plot_x_name, frame.plot_y_name
                )
            except ValueError:
                pass

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
        spec = self._dialog.get_spec()

        worker = DerivativePreviewWorker(
            plot_model,
            self.canvas._slice,
            self.canvas._cube_view_spec,
            region,
            spec,
            generation,
            self,
        )
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

    def _on_worker_finished(self, worker):
        self._pending_workers.discard(worker)
        if self._active_worker is worker:
            self._active_worker = None

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
