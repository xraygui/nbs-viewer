from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
)
from .dataSource import DataSourcePicker
from .plot.canvasControl import CanvasControlWidget


"""
This is now the primary thing to refactor -- very poorly named, this is really 
the central widget that controls the data sources and the plot list. It is what
controls adding and removing runs from the temporary plot.

We probably need to combine this with plotManager, or at least make it a lot more obvious
what is going on. The connections to the plotControl also need to be more obvious.
Possibly we need to separate out a model from the view.
"""


class DataSourceSwitcher(QWidget):
    """
    Widget managing data sources and their views.

    Connects catalog selection state to plot models and manages the UI for
    adding/removing data sources.
    """

    def __init__(self, plot_model, canvas_manager, config_file=None, parent=None):
        super().__init__(parent)
        self.plot_model = plot_model
        self.canvas_controls = CanvasControlWidget(canvas_manager, plot_model, self)
        self.config_file = config_file
        self._catalogs = {}  # label -> catalog

        # Create UI elements
        self.label = QLabel("Data Source")
        self.dropdown = QComboBox(self)
        self.dropdown.currentIndexChanged.connect(self.switch_table)

        # Add source management buttons
        self.new_source = QPushButton("New Data Source")
        self.new_source.clicked.connect(self.add_new_source)
        self.remove_source = QPushButton("Remove Data Source")
        self.remove_source.clicked.connect(self.remove_current_source)
        self.remove_source.setEnabled(False)  # Disabled until source added

        self.stacked_widget = QStackedWidget()

        # Layout
        source_buttons = QHBoxLayout()
        source_buttons.addWidget(self.new_source)
        source_buttons.addWidget(self.remove_source)

        header = QHBoxLayout()
        header.addWidget(self.label)
        header.addWidget(self.dropdown)

        layout = QVBoxLayout()
        layout.addLayout(header)
        layout.addLayout(source_buttons)
        layout.addWidget(self.stacked_widget)
        layout.addWidget(self.canvas_controls)
        self.setLayout(layout)

    def remove_current_source(self):
        """Remove the currently selected data source."""
        current_label = self.dropdown.currentText()
        if current_label in self._catalogs:
            # Get current view and catalog
            current_index = self.dropdown.currentIndex()
            view = self.stacked_widget.widget(current_index)
            catalog = self._catalogs[current_label]

            # Clean up view and catalog
            view.cleanup()  # This will clear selections
            catalog.item_selected.disconnect(self.plot_model.add_run)
            catalog.item_deselected.disconnect(self.plot_model.remove_run)

            # Remove from UI
            self.stacked_widget.removeWidget(view)
            self.dropdown.removeItem(current_index)

            # Remove from storage
            del self._catalogs[current_label]

            # Update button state
            self.remove_source.setEnabled(len(self._catalogs) > 0)

    def add_new_source(self):
        """Add a new data source via picker dialog."""
        picker = DataSourcePicker(config_file=self.config_file, parent=self)
        if picker.exec_():
            sourceView, catalog, label = picker.getSource()
            if catalog is not None and label is not None:
                # Store catalog and connect its signals
                self._catalogs[label] = catalog
                catalog.item_selected.connect(self.plot_model.add_run)
                catalog.item_deselected.connect(self.plot_model.remove_run)

                # Add view to UI
                self.stacked_widget.addWidget(sourceView)
                self.dropdown.addItem(label)
                self.dropdown.setCurrentIndex(self.dropdown.count() - 1)

                # Enable remove button when we have sources
                self.remove_source.setEnabled(True)

    def switch_table(self):
        """Switch the visible source view."""
        self.stacked_widget.setCurrentIndex(self.dropdown.currentIndex())
