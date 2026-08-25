from typing import Tuple
import uuid
from os.path import exists

import nslsii.kafka_utils
from bluesky_widgets.qt.kafka_dispatcher import QtRemoteDispatcher
from ..catalog.base import CatalogBase
from ..catalog.kafka import KafkaCatalog
from .base import SourceModel, CatalogLoadError


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
            raise CatalogLoadError("Kafka source model is not fully configured")
        label = f"Kafka: {self.beamline_acronym}"

        # Read Kafka configuration
        try:
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
        except Exception as e:
            raise CatalogLoadError(f"Kafka source model failed to load: {e}")