from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QSlider,
    QLabel,
    QSpinBox,
    QHBoxLayout,
    QDoubleSpinBox,
)
from qtpy.QtCore import Qt, Signal
from nbs_viewer.utils import print_debug


class PlotDimensionControl(QWidget):
    """
    Widget for controlling dimensions of N-dimensional data in plots.

    Creates sliders for navigating through dimensions of data that are not
    currently being plotted.
    """

    indicesUpdated = Signal(tuple)
    dimensionChanged = Signal(int)

    def __init__(self, run_list_model, canvas, parent=None):
        """
        Initialize the dimension control widget.

        Parameters
        ----------
        run_list_model : RunListModel
            The plot data model to control.
        parent : QWidget, optional
            Parent widget, by default None.
        """
        super().__init__(parent)
        self.run_list_model = run_list_model
        self.canvas = canvas
        self.sliders = []
        self.labels = []
        self._indices = tuple()
        self._nsliders = 0
        # Connect signals
        # Connect to model signals
        self.run_list_model.run_added.connect(self.on_run_added)
        self.run_list_model.run_removed.connect(self.on_run_removed)
        self.run_list_model.selected_keys_changed.connect(self.on_selection_changed)

        self.init_ui()

    def init_ui(self):
        """
        Initialize the user interface with dimension controls.
        """
        self.layout = QVBoxLayout()

        # Dimension selection spinbox
        self.dimension_container = QWidget()
        dimension_layout = QVBoxLayout(self.dimension_container)
        dimension_label = QLabel("Plot Dimensions:")
        self.dimension_spinbox = QSpinBox()
        self.dimension_spinbox.setMinimum(1)
        self.dimension_spinbox.setMaximum(2)
        self.dimension_spinbox.setValue(1)
        self.dimension_spinbox.valueChanged.connect(self.on_dimension_changed)

        dimension_layout.addWidget(dimension_label)
        dimension_layout.addWidget(self.dimension_spinbox)
        self.layout.addWidget(self.dimension_container)
        self.dimension_container.hide()  # Hide by default

        # Create sliders container
        self.sliders_container = QWidget()
        self.sliders_layout = QVBoxLayout(self.sliders_container)
        self.layout.addWidget(self.sliders_container)

        self.setLayout(self.layout)

        # Create initial sliders if we have data
        self.create_sliders()

    def create_sliders(self):
        """
        Create sliders based on the dimensions of the data.
        Clears existing sliders and creates new ones based on current data.
        Uses dimension analysis to get proper axis data and labels.
        """
        print_debug(
            "PlotDimensionControl.create_sliders",
            f"Creating sliders with current dimension: {self.dimension_spinbox.value()}",
            category="dimension",
        )

        # Clear existing sliders and reset state
        for slider in self.sliders:
            slider.deleteLater()
        self.sliders = []

        for label in self.labels:
            label.deleteLater()
        self.labels = []

        # Initialize indices based on plot dimensions
        plot_dims = self.dimension_spinbox.value()

        # Track which dimensions have sliders
        self._slider_dimensions = []

        # Get shape information from the model
        shape_info = self.get_shape_info()

        if not shape_info:
            print_debug(
                "PlotDimensionControl.create_sliders",
                "No shape info available, not creating sliders",
                category="dimension",
            )
            # Hide dimension control for 1D data
            self.dimension_container.hide()
            # Force update with empty indices when no sliders
            self._indices = None
            self.canvas.update_view_state(self._indices, 1, validate=False)
            return

        # Unpack shape info
        y_shape, dim_names, axis_arrays, associated_data = shape_info
        # print(f"  Y shape: {y_shape}, Dimension names: {dim_names}")
        # print(f"  Associated data: {associated_data}")

        # Show/hide dimension control based on data dimensionality
        if len(y_shape) > 1:
            self.dimension_container.show()
        else:
            self.dimension_container.hide()
            # Force 1D mode for 1D data
            if self.dimension_spinbox.value() != 1:
                self.dimension_spinbox.setValue(1)

        # Determine how many sliders we need based on dimension setting
        plot_dims = self.dimension_spinbox.value()
        # print(f"  Plot dimensions: {plot_dims}")

        # Create a slider for each dimension except the ones being plotted
        nsliders = len(y_shape) - plot_dims
        self._nsliders = nsliders

        slice_info = []

        # For each dimension up to the total number of dimensions
        for i in range(self._nsliders + plot_dims):
            if i >= self._nsliders:
                # Last plot_dims dimensions get full slice
                slice_info.append(slice(None))
            else:
                # Other dimensions get integer index from full_indices
                slice_info.append(0)

        # Convert to tuple for consistent handling
        self._indices = tuple(slice_info)
        print_debug(
            "PlotDimensionControl.create_sliders",
            f"Reset indices to: {self._indices}",
            category="dimension",
        )
        # print(f"  Number of sliders needed: {nsliders}")

        if nsliders <= 0:
            # print("  No sliders needed (nsliders <= 0)")
            # Force update with empty indices when no sliders needed
            self.canvas.update_view_state(self._indices, plot_dims, validate=False)
            return
        # Initialize full indices list with zeros
        for dim in range(nsliders):
            # print(f"  Creating slider for dimension {dim}")

            # Get dimension name and axis data
            dim_name = dim_names[dim]
            axis_data = axis_arrays[dim]
            slider_max = y_shape[dim] - 1

            # Skip dimensions with no points
            if slider_max <= 0:
                # print(f"  {dim_name} is a dummy dimension, skipping")
                continue

            # Create horizontal layout for this dimension
            dim_layout = QHBoxLayout()

            # Create label for dimension name
            name_label = QLabel(f"{dim_name}:")
            dim_layout.addWidget(name_label)
            self.labels.append(name_label)

            # Create slider
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(slider_max)
            # print(f"  Slider range: 0-{slider_max}")

            # Create value label if we have axis data
            if len(axis_data) > 0:
                value_label = QLabel(f"({axis_data[slider.value()]:g})")
                # Update value label when slider changes
                slider.valueChanged.connect(
                    lambda v, lbl=value_label, data=axis_data: lbl.setText(
                        f"({data[v]:g})"
                    )
                )
                dim_layout.addWidget(value_label)
                self.labels.append(value_label)

            # Add associated axis info if available
            if dim_name in associated_data:
                assoc_info = associated_data[dim_name]
                assoc_arrays = assoc_info["arrays"]
                assoc_names = assoc_info["names"]

                # Create labels for associated axes
                for arr, name in zip(assoc_arrays, assoc_names):
                    assoc_label = QLabel(f"{name}: {arr[slider.value()]:g}")
                    # Connect signal to update associated value
                    slider.valueChanged.connect(
                        lambda v, lbl=assoc_label, data=arr, name=name: lbl.setText(
                            f"{name}: {data[v]:g}"
                        )
                    )
                    dim_layout.addWidget(assoc_label)
                    self.labels.append(assoc_label)

            # Store the dimension index this slider corresponds to
            slider.dimension_index = dim
            self._slider_dimensions.append(dim)

            # Connect to update plot
            slider.valueChanged.connect(lambda x: self.sliders_changed())

            # Add to layout
            dim_layout.addWidget(slider)
            self.sliders_layout.addLayout(dim_layout)

            # Store references
            self.sliders.append(slider)

        # print(f"  Created {len(self.sliders)} sliders")
        # print(f"  Slider dimensions: {self._slider_dimensions}")

        # Emit initial indices
        self.sliders_changed()

    def get_shape_info(self):
        """
        Get shape and dimension information from the plot model.

        Uses the new dimension analysis code to get proper dimension information
        including axis data for each dimension.

        Returns
        -------
        tuple or None
            Tuple of:
            - shape: tuple of dimension sizes
            - dimension_names: list of dimension names
            - axis_arrays: list of arrays for each dimension
            - associated_data: dict mapping dimensions to associated motor data
            Returns None if no shape info available
        """
        # print("Getting shape info...")
        if not self.run_list_model:
            print("No plot model available")
            return None

        # Get all visible run models
        run_models = self.run_list_model.visible_models
        # print(f"Visible run models: {run_models}")

        if not run_models:
            # print("No visible run models")
            return None

        # Get dimension info from each visible run
        max_shape = None
        max_dim_info = None
        max_axes = None
        max_names = None
        max_associated = None

        for run_model in run_models:
            try:
                # Get selected keys for this run model
                x_keys, y_keys, norm_keys = run_model.get_selected_keys()
                # print(
                #     f"Selected keys for {run_model}: "
                #     f"x={x_keys}, y={y_keys}, norm={norm_keys}"
                # )

                # We're primarily interested in y_keys for shape information
                if not y_keys:
                    continue

                # Get dimension info for each y key
                for ykey in y_keys:
                    try:
                        # Get dimension analysis
                        axis_arrays, axis_names, associated_data = (
                            run_model._run.get_dimension_axes(ykey, x_keys)
                        )
                        shape = tuple(
                            len(arr) if len(arr) > 0 else 1 for arr in axis_arrays
                        )

                        # Update max shape if this is larger
                        if (
                            max_shape is None
                            or len(shape) > len(max_shape)
                            or (
                                len(shape) == len(max_shape)
                                and any(s > m for s, m in zip(shape, max_shape))
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

        if max_shape is None:
            # print("No shape information found")
            return None

        if len(max_shape) <= 1:
            # print("Data is 1D or less, no need for sliders")
            return None

        # print(f"Maximum shape: {max_shape}")
        # print(f"Dimension names: {max_names}")
        # print(f"Associated data: {max_associated}")

        return max_shape, max_names, max_axes, max_associated

    def get_dimension_name(self, dim_index):
        """
        Get a human-readable name for a dimension.

        Parameters
        ----------
        dim_index : int
            Index of the dimension

        Returns
        -------
        str
            Name of the dimension
        """
        # Try to get dimension name from the model
        if hasattr(self.run_list_model, "get_dimension_name"):
            name = self.run_list_model.get_dimension_name(dim_index)
            if name:
                return name

        # Fallback to generic name
        return f"Dimension {dim_index}"

    def on_dimension_changed(self):
        """
        Handle changes to the dimension spinbox.
        Updates the plot dimensions in the model and recreates sliders.
        """
        print_debug(
            "PlotDimensionControl",
            f"Dimension changing from {self.canvas._dimension} to {self.dimension_spinbox.value()}",
            category="dimension",
        )
        # Update the dimension in the model
        old_dim = self.canvas._dimension
        new_dim = self.dimension_spinbox.value()

        # Recreate the sliders
        print_debug(
            "PlotDimensionControl",
            "Recreating sliders for dimension change",
            category="dimension",
        )
        self.create_sliders()
        self.sliders_changed(update_plot=False)
        update_accepted = self.canvas.update_view_state(
            self._indices, new_dim, validate=True
        )

        if not update_accepted:
            print_debug(
                "PlotDimensionControl",
                f"Dimension change to {new_dim} rejected, reverting to {old_dim}",
                category="dimension",
            )
            self.dimension_spinbox.setValue(old_dim)
            self.create_sliders()
            self.sliders_changed()
            return

        print_debug(
            "PlotDimensionControl",
            f"Dimension change accepted, now at {new_dim}",
            category="dimension",
        )
        self.dimensionChanged.emit(new_dim)

    def sliders_changed(self, update_plot=True):
        """
        Handle slider value changes.
        Collects current indices and emits the indicesUpdated signal.
        Creates a complete slice tuple including slice(None) for fully sliced dimensions.
        """
        # Initialize all indices to 0
        full_indices = [0] * self._nsliders
        print_debug(
            "PlotDimensionControl", "Handling slider change", category="dimension"
        )
        print_debug(
            "PlotDimensionControl",
            f"Number of sliders: {self._nsliders}",
            category="dimension",
        )

        # Update indices for dimensions that have sliders
        for slider in self.sliders:
            dim_index = slider.dimension_index
            full_indices[dim_index] = slider.value()
            print_debug(
                "PlotDimensionControl",
                f"Slider {dim_index} value: {slider.value()}",
                category="dimension",
            )

        # Convert indices to slice objects based on plot dimensions
        plot_dims = self.dimension_spinbox.value()
        slice_info = []

        # For each dimension up to the total number of dimensions
        for i in range(self._nsliders + plot_dims):
            if i >= len(full_indices):
                # Last plot_dims dimensions get full slice
                slice_info.append(slice(None))
            else:
                # Other dimensions get integer index from full_indices
                slice_info.append(full_indices[i])

        # Convert to tuple for consistent handling
        self._indices = tuple(slice_info)
        print_debug(
            "PlotDimensionControl",
            f"Generated indices: {self._indices}",
            category="dimension",
        )
        print_debug(
            "PlotDimensionControl",
            f"Plot dimensions: {plot_dims}",
            category="dimension",
        )

        # Emit signal to update the plot
        dim = self.dimension_spinbox.value()

        if update_plot:
            print_debug(
                "PlotDimensionControl",
                f"Updating plot with indices: {self._indices}, dimension: {dim}",
                category="dimension",
            )
            self.canvas.update_view_state(self._indices, dim, validate=False)
        else:
            print_debug(
                "PlotDimensionControl",
                f"Not updating plot with indices: {self._indices}, dimension: {dim}",
                category="dimension",
            )
        self.indicesUpdated.emit(self._indices)

    def on_run_added(self, run_model):
        """
        Handle a run being added to the plot model.

        Parameters
        ----------
        run_model : RunModel
            The run model that was added
        """
        # Update sliders when a run is added
        self.create_sliders()

    def on_run_removed(self, run_model):
        """
        Handle a run being removed from the plot model.

        Parameters
        ----------
        run_model : RunModel
            The run model that was removed
        """
        # Update sliders when a run is removed
        self.create_sliders()

    def on_selection_changed(self):
        """
        Handle changes to the data selection in the plot model.
        """
        # Update sliders when selection changes
        self.create_sliders()
