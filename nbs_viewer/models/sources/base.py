"""Models for different catalog data sources."""

from typing import Optional, Tuple

from qtpy.QtCore import QObject, Signal

from ..catalog.base import CatalogBase
from ..catalog.base import load_catalog_models


class CatalogLoadError(RuntimeError):
    """Exception raised when a catalog load fails."""

    pass


class AuthenticationRejected(CatalogLoadError):
    """Exception raised when authentication is rejected."""

    pass


class SourceModel(QObject):
    """
    Base class for catalog source models.

    Long-lived factory/strategy on the catalog manager palette. Subclasses
    implement ``get_source``; ``load`` calls it and emits ``catalog_loaded``.
    """

    catalog_loaded = Signal(object, str)

    def __init__(self, parent: Optional[QObject] = None):
        """
        Initialize the source model.

        Parameters
        ----------
        parent : QObject, optional
            Qt parent object.
        """
        super().__init__(parent)
        self.catalog_models = load_catalog_models()

    def get_source(self, **kwargs) -> Tuple[CatalogBase, str]:
        """
        Get a catalog source from the model.

        Returns
        -------
        Tuple[CatalogBase, str]
            A tuple containing:
            - The catalog instance
            - A label describing the source
        """
        raise NotImplementedError("Subclasses must implement get_source")

    def load(self, **kwargs) -> Tuple[CatalogBase, str]:
        """
        Load a catalog via ``get_source`` and emit ``catalog_loaded``.

        Parameters
        ----------
        **kwargs
            Forwarded to ``get_source``.

        Returns
        -------
        Tuple[CatalogBase, str]
            The catalog instance and label.
        """
        catalog, label = self.get_source(**kwargs)
        self.catalog_loaded.emit(catalog, label)
        return catalog, label

    def emit_catalog_loaded(self, catalog: CatalogBase, label: str) -> None:
        """
        Emit ``catalog_loaded`` for a catalog built outside ``get_source``.

        Used by interactive views that assemble a catalog via staged
        connect / navigate / model-select APIs.

        Parameters
        ----------
        catalog : CatalogBase
            Loaded catalog.
        label : str
            Registry label for the catalog.
        """
        self.catalog_loaded.emit(catalog, label)

    def is_configured(self) -> bool:
        """
        Check if the model has all required configuration to get a source.

        Returns
        -------
        bool
            True if the model is fully configured, False otherwise
        """
        raise NotImplementedError("Subclasses must implement is_configured")

    def get_display_label(self) -> str:
        """
        Get a human-readable label for display in the authentication dialog.

        Returns
        -------
        str
            A human-readable label describing the catalog source
        """
        return "Unknown Catalog"
