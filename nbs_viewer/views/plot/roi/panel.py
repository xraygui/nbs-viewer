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


class RoiPanel(QWidget):
    """
    Inline crop controls and launcher for the ROI workbench window.

    Signals
    -------
    crop_draw_toggled : bool
        Emitted when the draw-crop toggle changes state.
    clear_crop_draft_requested : Signal
        Emitted when the user requests clearing the draft crop rectangle.
    apply_crop_requested : Signal
        Emitted when the user requests applying the draft crop.
    clear_crop_requested : Signal
        Emitted when the user requests clearing the applied view crop.
    roi_window_requested : Signal
        Emitted when the user opens the ROI workbench window.
    """

    crop_draw_toggled = Signal(bool)
    clear_crop_draft_requested = Signal()
    apply_crop_requested = Signal()
    clear_crop_requested = Signal()
    roi_window_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self.apply_crop_button.clicked.connect(self.apply_crop_requested.emit)
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
        from ..common.panel import CollapsiblePanel

        panel = self.parentWidget()
        while panel is not None and not isinstance(panel, CollapsiblePanel):
            panel = panel.parentWidget()
        if panel is not None:
            panel.refresh_expanded_size()
