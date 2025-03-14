"""Models for different catalog data sources."""

from typing import Dict, Any, Tuple, List
import uuid
from os.path import exists

from tiled.client import from_uri, from_profile
import nslsii.kafka_utils
from bluesky_widgets.qt.kafka_dispatcher import QtRemoteDispatcher
from bluesky_widgets.qt.zmq_dispatcher import RemoteDispatcher as QtZMQRemoteDispatcher
from .base import CatalogBase
from .kafka import KafkaCatalog
from .base import load_catalog_models


class SourceModel:
    """
    Base class for catalog source models.

    This class defines the interface for all source models that provide
    catalogs to the application.
    """

    def __init__(self):
        """Initialize the source model."""
        self.catalog_models = load_catalog_models()

    def get_source(self) -> Tuple[CatalogBase, str]:
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

    def __init__(self):
        """Initialize the URI source model."""
        super().__init__()
        self.uri = "http://localhost:8000"
        self.profile = ""
        self.selected_keys = []
        self.selected_model_name = None

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

    def is_configured(self) -> bool:
        """Check if the model is fully configured."""
        return bool(self.uri and self.selected_model_name)

    def get_source(self) -> Tuple[CatalogBase, str]:
        """Get a catalog source from the URI."""
        if not self.is_configured():
            raise ValueError("URI source model is not fully configured")

        catalog = from_uri(self.uri)
        label = f"Tiled: {self.uri}"

        if self.profile:
            catalog = catalog[self.profile]
            label += ":" + self.profile

        # Navigate through selected keys
        for key in self.selected_keys:
            catalog = catalog[key]
            label += ":" + key

        # Create the catalog with the selected model
        selected_model = self.catalog_models[self.selected_model_name]
        catalog = selected_model(catalog)

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

    def get_source(self) -> Tuple[CatalogBase, str]:
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

    def get_source(self) -> Tuple[CatalogBase, str]:
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

    def get_source(self) -> Tuple[CatalogBase, str]:
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

    def __init__(self, catalog_config: Dict[str, Any]):
        """
        Initialize the configuration source model.

        Parameters
        ----------
        catalog_config : Dict[str, Any]
            Configuration dictionary for the catalog
        """
        super().__init__()
        self.catalog_config = catalog_config
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
            model = URISourceModel()
            model.set_uri(self.catalog_config["url"])

            if self.catalog_config.get("catalog_keys"):
                if isinstance(self.catalog_config["catalog_keys"], list):
                    model.set_selected_keys(self.catalog_config["catalog_keys"])
                elif isinstance(self.catalog_config["catalog_keys"], str):
                    model.set_selected_keys([self.catalog_config["catalog_keys"]])

            model.set_selected_model(self.catalog_config["catalog_model"])
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

    def get_source(self) -> Tuple[CatalogBase, str]:
        """Get a catalog source from the configuration."""
        return self.source_model.get_source()
