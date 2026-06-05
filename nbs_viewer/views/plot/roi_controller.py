from qtpy.QtCore import QObject

from nbs_viewer.models.plot.region import RectRegion

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
        canvas.roi_region_changed.connect(self._on_roi_region_changed)
        canvas.plot_view_updated.connect(self._on_plot_view_updated)

        dimension_control.dimensionChanged.connect(self._on_dimension_changed)
        run_list_model.selected_keys_changed.connect(
            lambda *_: self._invalidate_roi("field selection changed")
        )

        self._update_region_active()
        self._update_derivative_button()

    def _update_derivative_button(self):
        enabled = (
            self.canvas.region_controls_enabled()
            and self.canvas.get_roi_region() is not None
        )
        self.panel.set_create_derivative_enabled(enabled)

    def _on_draw_toggled(self, enabled: bool):
        self.canvas.set_roi_draw_enabled(enabled)

    def _on_clear_requested(self):
        self.canvas.clear_roi()
        self.panel.clear_corners()
        self.panel.set_status("")

    def _on_roi_region_changed(self, region):
        self._update_derivative_button()
        if region is None:
            self.panel.clear_corners()
            return
        region = region.normalized()
        self.panel.set_corners(region.x0, region.y0, region.x1, region.y1)
        width = region.x1 - region.x0
        height = region.y1 - region.y0
        if width == 0.0 or height == 0.0:
            self.panel.set_status("ROI has zero width or height")
        else:
            self.panel.set_status("")

    def _on_plot_view_updated(self):
        self._update_region_active()
        if self.canvas.region_controls_enabled():
            draw_checked = self.panel.draw_checkbox.isChecked()
            if draw_checked != self.canvas.is_roi_draw_enabled():
                self.canvas.set_roi_draw_enabled(draw_checked)
        self._validate_roi_against_view()

    def _on_dimension_changed(self, dimension: int):
        if dimension != 2:
            self._invalidate_roi("switched out of 2D mode")
        self._update_region_active()

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

    def _invalidate_roi(self, reason: str):
        if self.canvas.get_roi_region() is None and not self.canvas.is_roi_draw_enabled():
            self._update_region_active()
            return
        self.canvas.set_roi_draw_enabled(False)
        self.canvas.clear_roi()
        self.panel.set_draw_checked(False)
        self.panel.clear_corners()
        self.panel.set_status(f"ROI cleared: {reason}")
        self._update_region_active()

    def _update_region_active(self):
        active = self.canvas.region_controls_enabled()
        self.panel.set_region_active(active)
        if not active:
            self.canvas.set_roi_draw_enabled(False)
