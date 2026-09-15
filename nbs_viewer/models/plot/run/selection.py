"""
Session key selection: a default plus full per-run overrides.

A ``QObject``: the selected keys are state the whole display reacts to, so
this is where ``selected_keys_changed`` lives. It used to live on
:class:`PlotSession`, which then had to subscribe to its own signal to
revalidate the selection when the available-key universe moved — the shape
that says the announcement is in the wrong object.

Selection is resolved *against* membership, so this object is constructed
with the :class:`RunCollection` and borrows two things from it: the
per-run key list that filters a resolved selection, and the notifications
that a run left or that the key universe changed. That is a real dependency,
not a convenience: a selection of keys means nothing without the runs the
keys belong to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, TYPE_CHECKING

from qtpy.QtCore import QObject, Signal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .collection import RunCollection


@dataclass(frozen=True)
class KeySelection:
    """
    Selected x, y, and norm keys for one run or the session default.

    Parameters
    ----------
    x : tuple of str
        X-axis keys.
    y : tuple of str
        Y-axis keys.
    norm : tuple of str
        Normalization keys.
    """

    x: Tuple[str, ...] = ()
    y: Tuple[str, ...] = ()
    norm: Tuple[str, ...] = ()

    @classmethod
    def from_lists(
        cls,
        x_keys: Optional[Sequence[str]] = None,
        y_keys: Optional[Sequence[str]] = None,
        norm_keys: Optional[Sequence[str]] = None,
    ) -> "KeySelection":
        """
        Build a selection from list-like sequences.

        Parameters
        ----------
        x_keys, y_keys, norm_keys : sequence of str, optional
            Key lists.

        Returns
        -------
        KeySelection
            Frozen selection.
        """
        return cls(
            tuple(x_keys or ()),
            tuple(y_keys or ()),
            tuple(norm_keys or ()),
        )

    def as_lists(self) -> Tuple[List[str], List[str], List[str]]:
        """
        Return mutable list copies of each axis.

        Returns
        -------
        tuple of list of str
            ``(x, y, norm)``.
        """
        return list(self.x), list(self.y), list(self.norm)

    def filtered(self, available: Iterable[str]) -> "KeySelection":
        """
        Return this selection restricted to ``available`` keys.

        Parameters
        ----------
        available : iterable of str
            Keys that exist on the target run.

        Returns
        -------
        KeySelection
            Filtered copy.
        """
        allowed = set(available)
        return KeySelection(
            tuple(k for k in self.x if k in allowed),
            tuple(k for k in self.y if k in allowed),
            tuple(k for k in self.norm if k in allowed),
        )


class Selection(QObject):
    """
    Session default key selection plus full per-uid overrides.

    :meth:`selection_for` returns the override if present, otherwise the
    default, filtered against the keys that run actually has.
    :meth:`clear_overrides` implements "Link Runs".

    Parameters
    ----------
    collection : RunCollection
        Membership this selection resolves against.
    parent : QObject, optional
        Qt parent.
    """

    selected_keys_changed = Signal(list, list, list)

    def __init__(
        self,
        collection: "RunCollection",
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._collection = collection
        self._default = KeySelection()
        self._overrides: Dict[str, KeySelection] = {}
        self._retain = False

        collection.run_removed.connect(self._on_run_removed)
        collection.available_keys_changed.connect(self._revalidate_default)
        collection.available_runs_changed.connect(self._maybe_apply_run_default)
        collection.visible_runs_changed.connect(self._maybe_apply_run_default)

    @property
    def default(self) -> KeySelection:
        """
        Return the session-default selection.
        """
        return self._default

    @property
    def selected_keys(self) -> Tuple[List[str], List[str], List[str]]:
        """
        Return session-default ``(x_keys, y_keys, norm_keys)`` copies.
        """
        return self._default.as_lists()

    def get_selected_keys(self) -> Tuple[List[str], List[str], List[str]]:
        """
        Return session-default selected x, y, and norm keys.
        """
        return self._default.as_lists()

    def set_selected_keys(
        self,
        x_keys: Sequence[str],
        y_keys: Sequence[str],
        norm_keys: Optional[Sequence[str]] = None,
    ) -> bool:
        """
        Replace the session-default selection.

        Guards on real change, as the view intent's mutators do, so a
        redundant set does not restart the fetch of every trace.

        Parameters
        ----------
        x_keys, y_keys : sequence of str
            Default axis keys.
        norm_keys : sequence of str, optional
            Default norm keys.

        Returns
        -------
        bool
            True if the selection changed and was announced.
        """
        wanted = KeySelection.from_lists(x_keys, y_keys, norm_keys)
        if wanted == self._default:
            return False
        self._default = wanted
        self._announce(self._default)
        return True

    def set_selection_for(
        self,
        uid: str,
        x_keys: Sequence[str],
        y_keys: Sequence[str],
        norm_keys: Optional[Sequence[str]] = None,
    ) -> bool:
        """
        Store a full per-run override.

        Parameters
        ----------
        uid : str
            Run uid.
        x_keys, y_keys : sequence of str
            Override axis keys.
        norm_keys : sequence of str, optional
            Override norm keys.

        Returns
        -------
        bool
            True if the override changed and was announced.
        """
        wanted = KeySelection.from_lists(x_keys, y_keys, norm_keys)
        if self._overrides.get(uid) == wanted:
            return False
        self._overrides[uid] = wanted
        self._announce(self.selection_for(uid))
        return True

    def clear_overrides(self) -> bool:
        """
        Clear all per-run overrides (Link Runs).

        Returns
        -------
        bool
            True if there were overrides to clear.
        """
        if not self._overrides:
            return False
        self._overrides.clear()
        self._announce(self._default)
        return True

    def selection_for(self, uid: str) -> KeySelection:
        """
        Resolve the selection for ``uid``.

        Parameters
        ----------
        uid : str
            Run uid.

        Returns
        -------
        KeySelection
            Override or default, filtered to the keys that run has.
        """
        sel = self._overrides.get(uid, self._default)
        source = self._collection.get(uid)
        if source is None:
            return sel
        return sel.filtered(source.available_keys)

    @property
    def retain_selection(self) -> bool:
        """
        Whether to keep selected keys when the available-key universe empties.
        """
        return self._retain

    def set_retain_selection(self, enabled: bool) -> None:
        """
        Set whether to retain key selection when available keys clear.

        Parameters
        ----------
        enabled : bool
            Retain selection when True.
        """
        self._retain = enabled

    def _announce(self, selection: KeySelection) -> None:
        x, y, norm = selection.as_lists()
        self.selected_keys_changed.emit(x, y, norm)

    def _on_run_removed(self, run_model) -> None:
        self._overrides.pop(run_model.uid, None)

    def _revalidate_default(self) -> None:
        """
        Drop default keys the available-key universe no longer offers.
        """
        available_keys = self._collection.available_keys
        if not available_keys:
            if not self._retain and len(self._collection) == 0:
                self.set_selected_keys([], [], [])
            return

        default = self._default
        self.set_selected_keys(
            [k for k in default.x if k in available_keys],
            [k for k in default.y if k in available_keys],
            [k for k in default.norm if k in available_keys],
        )

    def _maybe_apply_run_default(self, *_args) -> None:
        """
        Adopt the sole member run's own default selection, if nothing is set.
        """
        if self._retain:
            return
        default = self._default
        if default.x or default.y or default.norm:
            return
        models = self._collection.available_models
        if len(models) != 1:
            return
        x_keys, y_keys, norm_keys = models[0].run.get_default_selection()
        self.set_selected_keys(x_keys, y_keys, norm_keys)
