"""Kafka catalog implementation."""

from typing import Any, List, Optional, Generator, Tuple
from qtpy.QtCore import QObject

from .base import CatalogBase
from .table import CatalogTableModel
from ..data import KafkaRun


class KafkaCatalog(CatalogBase):
    """
    Catalog implementation for Kafka streams.

    This class manages a collection of runs from a Kafka message stream,
    providing access to run data and metadata.
    """

    def __init__(self, dispatcher: Any, parent: Optional[QObject] = None):
        """
        Initialize the catalog.

        Parameters
        ----------
        dispatcher : Any
            The Kafka message dispatcher.
        parent : QObject, optional
            Parent object, by default None.
        """
        super().__init__(parent)
        self._dispatcher = dispatcher
        self._run_map = {}
        self._runs = []
        # Connect to dispatcher
        self._dispatcher.subscribe(self._handle_document)

    @property
    def columns(self) -> List[str]:
        """Get column names for display."""
        return KafkaRun.to_header()

    def get_runs(self) -> List[KafkaRun]:
        """Get all available runs."""
        return self._runs

    def get_run(self, uid: str) -> KafkaRun:
        """
        Get a specific run by UID.

        Parameters
        ----------
        uid : str
            The run's unique identifier.

        Returns
        -------
        KafkaRun
            The requested run.

        Raises
        ------
        KeyError
            If run not found.
        """
        if uid not in self._run_map:
            raise KeyError(f"No run found with UID {uid}")
        return self._run_map[uid]

    def items_slice(
        self, s: slice
    ) -> Generator[Tuple[str, KafkaRun], None, None]:  # type: ignore
        """
        Get a slice of items from the catalog.

        For Kafka catalogs, this is a simple slice of the in-memory runs.

        Parameters
        ----------
        s : slice
            The slice to get.

        Yields
        ------
        Tuple[str, KafkaRun]
            Tuples of (key, run) pairs.
        """
        runs = self._runs[s]
        for run in runs:
            yield run.uid, run

    def _handle_document(self, name: str, doc: dict) -> None:
        """
        Handle incoming Kafka documents.

        Parameters
        ----------
        name : str
            Document type name.
        doc : dict
            Document content.
        """
        if name == "start":
            run = KafkaRun(doc)
            self._runs.append(run)
            self._run_map[run.uid] = run
            self.data_updated.emit()

        elif name == "stop":
            uid = doc.get("run_start")
            if uid in self._run_map:
                self._run_map[uid].add_stop(doc)
                self.data_updated.emit()

        elif name == "descriptor":
            uid = doc.get("run_start")
            if uid in self._run_map:
                self._run_map[uid].add_descriptor(doc)

        elif name == "event":
            desc = doc.get("descriptor")
            if desc in self._run_map:
                self._run_map[desc].add_event(doc)
