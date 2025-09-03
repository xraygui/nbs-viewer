from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
)
import logging
from .dataSource import DataSourcePicker, URISourceView
from nbs_viewer.models.catalog.source_models import CatalogLoadError
from nbs_viewer.views.display.displayControl import DisplayControlWidget
from nbs_viewer.utils import print_debug

"""
This is now the primary thing to refactor -- very poorly named, this is really
the central widget that controls the data sources and the plot list. It is what
controls adding and removing runs from the temporary plot.

We probably need to combine this with plotManager, or at least make it a lot
more obvious what is going on. The connections to the plotControl also need to
be more obvious. Possibly we need to separate out a model from the view.
"""


class DataSourceSwitcher(QWidget):
    """
    Widget managing data sources and their views.

    Connects catalog selection state to plot models and manages the UI for
    adding/removing data sources.
    """

    def __init__(
        self,
        app_model,
        run_list_model,
        display_id,
        parent=None,
    ):
        super().__init__(parent)
        self.app_model = app_model
        self.run_list_model = run_list_model
        self.display_id = display_id
        display_manager = app_model.display_manager
        self.display_controls = DisplayControlWidget(
            display_manager, run_list_model, self
        )
        self.config_file = app_model.config.path
        self._catalogs = {}  # label -> catalog

        # Create UI elements
        self.label = QLabel("Data Source")
        self.dropdown = QComboBox(self)
        self.dropdown.currentIndexChanged.connect(self.switch_table)

        # # Add source management buttons
        # self.new_source = QPushButton("New Data Source")
        # self.new_source.clicked.connect(self.add_new_source)
        # self.remove_source = QPushButton("Remove Data Source")
        # self.remove_source.clicked.connect(self.remove_current_source)
        # self.remove_source.setEnabled(False)  # Disabled until source added

        self.stacked_widget = QStackedWidget()

        # Layout
        # source_buttons = QHBoxLayout()
        # source_buttons.addWidget(self.new_source)
        # source_buttons.addWidget(self.remove_source)

        header = QHBoxLayout()
        header.addWidget(self.label)
        header.addWidget(self.dropdown)

        layout = QVBoxLayout()
        layout.addLayout(header)
        # layout.addLayout(source_buttons)
        layout.addWidget(self.stacked_widget)
        layout.addWidget(self.display_controls)
        self.setLayout(layout)

        # Automatically load catalogs with autoload=true
        if self.config_file:
            self.load_autoload_catalogs()

        # Catalogs now manage their own async state; nothing to wire here

    def load_autoload_catalogs(self):
        """
        Automatically load catalogs with autoload=true from the config file.

        """
        from .dataSource import ConfigSourceView

        try:
            import tomllib  # Python 3.11+
        except ModuleNotFoundError:
            import tomli as tomllib  # Python <3.11

        with open(self.config_file, "rb") as f:
            config = tomllib.load(f)
        try:
            # Import here to avoid circular imports

            # Read the config file
            # Load catalogs with autoload=true
            for catalog_config in config.get("catalog", []):
                if catalog_config.get("autoload", False):
                    config_view = ConfigSourceView(catalog_config, self.display_id)
                    sourceView, catalog, label = config_view.get_source(
                        interactive_auth=False
                    )

                    if catalog is not None and label is not None:
                        # Store catalog locally for view management
                        self._catalogs[label] = catalog
                        # Register catalog with app-level model (routes selections)
                        if self.app_model is not None:
                            self.app_model.catalogs.register_catalog(label, catalog)

                        # Add view to UI
                        self.stacked_widget.addWidget(sourceView)
                        self.dropdown.addItem(label)

                        # Enable remove button when we have sources
                        # self.remove_source.setEnabled(True)
        except Exception as e:
            logging.getLogger("nbs_viewer.catalog").exception(
                "Error loading autoload catalogs"
            )
            QMessageBox.critical(
                self, "Error Loading Catalogs", f"Failed to load config: {e}"
            )

    def get_catalog_labels(self):
        """Get the labels of all catalogs."""
        if self.app_model is not None:
            return self.app_model.catalogs.get_catalog_labels()
        return list(self._catalogs.keys())

    def remove_current_source(self):
        """Remove the currently selected data source."""
        current_label = self.dropdown.currentText()
        if current_label in self._catalogs:
            # Get current view and catalog
            current_index = self.dropdown.currentIndex()
            view = self.stacked_widget.widget(current_index)

            # Clean up view and catalog
            view.cleanup()  # This will clear selections
            if self.app_model is not None:
                self.app_model.catalogs.unregister_catalog(current_label)

            # Remove from UI
            self.stacked_widget.removeWidget(view)
            self.dropdown.removeItem(current_index)

            # Remove from storage
            del self._catalogs[current_label]

            # Update button state
            # self.remove_source.setEnabled(len(self._catalogs) > 0)

    def get_current_catalog(self):
        """Get the currently selected catalog."""
        if self.app_model is not None:
            return self.app_model.catalogs.get_current_catalog()
        current_label = self.dropdown.currentText()
        return self._catalogs.get(current_label)

    def refresh_catalog(self):
        if self.app_model is not None:
            self.app_model.catalogs.refresh_current()
            return
        catalogView = self.stacked_widget.currentWidget()
        if catalogView is not None:
            catalogView.refresh_filters()

    def deselect_all(self):
        """Deselect all items in the current catalog view."""
        view = self.stacked_widget.currentWidget()
        if view is not None:
            view.deselect_all()

    def get_selected_runs(self):
        """Return selected runs from the current catalog view."""
        view = self.stacked_widget.currentWidget()
        if view is not None and hasattr(view, "get_selected_runs"):
            return view.get_selected_runs()
        return []

    def load_catalog_config(self, path: str):
        """Load a catalog configuration TOML file at runtime."""
        from .dataSource import ConfigSourceView

        try:
            import tomllib  # Python 3.11+
        except ModuleNotFoundError:
            import tomli as tomllib  # Python <3.11

        try:
            # Import here to avoid circular imports
            with open(path, "rb") as f:
                config = tomllib.load(f)

            # Load all catalogs in the file (not only autoload)
            for catalog_config in config.get("catalog", []):
                config_view = ConfigSourceView(catalog_config, self.display_id)
                sourceView, catalog, label = config_view.get_source()
                if catalog is None or label is None:
                    continue
                # Store catalog locally and register with the app model
                self._catalogs[label] = catalog
                if self.app_model is not None:
                    self.app_model.catalogs.register_catalog(label, catalog)
                # Add to UI
                self.stacked_widget.addWidget(sourceView)
                self.dropdown.addItem(label)
                # self.remove_source.setEnabled(True)
        except Exception as e:
            logging.getLogger("nbs_viewer.catalog").exception(
                "Error loading catalog config '%s'", path
            )
            QMessageBox.critical(
                self,
                "Error Loading Catalogs",
                f"Failed to load config '{path}': {e}",
            )

    def switch_to_label(self, label: str):
        """Switch to a catalog view by its label (used by menu)."""
        for i in range(self.dropdown.count()):
            if self.dropdown.itemText(i) == label:
                self.dropdown.setCurrentIndex(i)
                return

    def add_new_source(self):
        """Add a new data source via picker dialog."""
        picker = DataSourcePicker(
            self.display_id, config_file=self.config_file, parent=self
        )
        if picker.exec_():
            try:
                sourceView, catalog, label = picker.get_source()
            except CatalogLoadError as e:
                QMessageBox.critical(self, "Catalog Load Error", str(e))
                return
            if catalog is not None and label is not None:
                # Store catalog locally for view management
                self._catalogs[label] = catalog
                # Register with app model
                if self.app_model is not None:
                    self.app_model.catalogs.register_catalog(label, catalog)

                # Add view to UI
                self.stacked_widget.addWidget(sourceView)
                self.dropdown.addItem(label)
                self.dropdown.setCurrentIndex(self.dropdown.count() - 1)

                # Enable remove button when we have sources
                # self.remove_source.setEnabled(True)

    def add_uri_source(self):
        """Add a new URI data source."""
        URIDialog = QDialog()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(URIDialog.accept)
        buttons.rejected.connect(URIDialog.reject)
        layout = QVBoxLayout()
        uriSource = URISourceView(self.display_id)
        layout.addWidget(uriSource)
        layout.addWidget(buttons)
        URIDialog.setLayout(layout)
        URIDialog.exec_()
        if URIDialog.result() == QDialog.Accepted:
            sourceView, catalog, label = uriSource.get_source()
            if catalog is not None and label is not None:
                # Store catalog locally for view management
                self._catalogs[label] = catalog
                # Register with app model
                if self.app_model is not None:
                    self.app_model.catalogs.register_catalog(label, catalog)
                self.stacked_widget.addWidget(sourceView)
                self.dropdown.addItem(label)
                self.dropdown.setCurrentIndex(self.dropdown.count() - 1)

            # Enable remove button when we have sources
            # self.remove_source.setEnabled(True)

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
        # Inform model about current catalog
        if self.app_model is not None and target_label:
            self.app_model.catalogs.set_current_catalog(target_label)
