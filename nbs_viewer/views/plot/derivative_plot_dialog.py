"""
Modeless dialog for configuring ROI derivative plots.
"""

from __future__ import annotations

from typing import Optional, Sequence

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
)

from nbs_viewer.models.plot.cube_view import (
    CubeViewSpec,
    eligible_profile_axes,
    profile_axis_name,
    plot_axis_to_storage_axis,
    storage_axis_to_plot_axis,
)
from nbs_viewer.models.plot.derived_fetch import (
    materialize_request_for_plane,
    materialize_request_for_profile,
)
from nbs_viewer.models.plot.plot_view_frame import PlotViewFrame
from nbs_viewer.models.plot.region import RectRegion

from .derivative_preview_canvas import DerivativePreviewCanvas


class DerivativePlotDialog(QDialog):
    """
    Modeless dialog to configure derivative operations and preview results.

    Signals
    -------
    request_changed : object
        Emitted when any operation control changes.
    preview_enabled_changed : bool
        Emitted when the preview checkbox toggles.
    """

    request_changed = Signal(object)
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

        self._parent_spec: Optional[CubeViewSpec] = None
        self._axis_names: Sequence[str] = ()
        self._parent_frame: Optional[PlotViewFrame] = None

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
            widget.toggled.connect(self._emit_request_changed)
        self.profile_axis_combo.currentIndexChanged.connect(
            self._emit_request_changed
        )
        self.reduce_combo.currentIndexChanged.connect(self._emit_request_changed)
        self.label_edit.textChanged.connect(self._emit_request_changed)
        self.span_full_checkbox.toggled.connect(self._emit_request_changed)
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
        self._emit_request_changed()

    def _emit_request_changed(self):
        self._update_profile_controls_enabled()
        self.request_changed.emit(None)

    def _update_profile_controls_enabled(self):
        profile = self.output_profile.isChecked()
        for widget in self._profile_widgets:
            widget.setEnabled(profile)
        self.pin_button.setEnabled(profile)
        in_plane = self._selected_axis_on_plot_plane()
        self.span_full_checkbox.setEnabled(profile and in_plane)
        storage_axis = self.get_profile_storage_axis()
        plot_x_axis = None
        plot_y_axis = None
        if self._parent_spec is not None:
            plot_order = self._parent_spec.plot_axis_order()
            if len(plot_order) >= 2:
                plot_y_axis, plot_x_axis = plot_order[-2], plot_order[-1]
        self.full_width_button.setEnabled(
            profile and in_plane and storage_axis == plot_x_axis
        )
        self.full_height_button.setEnabled(
            profile and in_plane and storage_axis == plot_y_axis
        )

    def _selected_axis_on_plot_plane(self) -> bool:
        if self._parent_spec is None:
            return False
        storage_axis = self.get_profile_storage_axis()
        return storage_axis in set(self._parent_spec.plot_axis_order())

    def is_profile_output(self) -> bool:
        """
        Return whether the dialog is configured for a 1D profile.
        """
        return self.output_profile.isChecked()

    def get_mask_mode(self) -> str:
        """
        Return the selected ROI mask mode.
        """
        return "inside" if self.mask_inside.isChecked() else "outside"

    def get_spatial_reduce(self) -> str:
        """
        Return the selected spatial reduce operation.
        """
        reduce = self.reduce_combo.currentData()
        return reduce if reduce in ("sum", "mean") else "sum"

    def get_label(self) -> str:
        """
        Return the optional user label text.
        """
        return self.label_edit.text().strip()

    def span_full_profile_axis(self) -> bool:
        """
        Return whether the ROI should span the full in-plane profile axis.
        """
        return self.span_full_checkbox.isChecked()

    def get_profile_storage_axis(self) -> int:
        """
        Return the selected profile storage axis index.
        """
        data = self.profile_axis_combo.currentData()
        if isinstance(data, int):
            return data
        if self._parent_spec is not None:
            return plot_axis_to_storage_axis(self._parent_spec, "plot_x")
        return 0

    def set_profile_context(
        self,
        parent_spec: Optional[CubeViewSpec],
        axis_names: Sequence[str],
        parent_frame: Optional[PlotViewFrame] = None,
    ):
        """
        Update parent view metadata used to build profile requests.
        """
        self._parent_spec = parent_spec
        self._axis_names = tuple(axis_names) if axis_names else ()
        self._parent_frame = parent_frame
        if parent_spec is None:
            self.profile_axis_combo.blockSignals(True)
            self.profile_axis_combo.clear()
            self.profile_axis_combo.blockSignals(False)
            return

        current = self.profile_axis_combo.currentData()
        eligible = eligible_profile_axes(parent_spec)
        plot_order = parent_spec.plot_axis_order()
        default_axis = plot_order[-1] if len(plot_order) >= 1 else None

        self.profile_axis_combo.blockSignals(True)
        self.profile_axis_combo.clear()
        for storage_axis in eligible:
            name = profile_axis_name(parent_spec, storage_axis, self._axis_names)
            self.profile_axis_combo.addItem(f"Along {name}", storage_axis)

        selected_idx = -1
        if isinstance(current, int) and current in eligible:
            selected_idx = self.profile_axis_combo.findData(current)
        if selected_idx < 0 and default_axis is not None:
            selected_idx = self.profile_axis_combo.findData(default_axis)
        if selected_idx < 0 and len(plot_order) >= 2:
            selected_idx = self.profile_axis_combo.findData(plot_order[-2])
        if selected_idx < 0 and self.profile_axis_combo.count() > 0:
            selected_idx = 0
        if selected_idx >= 0:
            self.profile_axis_combo.setCurrentIndex(selected_idx)
        self.profile_axis_combo.blockSignals(False)
        self._update_profile_controls_enabled()

    def build_profile_request(
        self,
        region: RectRegion,
        parent_spec: Optional[CubeViewSpec] = None,
    ):
        """
        Build a profile :class:`MaterializeRequest` from dialog controls.

        Parameters
        ----------
        region : RectRegion
            ROI in data coordinates on the parent plot plane.
        parent_spec : CubeViewSpec, optional
            Live parent cube view. Defaults to the last context snapshot.

        Returns
        -------
        MaterializeRequest or None
            Frozen request when parent context is available.
        """
        spec = parent_spec if parent_spec is not None else self._parent_spec
        if spec is None:
            return None
        return materialize_request_for_profile(
            spec,
            region,
            self.get_profile_storage_axis(),
            self.get_spatial_reduce(),
            self.get_mask_mode(),
            parent_frame=self._parent_frame,
            span_full_profile_axis=self.span_full_profile_axis(),
        )

    def build_plane_request(
        self,
        region: RectRegion,
        parent_spec: Optional[CubeViewSpec] = None,
    ):
        """
        Build a plane :class:`MaterializeRequest` from dialog controls.

        Parameters
        ----------
        region : RectRegion
            ROI in data coordinates on the parent plot plane.
        parent_spec : CubeViewSpec, optional
            Live parent cube view. Defaults to the last context snapshot.

        Returns
        -------
        MaterializeRequest or None
            Frozen request when parent context is available.
        """
        spec = parent_spec if parent_spec is not None else self._parent_spec
        if spec is None:
            return None
        return materialize_request_for_plane(
            spec,
            region,
            self.get_mask_mode(),
        )

    def build_materialize_request(
        self,
        region: RectRegion,
        parent_spec: Optional[CubeViewSpec] = None,
    ):
        """
        Build the active profile or plane materialize request.

        Parameters
        ----------
        region : RectRegion
            ROI in data coordinates on the parent plot plane.
        parent_spec : CubeViewSpec, optional
            Live parent cube view. Defaults to the last context snapshot.

        Returns
        -------
        MaterializeRequest or None
            Frozen request when parent context is available.
        """
        if self.is_profile_output():
            return self.build_profile_request(region, parent_spec=parent_spec)
        return self.build_plane_request(region, parent_spec=parent_spec)

    def is_preview_enabled(self) -> bool:
        """
        Return whether live preview is enabled.
        """
        return self.preview_checkbox.isChecked()

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

    def profile_axis_for_roi_span(self) -> Optional[str]:
        """
        Return the plot axis name for full-height or full-width ROI actions.
        """
        if self._parent_frame is None or self._parent_spec is None:
            return None
        storage_axis = self.get_profile_storage_axis()
        if storage_axis not in set(self._parent_spec.plot_axis_order()):
            return None
        return storage_axis_to_plot_axis(
            self._parent_frame,
            storage_axis,
            parent_spec=self._parent_spec,
        )
