from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QSlider,
    QLabel,
    QSpinBox,
    QHBoxLayout,
    QComboBox,
    QPushButton,
    QSizePolicy,
    QFrame,
)
import numpy as np
from qtpy.QtCore import Qt, Signal

from nbs_viewer.models.data.array_contract import index_placeholders
from nbs_viewer.models.plot.plane.roles import DimRole, ROLE_LABELS, SLICE_ROLES
from nbs_viewer.utils import print_debug
from nbs_viewer.views.common.panel import CollapsiblePanel


class _SliceReduceRow(QWidget):
    """
    Controls for one slice/reduce dimension (index, sum, or mean).
    """

    changed = Signal()
    move_up_requested = Signal()
    move_down_requested = Signal()

    def __init__(
        self,
        dim_name,
        axis_data,
        associated_data,
        slider_max,
        parent=None,
    ):
        super().__init__(parent)
        self.storage_axis = None
        self._axis_data = axis_data
        self._associated_data = associated_data or {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(3)

        self.up_button = QPushButton("\u2191")
        self.up_button.setFixedWidth(24)
        self.up_button.clicked.connect(self.move_up_requested.emit)
        header_row.addWidget(self.up_button)

        self.down_button = QPushButton("\u2193")
        self.down_button.setFixedWidth(24)
        self.down_button.clicked.connect(self.move_down_requested.emit)
        header_row.addWidget(self.down_button)

        self.name_label = QLabel(f"{dim_name}:")
        header_row.addWidget(self.name_label)

        self.role_combo = QComboBox()
        for role in SLICE_ROLES:
            self.role_combo.addItem(ROLE_LABELS[role], role)
        self.role_combo.currentIndexChanged.connect(self._emit_changed)
        header_row.addWidget(self.role_combo)
        header_row.addStretch(1)
        outer.addLayout(header_row)

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(4)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(max(0, slider_max))
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.slider.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        )
        slider_row.addWidget(self.slider, 1)

        self.value_label = QLabel()
        slider_row.addWidget(self.value_label)

        self._assoc_labels = []
        # Not strict: both sides default to an empty list when the key is
        # absent, so an associated array with no names yields no labels
        # rather than raising while a slider is being built.
        for arr, name in zip(
            self._associated_data.get("arrays", []),
            self._associated_data.get("names", []),
         strict=False):
            assoc_label = QLabel()
            slider_row.addWidget(assoc_label)
            self._assoc_labels.append((assoc_label, arr, name))
        outer.addLayout(slider_row)

        self._update_value_labels(0)

    def _emit_changed(self):
        self._apply_role_ui()
        self.changed.emit()

    def _apply_role_ui(self):
        """
        Enable the index slider only when the role is Index.
        """
        is_index = self.get_role() == DimRole.INDEX
        self.slider.setEnabled(is_index)
        self.value_label.setEnabled(is_index)
        for label, _, _ in self._assoc_labels:
            label.setEnabled(is_index)

    def _on_slider_changed(self, value):
        self._update_value_labels(value)
        self.changed.emit()

    def _update_value_labels(self, value):
        if len(self._axis_data) > 0 and value < len(self._axis_data):
            self.value_label.setText(f"({self._axis_data[value]:g})")
        else:
            self.value_label.setText(f"({value})")
        for label, arr, name in self._assoc_labels:
            if value < len(arr):
                label.setText(f"{name}: {arr[value]:g}")
            else:
                label.setText(f"{name}: —")

    def set_role(self, role):
        index = self.role_combo.findData(role)
        if index >= 0:
            self.role_combo.blockSignals(True)
            self.role_combo.setCurrentIndex(index)
            self.role_combo.blockSignals(False)
        self._apply_role_ui()

    def get_role(self):
        return self.role_combo.currentData()

    def get_index(self):
        return self.slider.value()

    def set_axis_data(self, axis_data, associated_data=None):
        """
        Replace axis coordinates and refresh the value readout.
        """
        axis_data = np.asarray(axis_data, dtype=float).ravel()
        self._axis_data = axis_data
        if associated_data is not None:
            self._associated_data = associated_data
            arrays = associated_data.get("arrays", [])
            names = associated_data.get("names", [])
            updated = []
            for i, (label, _, old_name) in enumerate(self._assoc_labels):
                arr = arrays[i] if i < len(arrays) else np.array([])
                name = names[i] if i < len(names) else old_name
                updated.append((label, arr, name))
            self._assoc_labels = updated
        if axis_data.size > 0:
            self.slider.setMaximum(max(0, int(axis_data.size) - 1))
        self._update_value_labels(self.slider.value())


class _PlotAxisRow(QWidget):
    """
    One fixed plot-axis row (Plot X or Plot Y); reorder only via up/down.
    """

    move_up_requested = Signal()
    move_down_requested = Signal()

    def __init__(self, dim_name, plot_label, parent=None):
        super().__init__(parent)
        self.storage_axis = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.up_button = QPushButton("\u2191")
        self.up_button.setFixedWidth(24)
        self.up_button.clicked.connect(self.move_up_requested.emit)
        layout.addWidget(self.up_button)

        self.down_button = QPushButton("\u2193")
        self.down_button.setFixedWidth(24)
        self.down_button.clicked.connect(self.move_down_requested.emit)
        layout.addWidget(self.down_button)

        self.name_label = QLabel(f"{dim_name}:")
        self.name_label.setMinimumWidth(88)
        layout.addWidget(self.name_label)

        self.plot_label = QLabel(plot_label)
        self.plot_label.setMinimumWidth(52)
        layout.addWidget(self.plot_label)


class DimensionControl(QWidget):
    """
    Widget for controlling the N-dimensional projection of a plot.

    Slice/reduce dimensions appear above a separator; trailing rows are
    Plot Y (2D only) and Plot X, assigned only by row order.
    """

    def __init__(self, presenter, canvas, parent=None):
        """
        Initialize the dimension control widget.

        Parameters
        ----------
        presenter : PlotPresenter
            Plot session presenter.
        canvas : MplCanvas
            Canvas receiving view state updates.
        parent : QWidget, optional
            Parent widget, by default None.
        """
        super().__init__(parent)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        self.presenter = presenter
        self.plot_model = presenter.session
        self.canvas = canvas
        self._slice_rows = []
        self._plot_rows = []
        self._shape = None
        self._dim_names = None
        self._axis_arrays = None
        self._associated_data = None
        # The projection currently drawn as rows. Read from the session on
        # every rebuild; never edited here. Axis order, roles and indices all
        # live on ``session.view_intent``.
        self._projection = None
        self._updating_ui = False

        self.plot_model.collection.run_added.connect(self.on_run_added)
        self.plot_model.collection.run_removed.connect(self.on_run_removed)
        self.plot_model.selection.selected_keys_changed.connect(
            self.on_selection_changed
        )
        self.canvas.plot_view_updated.connect(self.refresh_axis_coordinates)
        self.canvas.plot_view_updated.connect(self.refresh_plot_axis_labels)

        self.init_ui()

    def init_ui(self):
        """
        Initialize the user interface with dimension controls.
        """
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(2)

        self.dimension_container = QWidget()
        dimension_layout = QHBoxLayout(self.dimension_container)
        dimension_layout.setContentsMargins(0, 0, 0, 0)
        dimension_layout.setSpacing(4)
        dimension_label = QLabel("Plot Dimensions:")
        self.dimension_spinbox = QSpinBox()
        self.dimension_spinbox.setMinimum(1)
        self.dimension_spinbox.setMaximum(2)
        self.dimension_spinbox.setValue(1)
        self.dimension_spinbox.valueChanged.connect(self.on_dimension_changed)

        dimension_layout.addWidget(dimension_label)
        dimension_layout.addWidget(self.dimension_spinbox)
        self.layout.addWidget(self.dimension_container)
        self.dimension_container.hide()

        """
        hint = QLabel(
            "Controls apply to the selected Y array shape. "
            "Use arrows to move dimensions between slice/reduce and plot axes. "
            "Run Display X/Y selects scalar fields only."
        )
        hint.setWordWrap(True)
        self.layout.addWidget(hint)
        """
        self.sliders_container = QWidget()
        self.sliders_layout = QVBoxLayout(self.sliders_container)
        self.sliders_layout.setContentsMargins(0, 0, 0, 0)
        self.sliders_layout.setSpacing(2)
        self.layout.addWidget(self.sliders_container)

        self.setLayout(self.layout)
        self.create_sliders()

    def create_sliders(self):
        """
        Build dimension rows from the current Y-field shape.
        """
        print_debug(
            "DimensionControl.create_sliders",
            f"plot_ndim={self.dimension_spinbox.value()}",
            category="dimension",
        )

        self._clear_sliders_layout()
        shape_info = self.get_shape_info()

        if not shape_info:
            self.dimension_container.hide()
            self._projection = None
            self._refresh_parent_panel()
            return

        y_shape, dim_names, axis_arrays, associated_data = shape_info
        self._shape = y_shape
        self._dim_names = dim_names
        self._axis_arrays = axis_arrays
        self._associated_data = associated_data

        if len(y_shape) > 1:
            self.dimension_container.show()
        else:
            self.dimension_container.hide()
            if self.dimension_spinbox.value() != 1:
                self.dimension_spinbox.setValue(1)

        self._projection = self.plot_model.driving_projection()
        if self._projection is None:
            self._refresh_parent_panel()
            return

        order = self._projection.axis_order
        visible_positions = [
            pos for pos, sa in enumerate(order) if y_shape[sa] > 1
        ]
        if not visible_positions:
            self._refresh_parent_panel()
            return

        slice_header = QLabel("Slice / reduce")
        slice_header.setStyleSheet(
            "font-weight: bold; font-size: 11px; margin: 0; padding: 0;"
        )
        self.sliders_layout.addWidget(slice_header)

        n_slice = self._projection.n_slice_axes

        for pos in range(n_slice):
            storage_axis = order[pos]
            if y_shape[storage_axis] <= 1:
                continue
            row = self._build_slice_row(
                storage_axis,
                dim_names,
                axis_arrays,
                associated_data,
                y_shape,
                pos,
                len(order),
            )
            self.sliders_layout.addWidget(row)
            self._slice_rows.append(row)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setFixedHeight(1)
        self.sliders_layout.addWidget(separator)

        plot_header = QLabel("Plot axes")
        plot_header.setStyleSheet(
            "font-weight: bold; font-size: 11px; margin: 0; padding: 0;"
        )
        self.sliders_layout.addWidget(plot_header)

        for _offset, pos in enumerate(range(n_slice, len(order))):
            storage_axis = order[pos]
            if y_shape[storage_axis] <= 1:
                continue
            label = self._plot_axis_label_for_storage(storage_axis)
            row = _PlotAxisRow(dim_names[storage_axis], label)
            row.storage_axis = storage_axis
            row.move_up_requested.connect(
                lambda r=pos: self._move_row(r, direction=-1)
            )
            row.move_down_requested.connect(
                lambda r=pos: self._move_row(r, direction=1)
            )
            row.up_button.setEnabled(pos > 0)
            row.down_button.setEnabled(pos < len(order) - 1)
            self.sliders_layout.addWidget(row)
            self._plot_rows.append(row)

        self.refresh_plot_axis_labels()
        self._refresh_parent_panel()

    def _refresh_parent_panel(self):
        """
        Update the enclosing CollapsiblePanel after rows are rebuilt.
        """
        panel = self.parentWidget()
        while panel is not None and not isinstance(panel, CollapsiblePanel):
            panel = panel.parentWidget()
        if panel is not None:
            panel.refresh_expanded_size()

    def _build_slice_row(
        self,
        storage_axis,
        dim_names,
        axis_arrays,
        associated_data,
        y_shape,
        row_index,
        n_rows,
    ):
        dim_name = dim_names[storage_axis]
        axis_data = axis_arrays[storage_axis]
        assoc = associated_data.get(dim_name, {})
        row = _SliceReduceRow(
            dim_name,
            axis_data,
            assoc,
            y_shape[storage_axis] - 1,
        )
        row.storage_axis = storage_axis
        role = self._projection.roles[storage_axis]
        if role not in SLICE_ROLES:
            role = DimRole.INDEX
        row.set_role(role)
        row.slider.setValue(self._projection.indices[storage_axis])
        row.changed.connect(self._on_row_changed)
        row.move_up_requested.connect(
            lambda r=row_index: self._move_row(r, direction=-1)
        )
        row.move_down_requested.connect(
            lambda r=row_index: self._move_row(r, direction=1)
        )
        row.up_button.setEnabled(row_index > 0)
        row.down_button.setEnabled(row_index < n_rows - 1)
        return row

    def _clear_sliders_layout(self):
        """
        Remove every widget from the axis control layout.

        Headers, separators, and rows are all recreated in
        :meth:`create_sliders`.
        """
        while self.sliders_layout.count():
            item = self.sliders_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._slice_rows = []
        self._plot_rows = []

    def _move_row(self, row_index, direction):
        self.plot_model.move_view_axis(row_index, direction)
        self.create_sliders()

    def _on_row_changed(self):
        if self._updating_ui or self._projection is None:
            return
        self.plot_model.set_axis_reduce(
            {
                row.storage_axis: (row.get_role(), row.get_index())
                for row in self._slice_rows
            }
        )

    def _plot_axis_label_for_storage(self, storage_axis: int) -> str:
        """
        Return the Plot X / Plot Y label for a storage axis.

        The view spec's roles are authoritative and are kept in step with
        ``axis_order`` by the constructor. The rendered frame cannot answer
        this: ``PlotViewFrame.plot_x_dim`` / ``plot_y_dim`` are positions
        within the displayed plane (rows and columns), not storage axes, so
        reading them here returned a fixed mapping that stopped matching the
        plot as soon as the user reordered the rows.

        Parameters
        ----------
        storage_axis : int
            Storage dimension index.

        Returns
        -------
        str
            Plot axis role label, or empty when the axis is not a plot axis.
        """
        if self._projection is None:
            return ""
        role = self._projection.roles[storage_axis]
        if role in (DimRole.PLOT_X, DimRole.PLOT_Y):
            return ROLE_LABELS[role]
        return ""

    def refresh_plot_axis_labels(self):
        """
        Refresh plot-axis row labels from the rendered view frame.
        """
        for row in self._plot_rows:
            if row.storage_axis is None:
                continue
            row.plot_label.setText(
                self._plot_axis_label_for_storage(row.storage_axis)
            )

    def refresh_axis_coordinates(self):
        """
        Update slice slider readouts with loaded axis coordinate values.
        """
        if not self._slice_rows or self._dim_names is None:
            return
        shape_info = self.get_shape_info()
        if not shape_info:
            return
        _, dim_names, axis_arrays, associated_data = shape_info
        self._axis_arrays = axis_arrays
        self._associated_data = associated_data
        for row in self._slice_rows:
            storage_axis = row.storage_axis
            if storage_axis is None or storage_axis >= len(axis_arrays):
                continue
            dim_name = dim_names[storage_axis]
            row.set_axis_data(
                axis_arrays[storage_axis],
                associated_data.get(dim_name, {}),
            )

    def _axis_coordinates_for_run(self, run_model, ykey, x_keys, names, shape):
        """
        Return each axis's coordinates, and the other X keys riding on it.

        The coordinates are read from the 1-D keys the Y key's description
        names, never from the Y key itself. A further selected X key living
        on an axis arrives as a non-dimension coordinate there, and becomes a
        readout beside that axis's slider.
        """
        placeholders = index_placeholders(shape)
        try:
            coords = run_model.load_coords(ykey, None, x_keys)
        except Exception:
            return list(placeholders), {}

        aligned = []
        for i, (name, size) in enumerate(zip(names, shape, strict=True)):
            arr = (
                np.asarray(coords[name].values, dtype=float).ravel()
                if name in coords
                else np.array([])
            )
            aligned.append(arr if arr.size == size else placeholders[i])

        associated_data = {}
        for name, coord in coords.items():
            if name in coord.dims:
                continue
            entry = associated_data.setdefault(
                coord.dims[0], {"arrays": [], "names": []}
            )
            entry["arrays"].append(np.asarray(coord.values))
            entry["names"].append(name)
        return aligned, associated_data

    def get_shape_info(self):
        """
        Get shape and dimension layout from visible runs for slice controls.

        Axis coordinates use loaded motor or axis-hint values when available,
        otherwise integer index placeholders.

        Returns
        -------
        tuple or None
            ``(shape, dimension_names, axis_arrays, associated_data)`` or None.
        """
        if not self.plot_model:
            return None

        run_models = self.plot_model.collection.visible_models
        if not run_models:
            return None

        max_shape = None
        max_axes = None
        max_names = None
        max_associated = None

        for run_model in run_models:
            try:
                sel = self.plot_model.selection.selection_for(run_model.uid)
                x_keys, y_keys = list(sel.x), list(sel.y)
                if not y_keys:
                    continue

                for ykey in y_keys:
                    if run_model.is_synthetic_key(ykey):
                        continue
                    try:
                        shape = run_model.describe(ykey).shape
                        axis_names = list(
                            run_model.plot_axis_names(ykey, x_keys)
                        )
                        axis_arrays, associated_data = (
                            self._axis_coordinates_for_run(
                                run_model, ykey, x_keys, axis_names, shape
                            )
                        )

                        if (
                            max_shape is None
                            or len(shape) > len(max_shape)
                            or (
                                len(shape) == len(max_shape)
                                and any(s > m for s, m in zip(shape, max_shape, strict=True))
                            )
                        ):
                            max_shape = shape
                            max_axes = axis_arrays
                            max_names = axis_names
                            max_associated = associated_data

                    except Exception as e:
                        print(f"Error getting dimension info for {ykey}: {e}")

            except Exception as e:
                print(f"Error processing run model {run_model}: {e}")

        if max_shape is None or len(max_shape) <= 1:
            return None

        return max_shape, max_names, max_axes, max_associated

    def on_dimension_changed(self):
        """
        Handle changes to the plot dimension spinbox.

        The canvas may refuse 2-D when several datasets are visible, in which
        case only the spinbox is rolled back -- the session was never told,
        so there is no view state to undo.
        """
        old_dim = self.plot_model.view_intent.plot_ndim
        new_dim = self.dimension_spinbox.value()
        if new_dim == old_dim:
            return

        if not self.canvas.accepts_plot_ndim(new_dim):
            self._updating_ui = True
            self.dimension_spinbox.setValue(old_dim)
            self._updating_ui = False
            return

        self.plot_model.view_intent.set_plot_ndim(new_dim)
        self._updating_ui = True
        self.create_sliders()
        self._updating_ui = False

    def on_run_added(self, run_model):
        self.create_sliders()

    def on_run_removed(self, run_model):
        self.create_sliders()

    def on_selection_changed(self):
        self.plot_model.follow_x_selection()
        self.create_sliders()
