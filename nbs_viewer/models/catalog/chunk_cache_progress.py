"""
Qt signal bridge for in-flight Tiled chunk fetch status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from qtpy.QtCore import QObject, Signal


@dataclass(frozen=True)
class TiledFetchStatus:
    """
    Snapshot of an in-flight Tiled chunk fetch batch.

    Parameters
    ----------
    run_uid : str
        Run identifier.
    key : str
        Data key.
    pending_chunks : int
        Tiled chunks still outstanding in the current batch.
    batch_total : int
        Total chunks in the current batch.
    active : bool
        True while the batch is in progress.
    """

    run_uid: str
    key: str
    pending_chunks: int
    batch_total: int
    active: bool

    @property
    def loaded_chunks(self) -> int:
        """
        Return how many chunks in the batch have been loaded so far.
        """
        return max(0, self.batch_total - self.pending_chunks)

    def label_text(self) -> str:
        """
        Format short status text for a plot UI label.

        Returns
        -------
        str
            Empty when no Tiled chunks are waiting, otherwise
            ``Fetching loaded/total``.
        """
        if not self.active or self.batch_total <= 0:
            return ""

        if self.pending_chunks <= 0:
            return ""

        return f"Fetching {self.loaded_chunks}/{self.batch_total}"


L2CacheStatus = TiledFetchStatus


def format_tiled_fetch_status(
    run_uid: str,
    key: str,
    pending_chunks: int,
    batch_total: int,
    active: bool,
) -> TiledFetchStatus:
    """
    Build a :class:`TiledFetchStatus` instance.

    Parameters
    ----------
    run_uid : str
        Run identifier.
    key : str
        Data key.
    pending_chunks : int
        Chunks still to fetch from Tiled in this batch.
    batch_total : int
        Total chunks in this batch.
    active : bool
        Whether the batch is in progress.

    Returns
    -------
    TiledFetchStatus
    """
    return TiledFetchStatus(
        run_uid=run_uid,
        key=key,
        pending_chunks=pending_chunks,
        batch_total=batch_total,
        active=active,
    )


format_l2_cache_status = format_tiled_fetch_status


class ChunkCacheProgress(QObject):
    """
    Emit human-readable Tiled chunk fetch status updates for the plot UI.

    Parameters
    ----------
    parent : QObject, optional
        Qt parent object.
    """

    status_changed = Signal(object)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._last_status: Optional[TiledFetchStatus] = None

    def update(
        self,
        run_uid: str,
        key: str,
        pending_chunks: int,
        batch_total: int,
        active: bool,
    ) -> None:
        """
        Publish a new in-flight fetch status snapshot.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        pending_chunks : int
            Chunks still to fetch from Tiled in this batch.
        batch_total : int
            Total chunks in this batch.
        active : bool
            Whether the batch is in progress.
        """
        status = format_tiled_fetch_status(
            run_uid, key, pending_chunks, batch_total, active
        )
        if self._last_status is not None and self._last_status == status:
            return
        self._last_status = status
        self.status_changed.emit(status)

    def clear(self) -> None:
        """
        Clear the last published status and emit an empty label.
        """
        self._last_status = None
        self.status_changed.emit(
            TiledFetchStatus("", "", 0, 0, False)
        )
