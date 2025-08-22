from __future__ import annotations
from typing import Dict, List, Optional
from qtpy.QtCore import QObject, Signal

from .plot.displayManager import DisplayManager
from .plot.displayRegistry import DisplayRegistry

# Global reference to the top-level AppModel instance


class ConfigModel(QObject):
    """Application configuration and preferences."""

    config_changed = Signal(dict)

    def __init__(self, config_path: Optional[str] = None):
        super().__init__()
        self._path = config_path
        self._data: Dict = {}
        self._load_config()

    @property
    def path(self) -> Optional[str]:
        return self._path

    def _load_config(self) -> None:
        if not self._path:
            return
        try:
            try:
                import tomllib  # Python 3.11+
            except ModuleNotFoundError:  # pragma: no cover - older Python
                import tomli as tomllib  # type: ignore

            with open(self._path, "rb") as f:
                self._data = tomllib.load(f)
            self.config_changed.emit(self._data)
        except Exception as exc:  # pragma: no cover - defensive
            import logging

            msg = f"Failed to load config '{self._path}': {exc}"
            logging.getLogger("nbs_viewer.config").exception(msg)

    def get(self, path: str, default=None):
        """Get a nested key with dotted path.

        Example: 'plot_widgets.default_widget'
        """
        parts = path.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


class CatalogManagerModel(QObject):
    """Holds registered catalogs and forwards selection events as signals.

    This model is UI-agnostic: it does not create or own view widgets. Views
    can register catalogs they created (with a label) and this model will
    expose signals and state for the rest of the app.
    """

    catalogs_changed = Signal(list)  # list of labels
    current_catalog_changed = Signal(str)
    run_selected = Signal(object)  # CatalogRun
    run_deselected = Signal(object)  # CatalogRun
    error = Signal(str)

    def __init__(self, config: ConfigModel):
        super().__init__()
        self._config = config
        self._catalogs: Dict[str, object] = {}
        self._current_label: Optional[str] = None

    # Registration ---------------------------------------------------------
    def register_catalog(self, label: str, catalog: object) -> None:
        if label in self._catalogs:
            self.unregister_catalog(label)
        self._catalogs[label] = catalog
        # Forward catalog item selection events to app-level signals
        try:
            catalog.item_selected.connect(self._on_item_selected)
            catalog.item_deselected.connect(self._on_item_deselected)
        except Exception as exc:  # pragma: no cover - defensive
            import logging

            msg = f"Catalog '{label}' missing selection signals: {exc}"
            logging.getLogger("nbs_viewer.catalog").exception(msg)
            self.error.emit(msg)
        if self._current_label is None:
            self._current_label = label
            self.current_catalog_changed.emit(label)
        self.catalogs_changed.emit(self.get_catalog_labels())

    def unregister_catalog(self, label: str) -> None:
        if label not in self._catalogs:
            return
        cat = self._catalogs.pop(label)
        try:
            cat.item_selected.disconnect(self._on_item_selected)
            cat.item_deselected.disconnect(self._on_item_deselected)
        except Exception:
            pass
        if self._current_label == label:
            self._current_label = next(iter(self._catalogs), None)
            if self._current_label is not None:
                self.current_catalog_changed.emit(self._current_label)
        self.catalogs_changed.emit(self.get_catalog_labels())

    # Queries --------------------------------------------------------------
    def get_catalog_labels(self) -> List[str]:
        return list(self._catalogs.keys())

    def get_current_catalog(self) -> Optional[object]:
        if self._current_label is None:
            return None
        return self._catalogs.get(self._current_label)

    def set_current_catalog(self, label: str) -> None:
        if label in self._catalogs and self._current_label != label:
            self._current_label = label
            self.current_catalog_changed.emit(label)

    """     # Actions --------------------------------------------------------------
    def refresh_current(self) -> None:
        cat = self.get_current_catalog()
        if cat is None:
            return
        try:
            cat.refresh_filters()
        except Exception as exc:  # pragma: no cover - defensive
            import logging

            msg = f"Failed to refresh '{self._current_label}': {exc}"
            logging.getLogger("nbs_viewer.catalog").exception(msg)
            self.error.emit(msg)
    """

    # Internal signal handlers --------------------------------------------
    def _on_item_selected(self, run):
        self.run_selected.emit(run)

    def _on_item_deselected(self, run):
        self.run_deselected.emit(run)


class AppModel(QObject):
    """Top-level application model that owns persistent state."""

    active_display_changed = Signal(str)

    def __init__(self, config_path: Optional[str] = None):
        super().__init__()
        self.config = ConfigModel(config_path)
        self.display_registry = DisplayRegistry()
        self.display_manager = DisplayManager(self.display_registry)
        self.catalogs = CatalogManagerModel(self.config)

        self._active_display_id = "main"

        # Route catalog selections to the active display' RunListModel
        # TODO: Should this only be done for the main display?
        self.catalogs.run_selected.connect(self._on_run_selected)
        self.catalogs.run_deselected.connect(self._on_run_deselected)

    # Active display --------------------------------------------------------
    def set_active_display(self, display_id: str) -> None:
        self._active_display_id = display_id
        self.active_display_changed.emit(display_id)

    def get_active_display(self) -> str:
        return self._active_display_id

    # Catalog selection routing -------------------------------------------

    def _on_run_selected(self, run) -> None:
        self.display_manager.add_run_to_display(run, self._active_display_id)

    def _on_run_deselected(self, run) -> None:
        self.display_manager.remove_run_from_display(run, self._active_display_id)

    # Convenience actions for menus ---------------------------------------
    def new_display(self, widget_type: Optional[str] = None) -> str:
        return self.display_manager.register_display(widget_type)

    def close_display(self, display_id: str) -> None:
        self.display_manager.remove_display(display_id)
