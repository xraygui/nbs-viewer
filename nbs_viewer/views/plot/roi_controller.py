from qtpy.QtCore import QObject

from nbs_viewer.models.plot.cube_view import _fetch_plot_plane_storage_axes
from nbs_viewer.models.plot.view_crop import (
    crop_status_text,
    view_crop_from_region,
)

from .roi_panel import RoiPanel
from .plotDimensionWidget import PlotDimensionControl
from .mpl_canvas import MplCanvas


class RoiController(QObject):
    """
    Coordinate ROI panel, dimension controls, and canvas ROI state.
    """

    def __init__(
        self,
        canvas: MplCanvas,
        dimension_control: PlotDimensionControl,
        panel: RoiPanel,
        run_list_model,
        parent=None,
    ):
        super().__init__(parent)
        self.canvas = canvas
        self.dimension_control = dimension_control
        self.panel = panel
        self.run_list_model = run_list_model

        panel.draw_toggled.connect(self._on_draw_toggled)
        panel.clear_requested.connect(self._on_clear_requested)
        panel.apply_crop_requested.connect(self._on_apply_crop_requested)
        panel.clear_crop_requested.connect(self._on_clear_crop_requested)
        canvas.roi_region_changed.connect(self._on_roi_region_changed)
        canvas.view_crop_changed.connect(self._on_view_crop_changed)
        canvas.plot_view_updated.connect(self._on_plot_view_updated)

        dimension_control.dimensionChanged.connect(self._on_dimension_changed)
        dimension_control.cubeViewChanged.connect(self._on_cube_view_changed)
        run_list_model.selected_keys_changed.connect(
            lambda *_: self._invalidate_all("field selection changed")
        )

        self._update_region_active()
        self._update_panel_buttons()

    def _parent_spec(self):
        spec = self.dimension_control._cube_view_spec
        if spec is not None:
            return spec
        return self.canvas._cube_view_spec

    def _update_panel_buttons(self):
        roi_enabled = (
            self.canvas.region_controls_enabled()
            and self.canvas.get_roi_region() is not None
            and self.canvas.get_view_crop() is None
        )
        self.panel.set_create_derivative_enabled(
            self.canvas.region_controls_enabled()
            and self.canvas.get_roi_region() is not None
        )
        self.panel.set_apply_crop_enabled(roi_enabled)
        self.panel.set_clear_crop_enabled(
            self.canvas.region_controls_enabled()
            and self.canvas.get_view_crop() is not None
        )
        crop = self.canvas.get_view_crop()
        if crop is not None and not self.panel.draw_checkbox.isChecked():
            self.panel.set_status(crop_status_text(crop))

    def _on_draw_toggled(self, enabled: bool):
        self.canvas.set_roi_draw_enabled(enabled)

    def _on_clear_requested(self):
        self.canvas.clear_roi()
        self.panel.clear_corners()
        if self.canvas.get_view_crop() is None:
            self.panel.set_status("")

    def _on_apply_crop_requested(self):
        region = self.canvas.get_roi_region()
        if region is None:
            self.panel.set_status("Draw an ROI before applying crop")
            return
        if self.canvas.get_view_crop() is not None:
            self.panel.set_status("Clear the current crop before applying a new one")
            return

        model = self.canvas.get_single_visible_2d_model()
        parent_spec = self._parent_spec()
        if model is None or parent_spec is None:
            self.panel.set_status("Select a single 2D dataset")
            return

        width = region.normalized().x1 - region.normalized().x0
        height = region.normalized().y1 - region.normalized().y0
        if width == 0.0 or height == 0.0:
            self.panel.set_status("ROI has zero width or height")
            return

        try:
            full_frame = self.canvas.get_full_view_frame_for_crop()
            slice_info = parent_spec.to_load_slice_info()
            xlist, _names, _extra = model._run.get_dimension_axes(
                model._ykey,
                [model._xkey],
                slice_info,
            )
            plot_y_axis, plot_x_axis = _fetch_plot_plane_storage_axes(
                parent_spec,
                full_frame,
                parent_spec,
            )
            crop = view_crop_from_region(
                region,
                full_frame,
                parent_spec,
                model._key,
                xlist[plot_y_axis],
                xlist[plot_x_axis],
            )
        except ValueError as exc:
            self.panel.set_status(str(exc))
            return

        self.canvas.set_roi_draw_enabled(False)
        self.canvas.clear_roi()
        self.panel.set_draw_checked(False)
        self.panel.clear_corners()
        self.canvas.set_view_crop(crop)
        self.panel.set_status(crop_status_text(crop))
        self._update_panel_buttons()

    def _on_clear_crop_requested(self):
        self.canvas.clear_view_crop()
        self.panel.set_status("Crop cleared")
        self._update_panel_buttons()

    def _on_view_crop_changed(self, _crop):
        self._update_panel_buttons()

    def _on_roi_region_changed(self, region):
        self._update_panel_buttons()
        if region is None:
            if self.canvas.get_view_crop() is None:
                self.panel.clear_corners()
            return
        region = region.normalized()
        self.panel.set_corners(region.x0, region.y0, region.x1, region.y1)
        width = region.x1 - region.x0
        height = region.y1 - region.y0
        if width == 0.0 or height == 0.0:
            self.panel.set_status("ROI has zero width or height")
        elif self.canvas.get_view_crop() is None:
            self.panel.set_status("")

    def _on_plot_view_updated(self):
        self._update_region_active()
        if self.canvas.region_controls_enabled():
            draw_checked = self.panel.draw_checkbox.isChecked()
            if draw_checked != self.canvas.is_roi_draw_enabled():
                self.canvas.set_roi_draw_enabled(draw_checked)
        self._validate_roi_against_view()
        self._validate_crop_against_view()

    def _on_dimension_changed(self, dimension: int):
        if dimension != 2:
            self._invalidate_all("switched out of 2D mode")
        self._update_region_active()

    def _on_cube_view_changed(self, *_args):
        self._validate_crop_against_view()

    def _validate_roi_against_view(self):
        if self.canvas.get_roi_region() is None:
            return
        stored = self.canvas.get_roi_view_fingerprint()
        current = self.canvas.current_view_fingerprint()
        if stored is None or current is None:
            self._invalidate_roi("view no longer available")
            return
        if stored != current:
            self._invalidate_roi("view coordinates changed")

    def _validate_crop_against_view(self):
        crop = self.canvas.get_view_crop()
        if crop is None:
            return
        model = self.canvas.get_single_visible_2d_model()
        if model is None or model._key != crop.source_key:
            self._invalidate_crop("dataset changed")
            return
        parent_spec = self._parent_spec()
        if parent_spec is None:
            self._invalidate_crop("view no longer available")
            return
        try:
            plot_y_axis, plot_x_axis = _fetch_plot_plane_storage_axes(
                parent_spec,
                crop.full_frame,
                parent_spec,
            )
        except ValueError:
            self._invalidate_crop("plot axes changed")
            return
        if (
            plot_y_axis != crop.plot_y_axis
            or plot_x_axis != crop.plot_x_axis
        ):
            self._invalidate_crop("plot axes changed")

    def _invalidate_roi(self, reason: str):
        if self.canvas.get_roi_region() is None and not self.canvas.is_roi_draw_enabled():
            self._update_region_active()
            return
        self.canvas.set_roi_draw_enabled(False)
        self.canvas.clear_roi()
        self.panel.set_draw_checked(False)
        self.panel.clear_corners()
        if self.canvas.get_view_crop() is None:
            self.panel.set_status(f"ROI cleared: {reason}")
        self._update_region_active()

    def _invalidate_crop(self, reason: str):
        if self.canvas.get_view_crop() is None:
            return
        self.canvas.clear_view_crop()
        self.panel.set_status(f"Crop cleared: {reason}")
        self._update_panel_buttons()

    def _invalidate_all(self, reason: str):
        self._invalidate_crop(reason)
        self._invalidate_roi(reason)

    def _update_region_active(self):
        active = self.canvas.region_controls_enabled()
        self.panel.set_region_active(active)
        if not active:
            self.canvas.set_roi_draw_enabled(False)
        self._update_panel_buttons()
