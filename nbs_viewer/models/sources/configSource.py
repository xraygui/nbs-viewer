"""Configuration-backed catalog source wrapper."""

from typing import Dict, Any, Tuple

from ..catalog.base import CatalogBase
from .base import SourceModel


class ConfigSourceModel(SourceModel):
    """
    Thin wrapper around a configured source model from app config.

    Construction of the inner source is done by
    ``CatalogManagerModel.create_from_config``; this class only carries
    config metadata (label, autoload) and delegates load APIs.
    """

    def __init__(self, catalog_config: Dict[str, Any], source_model: SourceModel):
        """
        Initialize the configuration source model.

        Parameters
        ----------
        catalog_config : dict
            Configuration dictionary for the catalog.
        source_model : SourceModel
            Already-configured inner source model.
        """
        super().__init__()
        self.catalog_config = catalog_config
        self.source_model = source_model

    def get_display_label(self) -> str:
        """
        Get a human-readable label for display in the authentication dialog.

        Returns
        -------
        str
            A human-readable label describing the catalog source
        """
        return self.catalog_config.get("label", "Unknown Catalog")

    @property
    def autoload(self) -> bool:
        """
        Check if this catalog should be automatically loaded on startup.

        Returns
        -------
        bool
            True if the catalog should be automatically loaded, False otherwise
        """
        return self.catalog_config.get("autoload", False)

    def is_configured(self) -> bool:
        """Check if the model is fully configured."""
        return self.source_model.is_configured()

    def get_source(self, interactive_auth=True) -> Tuple[CatalogBase, str]:
        """
        Get a catalog source from the configuration.

        Prefers the config entry ``label`` over the inner source label.
        """
        catalog, inner_label = self.source_model.get_source(
            interactive_auth=interactive_auth
        )
        label = self.catalog_config.get("label") or inner_label
        return catalog, label
