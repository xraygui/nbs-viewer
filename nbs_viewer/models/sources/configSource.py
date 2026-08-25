"""Models for different catalog data sources."""

from typing import Dict, Any, Tuple

from ..catalog.base import CatalogBase
from .base import SourceModel
from .uriSource import URISourceModel
from .profileSource import ProfileSourceModel
from .kafkaSource import KafkaSourceModel


class ConfigSourceModel(SourceModel):
    """Model for configuration-based catalog sources."""

    def __init__(self, catalog_config: Dict[str, Any], auth_callback=None):
        """
        Initialize the configuration source model.

        Parameters
        ----------
        catalog_config : Dict[str, Any]
            Configuration dictionary for the catalog
        """
        super().__init__()
        self.catalog_config = catalog_config
        self.auth_callback = auth_callback
        self.source_model = self._create_source_model()

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

    def _create_source_model(self) -> SourceModel:
        """
        Create a source model based on the configuration.

        Returns
        -------
        SourceModel
            The appropriate source model for the configuration
        """
        source_type = self.catalog_config.get("source_type", "uri")

        if source_type == "uri":
            # Get cache_credentials setting from config, default to True for backward compatibility
            cache_credentials = self.catalog_config.get("cache_credentials", True)

            model = URISourceModel(
                auth_callback=self.auth_callback, cache_credentials=cache_credentials
            )
            model.set_uri(self.catalog_config["url"])

            if self.catalog_config.get("catalog_keys"):
                if isinstance(self.catalog_config["catalog_keys"], list):
                    model.set_selected_keys(self.catalog_config["catalog_keys"])
                elif isinstance(self.catalog_config["catalog_keys"], str):
                    model.set_selected_keys([self.catalog_config["catalog_keys"]])

            model.set_selected_model(self.catalog_config["catalog_model"])

            # Handle authentication options
            if self.catalog_config.get("api_key"):
                model.set_api_key(self.catalog_config["api_key"])

            if self.catalog_config.get("remember_me") is not None:
                model.remember_me = self.catalog_config["remember_me"]

            if self.catalog_config.get("username"):
                model.username = self.catalog_config["username"]

            return model

        elif source_type == "profile":
            model = ProfileSourceModel()
            model.set_profile(self.catalog_config["profile"])

            if self.catalog_config.get("catalog_keys"):
                if isinstance(self.catalog_config["catalog_keys"], list):
                    model.set_selected_keys(self.catalog_config["catalog_keys"])
                elif isinstance(self.catalog_config["catalog_keys"], str):
                    model.set_selected_keys([self.catalog_config["catalog_keys"]])

            model.set_selected_model(self.catalog_config["catalog_model"])
            return model

        elif source_type == "kafka":
            model = KafkaSourceModel()
            model.set_config_file(self.catalog_config["config_file"])
            model.set_beamline_acronym(self.catalog_config["beamline_acronym"])
            return model

        else:
            raise ValueError(f"Unknown source type: {source_type}")

    def is_configured(self) -> bool:
        """Check if the model is fully configured."""
        return self.source_model.is_configured()

    def get_source(self, interactive_auth=True) -> Tuple[CatalogBase, str]:
        """Get a catalog source from the configuration."""
        return self.source_model.get_source(interactive_auth=interactive_auth)
