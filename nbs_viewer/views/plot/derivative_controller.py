"""
Manage the derivative plot dialog and debounced preview updates.
"""

from __future__ import annotations

from uuid import uuid4

from qtpy.QtCore import QObject, QTimer

from nbs_viewer.models.plot.derived_plot_data_model import DerivedPlotDataModel
from nbs_viewer.models.plot.derived_product import DerivedProduct
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.region import expand_rect_for_profile

from .derivative_plot_dialog import DerivativePlotDialog
from .derivative_preview_canvas import DerivativePreviewWorker
from .derived_series_registry import DerivedSeriesRegistry
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
        self.registry = DerivedSeriesRegistry(self)
        self._dialog = None
        self._active_worker = None
        self._commit_worker = None
        self._pending_workers = set()
        self._generation = 0
        self._commit_generation = 0
        self._commit_pin_only = False

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.timeout.connect(self._run_preview)

        panel.create_derivative_requested.connect(self._open_or_raise_dialog)
        canvas.roi_region_changed.connect(self._on_roi_or_view_changed)
        canvas.plot_view_updated.connect(self._on_parent_plot_updated)
        dimension_control.indicesUpdated.connect(self._on_roi_or_view_changed)
        dimension_control.cubeViewChanged.connect(self._on_roi_or_view_changed)
        dimension_control.dimensionChanged.connect(
            self._on_dimension_changed
        )

        self._update_create_button_enabled()

    def _open_or_raise_dialog(self):
        if self._dialog is None:
            parent_window = self.panel.window()
            self._dialog = DerivativePlotDialog(parent_window)
            self._dialog.spec_changed.connect(self._schedule_preview)
            self._dialog.preview_enabled_changed.connect(
                self._schedule_preview
            )
            self._dialog.create_requested.connect(self._on_create_requested)
            self._dialog.pin_requested.connect(self._on_pin_requested)
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

    def _on_dimension_changed(self, _dimension: int):
        self.canvas.sync_derived_line_display()

    def _on_parent_plot_updated(self):
        if self._dialog is None or not self._dialog.isVisible():
            return
        if not self._dialog.is_preview_enabled():
            return
        if self.canvas.get_roi_region() is None:
            return
        self._schedule_preview()

    def _cached_parent_bundle(self, plot_model):
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
            parent_bundle=self._cached_parent_bundle(plot_model),
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

    def _on_pin_requested(self):
        self._start_commit(pin_only=True)

    def _on_create_requested(self):
        self._start_commit(pin_only=False)

    def _start_commit(self, pin_only: bool):
        if self._dialog is None:
            return
        spec = self._dialog.get_spec()
        if spec.output_kind != "profile":
            if pin_only:
                self._dialog.set_status(
                    "Pin for comparison applies to 1D profiles only"
                )
            else:
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

        self._cancel_commit_worker()
        self._commit_generation += 1
        generation = self._commit_generation
        self._commit_pin_only = pin_only
        action = "Pinning" if pin_only else "Creating"
        self._dialog.set_status(f"{action}…")

        worker = DerivativePreviewWorker(
            plot_model,
            self.canvas._slice,
            self.canvas._cube_view_spec,
            region,
            spec,
            generation,
            self,
            parent_bundle=self._cached_parent_bundle(plot_model),
        )
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
                "Committed derivatives must be 1D line profiles"
            )
            return

        plot_model = self.canvas.get_single_visible_2d_model()
        region = self.canvas.get_roi_region()
        if plot_model is None or region is None:
            return

        spec = self._dialog.get_spec()
        parent_bundle = plot_model.last_bundle
        axis_name = ""
        if parent_bundle is not None:
            try:
                frame = frame_from_bundle(parent_bundle)
                if spec.profile_axis == "plot_x":
                    axis_name = frame.plot_x_name
                else:
                    axis_name = frame.plot_y_name
            except ValueError:
                pass
        label = spec.label or spec.default_label(axis_name)
        product_id = str(uuid4())
        fetch_region = region
        if parent_bundle is not None:
            from nbs_viewer.models.plot.derived_fetch import (
                region_for_derivative_fetch,
            )

            fetch_region = region_for_derivative_fetch(
                parent_bundle, region, spec
            )

        product = DerivedProduct(
            product_id=product_id,
            spec=spec,
            source_key=plot_model._key,
            region=fetch_region,
            bundle=bundle,
            label=label,
            cube_fingerprint=(
                tuple(self.canvas._slice) if self.canvas._slice else None,
                str(self.canvas._cube_view_spec),
            ),
        )
        self.registry.append(product)
        model = DerivedPlotDataModel(product_id, bundle, label, self)
        self.canvas.add_derived_plot(model)

        pin_only = self._commit_pin_only
        if not pin_only:
            if self.dimension_control.dimension_spinbox.value() != 1:
                self.dimension_control.dimension_spinbox.setValue(1)
            else:
                self.canvas.sync_derived_line_display()

        verb = "Pinned" if pin_only else "Created"
        self._dialog.set_status(f"{verb}: {label}")

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
        expanded = expand_rect_for_profile(frame, region, profile_axis)
        self.canvas.apply_roi_from_region(expanded)
        if self._dialog is not None:
            self._schedule_preview()
