from typing import Any, Tuple, List

from tiled.client import Context, from_context
from tiled.profiles import ProfileNotFound, load_profiles, paths
from tiled.utils import prepend_to_sys_path

from ..catalog.base import CatalogBase
from .base import CatalogLoadError, AuthenticationRejected
from .uriSource import URISourceModel, tiled_retry_budget


class ProfileSourceModel(URISourceModel):
    """
    Model for Tiled profile catalog sources.

    Resolves URI-based profiles into a ``Context`` and reuses the URI
    authentication path (including the Qt auth callback) instead of
    ``tiled.client.from_profile``, which prompts on the terminal and can
    block the GUI on Tiled's Rich retry spinner.
    """

    def __init__(self, auth_callback=None, cache_credentials=True):
        """
        Initialize the profile source model.

        Parameters
        ----------
        auth_callback : callable, optional
            Callback for interactive authentication (e.g. Qt dialog).
        cache_credentials : bool, optional
            Whether to try cached tokens before prompting. Default True.
        """
        super().__init__(
            auth_callback=auth_callback, cache_credentials=cache_credentials
        )
        self.profile = ""
        self.uri = ""
        self.verify = True
        self._direct_config = None
        self._profile_filepath = None

    def get_display_label(self) -> str:
        """
        Get a human-readable label for the authentication dialog.

        Returns
        -------
        str
            Label describing this profile source.
        """
        if self.profile:
            return f"Tiled Profile: {self.profile}"
        return "Tiled Profile"

    def set_profile(self, profile: str) -> None:
        """
        Set the Tiled profile name and resolve its connection settings.

        Parameters
        ----------
        profile : str
            The profile name
        """
        self.profile = profile
        self.uri = ""
        self.verify = True
        self._direct_config = None
        self._profile_filepath = None
        if profile:
            self._resolve_profile()

    def _resolve_profile(self) -> None:
        """
        Load the named profile and extract URI or direct-app settings.

        Raises
        ------
        ProfileNotFound
            If the profile name is unknown.
        CatalogLoadError
            If the profile has neither a ``uri`` nor a ``direct`` section.
        """
        profiles = load_profiles()
        try:
            filepath, content = profiles[self.profile]
        except KeyError as err:
            raise ProfileNotFound(
                f"Profile {self.profile!r} not found. Found profiles "
                f"{list(profiles)} from directories {paths}."
            ) from err

        self._profile_filepath = filepath
        if "uri" in content:
            self.uri = content["uri"]
            self.verify = content.get("verify", True)
            self._direct_config = None
        elif "direct" in content:
            self.uri = ""
            self._direct_config = content["direct"]
        else:
            raise CatalogLoadError(
                f"Profile {self.profile!r} has neither a 'uri' nor a "
                f"'direct' section."
            )

    def is_configured(self) -> bool:
        """Check if the model has the minimum required configuration."""
        return bool(self.profile and (self.uri or self._direct_config))

    def is_fully_configured(self) -> bool:
        """Check if the model is fully configured for all stages."""
        return bool(self.is_configured() and self.selected_model_name)

    def _create_context(self) -> Tuple[Context, List[str]]:
        """
        Create a Tiled context from the resolved profile.

        Returns
        -------
        Tuple[Context, List[str]]
            Authenticated-ready context and node path parts.
        """
        if not self.profile:
            raise ValueError("Profile is required")
        if self.uri:
            return Context.from_any_uri(self.uri, verify=self.verify)
        if self._direct_config is not None:
            from tiled.server.app import build_app_from_config

            with prepend_to_sys_path(self._profile_filepath.parent):
                app = build_app_from_config(self._direct_config)
            return Context.from_app(app), []
        raise CatalogLoadError(f"Profile {self.profile!r} is not resolved")

    def connect_and_authenticate(
        self, interactive_auth=True
    ) -> Tuple[Context, List[str]]:
        """
        Stage 1: Resolve the profile, connect, and authenticate.

        Parameters
        ----------
        interactive_auth : bool, optional
            Whether to allow the interactive auth callback.

        Returns
        -------
        Tuple[Context, List[str]]
            The authenticated context and node path parts.
        """
        if not self.profile:
            raise ValueError("Profile is required")
        self._resolve_profile()

        with tiled_retry_budget():
            context, node_path_parts = self._create_context()
            auth_is_required = context.server_info.authentication.required
            if auth_is_required:
                success = self._handle_authentication(context, interactive_auth)
                if not success:
                    raise AuthenticationRejected("Authentication failed")

        return context, node_path_parts

    def navigate_catalog_tree(
        self, context: Context, node_path_parts: List[str]
    ) -> Tuple[Any, str]:
        """
        Stage 2: Build a client for the profile's catalog root.

        Parameters
        ----------
        context : Context
            The authenticated context
        node_path_parts : List[str]
            The node path parts from the profile URI

        Returns
        -------
        Tuple[Any, str]
            Catalog client and display label
        """
        with tiled_retry_budget():
            client = from_context(context, node_path_parts=node_path_parts)

        label = f"Profile: {self.profile}"
        for key in self.selected_keys:
            client = client[key]
            label += ":" + key

        return client, label

    def get_source(self, interactive_auth=True, **kwargs) -> Tuple[CatalogBase, str]:
        """
        Get a catalog source from the profile (all stages combined).

        Parameters
        ----------
        interactive_auth : bool, optional
            Whether to allow interactive authentication.

        Returns
        -------
        Tuple[CatalogBase, str]
            Catalog instance and source label
        """
        if not self.is_fully_configured():
            raise CatalogLoadError("Profile source model is not fully configured")

        context, node_path_parts = self.connect_and_authenticate(interactive_auth)
        client, label = self.navigate_catalog_tree(context, node_path_parts)
        catalog = self.select_catalog_model(client)
        return catalog, label
