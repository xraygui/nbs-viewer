from qtpy.QtCore import QObject

from nbs_viewer.models.plot.roi_set import RoiSetModel

from .panel import RoiPanel
from ..plotDimensionWidget import PlotDimensionControl
from ..mpl_canvas import MplCanvas


class RoiController(QObject):
    """
    Coordinate crop panel, dimension controls, canvas, and :class:`RoiSetModel`.
    """

    def __init__(
        self,
        canvas: MplCanvas,
        dimension_control: PlotDimensionControl,
        panel: RoiPanel,
        presenter,
        roi_set: RoiSetModel,
        parent=None,
    ):
        super().__init__(parent)
        self.canvas = canvas
        self.dimension_control = dimension_control
        self.panel = panel
        self.presenter = presenter
        self.plot_model = presenter.plot
        self.run_list_model = presenter.run_list
        self.roi_set = presenter.plot.roi_set

        canvas.plot_view_updated.connect(self._on_plot_view_updated)

        dimension_control.dimensionChanged.connect(self._on_dimension_changed)
        dimension_control.cubeViewChanged.connect(self._on_cube_view_changed)
        canvas.plot_model.selected_keys_changed.connect(
            lambda *_: self._invalidate_all("field selection changed")
        )

        self._update_region_active()

    def _on_plot_view_updated(self):
        self._update_region_active()
        self._validate_roi_against_view()
        self._validate_crop_against_view()

    def _on_dimension_changed(self, dimension: int):
        if dimension != 2:
            self._invalidate_all("switched out of 2D mode")
        self._update_region_active()

    def _on_cube_view_changed(self, *_args):
        self._validate_roi_against_view()
        self._validate_crop_against_view()

    def _validate_roi_against_view(self):
        if len(self.roi_set) == 0:
            return
        current = self.canvas.current_view_fingerprint()
        newly_stale = self.roi_set.mark_stale_for_fingerprint(current)
        if newly_stale:
            self.panel.set_status("ROI marked stale: view coordinates changed")

    def _validate_crop_against_view(self):
        reason = self.plot_model.invalidate_view_crop_if_invalid()
        if reason is not None:
            self.panel.set_status(f"Crop cleared: {reason}")

    def _invalidate_roi(self, reason: str):
        if len(self.roi_set) == 0 and not self.canvas.is_roi_draw_enabled():
            self._update_region_active()
            return
        self.canvas.set_roi_draw_enabled(False)
        self.roi_set.mark_stale_for_fingerprint(None)
        if self.plot_model.view_crop is None:
            self.panel.set_status(f"ROI marked stale: {reason}")
        self._update_region_active()

    def _invalidate_crop(self, reason: str):
        if self.plot_model.view_crop is None:
            return
        self.plot_model.clear_view_crop()
        self.panel.set_status(f"Crop cleared: {reason}")

    def _invalidate_all(self, reason: str):
        self._invalidate_crop(reason)
        self._invalidate_roi(reason)
        self.canvas.clear_crop_draft(paint=False)
        self.panel.clear_crop_corners()
        self.panel.set_crop_draw_checked(False)
        self.canvas.set_crop_draw_enabled(False)

    def _update_region_active(self):
        active = self.canvas.region_controls_enabled()
        self.panel.set_region_active(active)
