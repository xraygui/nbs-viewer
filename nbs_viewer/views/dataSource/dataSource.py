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
from tiled.profiles import list_profiles

from ..catalog.catalogTree import CatalogPicker

from ...models.sources import (
    SourceModel,
    CatalogLoadError,
)
from ...models.sources.configSource import ConfigSourceModel
from ...models.sources.uriSource import URISourceModel
from ...models.sources.profileSource import ProfileSourceModel
from ...models.sources.kafkaSource import KafkaSourceModel
from ...models.sources.zmqSource import ZMQSourceModel
from ...models.sources.testSource import TestSourceModel


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
        display_id : str
            Display identifier (unused for load; kept for callers)
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

    def load(self, **kwargs):
        """
        Configure the source from the UI and call ``model.load``.

        Parameters
        ----------
        **kwargs
            Forwarded to ``model.load``.

        Returns
        -------
        tuple
            ``(catalog, label)`` from ``model.load``.

        Raises
        ------
        CatalogLoadError
            If the source is not configured or load fails.
        """
        self.update_model()
        if not self.model.is_configured():
            raise CatalogLoadError("Source is not fully configured")
        return self.model.load(**kwargs)


class ConfigSourceView(SourceView):
    """View for configuration-based catalog sources."""

    def __init__(self, model, display_id, parent=None):
        """
        Initialize the configuration source view.

        Parameters
        ----------
        model : ConfigSourceModel
            Configured source model from CatalogManagerModel.create_from_config
        display_id : str
            Display identifier for the catalog view
        parent : QWidget, optional
            The parent widget
        """
        super().__init__(model, display_id, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        layout = QVBoxLayout()

        label = QLabel(
            f"Configured source: "
            f"{self.model.catalog_config.get('label', 'Unknown')}"
        )
        layout.addWidget(label)
        model = self.model.source_model
        if hasattr(model, "use_cached_tokens"):
            self.cached_credentials_cb = QCheckBox("Use cached credentials")
            self.cached_credentials_cb.setChecked(model.use_cached_tokens)
            self.cached_credentials_cb.toggled.connect(
                self._on_cached_credentials_toggled
            )
            layout.addWidget(self.cached_credentials_cb)

            note_label = QLabel(
                "Uncheck to clear cached credentials and enter new ones"
            )
            note_label.setStyleSheet("color: gray; font-size: 10px;")
            layout.addWidget(note_label)

        self.setLayout(layout)

    def update_model(self):
        """Update the model with values from the UI."""
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


class URISourceView(SourceView):
    """View for Tiled URI catalog sources."""

    def __init__(self, model, display_id, parent=None):
        """
        Initialize the URI source view.

        Parameters
        ----------
        model : URISourceModel
            Source model from CatalogManagerModel.create_uri_source
        display_id : str
            Display identifier for the catalog view
        parent : QWidget, optional
            The parent widget
        """
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

    def load(self, **kwargs):
        """
        Interactively connect, navigate, select model, then emit load.

        Returns
        -------
        tuple
            ``(catalog, label)``.

        Raises
        ------
        CatalogLoadError
            If configuration or load fails, or the user cancels.
        """
        self.update_model()

        if not self.model.uri:
            raise CatalogLoadError("URI is required")

        try:
            self.model.use_cached_tokens = self.cached_tokens_checkbox.isChecked()
            context, node_path_parts = self.model.connect_and_authenticate(**kwargs)
            client, label = self.model.navigate_catalog_tree(context, node_path_parts)

            try:
                test_uid = client.items_indexer[0][0]
                typical_uid4_len = 36
                if len(test_uid) < typical_uid4_len:
                    picker = CatalogPicker(client, self)
                    if picker.exec_():
                        selected_keys = picker.selected_entry
                        self.model.set_selected_keys(selected_keys)
                        for key in selected_keys:
                            client = client[key]
                            label += ":" + key
                    else:
                        raise CatalogLoadError("Catalog navigation cancelled")
            except IndexError:
                pass

            model_dialog = CatalogModelPicker(self.model.catalog_models, self)
            if not model_dialog.exec_():
                raise CatalogLoadError("Catalog model selection cancelled")

            self.model.set_selected_model(model_dialog.selected_model_name)
            catalog = self.model.select_catalog_model(client)
            self.model.emit_catalog_loaded(catalog, label)
            return catalog, label
        except CatalogLoadError:
            raise
        except Exception as e:
            raise CatalogLoadError(f"Error getting URI source: {e}") from e


class ProfileSourceView(SourceView):
    """View for Tiled profile catalog sources."""

    def __init__(self, model, profiles, display_id, parent=None):
        """
        Initialize the profile source view.

        Parameters
        ----------
        model : ProfileSourceModel
            Source model from CatalogManagerModel.create_profile_source
        profiles : dict
            Mapping of profile name to source path
        display_id : str
            Display identifier for the catalog view
        parent : QWidget, optional
            The parent widget
        """
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

        self.cached_tokens_label = QLabel("Use Cached Credentials", self)
        self.cached_tokens_checkbox = QCheckBox(self)
        self.cached_tokens_checkbox.setToolTip(
            "If checked, already-cached credentials will be used if available."
        )
        self.cached_tokens_checkbox.setChecked(self.model.use_cached_tokens)

        cached_tokens_hbox = QHBoxLayout()
        cached_tokens_hbox.addWidget(self.cached_tokens_label)
        cached_tokens_hbox.addWidget(self.cached_tokens_checkbox)

        self.profile_edit.currentTextChanged.connect(self.update_source_path)
        self.update_source_path()

        source_hbox.addWidget(self.source_label)
        source_hbox.addWidget(self.source_path)

        layout = QVBoxLayout()
        layout.addLayout(profile_hbox)
        layout.addLayout(source_hbox)
        layout.addLayout(cached_tokens_hbox)
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
        self.model.use_cached_tokens = self.cached_tokens_checkbox.isChecked()

    def load(self, **kwargs):
        """
        Interactively connect, navigate, select model, then emit load.

        Returns
        -------
        tuple
            ``(catalog, label)``.

        Raises
        ------
        CatalogLoadError
            If configuration or load fails, or the user cancels.
        """
        self.update_model()

        if not self.model.profile:
            raise CatalogLoadError("Profile is required")

        try:
            context, node_path_parts = self.model.connect_and_authenticate(**kwargs)
            client, label = self.model.navigate_catalog_tree(
                context, node_path_parts
            )

            try:
                test_uid = client.items_indexer[0][0]
                typical_uid4_len = 36
                if len(test_uid) < typical_uid4_len:
                    picker = CatalogPicker(client, self)
                    if picker.exec_():
                        selected_keys = picker.selected_entry
                        self.model.set_selected_keys(selected_keys)
                        for key in selected_keys:
                            client = client[key]
                            label += ":" + key
                    else:
                        raise CatalogLoadError("Catalog navigation cancelled")
            except IndexError:
                pass

            model_dialog = CatalogModelPicker(self.model.catalog_models, self)
            if not model_dialog.exec_():
                raise CatalogLoadError("Catalog model selection cancelled")

            self.model.set_selected_model(model_dialog.selected_model_name)
            catalog = self.model.select_catalog_model(client)
            self.model.emit_catalog_loaded(catalog, label)
            return catalog, label
        except CatalogLoadError:
            raise
        except Exception as e:
            raise CatalogLoadError(f"Error getting profile source: {e}") from e


class KafkaSourceView(SourceView):
    """View for Kafka catalog sources."""

    def __init__(self, model, display_id, parent=None):
        """
        Initialize the Kafka source view.

        Parameters
        ----------
        model : KafkaSourceModel
            Source model from CatalogManagerModel.create_kafka_source
        display_id : str
            Display identifier for the catalog view
        parent : QWidget, optional
            The parent widget
        """
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

    def __init__(self, model, display_id, parent=None):
        """
        Initialize the ZMQ source view.

        Parameters
        ----------
        model : ZMQSourceModel
            Source model from CatalogManagerModel.create_zmq_source
        display_id : str
            Display identifier for the catalog view
        parent : QWidget, optional
            The parent widget
        """
        super().__init__(model, display_id, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        layout = QVBoxLayout()
        label = QLabel("ZMQ Source: localhost:5578")
        layout.addWidget(label)
        self.setLayout(layout)

    def update_model(self):
        """Update the model with values from the UI."""
        pass


class TestSourceView(SourceView):
    """View for test catalog sources."""

    def __init__(self, model, display_id, parent=None):
        """
        Initialize the test source view.

        Parameters
        ----------
        model : TestSourceModel
            Source model from CatalogManagerModel.create_test_source
        display_id : str
            Display identifier for the catalog view
        parent : QWidget, optional
            The parent widget
        """
        super().__init__(model, display_id, parent)

    def _setup_ui(self):
        """Set up the user interface components."""
        layout = QVBoxLayout()
        label = QLabel("Test Catalog")
        layout.addWidget(label)
        self.setLayout(layout)

    def update_model(self):
        """Update the model with values from the UI."""
        pass


class SourceDialog(QDialog):
    """Dialog for configuring palette sources and triggering ``load``."""

    def __init__(self, display_id, catalog_manager, parent=None):
        """
        Initialize the source dialog.

        Parameters
        ----------
        display_id : str
            Display identifier for catalog views.
        catalog_manager : CatalogManagerModel
            Owns the source palette and registers catalogs.
        parent : QWidget, optional
            The parent widget
        """
        super().__init__(parent)
        self.setWindowTitle("Select Data Source")
        self.catalog_manager = catalog_manager
        self.display_id = display_id

        catalog_manager.ensure_interactive_palette(
            auth_callback=handle_authentication
        )

        self.source_type = QComboBox(self)
        self.layout_switcher = QStackedWidget(self)
        self.source_views = {}

        profiles = list_profiles()
        for key, source in catalog_manager.iter_palette():
            view = self._make_view(key, source, profiles)
            if view is None:
                continue
            display_name = self._display_name(key, source)
            self.source_views[display_name] = view
            self.source_type.addItem(display_name)
            self.layout_switcher.addWidget(view)

        self.source_type.currentIndexChanged.connect(self.switch_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.source_type)
        layout.addWidget(self.layout_switcher)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _display_name(self, key: str, source) -> str:
        """
        Human-readable combo label for a palette entry.

        Parameters
        ----------
        key : str
            Palette key.
        source : SourceModel
            Palette source.

        Returns
        -------
        str
            Display name for the combo box.
        """
        if key.startswith("config:"):
            return f"Config: {key[len('config:'):]}"
        names = {
            "uri": "Tiled URI",
            "profile": "Tiled Profile",
            "kafka": "Kafka",
            "zmq": "ZMQ",
            "test": "Test",
        }
        return names.get(key, source.get_display_label())

    def _make_view(self, key: str, source, profiles):
        """
        Build a SourceView for a palette source.

        Parameters
        ----------
        key : str
            Palette key.
        source : SourceModel
            Palette source.
        profiles : dict
            Tiled profiles for ProfileSourceView.

        Returns
        -------
        SourceView or None
            View widget, or None to skip (e.g. profile with no profiles).
        """
        if isinstance(source, ConfigSourceModel) or key.startswith("config:"):
            return ConfigSourceView(source, self.display_id)
        if isinstance(source, ProfileSourceModel) or key == "profile":
            if not profiles:
                return None
            return ProfileSourceView(source, profiles, self.display_id)
        if isinstance(source, URISourceModel) or key == "uri":
            return URISourceView(source, self.display_id)
        if isinstance(source, KafkaSourceModel) or key == "kafka":
            return KafkaSourceView(source, self.display_id)
        if isinstance(source, ZMQSourceModel) or key == "zmq":
            return ZMQSourceView(source, self.display_id)
        if isinstance(source, TestSourceModel) or key == "test":
            return TestSourceView(source, self.display_id)
        return None

    def switch_widget(self):
        """Switch the current widget based on the selected source type."""
        self.layout_switcher.setCurrentIndex(self.source_type.currentIndex())

    def load_selected(self, **kwargs):
        """
        Load the catalog from the currently selected source view.

        Registration happens via ``SourceModel.catalog_loaded`` on the
        manager palette. Does not construct catalog table widgets.

        Parameters
        ----------
        **kwargs
            Forwarded to the view ``load`` method.

        Returns
        -------
        tuple
            ``(catalog, label)`` from the view load.
        """
        return self.layout_switcher.currentWidget().load(**kwargs)


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
