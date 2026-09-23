from contextlib import contextmanager
from typing import Any, Tuple, List
import os
from tiled.client import Context, from_context
from ..catalog.base import CatalogBase
from nbs_viewer.utils import print_debug
from .base import SourceModel, CatalogLoadError, AuthenticationRejected


@contextmanager
def tiled_retry_budget(attempts=1, timeout=5.0):
    """
    Temporarily tighten Tiled client HTTP retry limits.

    Tiled retries 5xx responses for up to ~45s with a terminal Rich
    ``Retrying…`` spinner. In a Qt GUI that freezes the event loop, so
    interactive connect/auth paths should fail fast and fall through to
    the auth dialog instead.

    Parameters
    ----------
    attempts : int, optional
        Maximum HTTP attempts. Default is 1 (no retries).
    timeout : float, optional
        Maximum total retry budget in seconds. Default is 5.0.

    Yields
    ------
    None
    """
    import tiled.client.utils as tiled_utils

    old_attempts = tiled_utils.TILED_RETRY_ATTEMPTS
    old_timeout = tiled_utils.TILED_RETRY_TIMEOUT
    tiled_utils.TILED_RETRY_ATTEMPTS = int(attempts)
    tiled_utils.TILED_RETRY_TIMEOUT = float(timeout)
    try:
        yield
    finally:
        tiled_utils.TILED_RETRY_ATTEMPTS = old_attempts
        tiled_utils.TILED_RETRY_TIMEOUT = old_timeout


class URISourceModel(SourceModel):
    """Model for Tiled URI catalog sources."""

    def __init__(self, auth_callback=None, cache_credentials=True):
        """
        Initialize the URI source model.

        Parameters
        ----------
        auth_callback : callable, optional
            Callback function for handling interactive authentication.
            Should take a Context object and return authentication tokens.
        cache_credentials : bool, optional
            Whether to use cached authentication tokens. Default is True.
            Set to False for shared machines or when you want to force fresh auth.
        """
        super().__init__()
        self.uri = "http://localhost:8000"
        self.profile = ""
        self.selected_keys = []
        self.selected_model_name = None
        self.api_key = None
        self.use_cached_tokens = cache_credentials
        self.remember_me = True
        # New authentication properties
        self.username = ""
        self.password = ""
        self.auth_callback = auth_callback

    def get_display_label(self) -> str:
        """
        Get a human-readable label for display in the authentication dialog.

        Returns
        -------
        str
            A human-readable label describing the catalog source
        """
        if self.profile:
            return f"Tiled URI: {self.uri} (Profile: {self.profile})"
        return f"Tiled URI: {self.uri}"

    def set_uri(self, uri: str) -> None:
        """
        Set the URI for the catalog.

        Parameters
        ----------
        uri : str
            The URI to connect to
        """
        self.uri = uri

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

    def set_api_key(self, api_key: str) -> None:
        """
        Set the API key for the catalog.
        """
        self.api_key = api_key

    def set_credentials(self, username: str, password: str) -> None:
        """
        Set the username and password for interactive authentication.

        Parameters
        ----------
        username : str
            The username for authentication
        password : str
            The password for authentication
        """
        self.username = username
        self.password = password

    def _create_context(self) -> Tuple[Context, List[str]]:
        """
        Create a Tiled context using Context.from_any_uri.

        Returns
        -------
        Tuple[Context, List[str]]
            A tuple containing the context and node path parts
        """
        return Context.from_any_uri(self.uri)

    def _check_auth_required(self, context: Context) -> bool:
        """
        Check if the server requires authentication.

        Parameters
        ----------
        context : Context
            The Tiled context to check

        Returns
        -------
        bool
            True if authentication is required, False otherwise
        """
        return context.server_info.authentication.required

    def _handle_authentication(self, context: Context, interactive_auth=True) -> None:
        """
        Handle the authentication flow for the context.

        Parameters
        ----------
        context : Context
            The Tiled context to authenticate
        """
        auth_attempts = []
        auth_failures = []

        # Check for environment variable first
        api_key = os.environ.get("TILED_API_KEY")
        if api_key:
            auth_attempts.append("TILED_API_KEY environment variable")
            context.api_key = api_key
            try:
                context.which_api_key()
                return True
            except Exception as e:
                auth_failures.append(f"TILED_API_KEY environment variable: {e}")
                context.api_key = None
                print_debug("URISourceModel", f"TILED_API_KEY failed: {e}", category="catalog")

        # Check for manual API key
        if self.api_key:
            auth_attempts.append("Manual API key")
            context.api_key = self.api_key
            try:
                context.which_api_key()
                return True
            except Exception as e:
                auth_failures.append(f"Manual API key: {e}")
                context.api_key = None
                print_debug("URISourceModel", f"Manual API key failed: {e}", category="catalog")

        # Check if we have cached tokens and remember_me is True
        if self.use_cached_tokens:
            auth_attempts.append("Cached authentication tokens")
            try:
                found_valid_tokens = context.use_cached_tokens()
                if found_valid_tokens:
                    return True
                else:
                    auth_failures.append(
                        "Cached authentication tokens: No valid tokens found"
                    )
            except Exception as e:
                auth_failures.append(f"Cached authentication tokens: {e}")

        # Try interactive authentication via callback
        if self.auth_callback and interactive_auth:
            auth_attempts.append("Interactive authentication callback")
            try:
                auth_model = self.auth_callback(context, self)
                if auth_model:
                    tokens = auth_model.get_tokens()
                    self.remember_me = auth_model.get_remember_me()
                    context.configure_auth(tokens, remember_me=self.remember_me)
                    print("Authentication successful")
                    return True
                else:
                    auth_failures.append(
                        "Interactive authentication callback: No auth model returned"
                    )
            except Exception as e:
                auth_failures.append(f"Interactive authentication callback: {e}")
                print_debug("URISourceModel", f"Authentication callback failed: {e}", category="catalog")
        elif not self.auth_callback:
            auth_failures.append(
                "Interactive authentication callback: No callback provided"
            )

        # Build detailed error message
        error_msg = "Authentication required but all methods failed:\n\n"
        error_msg += "Authentication methods attempted:\n"
        for attempt in auth_attempts:
            error_msg += f"  ✓ {attempt}\n"

        error_msg += "\nAuthentication failures:\n"
        for failure in auth_failures:
            error_msg += f"  ✗ {failure}\n"

        error_msg += "\nPossible solutions:\n"
        if not self.api_key and not api_key:
            error_msg += "  • Set an API key via set_api_key() or TILED_API_KEY environment variable\n"
        if not self.auth_callback:
            error_msg += "  • Provide an authentication callback function\n"
        if not self.use_cached_tokens:
            error_msg += "  • Enable cached tokens (use_cached_tokens=True)\n"

        error_msg += f"  • Server URI: {self.uri}\n"
        if self.profile:
            error_msg += f"  • Profile: {self.profile}\n"

        raise AuthenticationRejected(error_msg)

    def is_configured(self) -> bool:
        """Check if the model has the minimum required configuration."""
        return bool(self.uri)

    def is_fully_configured(self) -> bool:
        """Check if the model is fully configured for all stages."""
        return bool(self.uri and self.selected_model_name)

    def connect_and_authenticate(
        self, interactive_auth=True
    ) -> Tuple[Context, List[str]]:
        """
        Stage 1: Connect to the server and handle authentication.

        Returns
        -------
        Tuple[Context, List[str]]
            A tuple containing:
            - The authenticated context
            - The node path parts
        """
        if not self.uri:
            raise ValueError("URI is required")

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
        Stage 2: Navigate through the catalog tree to get the final catalog.

        Parameters
        ----------
        context : Context
            The authenticated context
        node_path_parts : List[str]
            The node path parts

        Returns
        -------
        Tuple[Any, str]
            A tuple containing:
            - The catalog client
            - The label for the catalog
        """
        with tiled_retry_budget():
            client = from_context(context, node_path_parts=node_path_parts)

        label = f"Tiled: {self.uri}"

        if self.profile:
            client = client[self.profile]
            label += ":" + self.profile

        for key in self.selected_keys:
            client = client[key]
            label += ":" + key

        return client, label

    def select_catalog_model(self, client: Any) -> CatalogBase:
        """
        Stage 3: Apply the selected catalog model to the client.

        Parameters
        ----------
        client : Any
            The catalog client

        Returns
        -------
        CatalogBase
            The catalog with the model applied
        """
        if not self.selected_model_name:
            raise ValueError("Catalog model must be selected")

        # Create the catalog with the selected model
        selected_model = self.catalog_models[self.selected_model_name]
        catalog = selected_model(client)

        return catalog

    def get_source(self, interactive_auth=True, **kwargs) -> Tuple[CatalogBase, str]:
        """
        Get a catalog source from the URI (all stages combined).

        This method combines all three stages for backward compatibility.

        Returns
        -------
        Tuple[CatalogBase, str]
            A tuple containing:
            - The catalog instance
            - A label describing the source
        """
        if not self.is_fully_configured():
            raise CatalogLoadError("URI source model is not fully configured")

        # Stage 1: Connect and authenticate
        context, node_path_parts = self.connect_and_authenticate(interactive_auth)

        # Stage 2: Navigate catalog tree
        client, label = self.navigate_catalog_tree(context, node_path_parts)

        # Stage 3: Select catalog model
        catalog = self.select_catalog_model(client)

        return catalog, label
