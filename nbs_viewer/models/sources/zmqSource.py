from typing import Tuple
from bluesky_widgets.qt.zmq_dispatcher import RemoteDispatcher as QtZMQRemoteDispatcher
from ..catalog.base import CatalogBase
from ..catalog.kafka import KafkaCatalog
from .base import SourceModel, CatalogLoadError


class ZMQSourceModel(SourceModel):
    """Model for Kafka catalog sources."""

    def __init__(self):
        """Initialize the Kafka source model."""
        super().__init__()

    def is_configured(self) -> bool:
        """Check if the model is fully configured."""
        return True

    def get_source(self, **kwargs) -> Tuple[CatalogBase, str]:
        try:
            zmq_dispatcher = QtZMQRemoteDispatcher("localhost:5578")
            label = "ZMQ: localhost:5578"
            # Create the Kafka catalog (poorly named -- really a live catalog)
            catalog = KafkaCatalog(zmq_dispatcher)
            return catalog, label
        except Exception as e:
            raise CatalogLoadError(f"ZMQ source model failed to load: {e}")