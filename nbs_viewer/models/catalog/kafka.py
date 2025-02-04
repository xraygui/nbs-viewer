"""Kafka catalog implementation."""

from typing import Any, List, Optional, Generator, Tuple
from qtpy.QtCore import QObject, Signal

from .base import CatalogBase
from ..data import KafkaRun


class KafkaCatalog(CatalogBase):
    """
    Catalog implementation for Kafka streams.

    This class manages a collection of runs from a Kafka message stream,
    providing access to run data and metadata.
    """

    # Add new signal

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
        self._descriptors_map = {}
        self._runs = []
        # Connect to dispatcher
        self._dispatcher.subscribe(self._handle_document)
        self._dispatcher.start()

    def __getattr__(self, key):
        return getattr(self._run_map, key)

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

    def get_run_from_descriptor(self, doc):
        desc_uid = doc.get("descriptor")
        start_uid = self._descriptors_map.get(desc_uid, None)
        if start_uid in self._run_map:
            return self.get_run(start_uid)
        return None

    def add_descriptor(self, doc):
        desc_uid = doc.get("uid")
        start_uid = doc.get("run_start")
        self._descriptors_map[desc_uid] = start_uid

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
        # print(f"KafkaCatalog _handle_document {name}")
        if name == "start":
            run = KafkaRun(doc, doc.get("uid"))
            self._runs.append(run)
            self._run_map[run.uid] = run
            self.data_updated.emit()
            # Emit new signal when a run is added

        elif name == "stop":
            uid = doc.get("run_start")
            if uid in self._run_map:
                self._run_map[uid].process_stop(doc)
                self.data_updated.emit()
            else:
                # print(f"KafkaCatalog _handle_document unknown uid from stop doc: {uid}")
                pass
        elif name == "descriptor":
            uid = doc.get("run_start")
            try:
                run = self.get_run(uid)
                run.process_descriptor(doc)
                self.add_descriptor(doc)
                if doc.get("name") == "primary":
                    self.new_run_available.emit(uid)
            except KeyError:
                print(
                    f"KafkaCatalog _handle_document unknown uid from descriptor doc: {uid}"
                )

        elif name == "event":
            run = self.get_run_from_descriptor(doc)
            if run:
                run.process_event(doc)
            else:
                # print(f"KafkaCatalog _handle_document start_uid not found")
                pass
        elif name == "event_page":
            run = self.get_run_from_descriptor(doc)
            if run:
                run.process_event_page(doc)
            else:
                pass
                # print(f"KafkaCatalog _handle_document start_uid not found")

        else:
            print(f"KafkaCatalog _handle_document unknown name: {name}")

    def remove_runs(self, uids: List[str]) -> None:
        """Remove specified runs from the catalog.

        Parameters
        ----------
        uids : List[str]
            List of run UIDs to remove
        """
        # First, get the indices that will be removed
        indices_to_remove = []
        for i, run in enumerate(self._runs):
            if run.uid in uids:
                indices_to_remove.append(i)

        # Remove from highest index to lowest to maintain correct ordering
        for index in sorted(indices_to_remove, reverse=True):
            run = self._runs.pop(index)
            self._run_map.pop(run.uid)

            # Remove any descriptor mappings for this run
            desc_uids = [
                desc_uid
                for desc_uid, start_uid in self._descriptors_map.items()
                if start_uid == run.uid
            ]
            for desc_uid in desc_uids:
                self._descriptors_map.pop(desc_uid)

        # Emit signal after all removals are complete
        self.data_updated.emit()

    def remove_all_runs(self) -> None:
        """Remove all runs from the catalog."""
        self._run_map.clear()
        self._runs.clear()
        self._descriptors_map.clear()
        self.data_updated.emit()
