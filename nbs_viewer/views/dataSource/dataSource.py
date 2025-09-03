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
    QCheckBox,
)
from tiled.client import from_uri, from_profile

from ..catalog.catalogTree import CatalogPicker
from ..catalog.base import CatalogTableView
from ..catalog.kafka import KafkaView

from ...models.catalog.source_models import (
    SourceModel,
    URISourceModel,
    ProfileSourceModel,
    KafkaSourceModel,
    ConfigSourceModel,
    ZMQSourceModel,
)
from ...models.catalog.kafka import KafkaCatalog
from tiled.profiles import list_profiles

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # Python <3.11


def handle_authentication(context, catalog_model=None, parent=None):
    """
    Handle interactive authentication via GUI dialog.

    Parameters
    ----------
    context : Context
        The Tiled context that needs authentication
    catalog_model : SourceModel, optional
        The catalog source model that needs authentication
    parent : QWidget, optional
        The parent widget

    Returns
    -------
    dict or None
        Authentication tokens if successful, None if cancelled
    """
    from .tiledAuth import TiledAuthDialog

    auth_dialog = TiledAuthDialog(context, catalog_model, parent)
    if auth_dialog.exec_() == QDialog.Accepted:
        return auth_dialog
    return None


class SourceView(QWidget):
    """Base class for all source views."""

    def __init__(self, model: SourceModel, display_id, parent=None):
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
        self.display_id = display_id
        self._setup_ui()

    def _setup_ui(self):
        """Set up the user interface components."""
        raise NotImplementedError("Subclasses must implement _setup_ui")

    def update_model(self):
        """Update the model with values from the UI."""
        raise NotImplementedError("Subclasses must implement update_model")

    def get_source(self, **kwargs):
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
                catalog_view = KafkaView(catalog, self.display_id)
            else:
                catalog_view = CatalogTableView(catalog, self.display_id)

            return catalog_view, catalog, label
        except Exception as e:
            print(f"Error getting source: {e}")
            return None, None, None


class ConfigSourceView(SourceView):
    """View for configuration-based catalog sources."""

    def __init__(self, catalog_config, display_id, parent=None):
        """
        Initialize the configuration source view.

        Parameters
        ----------
        catalog_config : dict
            Configuration dictionary for the catalog
        parent : QWidget, optional
            The parent widget
        """
        model = ConfigSourceModel(catalog_config, auth_callback=handle_authentication)
        super().__init__(model, display_id, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        layout = QVBoxLayout()

        # Show the configured source label
        label = QLabel(
            f"Configured source: "
            f"{self.model.catalog_config.get('label', 'Unknown')}"
        )
        layout.addWidget(label)
        model = self.model.source_model
        # Add cached credentials checkbox for URI sources
        if hasattr(model, "use_cached_tokens"):
            self.cached_credentials_cb = QCheckBox("Use cached credentials")
            self.cached_credentials_cb.setChecked(model.use_cached_tokens)
            self.cached_credentials_cb.toggled.connect(
                self._on_cached_credentials_toggled
            )
            layout.addWidget(self.cached_credentials_cb)

            # Add note about clearing credentials
            note_label = QLabel(
                "Uncheck to clear cached credentials and enter new ones"
            )
            note_label.setStyleSheet("color: gray; font-size: 10px;")
            layout.addWidget(note_label)

        self.setLayout(layout)

    def update_model(self):
        """Update the model with values from the UI."""
        # Update cached credentials setting if available
        if hasattr(self, "cached_credentials_cb") and hasattr(
            self.model.source_model, "use_cached_tokens"
        ):
            self.model.source_model.use_cached_tokens = (
                self.cached_credentials_cb.isChecked()
            )

    def _on_cached_credentials_toggled(self, checked):
        """Handle cached credentials checkbox toggle."""
        if hasattr(self.model.source_model, "use_cached_tokens"):
            self.model.source_model.use_cached_tokens = checked
            print(f"Cached credentials {'enabled' if checked else 'disabled'}")


class URISourceView(SourceView):
    """View for Tiled URI catalog sources."""

    def __init__(self, display_id, parent=None):
        """
        Initialize the URI source view.

        Parameters
        ----------
        parent : QWidget, optional
            The parent widget
        """
        # Create the model with an authentication callback
        model = URISourceModel(auth_callback=handle_authentication)
        super().__init__(model, display_id, parent)

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

        self.cached_tokens_label = QLabel("Use Cached Credentials", self)
        self.cached_tokens_checkbox = QCheckBox(self)
        self.cached_tokens_checkbox.setToolTip(
            "If checked, already-cached credentials will be used if available."
        )
        self.cached_tokens_checkbox.setChecked(self.model.use_cached_tokens)

        cached_tokens_hbox = QHBoxLayout()
        cached_tokens_hbox.addWidget(self.cached_tokens_label)
        cached_tokens_hbox.addWidget(self.cached_tokens_checkbox)

        layout = QVBoxLayout()
        layout.addLayout(uri_hbox)
        layout.addLayout(profile_hbox)
        layout.addLayout(cached_tokens_hbox)
        self.setLayout(layout)

    def update_model(self):
        """Update the model with values from the UI."""
        self.model.set_uri(self.uri_edit.text())
        self.model.set_profile(self.profile_edit.text())

    def get_source(self, **kwargs):
        """
        Get a source from the model and create the appropriate view.

        This uses the three-stage approach:
        1. Connect and authenticate
        2. Navigate catalog tree (if needed)
        3. Select catalog model

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
            # Stage 1: Connect and authenticate
            self.model.use_cached_tokens = self.cached_tokens_checkbox.isChecked()
            context, node_path_parts = self.model.connect_and_authenticate(**kwargs)

            # Stage 2: Navigate catalog tree
            client, label = self.model.navigate_catalog_tree(context, node_path_parts)

            # Check if we need to navigate through a nested catalog
            try:
                test_uid = client.items_indexer[0][0]
                typical_uid4_len = 36
                if len(test_uid) < typical_uid4_len:
                    # Probably not really a UID, and we have a nested catalog
                    picker = CatalogPicker(client, self)
                    if picker.exec_():
                        selected_keys = picker.selected_entry
                        self.model.set_selected_keys(selected_keys)

                        # Update the label and catalog with selected keys
                        for key in selected_keys:
                            client = client[key]
                            label += ":" + key
                    else:
                        return None, None, None  # User cancelled the dialog
            except IndexError:
                # We have a blank catalog
                pass

            # Stage 3: Select catalog model
            model_dialog = CatalogModelPicker(self.model.catalog_models, self)
            if model_dialog.exec_():
                self.model.set_selected_model(model_dialog.selected_model_name)

                # Apply the selected model
                catalog = self.model.select_catalog_model(client)

                # Create the appropriate view
                if isinstance(catalog, KafkaCatalog):
                    catalog_view = KafkaView(catalog, self.display_id)
                else:
                    catalog_view = CatalogTableView(catalog, self.display_id)

                return catalog_view, catalog, label
            else:
                return None, None, None  # User cancelled the model selection

        except Exception as e:
            print(f"Error getting URI source: {e}")
            return None, None, None


class ProfileSourceView(SourceView):
    """View for Tiled profile catalog sources."""

    def __init__(self, profiles, display_id, parent=None):
        """
        Initialize the profile source view.

        Parameters
        ----------
        parent : QWidget, optional
            The parent widget
        """
        model = ProfileSourceModel()
        self.profiles = profiles

        super().__init__(model, display_id, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        self.profile_label = QLabel("Profile", self)
        self.profile_edit = QComboBox(self)
        self.profile_edit.addItems(self.profiles.keys())

        profile_hbox = QHBoxLayout()
        profile_hbox.addWidget(self.profile_label)
        profile_hbox.addWidget(self.profile_edit)

        source_hbox = QHBoxLayout()
        self.source_label = QLabel("Profile location", self)
        self.source_path = QLabel("")

        self.profile_edit.currentTextChanged.connect(self.update_source_path)
        self.update_source_path()

        source_hbox.addWidget(self.source_label)
        source_hbox.addWidget(self.source_path)

        layout = QVBoxLayout()
        layout.addLayout(profile_hbox)
        layout.addLayout(source_hbox)
        self.setLayout(layout)

    def update_source_path(self):
        """Update the source path label with the current profile."""
        try:
            self.source_path.setText(
                str(self.profiles[self.profile_edit.currentText()])
            )
        except KeyError:
            self.source_path.setText("")

    def update_model(self):
        """Update the model with values from the UI."""
        self.model.set_profile(self.profile_edit.currentText())

    def get_source(self, **kwargs):
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
                return super().get_source(**kwargs)
            else:
                return None, None, None  # User cancelled the model selection

        except Exception as e:
            print(f"Error getting profile source: {e}")
            return None, None, None


class KafkaSourceView(SourceView):
    """View for Kafka catalog sources."""

    def __init__(self, display_id, parent=None):
        """
        Initialize the Kafka source view.

        Parameters
        ----------
        parent : QWidget, optional
            The parent widget
        """
        model = KafkaSourceModel()
        super().__init__(model, display_id, parent)

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

    def __init__(self, display_id, parent=None):
        """
        Initialize the ZMQ source view.

        Parameters
        ----------
        parent : QWidget, optional
            The parent widget
        """
        model = ZMQSourceModel()
        super().__init__(model, display_id, parent)

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

    def __init__(self, display_id, config_file=None, parent=None):
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
                config_view = ConfigSourceView(catalog, display_id)
                self.source_views[source_name] = config_view

        # Add standard source types
        self.source_views["Tiled URI"] = URISourceView(display_id)
        profiles = list_profiles()
        if profiles:
            self.source_views["Tiled Profile"] = ProfileSourceView(profiles, display_id)
        self.source_views["Kafka"] = KafkaSourceView(display_id)
        self.source_views["ZMQ"] = ZMQSourceView(display_id)

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
