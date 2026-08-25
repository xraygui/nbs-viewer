from typing import Tuple, List
from tiled.client import from_profile
from ..catalog.base import CatalogBase
from .base import SourceModel, CatalogLoadError


class ProfileSourceModel(SourceModel):
    """Model for Tiled profile catalog sources."""

    def __init__(self):
        """Initialize the profile source model."""
        super().__init__()
        self.profile = ""
        self.selected_keys = []
        self.selected_model_name = None

    def set_profile(self, profile: str) -> None:
        """
        Set the profile for the catalog.

        Parameters
        ----------
        profile : str
            The profile name
        """
        self.profile = profile

    def set_selected_keys(self, keys: List[str]) -> None:
        """
        Set the selected keys for navigating nested catalogs.

        Parameters
        ----------
        keys : List[str]
            The keys to navigate through
        """
        self.selected_keys = keys

    def set_selected_model(self, model_name: str) -> None:
        """
        Set the selected catalog model.

        Parameters
        ----------
        model_name : str
            The name of the model to use
        """
        self.selected_model_name = model_name

    def is_configured(self) -> bool:
        """Check if the model is fully configured."""
        return bool(self.profile and self.selected_model_name)

    def get_source(self, **kwargs) -> Tuple[CatalogBase, str]:
        """Get a catalog source from the profile."""
        if not self.is_configured():
            raise CatalogLoadError("Profile source model is not fully configured")

        catalog = from_profile(self.profile)
        label = f"Profile: {self.profile}"

        # Navigate through selected keys
        for key in self.selected_keys:
            catalog = catalog[key]
            label += ":" + key

        # Create the catalog with the selected model
        selected_model = self.catalog_models[self.selected_model_name]
        catalog = selected_model(catalog)

        return catalog, label