"""
Multi-ROI state model for the ROI workbench.

Owns the set of ROI entries, selection, and per-entry stale flags. The canvas
renders from this model; it does not store ROI geometry itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Iterator, List, Optional, Sequence, Tuple
from uuid import uuid4

from qtpy.QtCore import QObject, Signal

from .region import RectRegion, RegionDefinition

MaskMode = str
SpatialReduce = str

PLACEHOLDER_RECT = RectRegion(x0=0.0, x1=0.0, y0=0.0, y1=0.0)

DEFAULT_ROI_COLORS: Tuple[str, ...] = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)


@dataclass(frozen=True)
class RoiOperation:
    """
    Per-ROI reduction parameters.

    Parameters
    ----------
    mask_mode : str
        ``inside`` or ``outside``.
    profile_storage_axis : int or None
        Storage axis along which the profile is taken.
    spatial_reduce : str
        ``sum`` or ``mean``.
    span_full_profile_axis : bool
        Expand separable shapes along the in-plane profile axis.
    label : str
        Optional user label for preview and save.
    """

    mask_mode: MaskMode = "inside"
    profile_storage_axis: Optional[int] = None
    spatial_reduce: SpatialReduce = "sum"
    span_full_profile_axis: bool = True
    label: str = ""


@dataclass(frozen=True)
class RoiEntry:
    """
    One ROI in the set, including geometry and reduction options.

    Parameters
    ----------
    id : str
        Stable unique id.
    display_label : str
        Short label for list displays.
    color : str
        Overlay and preview color.
    region : RegionDefinition
        Geometry in matplotlib data coordinates.
    operation : RoiOperation
        Per-ROI reduction parameters.
    visible : bool
        Whether the overlay is drawn.
    view_fingerprint : tuple or None
        Coordinate-frame fingerprint when the geometry was committed.
    stale : bool
        True when the view frame no longer matches ``view_fingerprint``.
    """

    id: str
    display_label: str
    color: str
    region: RegionDefinition
    operation: RoiOperation = field(default_factory=RoiOperation)
    visible: bool = True
    view_fingerprint: Optional[tuple] = None
    stale: bool = False


class RoiSetModel(QObject):
    """
    Own the multi-ROI entry list and selection.

    Signals
    -------
    entries_changed : Signal
        Emitted when entries are added, removed, or cleared.
    entry_changed : Signal
        Emitted with an entry id when that entry is updated.
    selection_changed : Signal
        Emitted with the selected entry id, or ``None``.
    """

    entries_changed = Signal()
    entry_changed = Signal(str)
    selection_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: Dict[str, RoiEntry] = {}
        self._order: List[str] = []
        self._selected_id: Optional[str] = None
        self._color_index = 0
        self._label_index = 1

    @property
    def selected_id(self) -> Optional[str]:
        """
        Return the selected entry id, if any.
        """
        return self._selected_id

    def entries(self) -> Sequence[RoiEntry]:
        """
        Return entries in display order.
        """
        return tuple(self._entries[eid] for eid in self._order)

    def __iter__(self) -> Iterator[RoiEntry]:
        return iter(self.entries())

    def __len__(self) -> int:
        return len(self._order)

    def get(self, entry_id: str) -> Optional[RoiEntry]:
        """
        Return an entry by id.
        """
        return self._entries.get(entry_id)

    def selected_entry(self) -> Optional[RoiEntry]:
        """
        Return the selected entry, if any.
        """
        if self._selected_id is None:
            return None
        return self._entries.get(self._selected_id)

    def selected_region(self) -> Optional[RegionDefinition]:
        """
        Return the geometry of the selected entry, if any.
        """
        entry = self.selected_entry()
        if entry is None:
            return None
        return entry.region

    def next_color(self) -> str:
        """
        Return the next unused default overlay color.
        """
        color = DEFAULT_ROI_COLORS[self._color_index % len(DEFAULT_ROI_COLORS)]
        self._color_index += 1
        return color

    def add(
        self,
        region: RegionDefinition,
        *,
        display_label: Optional[str] = None,
        color: Optional[str] = None,
        operation: Optional[RoiOperation] = None,
        view_fingerprint: Optional[tuple] = None,
        select: bool = True,
    ) -> str:
        """
        Add a new ROI entry.

        Parameters
        ----------
        region : RegionDefinition
            Geometry in data coordinates.
        display_label : str, optional
            List label. Defaults to ``roi_N``.
        color : str, optional
            Overlay color. Defaults to the next palette color.
        operation : RoiOperation, optional
            Reduction parameters.
        view_fingerprint : tuple, optional
            Fingerprint of the view when the region was drawn.
        select : bool
            Whether to select the new entry.

        Returns
        -------
        str
            New entry id.
        """
        entry_id = str(uuid4())
        if display_label is None:
            display_label = f"roi_{self._label_index}"
            self._label_index += 1
        entry = RoiEntry(
            id=entry_id,
            display_label=display_label,
            color=color or self.next_color(),
            region=region,
            operation=operation or RoiOperation(),
            view_fingerprint=view_fingerprint,
            stale=False,
        )
        self._entries[entry_id] = entry
        self._order.append(entry_id)
        self.entries_changed.emit()
        if select:
            self.set_selected(entry_id)
        return entry_id

    def remove(self, entry_id: str) -> None:
        """
        Remove an entry by id.
        """
        if entry_id not in self._entries:
            return
        del self._entries[entry_id]
        self._order = [eid for eid in self._order if eid != entry_id]
        self.entries_changed.emit()
        if self._selected_id == entry_id:
            self.set_selected(self._order[-1] if self._order else None)

    def clear(self) -> None:
        """
        Remove every entry and clear selection.
        """
        if not self._entries:
            if self._selected_id is not None:
                self.set_selected(None)
            return
        self._entries.clear()
        self._order.clear()
        self.entries_changed.emit()
        self.set_selected(None)

    def set_selected(self, entry_id: Optional[str]) -> None:
        """
        Select an entry, or clear selection when ``entry_id`` is ``None``.
        """
        if entry_id is not None and entry_id not in self._entries:
            return
        if entry_id == self._selected_id:
            return
        self._selected_id = entry_id
        self.selection_changed.emit(entry_id)

    def update_entry(self, entry_id: str, **changes) -> Optional[RoiEntry]:
        """
        Replace fields on an entry and emit ``entry_changed``.

        Parameters
        ----------
        entry_id : str
            Entry to update.
        **changes
            Fields accepted by :class:`RoiEntry`.

        Returns
        -------
        RoiEntry or None
            Updated entry, or ``None`` if the id is unknown.
        """
        entry = self._entries.get(entry_id)
        if entry is None:
            return None
        updated = replace(entry, **changes)
        self._entries[entry_id] = updated
        self.entry_changed.emit(entry_id)
        return updated

    def update_region(
        self,
        entry_id: str,
        region: RegionDefinition,
        *,
        view_fingerprint: Optional[tuple] = None,
        clear_stale: bool = True,
    ) -> Optional[RoiEntry]:
        """
        Update an entry's geometry.

        Parameters
        ----------
        entry_id : str
            Entry to update.
        region : RegionDefinition
            New geometry.
        view_fingerprint : tuple, optional
            Fingerprint to store with the geometry.
        clear_stale : bool
            Clear the stale flag when the geometry is rewritten.

        Returns
        -------
        RoiEntry or None
            Updated entry, or ``None`` if the id is unknown.
        """
        changes = {"region": region}
        if view_fingerprint is not None:
            changes["view_fingerprint"] = view_fingerprint
        if clear_stale:
            changes["stale"] = False
        return self.update_entry(entry_id, **changes)

    def update_operation(
        self, entry_id: str, operation: RoiOperation
    ) -> Optional[RoiEntry]:
        """
        Update an entry's reduction parameters.
        """
        return self.update_entry(entry_id, operation=operation)

    def set_stale(self, entry_id: str, stale: bool = True) -> Optional[RoiEntry]:
        """
        Mark an entry stale or fresh.
        """
        entry = self._entries.get(entry_id)
        if entry is None or entry.stale == stale:
            return entry
        return self.update_entry(entry_id, stale=stale)

    def mark_stale_for_fingerprint(
        self, current_fingerprint: Optional[tuple]
    ) -> List[str]:
        """
        Mark entries whose stored fingerprint does not match the current view.

        Parameters
        ----------
        current_fingerprint : tuple or None
            Fingerprint of the active view, or ``None`` when unavailable.

        Returns
        -------
        list of str
            Ids newly marked stale.
        """
        newly_stale = []
        for entry in list(self.entries()):
            if entry.stale:
                continue
            stored = entry.view_fingerprint
            if stored is None or current_fingerprint is None or stored != current_fingerprint:
                self.set_stale(entry.id, True)
                newly_stale.append(entry.id)
        return newly_stale

    def remove_stale(self) -> int:
        """
        Remove every stale entry.

        Returns
        -------
        int
            Number of entries removed.
        """
        stale_ids = [entry.id for entry in self.entries() if entry.stale]
        for entry_id in stale_ids:
            self.remove(entry_id)
        return len(stale_ids)

    def set_or_replace_single(
        self,
        region: RegionDefinition,
        *,
        view_fingerprint: Optional[tuple] = None,
    ) -> str:
        """
        Update the selected entry, or add one when the set is empty.

        Parameters
        ----------
        region : RegionDefinition
            Drawn geometry.
        view_fingerprint : tuple, optional
            Fingerprint of the active view.

        Returns
        -------
        str
            Id of the updated or created entry.
        """
        selected = self.selected_entry()
        if selected is not None:
            self.update_region(
                selected.id,
                region,
                view_fingerprint=view_fingerprint,
            )
            return selected.id
        if self._order:
            entry_id = self._order[0]
            self.update_region(
                entry_id,
                region,
                view_fingerprint=view_fingerprint,
            )
            self.set_selected(entry_id)
            return entry_id
        return self.add(region, view_fingerprint=view_fingerprint)

    def add_placeholder_rect(
        self,
        *,
        operation: Optional[RoiOperation] = None,
    ) -> str:
        """
        Add a rectangle entry with empty geometry awaiting a draw.

        Parameters
        ----------
        operation : RoiOperation, optional
            Initial reduction parameters.

        Returns
        -------
        str
            New entry id.
        """
        return self.add(PLACEHOLDER_RECT, operation=operation)

    def entry_is_drawable(self, entry: RoiEntry) -> bool:
        """
        Return whether an entry has nonzero geometry for preview or overlay.
        """
        return entry.region.has_area()
