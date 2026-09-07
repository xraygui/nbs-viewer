"""Session key selection: default plus per-run overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


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


@dataclass
class Selection:
    """
    Session default key selection plus full per-uid overrides.

    ``selection_for(uid, available)`` returns the override if present,
    otherwise the default, then filters against ``available``.
    ``clear_overrides()`` implements "Link Runs".
    """

    default: KeySelection = field(default_factory=KeySelection)
    overrides: Dict[str, KeySelection] = field(default_factory=dict)

    def set_default(
        self,
        x_keys: Sequence[str],
        y_keys: Sequence[str],
        norm_keys: Optional[Sequence[str]] = None,
    ) -> None:
        """
        Replace the session default selection.

        Parameters
        ----------
        x_keys, y_keys : sequence of str
            Default axis keys.
        norm_keys : sequence of str, optional
            Default norm keys.
        """
        self.default = KeySelection.from_lists(x_keys, y_keys, norm_keys)

    def set_override(
        self,
        uid: str,
        x_keys: Sequence[str],
        y_keys: Sequence[str],
        norm_keys: Optional[Sequence[str]] = None,
    ) -> None:
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
        """
        self.overrides[uid] = KeySelection.from_lists(x_keys, y_keys, norm_keys)

    def clear_override(self, uid: str) -> None:
        """
        Remove the override for one uid, if any.

        Parameters
        ----------
        uid : str
            Run uid.
        """
        self.overrides.pop(uid, None)

    def clear_overrides(self) -> None:
        """
        Clear all per-run overrides (Link Runs).
        """
        self.overrides.clear()

    def drop_uid(self, uid: str) -> None:
        """
        Drop override state when a run leaves membership.

        Parameters
        ----------
        uid : str
            Removed run uid.
        """
        self.overrides.pop(uid, None)

    def selection_for(
        self,
        uid: str,
        available: Optional[Iterable[str]] = None,
    ) -> KeySelection:
        """
        Resolve selection for ``uid``.

        Parameters
        ----------
        uid : str
            Run uid.
        available : iterable of str, optional
            If given, filter the resolved selection to these keys.

        Returns
        -------
        KeySelection
            Override or default, optionally filtered.
        """
        sel = self.overrides.get(uid, self.default)
        if available is None:
            return sel
        return sel.filtered(available)
