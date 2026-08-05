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
    Controls for drawing and inspecting a single rectangular ROI.

    Signals
    -------
    draw_toggled : bool
        Emitted when the draw-region toggle changes state.
    clear_requested : Signal
        Emitted when the user requests clearing the ROI.
    """

    draw_toggled = Signal(bool)
    clear_requested = Signal()
    apply_crop_requested = Signal()
    clear_crop_requested = Signal()
    create_derivative_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.draw_checkbox = QCheckBox("Draw region")
        self.draw_checkbox.toggled.connect(self.draw_toggled.emit)
        layout.addWidget(self.draw_checkbox)

        self.corners_label = QLabel("Corners: —")
        self.corners_label.setWordWrap(True)
        layout.addWidget(self.corners_label)

        button_layout = QVBoxLayout()
        button_row1 = QHBoxLayout()
        button_row1.setContentsMargins(0, 0, 0, 0)
        button_row1.setSpacing(4)
        self.clear_button = QPushButton("Clear ROI")
        self.clear_button.clicked.connect(self.clear_requested.emit)
        button_row1.addWidget(self.clear_button)

        self.apply_crop_button = QPushButton("Apply crop")
        self.apply_crop_button.clicked.connect(self.apply_crop_requested.emit)
        button_row1.addWidget(self.apply_crop_button)

        button_layout.addLayout(button_row1)
        button_row2 = QHBoxLayout()
        button_row2.setContentsMargins(0, 0, 0, 0)
        button_row2.setSpacing(4)

        self.create_derivative_button = QPushButton("Create ROI Plot")
        self.create_derivative_button.setEnabled(False)
        self.create_derivative_button.clicked.connect(
            self.create_derivative_requested.emit
        )
        button_row2.addWidget(self.create_derivative_button)

        self.clear_crop_button = QPushButton("Clear crop")
        self.clear_crop_button.clicked.connect(self.clear_crop_requested.emit)
        button_row2.addWidget(self.clear_crop_button)

        button_layout.addLayout(button_row2)
        layout.addLayout(button_layout)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self._panel_enabled = True
        self.set_region_active(False)

    def set_region_active(self, active: bool):
        """
        Enable or disable ROI controls for the current view mode.

        Parameters
        ----------
        active : bool
            True when a single 2D image or mesh plot is available.
        """
        self.draw_checkbox.setEnabled(active and self._panel_enabled)
        self.clear_button.setEnabled(active and self._panel_enabled)
        if not active:
            self.create_derivative_button.setEnabled(False)
            self.apply_crop_button.setEnabled(False)
            self.clear_crop_button.setEnabled(False)
        if not active:
            if self.draw_checkbox.isChecked():
                self.draw_checkbox.blockSignals(True)
                self.draw_checkbox.setChecked(False)
                self.draw_checkbox.blockSignals(False)
            self.corners_label.setText("Corners: —")

    def set_apply_crop_enabled(self, enabled: bool):
        """
        Enable the apply-crop button when an ROI is available.
        """
        active = self._panel_enabled and enabled
        self.apply_crop_button.setEnabled(active)

    def set_clear_crop_enabled(self, enabled: bool):
        """
        Enable the clear-crop button when a crop is active.
        """
        active = self._panel_enabled and enabled
        self.clear_crop_button.setEnabled(active)

    def set_create_derivative_enabled(self, enabled: bool):
        """
        Enable the derivative dialog button when an ROI is available.
        """
        active = self._panel_enabled and enabled
        self.create_derivative_button.setEnabled(active)

    def set_panel_enabled(self, enabled: bool):
        """
        Enable or disable the entire panel chrome.
        """
        self._panel_enabled = enabled
        self.setEnabled(enabled)

    def set_draw_checked(self, checked: bool):
        """
        Set the draw toggle without emitting ``draw_toggled``.
        """
        if self.draw_checkbox.isChecked() == checked:
            return
        self.draw_checkbox.blockSignals(True)
        self.draw_checkbox.setChecked(checked)
        self.draw_checkbox.blockSignals(False)

    def set_corners(self, x0, y0, x1, y1):
        """
        Display normalized rectangle corners in data coordinates.
        """
        self.corners_label.setText(
            f"Corners: ({x0:.2f}, {y0:.2f}) — ({x1:.2f}, {y1:.2f})"
        )

    def clear_corners(self):
        """
        Reset the corner readout.
        """
        self.corners_label.setText("Corners: —")

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
