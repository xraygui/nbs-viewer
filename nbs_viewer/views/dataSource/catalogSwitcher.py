from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QStackedWidget,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
)
import logging
from .dataSource import SourceDialog, URISourceView, handle_authentication
from ..catalog.base import CatalogTableView
from ..catalog.kafka import KafkaView
from nbs_viewer.models.sources import CatalogLoadError
from nbs_viewer.models.catalog.kafka import KafkaCatalog
from nbs_viewer.views.display.displayControl import DisplayControlWidget


class CatalogSwitcher(QWidget):
    """
    Widget for switching between registered catalogs.

    Reacts to ``CatalogManagerModel.catalog_added`` /
    ``catalog_removed``. Does not register catalogs itself.
    """

    def __init__(
        self,
        app_model,
        display_id,
        parent=None,
    ):
        """
        Initialize the catalog switcher.

        Parameters
        ----------
        app_model : AppModel
            Application model; catalogs and run list are resolved from it.
        display_id : str
            Display id for catalog views and the bound run list.
        parent : QWidget, optional
            Parent widget.
        """
        super().__init__(parent)
        self.app_model = app_model
        self.display_id = display_id
        self.presenter = app_model.display_manager.get_presenter(display_id)
        display_manager = app_model.display_manager
        self.display_controls = DisplayControlWidget(
            display_manager, self.presenter, self
        )
        self.config_file = app_model.config.path
        self._label_to_index = {}

        self.label = QLabel("Catalog")
        self.dropdown = QComboBox(self)
        self.dropdown.currentIndexChanged.connect(self.switch_table)

        self.stacked_widget = QStackedWidget()

        header = QHBoxLayout()
        header.addWidget(self.label)
        header.addWidget(self.dropdown)

        layout = QVBoxLayout()
        layout.addLayout(header)
        layout.addWidget(self.stacked_widget)
        layout.addWidget(self.display_controls)
        self.setLayout(layout)

        catalogs = self.app_model.catalogs
        catalogs.catalog_added.connect(self._on_catalog_added)
        catalogs.catalog_removed.connect(self._on_catalog_removed)

        for label in catalogs.get_catalog_labels():
            catalog = catalogs.get_catalog(label)
            if catalog is not None:
                self._add_catalog_to_ui(catalog, label, select=False)

        if self.config_file:
            self.load_autoload_catalogs()

    def _make_catalog_view(self, catalog):
        """
        Create a catalog table/kafka view for a registered catalog.

        Parameters
        ----------
        catalog : CatalogBase
            Catalog instance.

        Returns
        -------
        QWidget
            Catalog view widget.
        """
        if isinstance(catalog, KafkaCatalog):
            return KafkaView(catalog, self.display_id)
        return CatalogTableView(catalog, self.display_id)

    def _add_catalog_to_ui(self, catalog, label, select=True):
        """
        Add a catalog view to the stacked widget and dropdown.

        Parameters
        ----------
        catalog : CatalogBase
            Registered catalog.
        label : str
            Catalog label.
        select : bool, optional
            Whether to select the new catalog in the dropdown.
        """
        if label in self._label_to_index:
            return
        view = self._make_catalog_view(catalog)
        index = self.stacked_widget.count()
        self.stacked_widget.addWidget(view)
        self.dropdown.addItem(label)
        self._label_to_index[label] = index
        if select:
            self.dropdown.setCurrentIndex(index)

    def _on_catalog_added(self, label, catalog):
        """React to manager catalog registration."""
        select = self.dropdown.count() == 0
        self._add_catalog_to_ui(catalog, label, select=select)
        if not select:
            self.dropdown.setCurrentIndex(self._label_to_index[label])

    def _on_catalog_removed(self, label):
        """React to manager catalog unregistration."""
        index = self._label_to_index.pop(label, None)
        if index is None:
            return
        view = self.stacked_widget.widget(index)
        if view is not None:
            view.cleanup()
            self.stacked_widget.removeWidget(view)
            view.deleteLater()
        self.dropdown.removeItem(index)
        self._label_to_index = {
            self.dropdown.itemText(i): i for i in range(self.dropdown.count())
        }

    def load_autoload_catalogs(self):
        """Load catalogs with autoload=true via CatalogManagerModel."""
        try:
            self.app_model.catalogs.load_autoload_from_config(
                auth_callback=handle_authentication
            )
            if self.dropdown.count() > 0:
                self.dropdown.setCurrentIndex(0)
        except Exception as e:
            logging.getLogger("nbs_viewer.catalog").exception(
                "Error loading autoload catalogs"
            )
            QMessageBox.critical(
                self, "Error Loading Catalogs", f"Failed to load config: {e}"
            )

    def get_catalog_labels(self):
        """Get the labels of all catalogs."""
        return self.app_model.catalogs.get_catalog_labels()

    def remove_current_source(self):
        """Remove the currently selected data source."""
        current_label = self.dropdown.currentText()
        current_index = self.dropdown.currentIndex()
        if current_index < 0 or not current_label:
            return
        self.app_model.catalogs.unregister_catalog(current_label)

    def get_current_catalog(self):
        """Get the currently selected catalog."""
        return self.app_model.catalogs.get_current_catalog()

    def refresh_catalog(self):
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
        try:
            self.app_model.catalogs.load_catalogs_from_file(
                path,
                auth_callback=handle_authentication,
                interactive_auth=True,
            )
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
        """Add a new catalog via the source dialog."""
        picker = SourceDialog(
            self.display_id,
            self.app_model.catalogs,
            parent=self,
        )
        if picker.exec_():
            try:
                picker.load_selected()
            except CatalogLoadError as e:
                QMessageBox.critical(self, "Catalog Load Error", str(e))

    def add_uri_source(self):
        """Add a new URI data source."""
        self.app_model.catalogs.ensure_interactive_palette(
            auth_callback=handle_authentication
        )
        uri_model = self.app_model.catalogs.get_palette_source("uri")
        URIDialog = QDialog(self)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(URIDialog.accept)
        buttons.rejected.connect(URIDialog.reject)
        layout = QVBoxLayout()
        uriSource = URISourceView(uri_model, self.display_id)
        layout.addWidget(uriSource)
        layout.addWidget(buttons)
        URIDialog.setLayout(layout)
        URIDialog.exec_()
        if URIDialog.result() == QDialog.Accepted:
            try:
                uriSource.load()
            except CatalogLoadError as e:
                QMessageBox.critical(self, "Catalog Load Error", str(e))

    def switch_table(self):
        """Switch the visible source view."""
        target_label = self.dropdown.currentText()
        target_index = self.dropdown.currentIndex()

        for i in range(self.stacked_widget.count()):
            if i != target_index:
                view = self.stacked_widget.widget(i)
                view.deselect_all()

        self.stacked_widget.setCurrentIndex(target_index)
        if target_label:
            self.app_model.catalogs.set_current_catalog(target_label)
