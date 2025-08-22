"""Models for different catalog data sources."""

from typing import Dict, Any, Tuple, List
import uuid
import os
from os.path import exists

from tiled.client import from_profile, Context, from_context
import nslsii.kafka_utils
from bluesky_widgets.qt.kafka_dispatcher import QtRemoteDispatcher
from bluesky_widgets.qt.zmq_dispatcher import RemoteDispatcher as QtZMQRemoteDispatcher
from .base import CatalogBase
from .kafka import KafkaCatalog
from .base import load_catalog_models
from nbs_viewer.utils import print_debug


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


class URISourceModel(SourceModel):
    """Model for Tiled URI catalog sources."""

    def __init__(self, auth_callback=None):
        """
        Initialize the URI source model.

        Parameters
        ----------
        auth_callback : callable, optional
            Callback function for handling interactive authentication.
            Should take a Context object and return authentication tokens.
        """
        super().__init__()
        self.uri = "http://localhost:8000"
        self.profile = ""
        self.selected_keys = []
        self.selected_model_name = None
        self.api_key = None
        self.use_cached_tokens = True
        self.remember_me = True
        # New authentication properties
        self.username = ""
        self.password = ""
        self.auth_callback = auth_callback

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
        # Check for environment variable first
        api_key = os.environ.get("TILED_API_KEY")

        # Check for manual API key
        if self.api_key:
            context.api_key = self.api_key
            try:
                context.which_api_key()
                return
            except Exception as e:
                print_debug("URISourceModel", f"API key failed: {e}")
                context.api_key = None
                # If callback fails, we'll fall through to the exception below
                pass
        if api_key:
            context.api_key = api_key
            try:
                context.which_api_key()
                return
            except Exception as e:
                print_debug("URISourceModel", f"TILED_API_KEY failed: {e}")
                context.api_key = None
                # If callback fails, we'll fall through to the exception below
                pass

        # Check if we have cached tokens and remember_me is True
        if self.use_cached_tokens:
            found_valid_tokens = context.use_cached_tokens()
            if found_valid_tokens:
                return

        # Try interactive authentication via callback
        if self.auth_callback and interactive_auth:
            try:
                tokens = self.auth_callback(context)
                if tokens:
                    context.configure_auth(tokens, remember_me=self.remember_me)
                    return
            except Exception as e:
                print_debug("URISourceModel", f"Authentication callback failed: {e}")
                # If callback fails, we'll fall through to the exception below
                pass

        # If we get here, authentication failed
        raise RuntimeError(
            "Authentication required but no valid credentials found and no "
            "interactive authentication callback provided"
        )

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

        # Create context using new approach
        context, node_path_parts = self._create_context()

        # Check if authentication is required and handle it
        auth_is_required = context.server_info.authentication.required

        if auth_is_required:
            self._handle_authentication(context, interactive_auth)

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
        # Create client from context
        client = from_context(context, node_path_parts=node_path_parts)

        label = f"Tiled: {self.uri}"

        if self.profile:
            client = client[self.profile]
            label += ":" + self.profile

        # Navigate through selected keys
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
            raise ValueError("URI source model is not fully configured")

        # Stage 1: Connect and authenticate
        context, node_path_parts = self.connect_and_authenticate(interactive_auth)

        # Stage 2: Navigate catalog tree
        client, label = self.navigate_catalog_tree(context, node_path_parts)

        # Stage 3: Select catalog model
        catalog = self.select_catalog_model(client)

        return catalog, label


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
            raise ValueError("Profile source model is not fully configured")

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


class ZMQSourceModel(SourceModel):
    """Model for Kafka catalog sources."""

    def __init__(self):
        """Initialize the Kafka source model."""
        super().__init__()

    def is_configured(self) -> bool:
        """Check if the model is fully configured."""
        return True

    def get_source(self, **kwargs) -> Tuple[CatalogBase, str]:
        zmq_dispatcher = QtZMQRemoteDispatcher("localhost:5578")
        label = "ZMQ: localhost:5578"
        # Create the Kafka catalog (poorly named -- really a live catalog)
        catalog = KafkaCatalog(zmq_dispatcher)
        return catalog, label


class KafkaSourceModel(SourceModel):
    """Model for Kafka catalog sources."""

    def __init__(self):
        """Initialize the Kafka source model."""
        super().__init__()
        self.config_file = (
            "/etc/bluesky/kafka.yml" if exists("/etc/bluesky/kafka.yml") else None
        )
        self.beamline_acronym = ""

    def set_config_file(self, config_file: str) -> None:
        """
        Set the Kafka configuration file.

        Parameters
        ----------
        config_file : str
            Path to the Kafka configuration file
        """
        self.config_file = config_file

    def set_beamline_acronym(self, acronym: str) -> None:
        """
        Set the beamline acronym.

        Parameters
        ----------
        acronym : str
            The beamline acronym
        """
        self.beamline_acronym = acronym

    def is_configured(self) -> bool:
        """Check if the model is fully configured."""
        return bool(self.config_file and self.beamline_acronym)

    def get_source(self, **kwargs) -> Tuple[CatalogBase, str]:
        """Get a catalog source from Kafka."""
        if not self.is_configured():
            raise ValueError("Kafka source model is not fully configured")
        label = f"Kafka: {self.beamline_acronym}"

        # Read Kafka configuration
        kafka_config = nslsii.kafka_utils._read_bluesky_kafka_config_file(
            config_file_path=self.config_file
        )

        # Generate a unique consumer group ID
        unique_group_id = f"echo-{self.beamline_acronym}-{str(uuid.uuid4())[:8]}"
        topics = [f"{self.beamline_acronym}.bluesky.runengine.documents"]
        # Create the Kafka dispatcher
        kafka_dispatcher = QtRemoteDispatcher(
            topics,
            ",".join(kafka_config["bootstrap_servers"]),
            unique_group_id,
            consumer_config=kafka_config["runengine_producer_config"],
        )

        # Create the Kafka catalog
        catalog = KafkaCatalog(kafka_dispatcher)
        return catalog, label


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
            model = URISourceModel(auth_callback=self.auth_callback)
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
        return self.source_model.get_source(interactive_auth)
