from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QSlider,
    QLabel,
    QSpinBox,
)
from qtpy.QtCore import Qt, Signal


class PlotDimensionControl(QWidget):
    """
    Widget for controlling dimensions of N-dimensional data in plots.

    Creates sliders for navigating through dimensions of data that are not
    currently being plotted.
    """

    indicesUpdated = Signal(tuple)
    dimensionChanged = Signal(int)

    def __init__(self, plotModel, canvas, parent=None):
        """
        Initialize the dimension control widget.

        Parameters
        ----------
        plotModel : PlotDataModel
            The plot data model to control.
        parent : QWidget, optional
            Parent widget, by default None.
        """
        super().__init__(parent)
        self.plotModel = plotModel
        self.canvas = canvas
        self.sliders = []
        self.labels = []
        self._indices = tuple()

        # Connect signals
        # Connect to model signals
        self.plotModel.run_added.connect(self.on_run_added)
        self.plotModel.run_removed.connect(self.on_run_removed)
        self.plotModel.selected_keys_changed.connect(self.on_selection_changed)

        self.init_ui()

    def init_ui(self):
        """
        Initialize the user interface with dimension controls.
        """
        self.layout = QVBoxLayout()

        # Dimension selection spinbox
        dimension_layout = QVBoxLayout()
        dimension_label = QLabel("Plot Dimensions:")
        self.dimension_spinbox = QSpinBox()
        self.dimension_spinbox.setMinimum(1)
        self.dimension_spinbox.setMaximum(2)
        self.dimension_spinbox.setValue(1)
        self.dimension_spinbox.valueChanged.connect(self.on_dimension_changed)

        dimension_layout.addWidget(dimension_label)
        dimension_layout.addWidget(self.dimension_spinbox)
        self.layout.addLayout(dimension_layout)

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
        """
        print("\nDebugging create_sliders:")

        # Clear existing sliders
        for slider in self.sliders:
            slider.deleteLater()
        self.sliders = []

        for label in self.labels:
            label.deleteLater()
        self.labels = []

        # Get shape information from the model
        shape_info = self.get_shape_info()
        print(f"  Shape info: {shape_info}")

        if not shape_info:
            print("  No shape info available, not creating sliders")
            return

        # Determine how many sliders we need based on dimension setting
        plot_dims = self.dimension_spinbox.value()
        print(f"  Plot dimensions: {plot_dims}")

        y_shape, dim_names = shape_info
        print(f"  Y shape: {y_shape}, Dimension names: {dim_names}")

        # Create a slider for each dimension except the ones being plotted
        nsliders = len(y_shape) - plot_dims
        print(f"  Number of sliders needed: {nsliders}")

        if nsliders <= 0:
            print("  No sliders needed (nsliders <= 0)")
            return

        for dim in range(nsliders):
            print(f"  Creating slider for dimension {dim}")
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(y_shape[dim] - 1)
            print(f"  Slider range: 0-{y_shape[dim] - 1}")

            # Get dimension name
            dim_name = self.get_dimension_name(dim)
            print(f"  Dimension name: {dim_name}")
            label = QLabel(f"{dim_name} index: {slider.value()}")

            # Connect signals
            slider.valueChanged.connect(
                lambda value, lbl=label, d=dim: lbl.setText(
                    f"{self.get_dimension_name(d)} index: {value}"
                )
            )
            slider.valueChanged.connect(self.sliders_changed)

            # Add to layout
            self.sliders_layout.addWidget(label)
            self.sliders_layout.addWidget(slider)

            # Store references
            self.sliders.append(slider)
            self.labels.append(label)

        print(f"  Created {len(self.sliders)} sliders")

        # Emit initial indices
        self.sliders_changed()

    def get_shape_info(self):
        """
        Get shape information from the plot model.

        Returns
        -------
        tuple or None
            Tuple of (shape, dimension_names) or None if no shape info available
        """
        print("Getting shape info...")
        if not self.plotModel:
            print("No plot model available")
            return None

        # Get all visible run models
        run_models = self.plotModel.visible_models
        print(f"Visible run models: {run_models}")

        if not run_models:
            print("No visible run models")
            return None

        # Collect shape information from all visible run models
        shapes_by_dim = {}  # Dictionary to group shapes by dimensionality

        for run_model in run_models:
            try:
                # Get selected keys for this run model
                x_keys, y_keys, norm_keys = run_model.get_selected_keys()
                print(
                    f"Selected keys for {run_model}: "
                    f"x={x_keys}, y={y_keys}, norm={norm_keys}"
                )

                # We're primarily interested in y_keys for shape information
                if not y_keys:
                    continue

                # Get shape for each y key
                for key in y_keys:
                    try:
                        # Get shape from the run object
                        shape = run_model._run.getShape(key)
                        print(f"Shape for {key}: {shape}")

                        if shape:
                            # Group by dimensionality
                            dim = len(shape)
                            if dim not in shapes_by_dim:
                                shapes_by_dim[dim] = []
                            shapes_by_dim[dim].append(shape)
                    except Exception as e:
                        print(f"Error getting shape for {key}: {e}")
            except Exception as e:
                print(f"Error processing run model {run_model}: {e}")

        print(f"Shapes by dimension: {shapes_by_dim}")

        if not shapes_by_dim:
            print("No shape information found")
            return None

        # Find the maximum dimensionality
        max_dim = max(shapes_by_dim.keys()) if shapes_by_dim else 0
        print(f"Maximum dimensionality: {max_dim}")

        if max_dim <= 1:
            print("Data is 1D or less, no need for sliders")
            return None

        # Get the maximum shape for the maximum dimensionality
        max_shape = None
        for shape in shapes_by_dim[max_dim]:
            if max_shape is None:
                max_shape = shape
            else:
                # Take the maximum size for each dimension
                new_shape = []
                for a, b in zip(max_shape, shape):
                    new_shape.append(max(a, b))
                max_shape = tuple(new_shape)

        print(f"Maximum shape: {max_shape}")

        # Create dimension names
        dim_names = [f"Dimension {i+1}" for i in range(len(max_shape))]

        return max_shape, dim_names

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
        if hasattr(self.plotModel, "get_dimension_name"):
            name = self.plotModel.get_dimension_name(dim_index)
            if name:
                return name

        # Fallback to generic name
        return f"Dimension {dim_index}"

    def on_dimension_changed(self):
        """
        Handle changes to the dimension spinbox.
        Updates the plot dimensions in the model and recreates sliders.
        """
        print("\nDebugging dimension_changed:")
        # Update the dimension in the model
        old_dim = self.canvas._dimension
        new_dim = self.dimension_spinbox.value()
        print(f"  New dimension value: {new_dim}")

        # Recreate the sliders
        self.create_sliders()
        print("  Calling sliders_changed")
        self.sliders_changed()
        print("  Recreating sliders")
        update_accepted = self.canvas.update_view_state(
            self._indices, new_dim, validate=True
        )

        if not update_accepted:
            self.dimension_spinbox.setValue(old_dim)
            self.create_sliders()
            print("  Calling sliders_changed")
            self.sliders_changed()
            return

        self.dimensionChanged.emit(new_dim)

    def sliders_changed(self):
        """
        Handle slider value changes.
        Collects current indices and emits the indicesUpdated signal.
        """
        print("\nDebugging sliders_changed:")
        indices = []
        for slider in self.sliders:
            indices.append(slider.value())
            print(f"  Slider value: {slider.value()}")

        # Convert to tuple for consistent handling
        self._indices = tuple(indices)
        print(f"  Emitting indicesUpdated with indices: {self._indices}")

        # Emit signal to update the plot
        self.canvas.update_view_state(
            self._indices, self.canvas._dimension, validate=False
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
