from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QStackedWidget,
    QFileDialog,
)
from tiled.client import from_uri, from_profile


from .catalog.catalogTree import CatalogPicker
from .catalog.base import CatalogTableView
from .catalog.kafka import KafkaView

from ..models.catalog.source_models import (
    SourceModel,
    URISourceModel,
    ProfileSourceModel,
    KafkaSourceModel,
    ConfigSourceModel,
    ZMQSourceModel,
)
from ..models.catalog.kafka import KafkaCatalog

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # Python <3.11


class SourceView(QWidget):
    """Base class for all source views."""

    def __init__(self, model: SourceModel, parent=None):
        """
        Initialize the source view.

        Parameters
        ----------
        model : SourceModel
            The source model this view is connected to
        parent : QWidget, optional
            The parent widget
        """
        super().__init__(parent)
        self.model = model
        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface components."""
        raise NotImplementedError("Subclasses must implement _setup_ui")

    def update_model(self):
        """Update the model with values from the UI."""
        raise NotImplementedError("Subclasses must implement update_model")

    def get_source(self):
        """
        Get a source from the model and create the appropriate view.

        Returns
        -------
        tuple
            Contains:
            - QWidget : The catalog view widget
            - CatalogBase : The catalog instance
            - str : Label identifying the source
        """
        self.update_model()

        if not self.model.is_configured():
            return None, None, None

        try:
            catalog, label = self.model.get_source()

            # Create the appropriate view based on the catalog type
            if isinstance(catalog, KafkaCatalog):
                catalog_view = KafkaView(catalog)
            else:
                catalog_view = CatalogTableView(catalog)

            return catalog_view, catalog, label
        except Exception as e:
            print(f"Error getting source: {e}")
            return None, None, None


class ConfigSourceView(SourceView):
    """View for configuration-based catalog sources."""

    def __init__(self, catalog_config, parent=None):
        """
        Initialize the configuration source view.

        Parameters
        ----------
        catalog_config : dict
            Configuration dictionary for the catalog
        parent : QWidget, optional
            The parent widget
        """
        model = ConfigSourceModel(catalog_config)
        super().__init__(model, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        # Config source doesn't need UI components as it's pre-configured
        layout = QVBoxLayout()
        label = QLabel(
            f"Configured source: {self.model.catalog_config.get('label', 'Unknown')}"
        )
        layout.addWidget(label)
        self.setLayout(layout)

    def update_model(self):
        """Update the model with values from the UI."""
        # No UI updates needed for config source as it's pre-configured
        pass


class URISourceView(SourceView):
    """View for Tiled URI catalog sources."""

    def __init__(self, parent=None):
        """
        Initialize the URI source view.

        Parameters
        ----------
        parent : QWidget, optional
            The parent widget
        """
        model = URISourceModel()
        super().__init__(model, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        self.uri_label = QLabel("URI", self)
        self.uri_edit = QLineEdit(self)
        self.uri_edit.setText(self.model.uri)

        uri_hbox = QHBoxLayout()
        uri_hbox.addWidget(self.uri_label)
        uri_hbox.addWidget(self.uri_edit)

        self.profile_label = QLabel("Profile", self)
        self.profile_edit = QLineEdit(self)
        self.profile_edit.setText(self.model.profile)

        profile_hbox = QHBoxLayout()
        profile_hbox.addWidget(self.profile_label)
        profile_hbox.addWidget(self.profile_edit)

        layout = QVBoxLayout()
        layout.addLayout(uri_hbox)
        layout.addLayout(profile_hbox)
        self.setLayout(layout)

    def update_model(self):
        """Update the model with values from the UI."""
        self.model.set_uri(self.uri_edit.text())
        self.model.set_profile(self.profile_edit.text())

    def get_source(self):
        """
        Get a source from the model and create the appropriate view.

        This overrides the base implementation to handle nested catalogs
        and model selection.

        Returns
        -------
        tuple
            Contains:
            - QWidget : The catalog view widget
            - CatalogBase : The catalog instance
            - str : Label identifying the source
        """
        self.update_model()

        if not self.model.uri:
            return None, None, None

        try:
            # Get the initial catalog without applying a model
            from tiled.client import from_uri

            catalog = from_uri(self.model.uri)
            label = f"Tiled: {self.model.uri}"

            if self.model.profile:
                catalog = catalog[self.model.profile]
                label += ":" + self.model.profile

            # Check if we need to navigate through a nested catalog
            test_uid = catalog.items_indexer[0][0]
            typical_uid4_len = 36
            if len(test_uid) < typical_uid4_len:
                # Probably not really a UID, and we have a nested catalog
                picker = CatalogPicker(catalog, self)
                if picker.exec_():
                    selected_keys = picker.selected_entry
                    self.model.set_selected_keys(selected_keys)

                    # Update the label and catalog with selected keys
                    for key in selected_keys:
                        catalog = catalog[key]
                        label += ":" + key
                else:
                    return None, None, None  # User cancelled the dialog

            # Now that we have the final catalog, show the model selection dialog
            model_dialog = CatalogModelPicker(self.model.catalog_models, self)
            if model_dialog.exec_():
                self.model.set_selected_model(model_dialog.selected_model_name)

                # Now get the source with the fully configured model
                return super().get_source()
            else:
                return None, None, None  # User cancelled the model selection

        except Exception as e:
            print(f"Error getting URI source: {e}")
            return None, None, None


class ProfileSourceView(SourceView):
    """View for Tiled profile catalog sources."""

    def __init__(self, parent=None):
        """
        Initialize the profile source view.

        Parameters
        ----------
        parent : QWidget, optional
            The parent widget
        """
        model = ProfileSourceModel()
        super().__init__(model, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        self.profile_label = QLabel("Profile", self)
        self.profile_edit = QLineEdit(self)
        self.profile_edit.setText(self.model.profile)

        profile_hbox = QHBoxLayout()
        profile_hbox.addWidget(self.profile_label)
        profile_hbox.addWidget(self.profile_edit)

        layout = QVBoxLayout()
        layout.addLayout(profile_hbox)
        self.setLayout(layout)

    def update_model(self):
        """Update the model with values from the UI."""
        self.model.set_profile(self.profile_edit.text())

    def get_source(self):
        """
        Get a source from the model and create the appropriate view.

        This overrides the base implementation to handle nested catalogs
        and model selection.

        Returns
        -------
        tuple
            Contains:
            - QWidget : The catalog view widget
            - CatalogBase : The catalog instance
            - str : Label identifying the source
        """
        self.update_model()

        if not self.model.profile:
            return None, None, None

        try:
            # Get the initial catalog without applying a model
            from tiled.client import from_profile

            catalog = from_profile(self.model.profile)
            label = f"Profile: {self.model.profile}"

            # Check if we need to navigate through a nested catalog
            test_uid = catalog.items_indexer[0][0]
            typical_uid4_len = 36
            if len(test_uid) < typical_uid4_len:
                # Probably not really a UID, and we have a nested catalog
                picker = CatalogPicker(catalog, self)
                if picker.exec_():
                    selected_keys = picker.selected_entry
                    self.model.set_selected_keys(selected_keys)

                    # Update the label and catalog with selected keys
                    for key in selected_keys:
                        catalog = catalog[key]
                        label += ":" + key
                else:
                    return None, None, None  # User cancelled the dialog

            # Now that we have the final catalog, show the model selection dialog
            model_dialog = CatalogModelPicker(self.model.catalog_models, self)
            if model_dialog.exec_():
                self.model.set_selected_model(model_dialog.selected_model_name)

                # Now get the source with the fully configured model
                return super().get_source()
            else:
                return None, None, None  # User cancelled the model selection

        except Exception as e:
            print(f"Error getting profile source: {e}")
            return None, None, None


class KafkaSourceView(SourceView):
    """View for Kafka catalog sources."""

    def __init__(self, parent=None):
        """
        Initialize the Kafka source view.

        Parameters
        ----------
        parent : QWidget, optional
            The parent widget
        """
        model = KafkaSourceModel()
        super().__init__(model, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        self.config = QPushButton("Pick Kafka Config File")
        self.file_label = QLabel(f"Current file: {self.model.config_file or 'None'}")
        self.bl_label = QLabel("Beamline Acronym")
        self.bl_input = QLineEdit()
        self.bl_input.setText(self.model.beamline_acronym)

        layout = QVBoxLayout()
        bl_layout = QHBoxLayout()
        bl_layout.addWidget(self.bl_label)
        bl_layout.addWidget(self.bl_input)
        layout.addWidget(self.config)
        layout.addWidget(self.file_label)
        layout.addLayout(bl_layout)
        self.setLayout(layout)

        self.config.clicked.connect(self.make_file_picker)

    def make_file_picker(self):
        """Open a file dialog to select the Kafka configuration file."""
        file_dialog = QFileDialog()
        if file_dialog.exec_():
            selected_file = file_dialog.selectedFiles()[0]
            self.model.set_config_file(selected_file)
            self.file_label.setText(f"Current file: {selected_file}")

    def update_model(self):
        """Update the model with values from the UI."""
        self.model.set_beamline_acronym(self.bl_input.text())


class ZMQSourceView(SourceView):
    """View for ZMQ catalog sources."""

    def __init__(self, parent=None):
        """
        Initialize the ZMQ source view.

        Parameters
        ----------
        parent : QWidget, optional
            The parent widget
        """
        model = ZMQSourceModel()
        super().__init__(model, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        layout = QVBoxLayout()
        label = QLabel("ZMQ Source: localhost:5578")
        layout.addWidget(label)
        self.setLayout(layout)

    def update_model(self):
        """Update the model with values from the UI."""
        # No UI updates needed for ZMQ source as it's pre-configured
        pass


class DataSourcePicker(QDialog):
    """Dialog for selecting a data source."""

    def __init__(self, config_file=None, parent=None):
        """
        Initialize the data source picker dialog.

        Parameters
        ----------
        config_file : str, optional
            Path to a configuration file
        parent : QWidget, optional
            The parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Select Data Source")

        self.source_type = QComboBox(self)
        self.layout_switcher = QStackedWidget(self)
        self.source_views = {}

        # Add config sources if a config file is provided
        if config_file:
            with open(config_file, "rb") as f:
                config = tomllib.load(f)
            for catalog in config.get("catalog", []):
                source_name = f"Config: {catalog['label']}"
                config_view = ConfigSourceView(catalog)
                self.source_views[source_name] = config_view

        # Add standard source types
        self.source_views["Tiled URI"] = URISourceView()
        self.source_views["Tiled Profile"] = ProfileSourceView()
        self.source_views["Kafka"] = KafkaSourceView()
        self.source_views["ZMQ"] = ZMQSourceView()

        # Add all views to the UI
        for name, view in self.source_views.items():
            self.source_type.addItem(name)
            self.layout_switcher.addWidget(view)

        self.source_type.currentIndexChanged.connect(self.switch_widget)

        # Add buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # Set up layout
        layout = QVBoxLayout()
        layout.addWidget(self.source_type)
        layout.addWidget(self.layout_switcher)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def switch_widget(self):
        """Switch the current widget based on the selected source type."""
        self.layout_switcher.setCurrentIndex(self.source_type.currentIndex())

    def get_source(self):
        """
        Get a source from the currently selected view.

        Returns
        -------
        tuple
            Contains:
            - QWidget : The catalog view widget
            - CatalogBase : The catalog instance
            - str : Label identifying the source
        """
        return self.layout_switcher.currentWidget().get_source()


class CatalogModelPicker(QDialog):
    """Dialog for selecting a catalog model."""

    def __init__(self, catalog_models, parent=None):
        """
        Initialize the catalog model picker dialog.

        Parameters
        ----------
        catalog_models : dict
            Dictionary of available catalog models
        parent : QWidget, optional
            The parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Select Catalog Model")
        self.catalog_models = catalog_models
        self.selected_model = None
        self.selected_model_name = None

        layout = QVBoxLayout(self)

        self.model_combo = QComboBox(self)
        self.model_combo.addItems(self.catalog_models.keys())
        layout.addWidget(QLabel("Select a catalog model:"))
        layout.addWidget(self.model_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def accept(self):
        """Handle dialog acceptance."""
        self.selected_model_name = self.model_combo.currentText()
        self.selected_model = self.catalog_models[self.selected_model_name]
        super().accept()
