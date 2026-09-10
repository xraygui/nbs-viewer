"""Qt run-list adapter over a :class:`RunCollection`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qtpy.QtCore import Qt
from qtpy.QtGui import QStandardItem, QStandardItemModel

from ...models.plot.run_source import RunSource

if TYPE_CHECKING:
    from ...models.plot.run_collection import RunCollection


class RunListItemModel(QStandardItemModel):
    """
    Sidebar rows for one run collection.

    Membership, visibility, keys and combine/freeze all live on
    :class:`RunCollection`, which is the only thing this adapter needs to
    see. It keeps ``QStandardItem`` rows in sync and exposes index helpers
    for the list view.

    Parameters
    ----------
    collection : RunCollection
        Membership and visibility this sidebar mirrors.
    """

    def __init__(self, collection: "RunCollection"):
        super().__init__()
        self._plot = collection

        self._plot.run_added.connect(self._on_session_run_added)
        self._plot.run_removed.connect(self._on_session_run_removed)
        self._plot.visible_runs_changed.connect(self._on_session_visible_changed)
        self.itemChanged.connect(self._on_item_changed)

        for run in self._plot.available_models:
            self._add_run_item(run)

    @property
    def collection(self) -> "RunCollection":
        """
        Return the observed run collection.
        """
        return self._plot

    def _add_run_item(self, run: RunSource) -> None:
        item = QStandardItem(run.display_name)
        item.setData(run.uid, Qt.UserRole)
        item.setData(run, Qt.UserRole + 1)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        item.setCheckState(
            Qt.Checked if run.uid in self._plot.visible_uids else Qt.Unchecked
        )
        self.appendRow(item)

    def _on_session_run_added(self, run: RunSource) -> None:
        self._add_run_item(run)

    def _on_session_run_removed(self, run: RunSource) -> None:
        for row in range(self.rowCount()):
            item = self.item(row)
            if item.data(Qt.UserRole) == run.uid:
                self.removeRow(row)
                break

    def _on_session_visible_changed(self, _visible_runs) -> None:
        visible = self._plot.visible_uids
        self.blockSignals(True)
        try:
            for row in range(self.rowCount()):
                item = self.item(row)
                uid = item.data(Qt.UserRole)
                item.setCheckState(
                    Qt.Checked if uid in visible else Qt.Unchecked
                )
        finally:
            self.blockSignals(False)

    def get_run_at_index(self, index):
        """
        Get the run object at the given index.

        Parameters
        ----------
        index : QModelIndex
            The model index

        Returns
        -------
        RunSource or None
            The run object or None if invalid index
        """
        if not index.isValid():
            return None
        item = self.itemFromIndex(index)
        if item:
            return item.data(Qt.UserRole + 1)
        return None

    def get_uid_at_index(self, index):
        """
        Get the UID at the given index.

        Parameters
        ----------
        index : QModelIndex
            The model index

        Returns
        -------
        str or None
            The UID or None if invalid index
        """
        if not index.isValid():
            return None
        item = self.itemFromIndex(index)
        if item:
            return item.data(Qt.UserRole)
        return None

    def find_index_by_uid(self, uid):
        """
        Find the model index for a given UID.

        Parameters
        ----------
        uid : str
            The UID to search for

        Returns
        -------
        QModelIndex
            The model index or invalid index if not found
        """
        for row in range(self.rowCount()):
            item = self.item(row)
            if item.data(Qt.UserRole) == uid:
                return self.indexFromItem(item)
        return self.index(-1, -1)

    def get_first_run(self):
        """
        Return the first run in the list, or ``None``.
        """
        index = self.index(0, 0)
        if not index.isValid():
            return None
        return self.get_run_at_index(index)

    def get_siblings_of_run(self, run):
        """
        Return the previous and next runs adjacent to ``run``.

        Parameters
        ----------
        run : RunSource
            Reference run.

        Returns
        -------
        list
            ``[previous, next]``, each ``None`` when absent.
        """
        index = self.find_index_by_uid(run.uid)
        if not index.isValid():
            return [None, None]
        siblings = []
        for offset in [-1, 1]:
            sibling_index = index.sibling(index.row() + offset, index.column())
            if sibling_index.isValid():
                sibling = self.get_run_at_index(sibling_index)
                siblings.append(sibling if sibling else None)
            else:
                siblings.append(None)
        return siblings

    def _on_item_changed(self, item) -> None:
        uid = item.data(Qt.UserRole)
        if uid:
            is_visible = item.checkState() == Qt.Checked
            self._plot.set_uids_visible([uid], is_visible)

