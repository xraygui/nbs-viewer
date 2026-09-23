"""
The run classes: one catalog entry, as the rest of the application reads it.

A re-export surface, unlike the packages under ``models/plot``. These three
are the whole of what ``models/catalog`` asks for, and naming them here means
a catalog imports a run rather than a module path.
"""

from .bluesky import BlueskyRun
from .nbs import NBSRun
from .kafka import KafkaRun

__all__ = ["BlueskyRun", "NBSRun", "KafkaRun"]
