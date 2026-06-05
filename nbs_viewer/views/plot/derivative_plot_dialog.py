"""
Modeless dialog for configuring ROI derivative plots.
"""

from __future__ import annotations

from qtpy.QtCore import Signal
from qtpy.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from nbs_viewer.models.plot.derivative_spec import DerivativeSpec

from .derivative_preview_canvas import DerivativePreviewCanvas


class DerivativePlotDialog(QDialog):
    """
    Modeless dialog to configure derivative operations and preview results.

    Signals
    -------
    spec_changed : DerivativeSpec
        Emitted when any operation control changes.
    preview_enabled_changed : bool
        Emitted when the preview checkbox toggles.
    """

    spec_changed = Signal(object)
    preview_enabled_changed = Signal(bool)
    create_requested = Signal()
    pin_requested = Signal()
    full_height_requested = Signal()
    full_width_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Derivative Plot")
        self.setModal(False)
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)

        self.context_label = QLabel()
        self.context_label.setWordWrap(True)
        root.addWidget(self.context_label)

        self.roi_label = QLabel("ROI: —")
        self.roi_label.setWordWrap(True)
        root.addWidget(self.roi_label)

        operation_box = QGroupBox("Operation")
        operation_layout = QVBoxLayout(operation_box)

        mask_row = QHBoxLayout()
        self.mask_inside = QRadioButton("Inside ROI")
        self.mask_outside = QRadioButton("Outside ROI")
        self.mask_inside.setChecked(True)
        mask_group = QButtonGroup(self)
        mask_group.addButton(self.mask_inside)
        mask_group.addButton(self.mask_outside)
        mask_row.addWidget(self.mask_inside)
        mask_row.addWidget(self.mask_outside)
        operation_layout.addLayout(mask_row)

        output_row = QHBoxLayout()
        self.output_profile = QRadioButton("1D profile")
        self.output_plane = QRadioButton("2D plane")
        self.output_profile.setChecked(True)
        output_group = QButtonGroup(self)
        output_group.addButton(self.output_profile)
        output_group.addButton(self.output_plane)
        output_row.addWidget(self.output_profile)
        output_row.addWidget(self.output_plane)
        operation_layout.addLayout(output_row)

        profile_form = QFormLayout()
        self.profile_axis_combo = QComboBox()
        self.profile_axis_combo.addItem("Along plot X", "plot_x")
        self.profile_axis_combo.addItem("Along plot Y", "plot_y")
        profile_form.addRow("Profile axis:", self.profile_axis_combo)

        self.reduce_combo = QComboBox()
        self.reduce_combo.addItem("Sum", "sum")
        self.reduce_combo.addItem("Mean", "mean")
        profile_form.addRow("Reduce:", self.reduce_combo)
        operation_layout.addLayout(profile_form)

        self.span_full_checkbox = QCheckBox(
            "Span full profile axis (recommended for comparable 1D spectra)"
        )
        self.span_full_checkbox.setChecked(True)
        operation_layout.addWidget(self.span_full_checkbox)

        span_button_row = QHBoxLayout()
        self.full_height_button = QPushButton("Set ROI: full height")
        self.full_width_button = QPushButton("Set ROI: full width")
        span_button_row.addWidget(self.full_height_button)
        span_button_row.addWidget(self.full_width_button)
        operation_layout.addLayout(span_button_row)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Optional label")
        operation_layout.addWidget(self.label_edit)

        root.addWidget(operation_box)

        self.preview_checkbox = QCheckBox("Preview plot")
        self.preview_checkbox.setChecked(True)
        root.addWidget(self.preview_checkbox)

        self.preview_canvas = DerivativePreviewCanvas(self)
        root.addWidget(self.preview_canvas, stretch=1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.create_button = QPushButton("Create")
        self.pin_button = QPushButton("Pin for comparison")
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.create_button)
        button_row.addWidget(self.pin_button)
        button_row.addWidget(self.close_button)
        root.addLayout(button_row)

        for widget in (
            self.mask_inside,
            self.mask_outside,
            self.output_profile,
            self.output_plane,
        ):
            widget.toggled.connect(self._emit_spec_changed)
        self.profile_axis_combo.currentIndexChanged.connect(
            self._emit_spec_changed
        )
        self.reduce_combo.currentIndexChanged.connect(self._emit_spec_changed)
        self.label_edit.textChanged.connect(self._emit_spec_changed)
        self.span_full_checkbox.toggled.connect(self._emit_spec_changed)
        self.preview_checkbox.toggled.connect(self._on_preview_toggled)
        self.create_button.clicked.connect(self.create_requested.emit)
        self.pin_button.clicked.connect(self.pin_requested.emit)
        self.full_height_button.clicked.connect(self.full_height_requested.emit)
        self.full_width_button.clicked.connect(self.full_width_requested.emit)

        self._profile_widgets = (
            self.profile_axis_combo,
            self.reduce_combo,
            self.span_full_checkbox,
            self.full_height_button,
            self.full_width_button,
        )
        self._update_profile_controls_enabled()

    def _on_preview_toggled(self, enabled: bool):
        self.preview_enabled_changed.emit(enabled)
        if enabled:
            self.preview_canvas.show_message("Updating preview…")
        else:
            self.preview_canvas.show_message("Preview disabled")
        self._emit_spec_changed()

    def _emit_spec_changed(self):
        self._update_profile_controls_enabled()
        self.spec_changed.emit(self.get_spec())

    def _update_profile_controls_enabled(self):
        profile = self.output_profile.isChecked()
        for widget in self._profile_widgets:
            widget.setEnabled(profile)
        self.pin_button.setEnabled(profile)
        axis = self.profile_axis_combo.currentData()
        self.full_width_button.setEnabled(profile and axis == "plot_x")
        self.full_height_button.setEnabled(profile and axis == "plot_y")

    def get_spec(self) -> DerivativeSpec:
        """
        Return the current derivative specification from dialog controls.
        """
        profile_axis = self.profile_axis_combo.currentData()
        if profile_axis not in ("plot_x", "plot_y"):
            profile_axis = "plot_x"
        reduce = self.reduce_combo.currentData()
        if reduce not in ("sum", "mean"):
            reduce = "sum"
        return DerivativeSpec(
            mask_mode=(
                "inside" if self.mask_inside.isChecked() else "outside"
            ),
            output_kind=(
                "profile" if self.output_profile.isChecked() else "plane"
            ),
            profile_axis=profile_axis,
            reduce=reduce,
            label=self.label_edit.text().strip(),
            span_full_profile_axis=self.span_full_checkbox.isChecked(),
        )

    def is_preview_enabled(self) -> bool:
        """
        Return whether live preview is enabled.
        """
        return self.preview_checkbox.isChecked()

    def set_profile_axis_choices(self, plot_x_name: str, plot_y_name: str):
        """
        Populate profile-axis choices using the parent plot axis names.
        """
        current = self.profile_axis_combo.currentData()
        self.profile_axis_combo.blockSignals(True)
        self.profile_axis_combo.clear()
        self.profile_axis_combo.addItem(f"Along {plot_x_name}", "plot_x")
        self.profile_axis_combo.addItem(f"Along {plot_y_name}", "plot_y")
        if current in ("plot_x", "plot_y"):
            idx = self.profile_axis_combo.findData(current)
            if idx >= 0:
                self.profile_axis_combo.setCurrentIndex(idx)
        elif self.profile_axis_combo.count() > 0:
            self.profile_axis_combo.setCurrentIndex(0)
        self.profile_axis_combo.blockSignals(False)

    def set_context(self, source_text: str, roi_text: str):
        """
        Update read-only source and ROI summary lines.
        """
        self.context_label.setText(source_text)
        self.roi_label.setText(roi_text)

    def set_status(self, message: str):
        """
        Show a status or error message below the preview.
        """
        self.status_label.setText(message or "")

    def show_preview_bundle(self, bundle):
        """
        Render a preview bundle on the embedded canvas.
        """
        self.preview_canvas.show_bundle(bundle)
        self.set_status("")

    def show_preview_message(self, message: str):
        """
        Show a message in the preview area.
        """
        self.preview_canvas.show_message(message)
