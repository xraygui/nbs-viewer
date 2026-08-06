"""
Non-modal ROI workbench window bound to :class:`RoiSetModel`.
"""

from __future__ import annotations

from typing import Optional, Sequence

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QColor, QBrush
from qtpy.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from nbs_viewer.models.plot.cube_view import (
    CubeViewSpec,
    eligible_profile_axes,
    profile_axis_name,
    plot_axis_to_storage_axis,
    scan_profile_storage_axis,
    storage_axis_to_plot_axis,
)
from nbs_viewer.models.plot.derived_fetch import materialize_request_for_profile
from nbs_viewer.models.plot.plot_view_frame import PlotViewFrame
from nbs_viewer.models.plot.region import RegionDefinition
from nbs_viewer.models.plot.roi_set import RoiEntry, RoiOperation, RoiSetModel

from .derivative_preview_canvas import DerivativePreviewCanvas
from .roi_types import (
    DescribeOptionsWidget,
    EllipseOptionsWidget,
    ShapeOptionsWidget,
    get_roi_type,
    iter_roi_types,
)


class RoiWindow(QDialog):
    """
    Dedicated ROI workbench: list, reduction options, and selected-ROI preview.

    Signals
    -------
    draw_toggled : bool
        Emitted when the Draw toggle changes.
    clear_requested : Signal
        Emitted when Clear (all ROIs) is requested.
    delete_requested : Signal
        Emitted when Delete (selected) is requested.
    remove_stale_requested : Signal
        Emitted when Remove stale is requested.
    add_roi_requested : str
        Emitted with the region type id to add.
    operation_changed : Signal
        Emitted when the selected ROI's reduction options change.
    preview_enabled_changed : bool
        Emitted when the preview checkbox toggles.
    save_selected_requested : Signal
        Emitted when Save selected is clicked.
    save_all_requested : Signal
        Emitted when Save all is clicked.
    full_height_requested : Signal
        Emitted when Set ROI: full height is clicked.
    full_width_requested : Signal
        Emitted when Set ROI: full width is clicked.
    """

    draw_toggled = Signal(bool)
    clear_requested = Signal()
    delete_requested = Signal()
    remove_stale_requested = Signal()
    add_roi_requested = Signal(str)
    operation_changed = Signal()
    preview_enabled_changed = Signal(bool)
    save_selected_requested = Signal()
    save_all_requested = Signal()
    full_height_requested = Signal()
    full_width_requested = Signal()
    ellipse_circle_lock_changed = Signal(bool)

    def __init__(self, roi_set: RoiSetModel, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Regions of Interest")
        self.setModal(False)
        self.setMinimumSize(760, 640)
        self._roi_set = roi_set
        self._parent_spec: Optional[CubeViewSpec] = None
        self._axis_names: Sequence[str] = ()
        self._parent_frame: Optional[PlotViewFrame] = None
        self._loading_form = False
        self._shape_options: Optional[ShapeOptionsWidget] = None

        root = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.add_type_combo = QComboBox()
        for spec in iter_roi_types():
            self.add_type_combo.addItem(spec.display_name, spec.type_id)
        self.add_button = QPushButton("Add ROI")
        self.draw_button = QPushButton("Draw")
        self.draw_button.setCheckable(True)
        self.clear_button = QPushButton("Clear")
        self.delete_button = QPushButton("Delete")
        self.remove_stale_button = QPushButton("Remove stale")
        toolbar.addWidget(self.add_type_combo)
        toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.draw_button)
        toolbar.addWidget(self.clear_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addWidget(self.remove_stale_button)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._controls_splitter = splitter
        self.entry_list = QListWidget()
        self.entry_list.setMinimumWidth(180)
        splitter.addWidget(self.entry_list)

        right = QWidget()
        right.setMinimumWidth(300)
        right.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._controls_right = right
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        self.shape_box = QGroupBox("Shape")
        self.shape_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._shape_layout = QVBoxLayout(self.shape_box)
        self._shape_layout.setSpacing(6)
        self._shape_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        self._shape_options = DescribeOptionsWidget(self)
        self._shape_options._bound_type_id = None
        self._shape_layout.addWidget(self._shape_options)
        right_layout.addWidget(self.shape_box)

        self.reduction_box = QGroupBox("Reduction")
        self.reduction_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        reduction_layout = QVBoxLayout(self.reduction_box)
        reduction_layout.setSpacing(8)
        reduction_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)

        mask_row = QHBoxLayout()
        self.mask_inside = QRadioButton("Inside")
        self.mask_outside = QRadioButton("Outside")
        self.mask_inside.setChecked(True)
        mask_group = QButtonGroup(self)
        mask_group.addButton(self.mask_inside)
        mask_group.addButton(self.mask_outside)
        mask_row.addWidget(self.mask_inside)
        mask_row.addWidget(self.mask_outside)
        mask_row.addStretch(1)
        reduction_layout.addLayout(mask_row)

        self.profile_axis_combo = QComboBox()
        self.profile_axis_combo.setMinimumHeight(28)
        self.profile_axis_combo.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )
        reduction_layout.addLayout(
            self._labeled_row("Profile axis:", self.profile_axis_combo)
        )

        self.reduce_combo = QComboBox()
        self.reduce_combo.setMinimumHeight(28)
        self.reduce_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.reduce_combo.addItem("Sum", "sum")
        self.reduce_combo.addItem("Mean", "mean")
        reduction_layout.addLayout(self._labeled_row("Reduce:", self.reduce_combo))

        self.span_full_checkbox = QCheckBox(
            "Span full profile axis (recommended for comparable 1D spectra)"
        )
        self.span_full_checkbox.setChecked(True)
        self.span_full_checkbox.setMinimumHeight(24)
        reduction_layout.addWidget(self.span_full_checkbox)

        span_button_row = QHBoxLayout()
        self.full_height_button = QPushButton("Set ROI: full height")
        self.full_width_button = QPushButton("Set ROI: full width")
        span_button_row.addWidget(self.full_height_button)
        span_button_row.addWidget(self.full_width_button)
        reduction_layout.addLayout(span_button_row)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Optional label")
        self.label_edit.setMinimumHeight(28)
        reduction_layout.addWidget(QLabel("Label:"))
        reduction_layout.addWidget(self.label_edit)
        right_layout.addWidget(self.reduction_box)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, stretch=0)
        self._update_controls_minimum_sizes()


        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("Preview:"))
        self.selected_only_checkbox = QCheckBox("Selected only")
        self.selected_only_checkbox.setChecked(True)
        self.selected_only_checkbox.setEnabled(False)
        self.selected_only_checkbox.setToolTip(
            "Multi-ROI preview overlay arrives in a later phase"
        )
        preview_header.addWidget(self.selected_only_checkbox)
        self.preview_checkbox = QCheckBox("Live preview")
        self.preview_checkbox.setChecked(True)
        preview_header.addWidget(self.preview_checkbox)
        preview_header.addStretch(1)
        root.addLayout(preview_header)

        self.preview_canvas = DerivativePreviewCanvas(self)
        root.addWidget(self.preview_canvas, stretch=1)

        self.context_label = QLabel()
        self.context_label.setWordWrap(True)
        root.addWidget(self.context_label)

        footer = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, stretch=1)
        self.save_selected_button = QPushButton("Save selected")
        self.save_all_button = QPushButton("Save all")
        self.close_button = QPushButton("Close")
        footer.addWidget(self.save_selected_button)
        footer.addWidget(self.save_all_button)
        footer.addWidget(self.close_button)
        root.addLayout(footer)

        self.add_button.clicked.connect(self._on_add_clicked)
        self.draw_button.toggled.connect(self.draw_toggled.emit)
        self.clear_button.clicked.connect(self.clear_requested.emit)
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self.remove_stale_button.clicked.connect(self.remove_stale_requested.emit)
        self.entry_list.currentItemChanged.connect(self._on_list_selection_changed)
        self.close_button.clicked.connect(self.close)
        self.save_selected_button.clicked.connect(self.save_selected_requested.emit)
        self.save_all_button.clicked.connect(self.save_all_requested.emit)
        self.full_height_button.clicked.connect(self.full_height_requested.emit)
        self.full_width_button.clicked.connect(self.full_width_requested.emit)
        self.preview_checkbox.toggled.connect(self._on_preview_toggled)
        self._shape_options.region_edited.connect(self._on_shape_region_edited)

        for widget in (self.mask_inside, self.mask_outside):
            widget.toggled.connect(self._on_form_changed)
        self.profile_axis_combo.currentIndexChanged.connect(self._on_form_changed)
        self.reduce_combo.currentIndexChanged.connect(self._on_form_changed)
        self.span_full_checkbox.toggled.connect(self._on_form_changed)
        self.label_edit.textChanged.connect(self._on_form_changed)

        roi_set.entries_changed.connect(self.refresh_entry_list)
        roi_set.entry_changed.connect(self._on_entry_changed)
        roi_set.selection_changed.connect(self._on_model_selection_changed)

        self.refresh_entry_list()
        self._load_selected_into_form()
        self._update_form_enabled()
        self._update_controls_minimum_sizes()

    @staticmethod
    def _labeled_row(label: str, widget: QWidget) -> QHBoxLayout:
        """
        Build a non-collapsing label + field row.
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        text = QLabel(label)
        text.setMinimumWidth(90)
        text.setMinimumHeight(28)
        text.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        row.addWidget(text)
        row.addWidget(widget, stretch=1)
        return row

    def _update_controls_minimum_sizes(self):
        """
        Force the controls pane to stay tall enough for its contents.
        """
        self.shape_box.adjustSize()
        self.reduction_box.adjustSize()
        self._controls_right.adjustSize()
        spacing = self._controls_right.layout().spacing()
        height = (
            self.shape_box.sizeHint().height()
            + self.reduction_box.sizeHint().height()
            + spacing
            + 8
        )
        self._controls_right.setMinimumHeight(height)
        self.entry_list.setMinimumHeight(height)
        self._controls_splitter.setMinimumHeight(height)
        chrome = 160
        preview_floor = 160
        self.setMinimumHeight(height + chrome + preview_floor)

    def _on_add_clicked(self):
        region_type = self.add_type_combo.currentData()
        self.add_roi_requested.emit(region_type or "rect")

    def _on_shape_region_edited(self, region: RegionDefinition):
        if self._loading_form:
            return
        entry = self._roi_set.selected_entry()
        if entry is None:
            return
        self._roi_set.update_region(
            entry.id,
            region,
            view_fingerprint=entry.view_fingerprint,
            clear_stale=False,
        )
        self.operation_changed.emit()

    def _replace_shape_options(
        self, region: Optional[RegionDefinition], *, sync_circle_lock: bool = False
    ):
        type_id = getattr(region, "region_type", None) if region is not None else None
        spec = get_roi_type(type_id) if type_id else None
        bound = getattr(self._shape_options, "_bound_type_id", None)
        wanted = spec.type_id if spec is not None else None
        if self._shape_options is not None and bound == wanted:
            if region is not None:
                if isinstance(self._shape_options, EllipseOptionsWidget):
                    self._shape_options.set_region(
                        region, sync_circle_lock=sync_circle_lock
                    )
                else:
                    self._shape_options.set_region(region)
            elif isinstance(self._shape_options, DescribeOptionsWidget):
                self._shape_options.clear_summary()
            return
        if self._shape_options is not None:
            try:
                self._shape_options.region_edited.disconnect(
                    self._on_shape_region_edited
                )
            except TypeError:
                pass
            if isinstance(self._shape_options, EllipseOptionsWidget):
                try:
                    self._shape_options.circle_lock_changed.disconnect(
                        self._on_ellipse_circle_lock_changed
                    )
                except TypeError:
                    pass
            self._shape_layout.removeWidget(self._shape_options)
            self._shape_options.deleteLater()
            self._shape_options = None
        if spec is None:
            self._shape_options = DescribeOptionsWidget(self)
            self._shape_options._bound_type_id = None
            self._shape_options.clear_summary()
            self.ellipse_circle_lock_changed.emit(False)
        else:
            self._shape_options = spec.create_options_widget(self)
            self._shape_options._bound_type_id = spec.type_id
            if region is not None:
                if isinstance(self._shape_options, EllipseOptionsWidget):
                    self._shape_options.set_region(
                        region, sync_circle_lock=True
                    )
                else:
                    self._shape_options.set_region(region)
            if isinstance(self._shape_options, EllipseOptionsWidget):
                self._shape_options.circle_lock_changed.connect(
                    self._on_ellipse_circle_lock_changed
                )
                self.ellipse_circle_lock_changed.emit(
                    self._shape_options.is_circle_locked()
                )
            else:
                self.ellipse_circle_lock_changed.emit(False)
        self._shape_options.region_edited.connect(self._on_shape_region_edited)
        self._shape_layout.addWidget(self._shape_options)
        self._update_controls_minimum_sizes()

    def _on_ellipse_circle_lock_changed(self, locked: bool):
        self.ellipse_circle_lock_changed.emit(locked)
    def _on_preview_toggled(self, enabled: bool):
        self.preview_enabled_changed.emit(enabled)
        if enabled:
            self.preview_canvas.show_message("Updating preview…")
        else:
            self.preview_canvas.show_message("Preview disabled")

    def _on_form_changed(self, *_args):
        if self._loading_form:
            return
        entry = self._roi_set.selected_entry()
        if entry is None:
            return
        operation = RoiOperation(
            mask_mode=self.get_mask_mode(),
            profile_storage_axis=self.get_profile_storage_axis(),
            spatial_reduce=self.get_spatial_reduce(),
            span_full_profile_axis=self.span_full_profile_axis(),
            label=self.get_label(),
        )
        self._loading_form = True
        try:
            self._roi_set.update_operation(entry.id, operation)
            if operation.label and operation.label != entry.display_label:
                self._roi_set.update_entry(entry.id, display_label=operation.label)
            self._refresh_list_item(entry.id)
        finally:
            self._loading_form = False
        self._update_profile_controls_enabled()
        self.operation_changed.emit()

    def _on_list_selection_changed(self, current: Optional[QListWidgetItem], _previous):
        if current is None:
            self._roi_set.set_selected(None)
            return
        entry_id = current.data(Qt.ItemDataRole.UserRole)
        if entry_id != self._roi_set.selected_id:
            self._roi_set.set_selected(entry_id)

    def _on_model_selection_changed(self, entry_id):
        self._sync_list_selection(entry_id)
        self._load_selected_into_form()
        self._update_form_enabled()

    def _on_entry_changed(self, entry_id: str):
        if self._loading_form:
            self._refresh_list_item(entry_id)
            return
        self._refresh_list_item(entry_id)
        if entry_id == self._roi_set.selected_id:
            entry = self._roi_set.get(entry_id)
            if entry is not None:
                self._replace_shape_options(entry.region)
    def _refresh_list_item(self, entry_id: str):
        entry = self._roi_set.get(entry_id)
        if entry is None:
            return
        for row in range(self.entry_list.count()):
            item = self.entry_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == entry_id:
                item.setText(self._entry_list_text(entry))
                item.setForeground(
                    QBrush(QColor("#9e9e9e" if entry.stale else entry.color))
                )
                return

    def _sync_list_selection(self, entry_id: Optional[str]):
        if entry_id is None:
            self.entry_list.clearSelection()
            return
        for row in range(self.entry_list.count()):
            item = self.entry_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == entry_id:
                self.entry_list.blockSignals(True)
                self.entry_list.setCurrentItem(item)
                self.entry_list.blockSignals(False)
                return

    def refresh_entry_list(self):
        """
        Rebuild the ROI list from the model.
        """
        selected = self._roi_set.selected_id
        self.entry_list.blockSignals(True)
        self.entry_list.clear()
        for entry in self._roi_set.entries():
            item = QListWidgetItem(self._entry_list_text(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setForeground(QBrush(QColor("#9e9e9e" if entry.stale else entry.color)))
            self.entry_list.addItem(item)
        self.entry_list.blockSignals(False)
        self._sync_list_selection(selected)
        self._load_selected_into_form()
        self._update_form_enabled()

    def _entry_list_text(self, entry: RoiEntry) -> str:
        kind = getattr(entry.region, "region_type", "?")
        spec = get_roi_type(kind)
        kind_label = spec.short_name if spec is not None else kind
        mark = "stale" if entry.stale else "✓"
        return f"{entry.display_label}  {kind_label}  {mark}"

    def _load_selected_into_form(self):
        entry = self._roi_set.selected_entry()
        self._loading_form = True
        try:
            if entry is None:
                self._replace_shape_options(None)
                self.label_edit.clear()
                return
            self._replace_shape_options(entry.region, sync_circle_lock=True)
            op = entry.operation
            self.mask_inside.setChecked(op.mask_mode != "outside")
            self.mask_outside.setChecked(op.mask_mode == "outside")
            reduce_idx = self.reduce_combo.findData(op.spatial_reduce)
            if reduce_idx >= 0:
                self.reduce_combo.setCurrentIndex(reduce_idx)
            self.span_full_checkbox.setChecked(op.span_full_profile_axis)
            self.label_edit.setText(op.label or entry.display_label)
            if op.profile_storage_axis is not None:
                axis_idx = self.profile_axis_combo.findData(op.profile_storage_axis)
                if axis_idx >= 0:
                    self.profile_axis_combo.setCurrentIndex(axis_idx)
            self._update_profile_controls_enabled()
        finally:
            self._loading_form = False

    def _update_form_enabled(self):
        has_selection = self._roi_set.selected_entry() is not None
        for widget in (
            self.reduction_box,
            self.shape_box,
            self.draw_button,
            self.delete_button,
            self.save_selected_button,
            self.full_height_button,
            self.full_width_button,
        ):
            widget.setEnabled(has_selection)
        self.save_all_button.setEnabled(len(self._roi_set) > 0)
        self.clear_button.setEnabled(len(self._roi_set) > 0)
        if has_selection:
            self._update_profile_controls_enabled()

    def _update_profile_controls_enabled(self):
        entry = self._roi_set.selected_entry()
        separable = (
            entry is not None and entry.region.separable_for_profile
        )
        outside = self.get_mask_mode() == "outside"
        in_plane = self._selected_axis_on_plot_plane()
        span_ok = separable and in_plane and not outside
        self.span_full_checkbox.setEnabled(span_ok)
        if not span_ok:
            if not separable:
                self.span_full_checkbox.setToolTip(
                    "Span-full only applies to rectangles and axis bands; "
                    "expanding a non-separable shape would discard the drawn geometry."
                )
            elif outside:
                self.span_full_checkbox.setToolTip(
                    "Span-full is disabled in outside mode; the inverted mask "
                    "already covers the full profile axis."
                )
            else:
                self.span_full_checkbox.setToolTip(
                    "Span-full applies only to in-plane profile axes."
                )
        else:
            self.span_full_checkbox.setToolTip(
                "Expand the ROI along the profile axis so every bin is included."
            )
        storage_axis = self.get_profile_storage_axis()
        profile_plot_axis = None
        if (
            in_plane
            and separable
            and self._parent_frame is not None
            and self._parent_spec is not None
        ):
            try:
                profile_plot_axis = storage_axis_to_plot_axis(
                    self._parent_frame,
                    storage_axis,
                    parent_spec=self._parent_spec,
                )
            except ValueError:
                profile_plot_axis = None
        has_selection = entry is not None
        self.full_width_button.setEnabled(
            has_selection and separable and profile_plot_axis == "plot_x"
        )
        self.full_height_button.setEnabled(
            has_selection and separable and profile_plot_axis == "plot_y"
        )
    def _selected_axis_on_plot_plane(self) -> bool:
        if self._parent_spec is None:
            return False
        storage_axis = self.get_profile_storage_axis()
        return storage_axis in set(self._parent_spec.plot_axis_order())

    def set_draw_checked(self, checked: bool):
        """
        Set the Draw toggle without emitting ``draw_toggled``.
        """
        if self.draw_button.isChecked() == checked:
            return
        self.draw_button.blockSignals(True)
        self.draw_button.setChecked(checked)
        self.draw_button.blockSignals(False)

    def get_mask_mode(self) -> str:
        """
        Return the selected mask mode.
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
        self._loading_form = True
        try:
            if parent_spec is None:
                self.profile_axis_combo.clear()
                return

            entry = self._roi_set.selected_entry()
            current = (
                entry.operation.profile_storage_axis
                if entry is not None
                else self.profile_axis_combo.currentData()
            )
            eligible = eligible_profile_axes(parent_spec)
            plot_order = parent_spec.plot_axis_order()
            default_axis = scan_profile_storage_axis(parent_spec)
            if default_axis is None and len(plot_order) >= 1:
                default_axis = plot_order[-1]

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

            if entry is not None and entry.operation.profile_storage_axis is None:
                axis = self.get_profile_storage_axis()
                self._roi_set.update_operation(
                    entry.id,
                    RoiOperation(
                        mask_mode=entry.operation.mask_mode,
                        profile_storage_axis=axis,
                        spatial_reduce=entry.operation.spatial_reduce,
                        span_full_profile_axis=entry.operation.span_full_profile_axis,
                        label=entry.operation.label,
                    ),
                )
        finally:
            self._loading_form = False
        self._update_profile_controls_enabled()

    def build_profile_request(
        self,
        region: RegionDefinition,
        parent_spec: Optional[CubeViewSpec] = None,
        *,
        span_full_profile_axis: Optional[bool] = None,
        operation: Optional[RoiOperation] = None,
    ):
        """
        Build a profile :class:`MaterializeRequest` for a region.

        Parameters
        ----------
        region : RegionDefinition
            ROI geometry on the parent plot plane.
        parent_spec : CubeViewSpec, optional
            Live parent cube view.
        span_full_profile_axis : bool, optional
            Override for span-full.
        operation : RoiOperation, optional
            Reduction parameters. Defaults to the selected entry or form values.

        Returns
        -------
        MaterializeRequest or None
        """
        spec = parent_spec if parent_spec is not None else self._parent_spec
        if spec is None:
            return None
        if operation is None:
            entry = self._roi_set.selected_entry()
            operation = entry.operation if entry is not None else None
        if operation is not None:
            profile_axis = operation.profile_storage_axis
            if profile_axis is None:
                profile_axis = self.get_profile_storage_axis()
            spatial_reduce = operation.spatial_reduce
            mask_mode = operation.mask_mode
            span_default = operation.span_full_profile_axis
        else:
            profile_axis = self.get_profile_storage_axis()
            spatial_reduce = self.get_spatial_reduce()
            mask_mode = self.get_mask_mode()
            span_default = self.span_full_profile_axis()
        span_full = (
            span_default if span_full_profile_axis is None else span_full_profile_axis
        )
        return materialize_request_for_profile(
            spec,
            region,
            profile_axis,
            spatial_reduce,
            mask_mode,
            parent_frame=self._parent_frame,
            span_full_profile_axis=span_full,
        )

    def is_preview_enabled(self) -> bool:
        """
        Return whether live preview is enabled.
        """
        return self.preview_checkbox.isChecked()

    def set_context(self, source_text: str):
        """
        Update the read-only source summary line.
        """
        self.context_label.setText(source_text)

    def set_status(self, message: str):
        """
        Show a status or error message.
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
