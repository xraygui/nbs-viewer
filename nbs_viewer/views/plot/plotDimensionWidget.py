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
    Must be updated to be able to hold a list of DataPlotters! Most Key thing.
    A class to create control widgets for DataPlotter based on the dimensions of the y data.

    Attributes
    ----------
    data_plotter : DataPlotter
        The DataPlotter instance to control.
    sliders : list
        A list of QSlider widgets for controlling the dimensions of the y data.
    """

    indicesUpdated = Signal(tuple)

    def __init__(self, plotModel, parent=None):
        """
        Initializes the DataPlotterControl with a DataPlotter instance and creates sliders.

        Parameters
        ----------
        data_plotter : DataPlotter
            The DataPlotter instance to control.
        """
        super().__init__(parent)
        self.plotModel = plotModel
        self.indicesUpdated.connect(self.plotModel.update_indices)
        self.init_ui()

    def add_data(self, data_plotter):
        # print(f"Adding data {data_plotter._label}")
        old_dim = self.dimension_spinbox.value()
        new_dim = data_plotter.x_dim
        if new_dim != old_dim:
            self.dimension_spinbox.setValue(data_plotter.x_dim)
        else:
            self.dimension_changed()

    def remove_data(self, data_plotter):
        if data_plotter in self.data_list:
            idx = self.data_list.index(data_plotter)
            self.data_list.pop(idx)
            # print(f"Removed {idx}, data list len: {len(self.data_list)}")
            self.indicesUpdated.disconnect(data_plotter.update_indices)
        data_plotter.clear()

    def clear_data(self):
        while self.data_list:
            data_plotter = self.data_list.pop()
            self.indicesUpdated.disconnect(data_plotter.update_indices)
            data_plotter.clear()

    def init_ui(self):
        """
        Initializes the user interface, creating sliders based on the dimensions of the y data.
        """
        self.layout = QVBoxLayout()

        self.dimension_spinbox = QSpinBox()
        self.dimension_spinbox.setMinimum(1)
        self.dimension_spinbox.setMaximum(2)
        self.dimension_spinbox.setValue(1)
        self.dimension_spinbox.valueChanged.connect(self.dimension_changed)
        self.layout.addWidget(self.dimension_spinbox)
        self.create_sliders()

        self.setLayout(self.layout)

    def create_sliders(self):
        for slider in getattr(self, "sliders", []):
            slider.deleteLater()
        self.sliders = []

        for label in getattr(self, "labels", []):
            label.deleteLater()
        self.labels = []

        # Assuming _y is accessible and is a numpy array
        # Need to have the data_plotter report the shape itself!!
        if len(self.plotModel._artist_manager.artists) == 0:
            return
        else:
            runModel = self.plotModel.runModels[0]
        y_shape = runModel.shape

        def create_slider_callback(label, dim):
            def callback(value):
                label.setText(f"{data_plotter._xkeys[dim]} index: {value}")
                # Here you can also add the logic to update the plotted data based on the slider's value

            return callback

        # Create a slider for each dimension of y, except the last one
        nsliders = len(y_shape) - self.dimension_spinbox.value()

        # If we don't have enough x data, just return (maybe later we will warn)
        if nsliders > len(data_plotter._x):
            print("Not enough selected x data for desired dimension")
            return

        for dim in range(nsliders):
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(y_shape[dim] - 1)
            label = QLabel(f"{data_plotter._xkeys[dim]} index: {slider.value()}")
            slider.valueChanged.connect(create_slider_callback(label, dim))
            slider.valueChanged.connect(self.sliders_changed)
            self.layout.addWidget(label)
            self.layout.addWidget(slider)
            self.sliders.append(slider)
            self.labels.append(label)

    def dimension_changed(self):
        # Update the dimension in DataPlotter
        # print(f"New dimension {self.dimension_spinbox.value()}")
        # print(f"Data list len: {len(self.data_list)}")
        for data_plotter in self.data_list:
            data_plotter.x_dim = self.dimension_spinbox.value()
        # Recreate the sliders
        self.create_sliders()
        self.sliders_changed()
        # You might need to update the plot here as well

    def sliders_changed(self):
        """
        Creates a callback function for a slider that updates the plotted data based on the slider's value.

        Parameters
        ----------
        dim : int
            The dimension that the slider controls.

        Returns
        -------
        function
            A callback function to be connected to the slider's valueChanged signal.
        """
        # print("Sliders changed")
        indices = []
        for s in self.sliders:
            value = s.value()
            indices.append(value)
        indices = tuple(indices)
        # print(indices)
        self.indicesUpdated.emit(indices)
