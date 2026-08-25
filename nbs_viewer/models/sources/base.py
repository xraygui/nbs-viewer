"""Models for different catalog data sources."""

from typing import Tuple

from ..catalog.base import CatalogBase
from ..catalog.base import load_catalog_models


class CatalogLoadError(RuntimeError):
    """Exception raised when a catalog load fails."""

    pass


class AuthenticationRejected(CatalogLoadError):
    """Exception raised when authentication is rejected."""

    pass


class SourceModel:
    """
    Base class for catalog source models.

    This class defines the interface for all source models that provide
    catalogs to the application.
    """

    def __init__(self):
        """Initialize the source model."""
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