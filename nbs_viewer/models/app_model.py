from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from qtpy.QtCore import QObject, Signal

from .plot.displayManager import DisplayManager


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

    @property
    def data(self) -> Dict:
        """Return the raw loaded configuration dictionary."""
        return self._data

    def get_catalog_configs(self) -> List[Dict[str, Any]]:
        """
        Return catalog entries from the config file.

        Returns
        -------
        list of dict
            Entries under the top-level ``catalog`` key, or an empty list.
        """
        catalogs = self._data.get("catalog", [])
        if not isinstance(catalogs, list):
            return []
        return list(catalogs)

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
    """
    Registry and factory for catalog sources.

    Owns a long-lived source **palette**, creates ``*SourceModel`` instances,
    connects each palette source's ``catalog_loaded`` to ``register_catalog``,
    and forwards selection events. Does not create view widgets.
    """

    catalogs_changed = Signal(list)
    catalog_added = Signal(str, object)
    catalog_removed = Signal(str)
    current_catalog_changed = Signal(str)
    run_selected = Signal(object)
    run_deselected = Signal(object)
    error = Signal(str)

    def __init__(self, config: ConfigModel):
        super().__init__()
        self._config = config
        self._catalogs: Dict[str, object] = {}
        self._sources: Dict[str, object] = {}
        self._current_label: Optional[str] = None

    def create_uri_source(self, auth_callback=None, cache_credentials: bool = True):
        """
        Create an unconfigured URI source model.

        Parameters
        ----------
        auth_callback : callable, optional
            Interactive authentication callback.
        cache_credentials : bool, optional
            Whether to use cached tokens by default.

        Returns
        -------
        URISourceModel
            New URI source model.
        """
        from .sources.uriSource import URISourceModel

        return URISourceModel(
            auth_callback=auth_callback, cache_credentials=cache_credentials
        )

    def create_profile_source(
        self, auth_callback=None, cache_credentials: bool = True
    ):
        """
        Create an unconfigured Tiled profile source model.

        Parameters
        ----------
        auth_callback : callable, optional
            Interactive authentication callback.
        cache_credentials : bool, optional
            Whether to use cached tokens by default.

        Returns
        -------
        ProfileSourceModel
            New profile source model.
        """
        from .sources.profileSource import ProfileSourceModel

        return ProfileSourceModel(
            auth_callback=auth_callback, cache_credentials=cache_credentials
        )

    def create_kafka_source(self):
        """
        Create an unconfigured Kafka source model.

        Returns
        -------
        KafkaSourceModel
            New Kafka source model.
        """
        from .sources.kafkaSource import KafkaSourceModel

        return KafkaSourceModel()

    def create_zmq_source(self):
        """
        Create a ZMQ source model.

        Returns
        -------
        ZMQSourceModel
            New ZMQ source model.
        """
        from .sources.zmqSource import ZMQSourceModel

        return ZMQSourceModel()

    def create_test_source(self, runs: int = 10):
        """
        Create a test in-memory catalog source.

        Parameters
        ----------
        runs : int, optional
            Number of synthetic runs to include.

        Returns
        -------
        TestSourceModel
            New test source model.
        """
        from .sources.testSource import TestSourceModel

        return TestSourceModel(runs=runs)

    def create_from_config(
        self, catalog_config: Dict[str, Any], auth_callback=None
    ):
        """
        Create a configured source model from a config dictionary.

        Dispatches on ``catalog_config["source_type"]`` (default ``"uri"``).

        Parameters
        ----------
        catalog_config : dict
            Catalog entry from application TOML.
        auth_callback : callable, optional
            Interactive authentication callback for URI/profile sources.

        Returns
        -------
        ConfigSourceModel
            Wrapper around the configured inner source model.

        Raises
        ------
        ValueError
            If ``source_type`` is unknown.
        """
        from .sources.configSource import ConfigSourceModel

        inner = self._build_source_from_config(catalog_config, auth_callback)
        return ConfigSourceModel(catalog_config, inner)

    def _build_source_from_config(
        self, catalog_config: Dict[str, Any], auth_callback=None
    ):
        """
        Build the inner source model for a config entry.

        Parameters
        ----------
        catalog_config : dict
            Catalog configuration entry.
        auth_callback : callable, optional
            Authentication callback.

        Returns
        -------
        SourceModel
            Configured URI, profile, or Kafka source model.
        """
        source_type = catalog_config.get("source_type", "uri")

        if source_type == "uri":
            cache_credentials = catalog_config.get("cache_credentials", True)
            model = self.create_uri_source(
                auth_callback=auth_callback, cache_credentials=cache_credentials
            )
            model.set_uri(catalog_config["url"])

            if catalog_config.get("catalog_keys"):
                keys = catalog_config["catalog_keys"]
                if isinstance(keys, str):
                    keys = [keys]
                model.set_selected_keys(keys)

            model.set_selected_model(catalog_config["catalog_model"])

            if catalog_config.get("api_key"):
                model.set_api_key(catalog_config["api_key"])

            if catalog_config.get("remember_me") is not None:
                model.remember_me = catalog_config["remember_me"]

            if catalog_config.get("username"):
                model.username = catalog_config["username"]

            return model

        if source_type == "profile":
            model = self.create_profile_source(auth_callback=auth_callback)
            model.set_profile(catalog_config["profile"])

            if catalog_config.get("catalog_keys"):
                keys = catalog_config["catalog_keys"]
                if isinstance(keys, str):
                    keys = [keys]
                model.set_selected_keys(keys)

            model.set_selected_model(catalog_config["catalog_model"])
            return model

        if source_type == "kafka":
            model = self.create_kafka_source()
            model.set_config_file(catalog_config["config_file"])
            model.set_beamline_acronym(catalog_config["beamline_acronym"])
            return model

        raise ValueError(f"Unknown source type: {source_type}")

    def add_source(self, key: str, source_model) -> object:
        """
        Add a source model to the long-lived palette.

        Connects ``catalog_loaded`` to ``register_catalog``. If ``key`` is
        already present, returns the existing source without replacing it.

        Parameters
        ----------
        key : str
            Palette key (e.g. ``"uri"``, ``"config:MyLabel"``).
        source_model : SourceModel
            Source to own on the palette.

        Returns
        -------
        SourceModel
            The palette source for ``key``.
        """
        existing = self._sources.get(key)
        if existing is not None:
            return existing
        self._sources[key] = source_model
        source_model.catalog_loaded.connect(self._on_catalog_loaded)
        return source_model

    def get_palette_source(self, key: str) -> Optional[object]:
        """
        Return a palette source by key.

        Parameters
        ----------
        key : str
            Palette key.

        Returns
        -------
        SourceModel or None
            The source if present.
        """
        return self._sources.get(key)

    def iter_palette(self) -> List[Tuple[str, object]]:
        """
        Return palette entries in insertion order.

        Returns
        -------
        list of tuple
            ``(key, source_model)`` pairs.
        """
        return list(self._sources.items())

    def ensure_interactive_palette(self, auth_callback=None) -> None:
        """
        Ensure config recipes and default interactive sources are on the palette.

        Parameters
        ----------
        auth_callback : callable, optional
            Auth callback applied when creating new URI/profile/config sources.
        """
        for catalog_config in self._config.get_catalog_configs():
            label = catalog_config.get("label")
            if not label:
                continue
            key = f"config:{label}"
            if key in self._sources:
                continue
            source = self.create_from_config(
                catalog_config, auth_callback=auth_callback
            )
            self.add_source(key, source)

        if "uri" not in self._sources:
            self.add_source(
                "uri",
                self.create_uri_source(auth_callback=auth_callback),
            )
        elif auth_callback is not None:
            self._sources["uri"].auth_callback = auth_callback

        if "profile" not in self._sources:
            self.add_source(
                "profile",
                self.create_profile_source(auth_callback=auth_callback),
            )
        elif auth_callback is not None:
            self._sources["profile"].auth_callback = auth_callback

        if "kafka" not in self._sources:
            self.add_source("kafka", self.create_kafka_source())

        if "zmq" not in self._sources:
            self.add_source("zmq", self.create_zmq_source())

        if "test" not in self._sources:
            self.add_source("test", self.create_test_source())

    def _on_catalog_loaded(self, catalog, label: str) -> None:
        """Slot: register a catalog emitted by a palette source."""
        self.register_catalog(label, catalog)

    def _unique_label(self, label: str) -> str:
        """
        Return ``label`` or ``label (n)`` if already registered.

        Parameters
        ----------
        label : str
            Requested catalog label.

        Returns
        -------
        str
            Unique label for the registry.
        """
        if label not in self._catalogs:
            return label
        n = 2
        while f"{label} ({n})" in self._catalogs:
            n += 1
        return f"{label} ({n})"

    def load_catalog(self, source_model, **kwargs) -> Tuple[object, str]:
        """
        Load a catalog from a configured source model without registering.

        Parameters
        ----------
        source_model : SourceModel
            Source that implements ``get_source``.
        **kwargs
            Forwarded to ``source_model.get_source`` (e.g. ``interactive_auth``).

        Returns
        -------
        tuple
            ``(catalog, label)``.
        """
        return source_model.get_source(**kwargs)

    def load_and_register(
        self, source_model, label: Optional[str] = None, **kwargs
    ) -> str:
        """
        Headless helper: load via ``get_source`` and register.

        Does not use ``source_model.load()`` so palette signal wiring cannot
        double-register. Prefer ``source.load()`` for the GUI path.

        Parameters
        ----------
        source_model : SourceModel
            Configured source model.
        label : str, optional
            Override label for registration. Defaults to the label from
            ``get_source``.
        **kwargs
            Forwarded to ``load_catalog``.

        Returns
        -------
        str
            Registered catalog label.
        """
        catalog, source_label = self.load_catalog(source_model, **kwargs)
        resolved = label if label is not None else source_label
        return self.register_catalog(resolved, catalog)

    def _label_for_catalog(self, catalog) -> Optional[str]:
        """Return the registry label for a catalog instance, if any."""
        for label, registered in self._catalogs.items():
            if registered is catalog:
                return label
        return None

    def load_autoload_from_config(self, auth_callback=None) -> List[Tuple[object, str]]:
        """
        Load catalogs marked ``autoload`` via palette sources and ``load()``.

        Parameters
        ----------
        auth_callback : callable, optional
            Auth callback for URI/profile sources.

        Returns
        -------
        list of tuple
            ``(catalog, label)`` for each successfully loaded catalog.
        """
        self.ensure_interactive_palette(auth_callback=auth_callback)
        results: List[Tuple[object, str]] = []
        for catalog_config in self._config.get_catalog_configs():
            if not catalog_config.get("autoload", False):
                continue
            label = catalog_config.get("label")
            if not label:
                continue
            key = f"config:{label}"
            source = self._sources.get(key)
            if source is None:
                continue
            try:
                catalog, _ = source.load(interactive_auth=False)
                registered = self._label_for_catalog(catalog) or label
                results.append((catalog, registered))
            except Exception as exc:
                import logging

                msg = (
                    f"Failed to autoload catalog "
                    f"{catalog_config.get('label', '?')}: {exc}"
                )
                logging.getLogger("nbs_viewer.catalog").exception(msg)
                self.error.emit(msg)
        return results

    def load_catalogs_from_file(
        self,
        path: str,
        auth_callback=None,
        interactive_auth: bool = True,
        autoload_only: bool = False,
    ) -> List[Tuple[object, str]]:
        """
        Load catalog entries from a TOML file onto the palette and load them.

        Parameters
        ----------
        path : str
            Path to a TOML config file with a ``catalog`` array.
        auth_callback : callable, optional
            Authentication callback.
        interactive_auth : bool, optional
            Whether interactive auth is allowed.
        autoload_only : bool, optional
            If True, only entries with ``autoload`` are loaded.

        Returns
        -------
        list of tuple
            ``(catalog, label)`` for each loaded catalog.
        """
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover
            import tomli as tomllib  # type: ignore

        with open(path, "rb") as f:
            data = tomllib.load(f)

        results: List[Tuple[object, str]] = []
        for catalog_config in data.get("catalog", []):
            if autoload_only and not catalog_config.get("autoload", False):
                continue
            label = catalog_config.get("label")
            if not label:
                continue
            key = f"config:{label}"
            try:
                if key not in self._sources:
                    source = self.create_from_config(
                        catalog_config, auth_callback=auth_callback
                    )
                    self.add_source(key, source)
                source = self._sources[key]
                catalog, _ = source.load(interactive_auth=interactive_auth)
                registered = self._label_for_catalog(catalog) or label
                results.append((catalog, registered))
            except Exception as exc:
                import logging

                msg = (
                    f"Failed to load catalog "
                    f"{catalog_config.get('label', '?')} from '{path}': {exc}"
                )
                logging.getLogger("nbs_viewer.catalog").exception(msg)
                self.error.emit(msg)
        return results

    def register_catalog(self, label: str, catalog: object) -> str:
        """
        Register a catalog under a unique label.

        Parameters
        ----------
        label : str
            Requested label (may be uniquified).
        catalog : object
            Catalog instance.

        Returns
        -------
        str
            The label actually used in the registry.
        """
        label = self._unique_label(label)
        self._catalogs[label] = catalog
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
        self.catalog_added.emit(label, catalog)
        self.catalogs_changed.emit(self.get_catalog_labels())
        return label

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
        self.catalog_removed.emit(label)
        self.catalogs_changed.emit(self.get_catalog_labels())

    def get_catalog_labels(self) -> List[str]:
        return list(self._catalogs.keys())

    def get_catalog(self, label: str) -> Optional[object]:
        """
        Return a registered catalog by label.

        Parameters
        ----------
        label : str
            Catalog label.

        Returns
        -------
        object or None
            The catalog if registered.
        """
        return self._catalogs.get(label)

    def get_current_catalog(self) -> Optional[object]:
        if self._current_label is None:
            return None
        return self._catalogs.get(self._current_label)

    def set_current_catalog(self, label: str) -> None:
        if label in self._catalogs and self._current_label != label:
            self._current_label = label
            self.current_catalog_changed.emit(label)

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
        self.display_manager = DisplayManager()
        self.catalogs = CatalogManagerModel(self.config)

        self._active_display_id = "main"

        self.catalogs.run_selected.connect(self._on_run_selected)
        self.catalogs.run_deselected.connect(self._on_run_deselected)

    def set_active_display(self, display_id: str) -> None:
        self._active_display_id = display_id
        self.active_display_changed.emit(display_id)

    def get_active_display(self) -> str:
        return self._active_display_id

    def _on_run_selected(self, run) -> None:
        self.display_manager.add_run_to_display(run, self._active_display_id)

    def _on_run_deselected(self, run) -> None:
        self.display_manager.remove_run_from_display(run, self._active_display_id)

    def new_display(self, widget_type: Optional[str] = None) -> str:
        return self.display_manager.register_display(widget_type)

    def close_display(self, display_id: str) -> None:
        self.display_manager.remove_display(display_id)
