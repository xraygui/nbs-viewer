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

        # Automatically load catalogs with autoload=true
        if self.config_file:
            self.load_autoload_catalogs()

    def load_autoload_catalogs(self):
        """
        Automatically load catalogs with autoload=true from the config file.
        """
        try:
            # Import here to avoid circular imports
            from .dataSource import ConfigSourceView

            # Read the config file
            try:
                import tomllib  # Python 3.11+
            except ModuleNotFoundError:
                import tomli as tomllib  # Python <3.11

            with open(self.config_file, "rb") as f:
                config = tomllib.load(f)

            # Load catalogs with autoload=true
            for catalog_config in config.get("catalog", []):
                if catalog_config.get("autoload", False):
                    config_view = ConfigSourceView(catalog_config)
                    sourceView, catalog, label = config_view.get_source()

                    if catalog is not None and label is not None:
                        # Store catalog and connect its signals
                        self._catalogs[label] = catalog
                        catalog.item_selected.connect(self.plot_model.add_run)
                        catalog.item_deselected.connect(self.plot_model.remove_run)

                        # Add view to UI
                        self.stacked_widget.addWidget(sourceView)
                        self.dropdown.addItem(label)

                        # Enable remove button when we have sources
                        self.remove_source.setEnabled(True)
        except Exception as e:
            print(f"Error loading autoload catalogs: {e}")

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
            sourceView, catalog, label = picker.get_source()
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
        # Get the target catalog label
        target_label = self.dropdown.currentText()
        target_index = self.dropdown.currentIndex()

        # Clear selections from all other catalogs
        for i in range(self.stacked_widget.count()):
            if i != target_index:
                view = self.stacked_widget.widget(i)
                view.deselect_all()

        # Switch to the new view
        self.stacked_widget.setCurrentIndex(target_index)
