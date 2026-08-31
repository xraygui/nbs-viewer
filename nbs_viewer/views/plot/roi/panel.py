from qtpy.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QCheckBox,
    QLabel,
    QSizePolicy,
)
from qtpy.QtCore import Signal
from nbs_viewer.views.common.panel import CollapsiblePanel
from nbs_viewer.models.plot.view_crop import crop_status_text


class RoiPanel(QWidget):
    """
    Inline crop controls and launcher for the ROI workbench window.

    Signals
    -------
    crop_draw_toggled : bool
        Emitted when the draw-crop toggle changes state.
    clear_crop_draft_requested : Signal
        Emitted when the user requests clearing the draft crop rectangle.
    clear_crop_requested : Signal
        Emitted when the user requests clearing the applied view crop.
    roi_window_requested : Signal
        Emitted when the user opens the ROI workbench window.
    """

    crop_draw_toggled = Signal(bool)
    clear_crop_draft_requested = Signal()
    clear_crop_requested = Signal()
    roi_window_requested = Signal()

    def __init__(self, presenter, canvas, dimension_control=None, parent=None):
        super().__init__(parent)
        self.presenter = presenter
        self.plot_model = presenter.plot
        self.canvas = canvas
        self.dimension_control = dimension_control
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.crop_draw_checkbox = QCheckBox("Draw crop region")
        self.crop_draw_checkbox.toggled.connect(self.crop_draw_toggled.emit)
        layout.addWidget(self.crop_draw_checkbox)

        self.crop_corners_label = QLabel("Crop: —")
        self.crop_corners_label.setWordWrap(True)
        layout.addWidget(self.crop_corners_label)

        button_row1 = QHBoxLayout()
        button_row1.setContentsMargins(0, 0, 0, 0)
        button_row1.setSpacing(4)
        self.apply_crop_button = QPushButton("Apply crop")
        button_row1.addWidget(self.apply_crop_button)

        self.clear_crop_button = QPushButton("Clear crop")
        self.clear_crop_button.clicked.connect(self.clear_crop_requested.emit)
        button_row1.addWidget(self.clear_crop_button)
        layout.addLayout(button_row1)

        button_row2 = QHBoxLayout()
        button_row2.setContentsMargins(0, 0, 0, 0)
        button_row2.setSpacing(4)
        self.clear_crop_draft_button = QPushButton("Clear crop draft")
        self.clear_crop_draft_button.clicked.connect(
            self.clear_crop_draft_requested.emit
        )
        button_row2.addWidget(self.clear_crop_draft_button)

        self.roi_window_button = QPushButton("ROI Window…")
        self.roi_window_button.clicked.connect(self.roi_window_requested.emit)
        button_row2.addWidget(self.roi_window_button)
        layout.addLayout(button_row2)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self._panel_enabled = True
        self.set_region_active(False)

    def connect_signals(self):
        self.crop_draw_toggled.connect(self._on_crop_draw_toggled)
        self.clear_crop_draft_requested.connect(self._on_clear_crop_draft_requested)
        self.clear_crop_requested.connect(self._on_clear_crop_requested)
        self.apply_crop_button.clicked.connect(self._on_apply_crop_requested)
        self.canvas.crop_region_changed.connect(self._on_crop_region_changed)
        self.plot_model.view_crop_changed.connect(self._on_view_crop_changed)
        self.canvas.plot_view_updated.connect(self._on_plot_view_updated)
        self.plot_model.region_status_changed.connect(self.set_status)
        self.plot_model.region_invalidation_requested.connect(
            self._on_region_invalidation_requested
        )
        self.plot_model.roi_draw_enabled_changed.connect(
            self._on_roi_draw_enabled_changed
        )
        self.roi_window_requested.connect(self._on_roi_window_requested)

    def _on_roi_window_requested(self):
        from .window import RoiWindow

        RoiWindow.open_or_raise(
            self.presenter,
            parent=self.window(),
            dimension_control=self.dimension_control,
        )

    def set_region_active(self, active: bool):
        """
        Enable or disable crop controls for the current view mode.

        Parameters
        ----------
        active : bool
            True when a single 2D image or mesh plot is available.
        """
        enabled = active and self._panel_enabled
        self.crop_draw_checkbox.setEnabled(enabled)
        self.clear_crop_draft_button.setEnabled(enabled)
        self.roi_window_button.setEnabled(enabled)
        if not active:
            self.apply_crop_button.setEnabled(False)
            self.clear_crop_button.setEnabled(False)
            if self.crop_draw_checkbox.isChecked():
                self.crop_draw_checkbox.blockSignals(True)
                self.crop_draw_checkbox.setChecked(False)
                self.crop_draw_checkbox.blockSignals(False)
            self.crop_corners_label.setText("Crop: —")
            self.canvas.set_crop_draw_enabled(False)

    def set_apply_crop_enabled(self, enabled: bool):
        """
        Enable the apply-crop button when a draft crop is available.
        """
        self.apply_crop_button.setEnabled(self._panel_enabled and enabled)

    def set_clear_crop_enabled(self, enabled: bool):
        """
        Enable the clear-crop button when a crop is active.
        """
        self.clear_crop_button.setEnabled(self._panel_enabled and enabled)

    def set_roi_window_enabled(self, enabled: bool):
        """
        Enable the ROI window launcher when a 2D view is available.
        """
        self.roi_window_button.setEnabled(self._panel_enabled and enabled)

    def set_panel_enabled(self, enabled: bool):
        """
        Enable or disable the entire panel chrome.
        """
        self._panel_enabled = enabled
        self.setEnabled(enabled)

    def set_crop_draw_checked(self, checked: bool):
        """
        Set the crop draw toggle without emitting ``crop_draw_toggled``.
        """
        if self.crop_draw_checkbox.isChecked() == checked:
            return
        self.crop_draw_checkbox.blockSignals(True)
        self.crop_draw_checkbox.setChecked(checked)
        self.crop_draw_checkbox.blockSignals(False)

    def set_crop_corners(self, x0, y0, x1, y1):
        """
        Display draft crop corners in data coordinates.
        """
        self.crop_corners_label.setText(
            f"Crop: ({x0:.2f}, {y0:.2f}) — ({x1:.2f}, {y1:.2f})"
        )

    def clear_crop_corners(self):
        """
        Reset the draft crop corner readout.
        """
        self.crop_corners_label.setText("Crop: —")

    def set_status(self, message: str):
        """
        Show a short status message.
        """
        self.status_label.setText(message or "")

    def refresh_parent_panel(self):
        """
        Update the enclosing :class:`CollapsiblePanel` height.
        """

        panel = self.parentWidget()
        while panel is not None and not isinstance(panel, CollapsiblePanel):
            panel = panel.parentWidget()
        if panel is not None:
            panel.refresh_expanded_size()

    def _on_roi_draw_enabled_changed(self, enabled: bool):
        if enabled:
            self.set_crop_draw_checked(False)
            self.canvas.set_crop_draw_enabled(False)

    def _on_crop_draw_toggled(self, enabled: bool):
        if enabled and self.plot_model.is_roi_draw_enabled():
            self.plot_model.set_roi_draw_enabled(False)
        self.canvas.set_crop_draw_enabled(enabled)

    def _on_clear_crop_draft_requested(self):
        self.canvas.clear_crop_draft()
        self.clear_crop_corners()
        self.set_crop_draw_checked(False)
        self.canvas.set_crop_draw_enabled(False)
        if self.plot_model.view_crop is None:
            self.set_status("")
        self._update_panel_buttons()

    def _on_clear_crop_requested(self):
        self.plot_model.clear_view_crop()
        self.set_status("Crop cleared")
        self._update_panel_buttons()

    def _on_apply_crop_requested(self):
        region = self.canvas.get_crop_region()
        if region is None:
            self.set_status("Draw a crop region before applying crop")
            return
        try:
            crop = self.plot_model.apply_view_crop_from_region(region)
        except ValueError as exc:
            self.set_status(str(exc))
            return
        self.canvas.set_crop_draw_enabled(False)
        self.set_crop_draw_checked(False)
        self.canvas.clear_crop_draft(paint=False)
        self.clear_crop_corners()
        self.set_status(crop_status_text(crop))
        self._update_panel_buttons()

    def _on_crop_region_changed(self, region):
        self._update_panel_buttons()
        if region is None:
            self.clear_crop_corners()
            return
        region = region.normalized()
        self.set_crop_corners(region.x0, region.y0, region.x1, region.y1)
        width = region.x1 - region.x0
        height = region.y1 - region.y0
        if width == 0.0 or height == 0.0:
            self.set_status("Crop region has zero width or height")
        elif self.plot_model.view_crop is None:
            self.set_status("")

    def _on_view_crop_changed(self, _crop):
        self._update_panel_buttons()

    def _on_plot_view_updated(self):
        self.set_region_active(self.canvas.region_controls_enabled())
        if self.canvas.region_controls_enabled():
            crop_draw_checked = self.crop_draw_checkbox.isChecked()
            if crop_draw_checked != self.canvas.is_crop_draw_enabled():
                self.canvas.set_crop_draw_enabled(crop_draw_checked)
        self._update_panel_buttons()

    def _on_region_invalidation_requested(self, _reason: str):
        self.clear_crop_corners()
        self.set_crop_draw_checked(False)

    def _update_panel_buttons(self):
        region_active = self.canvas.region_controls_enabled()
        has_crop_draft = self.canvas.get_crop_region() is not None
        self.set_apply_crop_enabled(region_active and has_crop_draft)
        self.set_clear_crop_enabled(
            region_active and self.plot_model.view_crop is not None
        )
        self.set_roi_window_enabled(region_active)
        crop = self.plot_model.view_crop
        if (
            crop is not None
            and not self.crop_draw_checkbox.isChecked()
            and not has_crop_draft
        ):
            self.set_status(crop_status_text(crop))
