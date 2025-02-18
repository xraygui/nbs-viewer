from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
)
from qtpy.QtCore import Signal
from .dataSource import DataSourcePicker
from .views.plot.canvasControl import CanvasControlWidget


"""
This is now the primary thing to refactor -- very poorly named, this is really 
the central widget that controls the data sources and the plot list. It is what
controls adding and removing runs from the temporary plot.

We probably need to combine this with plotManager, or at least make it a lot more obvious
what is going on. The connections to the plotControl also need to be more obvious.
Possibly we need to separate out a model from the view.
"""


class DataSourceManager(QWidget):
    """
    Widget managing data sources and their selection state.

    Signals
    -------
    itemSelected : Signal
        Emitted when a run is selected (RunData, canvas_id)
    itemDeselected : Signal
        Emitted when a run is deselected (RunData, canvas_id)
    selectionChanged : Signal
        Emitted when the overall selection changes (List[RunData], canvas_id)
    """

    itemSelected = Signal(object)  # (RunData, canvas_id)
    itemDeselected = Signal(object)  # (RunData, canvas_id)
    selectionChanged = Signal(list)  # (List[RunData], canvas_id)

    def __init__(self, plot_model, canvas_manager, config_file=None, parent=None):
        super().__init__(parent)
        self.plot_model = plot_model
        self.canvas_controls = CanvasControlWidget(canvas_manager, self)
        self.config_file = config_file

        # Connect selection signals to plot model
        self.itemSelected.connect(self.plot_model.add_run)
        self.itemDeselected.connect(self.plot_model.remove_run)

        # Connect selection changed to canvas controls
        self.selectionChanged.connect(self.canvas_controls.handle_run_selection)

        # Create UI elements
        self.label = QLabel("Data Source")
        self.dropdown = QComboBox(self)
        self.dropdown.currentIndexChanged.connect(self.switch_table)
        self.new_source = QPushButton("New Data Source")
        self.new_source.clicked.connect(self.add_new_source)
        self.plot_button = QPushButton("Add Selected to Plot List", self)
        self.plot_button.clicked.connect(self.add_selected_items)

        self.stacked_widget = QStackedWidget()

        # Layout
        hbox_layout = QHBoxLayout()
        hbox_layout.addWidget(self.label)
        hbox_layout.addWidget(self.dropdown)

        layout = QVBoxLayout()
        layout.addLayout(hbox_layout)
        layout.addWidget(self.new_source)
        layout.addWidget(self.stacked_widget)
        layout.addWidget(self.canvas_controls)
        layout.addWidget(self.plot_button)
        self.setLayout(layout)

    def add_new_source(self):
        picker = DataSourcePicker(config_file=self.config_file, parent=self)
        if picker.exec_():
            sourceView, label = picker.getSource()
            if sourceView is not None and label is not None:
                # Connect to individual selection signals
                sourceView.itemSelected.connect(self.itemSelected)
                sourceView.itemDeselected.connect(self.itemDeselected)
                sourceView.selectionChanged.connect(self.selectionChanged)

                self.stacked_widget.addWidget(sourceView)
                self.dropdown.addItem(label)
                self.dropdown.setCurrentIndex(self.dropdown.count() - 1)

    def switch_table(self):
        self.stacked_widget.setCurrentIndex(self.dropdown.currentIndex())

    def add_selected_items(self):
        current_widget = self.stacked_widget.currentWidget()
        if hasattr(current_widget, "get_selected_items"):
            selected_items = current_widget.get_selected_items()
            if selected_items:
                if hasattr(current_widget, "deselect_items"):
                    current_widget.deselect_items(selected_items)

                for item in selected_items:
                    print("Disconnecting item")
                    item.disconnect_plot()
                    # Emit selection for each item
                    self.itemSelected.emit(item, "main")
