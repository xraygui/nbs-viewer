"""
Plot session: membership, visibility, selection, view, and the trace set.

Owns a :class:`RunCollection`, the visible-uid set, selected keys, transform,
cube/slice/crop view state, the :class:`TraceSet`, and the ROI set.
:class:`RunListItemModel` (in ``views/``) is a Qt facade that observes it.

``rebuild()`` is the sole mutator of trace *membership*. Retention is
membership × selection; visibility only filters drawing.

Key selection is a session :class:`Selection` (default + per-uid overrides).
Freeze and unlinked display read :meth:`selection_for`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple, Union

from qtpy.QtCore import QObject, Signal

from nbs_viewer.models.catalog.base import CatalogRun
from nbs_viewer.utils import print_debug

from nbs_viewer.models.cache.chunk_cache_progress import (
    ChunkCacheProgress,
    TiledFetchStatus,
    aggregate_tiled_fetch_label,
)
from .combinedRunSource import CombinationMethod, CombinedRunSource

from .frozenRunSource import FrozenRunSource
from .plot_request import (
    PlotRequest,
    TraceKey,
    build_plot_request,
    crop_from_region,
    roi_profile_request,
)
from .plot_view_frame import (
    PlotViewFrame,
    frame_from_bundle,
    view_fingerprint_from_bundle,
)
from .region import RectRegion, RegionDefinition, expand_region_for_profile
from .roi_set import RoiEntry, RoiSetModel
from .run_collection import RunCollection
from .runSource import RunSource
from .selection import KeySelection, Selection
from .trace import Trace
from .trace_set import TraceSet
from .view_spec import (
    ViewCrop,
    classify_profile_kind,
    default_profile_label,
    is_plot_plane_storage_axis,
    scan_profile_storage_axis,
)

if TYPE_CHECKING:
    from .frozen_spectrum import FrozenSpectrum
    from .plot_geometry import PlotBundle


class PlotSession(QObject):
    """
    One plot session (membership + plot state).

    Parameters
    ----------
    is_main_display : bool, optional
        If True, newly added runs become visible by default.
    single_selection_mode : bool, optional
        If True, only one run can be visible at a time.
    parent : QObject, optional
        Qt parent.
    """

    selected_keys_changed = Signal(list, list, list)
    transform_changed = Signal(dict)
    request_plot_update = Signal()
    cube_view_changed = Signal(object)
    view_crop_changed = Signal(object)
    region_status_changed = Signal(str)
    region_invalidation_requested = Signal(str)
    roi_draw_enabled_changed = Signal(bool)
    ellipse_circle_locked_changed = Signal(bool)
    roi_live_region_sync_requested = Signal()
    available_keys_changed = Signal()
    frozen_spectra_changed = Signal()
    run_added = Signal(object)
    run_removed = Signal(object)
    available_runs_changed = Signal(list)
    visible_runs_changed = Signal(set)
    cache_status_changed = Signal(str)

    def __init__(
        self,
        is_main_display: bool = False,
        single_selection_mode: bool = False,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._collection = RunCollection()
        self._is_main_display = is_main_display
        self._single_selection_mode = single_selection_mode
        self._available_keys: List[str] = []
        self._auto_add = True
        self._visible_uids: Set[str] = set()
        self._roi_set = RoiSetModel(parent=self)

        self._selection = Selection()
        self._retain_selection = False
        self._transform = {"enabled": False, "text": ""}

        self._dimension = 1
        self._slice = None
        self._cube_view_spec = None
        self._view_crop: Optional[ViewCrop] = None
        self._view_crop_key: Optional[tuple] = None
        self._roi_draw_enabled = False
        self._ellipse_circle_locked = False

        self._traces = TraceSet(parent=self)
        self._connected_run_uids = set()

        self._progress_sources: Dict[int, ChunkCacheProgress] = {}
        self._cache_statuses: Dict[int, TiledFetchStatus] = {}


        self.available_keys_changed.connect(self._on_available_keys_changed)
        self.cube_view_changed.connect(self._on_cube_view_changed_for_region)
        self.selected_keys_changed.connect(self._on_selected_keys_changed_for_region)
        self.run_added.connect(self._refresh_cache_progress_connections)
        self.run_removed.connect(self._refresh_cache_progress_connections)
        self._refresh_cache_progress_connections()

    @property
    def collection(self) -> RunCollection:
        """
        Return the owned run collection.
        """
        return self._collection

    @property
    def visible_uids(self) -> Set[str]:
        """
        Return visible run uids.
        """
        return set(self._visible_uids)

    @property
    def available_keys(self) -> List[str]:
        """
        Return the available-key universe (visible catalog-key intersection).
        """
        return list(self._available_keys)

    @property
    def available_models(self) -> List[RunSource]:
        """
        Return all member run models.
        """
        return self._collection.sources()

    @property
    def available_runs(self) -> List[CatalogRun]:
        """
        Return underlying CatalogRun objects for all members.
        """
        return [model._run for model in self._collection.sources()]

    @property
    def available_uids(self) -> List[str]:
        """
        Return member uids in order.
        """
        return self._collection.uids()

    @property
    def visible_models(self) -> List[RunSource]:
        """
        Return visible run models.
        """
        return [
            model
            for model in self._collection.sources()
            if model.uid in self._visible_uids
        ]

    @property
    def visible_runs(self) -> Set[str]:
        """
        Return visible run uids (alias of :attr:`visible_uids`).
        """
        return set(self._visible_uids)

    @property
    def auto_add(self) -> bool:
        """
        Whether newly added runs become visible automatically.
        """
        return self._auto_add

    def set_auto_add(self, enabled: bool) -> None:
        """
        Set whether newly added runs become visible automatically.

        Parameters
        ----------
        enabled : bool
            When True, new runs are checked/visible on add.
        """
        self._auto_add = enabled

    def set_dynamic_update(self, enabled: bool) -> None:
        """
        Set dynamic update state on every member source.

        Parameters
        ----------
        enabled : bool
            Whether to enable dynamic updates.
        """
        for model in self._collection.sources():
            model.set_dynamic(enabled)

    @property
    def dynamic_update(self) -> bool:
        """
        Whether dynamic update is enabled on all members.
        """
        models = self._collection.sources()
        return all(model.dynamic_update for model in models) if models else True

    def update_available_keys(self) -> None:
        """
        Update the intersection of catalog keys among visible runs.
        """
        runs = self.visible_models
        if not runs:
            if self._available_keys:
                self._available_keys = []
                self.available_keys_changed.emit()
            return

        first_run = runs[0]
        print_debug(
            "PlotSession.update_available_keys",
            f"available_keys from first_run.uid {first_run.uid}: "
            f"{first_run.available_keys}",
            "run",
        )
        available_keys = list(first_run.catalog_keys)
        for run in runs[1:]:
            available_keys = [
                key for key in available_keys if key in run.catalog_keys
            ]

        if available_keys != self._available_keys:
            self._available_keys = available_keys
            self.available_keys_changed.emit()

    def synthetic_display_entries(self):
        """
        Return frozen stack spectra for visible runs.

        Returns
        -------
        list of tuple
            ``(run_model, key, display_label)`` entries for Run Display.
        """
        entries = []
        runs = self.visible_models
        multi = len(runs) > 1
        for run_model in runs:
            for entry in run_model.frozen_spectra():
                if entry.kind != "stack_spectrum":
                    continue
                label = entry.label
                if multi:
                    label = f"{run_model.scan_id} · {label}"
                entries.append((run_model, entry.key, label))
        return entries

    def _connect_run_keys(self, run_model: RunSource) -> None:
        run_model.available_keys_changed.connect(self.update_available_keys)
        run_model.frozen_spectra_changed.connect(self._on_frozen_spectra_changed)

    def _disconnect_run_keys(self, run_model: RunSource) -> None:
        try:
            run_model.available_keys_changed.disconnect(self.update_available_keys)
        except (TypeError, RuntimeError):
            pass
        try:
            run_model.frozen_spectra_changed.disconnect(
                self._on_frozen_spectra_changed
            )
        except (TypeError, RuntimeError):
            pass

    def _on_frozen_spectra_changed(self) -> None:
        self.frozen_spectra_changed.emit()
        self.rebuild()
        self.request_plot_update.emit()

    def add_runs(
        self, run_list: Union[List[CatalogRun], List[RunSource]]
    ) -> None:
        """
        Add CatalogRun or RunSource instances to the session.

        Parameters
        ----------
        run_list : list of CatalogRun or RunSource
            Runs to add.
        """
        print_debug("PlotSession.add_runs", f"Adding {len(run_list)} runs", "run")
        run_list = sorted(run_list, key=lambda x: x.scan_id)
        uid_list = []
        for run in run_list:
            uid = run.uid
            uid_list.append(uid)
            if uid in self._collection:
                print_debug(
                    "PlotSession.add_runs", f"Run {uid} already in model", "run"
                )
                continue

            run_model = self._collection.wrap(run)
            self._connect_run_keys(run_model)
            self._collection.add(run_model)
            self._attach_run_model(run_model)
            self.run_added.emit(run_model)

        self.update_available_keys()

        if self._is_main_display or self._auto_add:
            self.set_uids_visible(uid_list, True)
        else:
            self._maybe_apply_default_selection()
            self.rebuild()
            self.request_plot_update.emit()

        self.available_runs_changed.emit(self.available_runs)

    def add_run(self, run: Union[CatalogRun, RunSource]) -> None:
        """
        Add a single run to the session.

        Parameters
        ----------
        run : CatalogRun or RunSource
            Run to add.
        """
        self.add_runs([run])

    def validate_combine(self, runs: List[RunSource]) -> None:
        """
        Check whether runs can be combined.

        Parameters
        ----------
        runs : list of RunSource
            Candidate source runs.
        """
        self._collection.validate_combine(runs)

    def combine_runs(
        self,
        runs: List[RunSource],
        method: CombinationMethod = CombinationMethod.AVERAGE,
        expression: Optional[str] = None,
    ) -> CombinedRunSource:
        """
        Build a combined run via the collection and add it.

        Parameters
        ----------
        runs : list of RunSource
            Source runs to combine.
        method : CombinationMethod, optional
            Combination method, by default AVERAGE.
        expression : str, optional
            Expression used when method is EXPRESSION.

        Returns
        -------
        CombinedRunSource
            The combined run that was added.
        """
        combined = self._collection.make_combined(
            runs, method=method, expression=expression
        )
        self.add_run(combined)
        return combined

    def freeze_runs(self, runs: List[RunSource]) -> List[FrozenRunSource]:
        """
        Freeze selected Y keys via the collection and add the results.

        Parameters
        ----------
        runs : list of RunSource
            Runs whose currently selected Y keys should be frozen.

        Returns
        -------
        list of FrozenRunSource
            Frozen runs that were added.
        """
        to_freeze = []
        for model in runs:
            sel = self.selection_for(model.uid)
            for key in sel.y:
                to_freeze.append((model, key))
        frozen_runs = self._collection.make_frozen(to_freeze)
        if frozen_runs:
            self.add_runs(frozen_runs)
        return frozen_runs

    def remove_uids(self, uid_list) -> None:
        """
        Remove runs from the session by uid.

        Parameters
        ----------
        uid_list : list of str
            UIDs to remove.
        """
        print_debug(
            "PlotSession.remove_uids",
            f"Removing uids {uid_list}",
            category="runlist",
        )
        for uid in uid_list:
            run_model = self._collection.remove(uid)
            if run_model is None:
                continue
            self._disconnect_run_keys(run_model)
            self._detach_run_model(run_model)
            run_model.cleanup()
            self._visible_uids.discard(uid)
            self._selection.drop_uid(uid)
            self.run_removed.emit(run_model)

        self.update_available_keys()
        self.visible_runs_changed.emit(self.visible_runs)
        self.available_runs_changed.emit(self.available_runs)
        self.rebuild()
        self.request_plot_update.emit()

    def remove_run(self, run: Union[CatalogRun, RunSource]) -> None:
        """
        Remove a single run by uid.

        Parameters
        ----------
        run : CatalogRun or RunSource
            Run to remove.
        """
        self.remove_uids([run.uid])

    def set_runs(self, run_list, display_id="main") -> None:
        """
        Replace membership with ``run_list``.

        Parameters
        ----------
        run_list : list
            CatalogRun objects that should remain.
        display_id : str, optional
            Unused; kept for API compatibility.
        """
        print_debug("PlotSession.set_runs", f"Setting runs {len(run_list)}", "run")
        current_uids = {run.uid for run in run_list}
        existing_uids = set(self._collection.uids())
        self.remove_uids(list(existing_uids - current_uids))
        self.add_runs(run_list)
        self.cleanup_state()

    def set_uids_visible(self, uids, is_visible: bool) -> None:
        """
        Set visibility for specific run uids.

        Parameters
        ----------
        uids : list of str
            UIDs to update.
        is_visible : bool
            New visibility state.
        """
        print_debug(
            "PlotSession.set_uids_visible",
            f"Setting uids {uids} to {is_visible}",
            category="runlist",
        )
        if self._single_selection_mode and is_visible and uids:
            all_uids = list(self._collection.uids())
            for uid in all_uids:
                self._visible_uids.discard(uid)

            first_uid = uids[0]
            if first_uid in self._collection:
                self._visible_uids.add(first_uid)
        else:
            for uid in uids:
                if uid not in self._collection:
                    continue
                if is_visible:
                    self._visible_uids.add(uid)
                else:
                    self._visible_uids.discard(uid)

        self.update_available_keys()
        self.visible_runs_changed.emit(self.visible_runs)
        self._maybe_apply_default_selection()
        self.rebuild()
        self.request_plot_update.emit()
        print_debug(
            "PlotSession.set_uids_visible",
            f"visible_runs_changed uids={uids} visible={is_visible}",
            category="plots",
        )

    def set_run_visible(
        self, run: Union[CatalogRun, RunSource], is_visible: bool
    ) -> None:
        """
        Update visibility for one run.

        Parameters
        ----------
        run : CatalogRun or RunSource
            Run to update.
        is_visible : bool
            New visibility state.
        """
        self.set_uids_visible([run.uid], is_visible)

    def cleanup_state(self) -> None:
        """
        Drop visible uids that are no longer members.
        """
        valid_uids = set(self._collection.uids())
        self._visible_uids.intersection_update(valid_uids)

    @property
    def roi_set(self) -> RoiSetModel:
        """
        Return the ROI set owned by this plot session.
        """
        return self._roi_set

    @property
    def traces(self) -> TraceSet:
        """
        Return the live :class:`TraceSet`, keyed by :class:`TraceKey`.
        """
        return self._traces

    @property
    def retain_selection(self) -> bool:
        """
        Whether to keep selected keys when the available-key universe empties.
        """
        return self._retain_selection

    def set_retain_selection(self, enabled: bool) -> None:
        """
        Set whether to retain key selection when available keys clear.

        Parameters
        ----------
        enabled : bool
            Retain selection when True.
        """
        self._retain_selection = enabled

    @property
    def transform(self) -> dict:
        """
        Current transform state with defaults.
        """
        return {**{"enabled": False, "text": ""}, **self._transform}

    def set_transform(self, transform_state: dict) -> None:
        """
        Set transform state for the session.

        Parameters
        ----------
        transform_state : dict
            Transform configuration with ``enabled`` and ``text``.
        """
        self._transform = transform_state.copy()
        self.transform_changed.emit(self.transform)
        self._refresh_held_requests()
        self.request_plot_update.emit()
        print_debug(
            "PlotSession.set_transform",
            "applied (request refresh via transform_changed)",
            category="plots",
        )

    @property
    def selected_keys(self) -> tuple:
        """
        Return session-default ``(x_keys, y_keys, norm_keys)`` copies.
        """
        return self._selection.default.as_lists()

    def get_selected_keys(self):
        """
        Return session-default selected x, y, and norm keys.
        """
        return self._selection.default.as_lists()

    def selection_for(self, uid: str) -> KeySelection:
        """
        Resolve selection for ``uid`` (override or default, filtered).

        Parameters
        ----------
        uid : str
            Run uid.

        Returns
        -------
        KeySelection
            Filtered selection for that run.
        """
        source = self._collection.get(uid)
        available = None
        if source is not None:
            available = source.available_keys
        return self._selection.selection_for(uid, available)

    def set_selection_for(
        self,
        uid: str,
        x_keys: List[str],
        y_keys: List[str],
        norm_keys: Optional[List[str]] = None,
    ) -> None:
        """
        Set a per-run selection override and rebuild.

        Parameters
        ----------
        uid : str
            Run uid.
        x_keys, y_keys : list of str
            Axis keys.
        norm_keys : list of str, optional
            Normalization keys.
        """
        self._selection.set_override(uid, x_keys, y_keys, norm_keys)
        self.rebuild()
        sel = self.selection_for(uid)
        self.selected_keys_changed.emit(list(sel.x), list(sel.y), list(sel.norm))
        self.request_plot_update.emit()

    def clear_selection_overrides(self) -> None:
        """
        Clear per-run overrides (Link Runs) and rebuild from the default.
        """
        self._selection.clear_overrides()
        self.rebuild()
        x, y, n = self._selection.default.as_lists()
        self.selected_keys_changed.emit(x, y, n)
        self.request_plot_update.emit()

    def is_key_selected(self, key: str, axis: str) -> bool:
        """
        Return whether a key is selected on the session default.

        Parameters
        ----------
        key : str
            Data key.
        axis : str
            One of ``'x'``, ``'y'``, or ``'norm'``.
        """
        default = self._selection.default
        if axis == "x":
            return key in default.x
        if axis == "y":
            return key in default.y
        if axis == "norm":
            return key in default.norm
        return False

    def set_selected_keys(
        self,
        x_keys: List[str],
        y_keys: List[str],
        norm_keys: Optional[List[str]] = None,
        force_update: bool = False,
    ) -> None:
        """
        Set the session-default key selection.

        Parameters
        ----------
        x_keys : list of str
            X-axis keys.
        y_keys : list of str
            Y-axis keys.
        norm_keys : list of str, optional
            Normalization keys.
        force_update : bool, optional
            Accepted for API compatibility; plot refresh is always requested.
        """
        self._selection.set_default(x_keys, y_keys, norm_keys)
        self.rebuild()
        x, y, n = self._selection.default.as_lists()
        self.selected_keys_changed.emit(x, y, n)
        print_debug(
            "PlotSession.set_selected_keys",
            f"request_plot_update x={x_keys} y={y_keys} norm={norm_keys}",
            category="plots",
        )
        self.request_plot_update.emit()

    @property
    def dimension(self) -> int:
        """
        Plot dimensionality (1 or 2).
        """
        return self._dimension

    @property
    def slice(self):
        """
        Current load slice info.
        """
        return self._slice

    @property
    def cube_view_spec(self):
        """
        Current projection, if any.
        """
        return self._cube_view_spec

    def set_view_state(
        self,
        indices=None,
        dimension: Optional[int] = None,
        cube_view_spec: Optional["Projection"] = None,
    ) -> None:
        """
        Update slice, plot dimension, and projection.

        Parameters
        ----------
        indices : optional
            Load slice info.
        dimension : int, optional
            Plot dimensionality.
        cube_view_spec : Projection, optional
            N-D view specification.
        """
        changed = False
        if dimension is not None and dimension != self._dimension:
            self._dimension = dimension
            changed = True
            if dimension != 2:
                self.invalidate_all_region_state("switched out of 2D mode")
        if indices != self._slice:
            self._slice = indices
            changed = True
        if cube_view_spec != self._cube_view_spec:
            self._cube_view_spec = cube_view_spec
            changed = True
            self.cube_view_changed.emit(self._cube_view_spec)

        if changed:
            self._refresh_held_requests()
            self.request_plot_update.emit()

    @property
    def view_crop(self) -> Optional[ViewCrop]:
        """
        Active persistent view crop, if any.
        """
        return self._view_crop

    def set_view_crop(
        self,
        crop: Optional[ViewCrop],
        source_key: Optional[tuple] = None,
    ) -> None:
        """
        Set or clear the persistent view crop.

        Parameters
        ----------
        crop : ViewCrop or None
            Crop to apply, or ``None`` to clear.
        source_key : tuple, optional
            ``(xkey, ykey, uid)`` of the trace the crop was drawn on. The
            crop itself is storage indices on that trace's plot plane and
            means nothing on another one.
        """
        self._view_crop = crop
        self._view_crop_key = source_key if crop is not None else None
        self.view_crop_changed.emit(crop)
        self._refresh_held_requests()
        self.request_plot_update.emit()

    def clear_view_crop(self) -> None:
        """
        Clear the persistent view crop when one is set.
        """
        if self._view_crop is None:
            return
        self.set_view_crop(None)

    def crop_applies_to(self, trace_key: TraceKey) -> bool:
        """
        Return whether the active crop was drawn on this trace.

        Parameters
        ----------
        trace_key : TraceKey
            Trace identity to test.

        Returns
        -------
        bool
            True when a crop is active and names this trace.
        """
        return (
            self._view_crop is not None
            and self._view_crop_key == trace_key.as_tuple()
        )

    def crop_status_text(self) -> str:
        """
        Return a short status line describing the active crop.

        Data coordinates are read off the displayed plane once it has been
        refetched at the cropped size; until then the storage bounds are all
        that is known, so those are reported instead of stale coordinates.

        Returns
        -------
        str
            Human-readable crop bounds, or the empty string when no crop is
            active.
        """
        crop = self._view_crop
        if crop is None:
            return ""
        r0, r1, c0, c1 = crop.storage_bbox
        trace = self.resolve_single_visible_2d_trace()
        bundle = trace.last_bundle if trace is not None else None
        if (
            bundle is not None
            and bundle.ndim == 2
            and bundle.extent is not None
            and tuple(bundle.y.shape) == (r1 - r0, c1 - c0)
        ):
            left, right, bottom, top = bundle.extent
            return (
                f"Crop active: ({left:.2f}, {bottom:.2f}) — "
                f"({right:.2f}, {top:.2f})"
            )
        return f"Crop active: rows {r0}–{r1}, cols {c0}–{c1}"

    def apply_view_crop_from_region(
        self,
        region: RegionDefinition,
        *,
        trace: Optional[Trace] = None,
    ) -> ViewCrop:
        """
        Commit a drawn rectangle to the persistent view crop.

        Parameters
        ----------
        region : RegionDefinition
            Crop rectangle in matplotlib data coordinates on the oriented plot
            plane. Only :class:`RectRegion` is supported.
        trace : Trace, optional
            Parent 2D trace. Defaults to the sole visible 2D trace.

        Returns
        -------
        ViewCrop
            Applied crop state.

        Raises
        ------
        ValueError
            If the region is invalid or crop context cannot be resolved.
        """
        if self._view_crop is not None:
            raise ValueError("Clear the current crop before applying a new one")
        if not isinstance(region, RectRegion):
            raise ValueError("Crop region must be a rectangle")
        region = region.normalized()
        width = region.x1 - region.x0
        height = region.y1 - region.y0
        if width == 0.0 or height == 0.0:
            raise ValueError("Crop region has zero width or height")

        trace = trace or self.resolve_single_visible_2d_trace()
        if trace is None:
            raise ValueError("Select a single 2D dataset")
        plane_axes = trace.request.plane_axes
        if plane_axes is None:
            raise ValueError("Select a single 2D dataset")

        bundle = trace.last_bundle
        if bundle is None or bundle.ndim != 2:
            raise ValueError("Select a single 2D dataset")
        crop = crop_from_region(region, frame_from_bundle(bundle), plane_axes)
        self.set_view_crop(crop, trace.trace_key.as_tuple())
        return crop

    def invalidate_view_crop_if_invalid(self) -> Optional[str]:
        """
        Clear the view crop when the current plot context no longer matches it.

        Returns
        -------
        str or None
            Reason the crop was cleared, or ``None`` if the crop remains valid.
        """
        crop = self._view_crop
        if crop is None:
            return None
        trace = self.resolve_single_visible_2d_trace()
        if trace is None or trace.trace_key.as_tuple() != self._view_crop_key:
            self.clear_view_crop()
            return "dataset changed"
        parent_spec = self._cube_view_spec
        if parent_spec is None or parent_spec.plot_ndim != 2:
            self.clear_view_crop()
            return "view no longer available"
        plot_order = parent_spec.plot_axis_order()
        if (plot_order[-2], plot_order[-1]) != (
            crop.plot_y_axis,
            crop.plot_x_axis,
        ):
            self.clear_view_crop()
            return "plot axes changed"
        return None

    def resolve_current_view_fingerprint(self) -> Optional[tuple]:
        """
        Return a fingerprint for the sole visible 2D plot coordinate frame.

        Returns
        -------
        tuple or None
            View fingerprint from the active plot bundle, if available.
        """
        trace = self.resolve_single_visible_2d_trace()
        if trace is None or trace.last_bundle is None:
            return None
        try:
            return view_fingerprint_from_bundle(trace.last_bundle)
        except ValueError:
            return None

    def sync_region_state_with_view(self) -> None:
        """
        Mark stale ROIs and clear invalid crops for the current plot view.
        """
        if len(self._roi_set) > 0:
            fingerprint = self.resolve_current_view_fingerprint()
            newly_stale = self._roi_set.mark_stale_for_fingerprint(fingerprint)
            if newly_stale:
                self.region_status_changed.emit(
                    "ROI marked stale: view coordinates changed"
                )
        crop_reason = self.invalidate_view_crop_if_invalid()
        if crop_reason is not None:
            self.region_status_changed.emit(f"Crop cleared: {crop_reason}")

    def invalidate_all_region_state(self, reason: str) -> None:
        """
        Force-clear crop and mark all ROIs stale after a view-context change.

        Parameters
        ----------
        reason : str
            Short description emitted to views for status readouts.
        """
        had_crop = self._view_crop is not None
        if had_crop:
            self.clear_view_crop()

        had_rois = len(self._roi_set) > 0
        if had_rois:
            self._roi_set.mark_stale_for_fingerprint(None)

        self.region_invalidation_requested.emit(reason)

        if had_crop:
            self.region_status_changed.emit(f"Crop cleared: {reason}")
        if had_rois and self._view_crop is None:
            self.region_status_changed.emit(f"ROI marked stale: {reason}")

    def _on_cube_view_changed_for_region(self, _spec) -> None:
        self.sync_region_state_with_view()

    def _on_selected_keys_changed_for_region(
        self,
        _xkeys,
        _ykeys,
        _normkeys,
    ) -> None:
        self.invalidate_all_region_state("field selection changed")

    def _effective_transform_text(self, run_model: "RunSource" = None) -> str:
        """
        Return the session effective transform expression.

        Parameters
        ----------
        run_model : RunSource, optional
            Unused; kept for call-site compatibility.

        Returns
        -------
        str
            Transform text when enabled on the session, otherwise empty.
        """
        if self._transform.get("enabled"):
            return self._transform.get("text", "") or ""
        return ""

    def _crop_for_trace(self, trace_key: TraceKey):
        """
        Return the session crop if it applies to this trace.

        Parameters
        ----------
        trace_key : TraceKey
            Trace to match against the crop's source trace.

        Returns
        -------
        ViewCrop or None
            Active crop when it names this trace, otherwise None.
        """
        if not self.crop_applies_to(trace_key):
            return None
        return self._view_crop

    def _build_plot_request(
        self,
        run_model: "RunSource",
        xkey: str,
        ykey: str,
        norm_keys: Optional[List[str]] = None,
    ):
        """
        Assemble a :class:`PlotRequest` from session view state.

        Parameters
        ----------
        run_model : RunSource
            Source run.
        xkey : str
            X key.
        ykey : str
            Y key.
        norm_keys : list of str, optional
            Normalization keys.

        Returns
        -------
        PlotRequest
            Frozen request for this trace.
        """
        trace_key = TraceKey(run_model.uid, xkey, ykey)
        return build_plot_request(
            uid=run_model.uid,
            xkeys=[xkey] if xkey else (),
            ykey=ykey,
            shape=run_model.get_shape(ykey),
            norm_keys=norm_keys,
            plot_ndim=self._dimension,
            projection=self._cube_view_spec,
            slice_info=self._slice,
            crop=self._crop_for_trace(trace_key),
            transform=self._effective_transform_text(run_model),
        )

    def ensure_trace(
        self,
        run_model: "RunSource",
        xkey: str,
        ykey: str,
        norm_keys: Optional[List[str]] = None,
    ) -> Trace:
        """
        Return the trace for ``(xkey, ykey, run uid)``, creating it.

        Assembles a :class:`PlotRequest` from session slice / cube / crop and
        stores it on the model. Existing models keep their artist.

        Parameters
        ----------
        run_model : RunSource
            Source run.
        xkey : str
            X key.
        ykey : str
            Y key.
        norm_keys : list of str, optional
            Normalization keys.

        Returns
        -------
        Trace
            Existing or newly created trace.
        """
        key = TraceKey(run_model.uid, xkey, ykey)
        request = self._build_plot_request(run_model, xkey, ykey, norm_keys)
        trace, created = self._traces.ensure(run_model, request, key)
        if created:
            print_debug(
                "PlotSession.ensure_trace",
                f"create {xkey}/{ykey}",
                category="plots",
            )
        return trace

    def drop_traces_for_uid(self, uid: str) -> None:
        """
        Remove and clean up all traces for a run uid.

        Parameters
        ----------
        uid : str
            Run uid whose traces should be dropped.
        """
        for key in self._traces.keys_for_uid(uid):
            self._dispose_trace(key)

    def iter_visible_traces(self):
        """
        Yield traces whose run uid is currently visible.
        """
        visible = self.visible_uids
        for key, trace in self._traces.items():
            if key.uid in visible:
                yield trace

    def resolve_single_visible_2d_trace(self) -> Optional[Trace]:
        """
        Return the sole visible 2D trace, if exactly one exists.

        Uses cached render mode or ``last_bundle`` dimensionality. When neither
        is available, falls back to ``dimension == 2``.

        Returns
        -------
        Trace or None
        """
        matches = []
        for trace in self.iter_visible_traces():
            if not trace.visible:
                continue
            render_mode = trace.render_mode
            if render_mode in ("image", "mesh"):
                matches.append(trace)
                continue
            bundle = trace.last_bundle
            if bundle is not None and bundle.ndim == 2:
                matches.append(trace)
                continue
            if (
                trace.projection.plot_ndim == 2
                and render_mode is None
                and bundle is None
            ):
                matches.append(trace)
        if len(matches) == 1:
            return matches[0]
        return None

    def is_roi_draw_enabled(self) -> bool:
        """
        Return whether interactive ROI drawing is requested on the parent plot.
        """
        return self._roi_draw_enabled

    def set_roi_draw_enabled(self, enabled: bool) -> None:
        """
        Request interactive ROI drawing on the parent plot view.

        Parameters
        ----------
        enabled : bool
            True to enable ROI drawing.
        """
        enabled = bool(enabled)
        if enabled == self._roi_draw_enabled:
            return
        self._roi_draw_enabled = enabled
        self.roi_draw_enabled_changed.emit(enabled)

    def is_ellipse_circle_locked(self) -> bool:
        """
        Return whether ellipse ROI drawing is locked to a circle.
        """
        return self._ellipse_circle_locked

    def set_ellipse_circle_locked(self, locked: bool) -> None:
        """
        Request circle-locked ellipse ROI drawing on the parent plot.

        Parameters
        ----------
        locked : bool
            True to lock ellipse drawing to a circle.
        """
        locked = bool(locked)
        if locked == self._ellipse_circle_locked:
            return
        self._ellipse_circle_locked = locked
        self.ellipse_circle_locked_changed.emit(locked)

    def request_roi_live_region_sync(self) -> None:
        """
        Ask the parent plot view to commit any in-progress ROI draw geometry.
        """
        self.roi_live_region_sync_requested.emit()

    def resolve_parent_frame(
        self,
        trace: Optional[Trace] = None,
    ) -> Optional[PlotViewFrame]:
        """
        Return the view frame for the visible 2D trace.

        Parameters
        ----------
        trace : Trace, optional
            Plot-data model. Defaults to the sole visible 2D model.

        Returns
        -------
        PlotViewFrame or None
        """
        trace = trace or self.resolve_single_visible_2d_trace()
        if trace is None or trace.last_bundle is None:
            return None
        try:
            return frame_from_bundle(trace.last_bundle)
        except ValueError:
            return None

    def cached_parent_bundle_for_preview(
        self,
        trace: Trace,
    ) -> Optional["PlotBundle"]:
        """
        Return the loaded plot plane when it still matches the session view.

        Parameters
        ----------
        trace : Trace
            Parent trace.

        Returns
        -------
        PlotBundle or None
            Plane to hand to the fetch as ``cached_plane``. Whether it can
            actually serve a given profile is the fetch's decision, not this
            one; this only answers whether it is still the right plane.
        """
        bundle = trace.last_bundle
        if bundle is None or bundle.ndim != 2:
            return None
        session_request = self._build_plot_request(
            trace.run,
            trace.xkey,
            trace.ykey,
            list(trace.request.norm_keys),
        )
        if trace.request.view != session_request.view:
            return None
        return bundle

    def apply_roi_region_to_selected(self, region: RegionDefinition) -> None:
        """
        Update the selected ROI geometry from a region in data coordinates.

        Parameters
        ----------
        region : RegionDefinition
            ROI geometry on the oriented plot plane.

        Raises
        ------
        ValueError
            If no ROI is selected.
        """
        entry = self._roi_set.selected_entry()
        if entry is None:
            raise ValueError("Select an ROI")
        if hasattr(region, "normalized"):
            region = region.normalized()
        self._roi_set.update_region(
            entry.id,
            region,
            view_fingerprint=self.resolve_current_view_fingerprint(),
            clear_stale=True,
        )

    def apply_expanded_roi_profile_span(self, profile_axis: str) -> None:
        """
        Expand the selected ROI along a plot axis for span-full profile actions.

        Parameters
        ----------
        profile_axis : str
            ``plot_x`` or ``plot_y``.

        Raises
        ------
        ValueError
            If the ROI or parent view frame is unavailable.
        """
        entry = self._roi_set.selected_entry()
        if entry is None:
            raise ValueError("Select an ROI")
        region = entry.region
        if not region.has_area():
            raise ValueError("Draw an ROI on the parent plot first")
        frame = self.resolve_parent_frame()
        if frame is None:
            raise ValueError("Select a single 2D dataset")
        expanded = expand_region_for_profile(frame, region, profile_axis)
        self.apply_roi_region_to_selected(expanded)

    def resolve_roi_entry(self, entry_id: Optional[str] = None) -> RoiEntry:
        """
        Return a drawable, non-stale ROI entry.

        Parameters
        ----------
        entry_id : str, optional
            Entry id. Defaults to the current selection.

        Returns
        -------
        RoiEntry
            Validated ROI entry.

        Raises
        ------
        ValueError
            If the entry is missing, stale, or has no drawable area.
        """
        if entry_id is None:
            entry = self._roi_set.selected_entry()
        else:
            entry = self._roi_set.get(entry_id)
        if entry is None:
            raise ValueError("Select an ROI")
        if entry.stale:
            raise ValueError("Selected ROI is stale; redraw it before previewing")
        if not entry.region.has_area():
            raise ValueError("Draw the selected ROI on the parent plot")
        if isinstance(entry.region, RectRegion):
            region = entry.region.normalized()
            if region.x1 - region.x0 == 0.0 or region.y1 - region.y0 == 0.0:
                raise ValueError("ROI has zero width or height")
        return entry

    def build_roi_profile_request(
        self,
        entry: RoiEntry,
        *,
        trace: Optional[Trace] = None,
        parent_frame=None,
        span_full_override: Optional[bool] = None,
        default_profile_axis=None,
    ) -> PlotRequest:
        """
        Build the profile request for an ROI entry.

        The parent trace's own request supplies the run, the keys, the
        projection and the crop; the entry supplies the region and the four
        reduction parameters. Nothing else travels alongside.

        Parameters
        ----------
        entry : RoiEntry
            ROI geometry and operation.
        trace : Trace, optional
            Parent 2D trace. Defaults to the sole visible one.
        parent_frame : PlotViewFrame, optional
            Parent view frame for span-full expansion.
        span_full_override : bool, optional
            Override ``entry.operation.span_full_profile_axis``.
        default_profile_axis : str or int, optional
            Profile axis used when the entry does not name one.

        Returns
        -------
        PlotRequest
            Request for preview or commit.

        Raises
        ------
        ValueError
            If no parent plane or no profile axis can be resolved.
        """
        trace = trace or self.resolve_single_visible_2d_trace()
        if trace is None:
            raise ValueError("Select a single 2D dataset")
        parent = trace.request
        if parent.plane_axes is None:
            raise ValueError("Parent projection is unavailable")
        profile_axis = entry.operation.profile_storage_axis
        if profile_axis is None:
            profile_axis = default_profile_axis
        if profile_axis is None:
            raise ValueError("Profile axis is unavailable")
        span_full = (
            entry.operation.span_full_profile_axis
            if span_full_override is None
            else span_full_override
        )
        return roi_profile_request(
            parent,
            entry.region,
            profile_axis=profile_axis,
            spatial_reduce=entry.operation.spatial_reduce,
            mask_mode=entry.operation.mask_mode,
            plane_frame=parent_frame,
            span_full=span_full,
        )

    def _commit_span_full(
        self,
        parent_spec: "Projection",
        profile_storage_axis: int,
        span_full: bool,
    ) -> bool:
        if classify_profile_kind(parent_spec, profile_storage_axis) != "stack_spectrum":
            return span_full
        if is_plot_plane_storage_axis(parent_spec, profile_storage_axis):
            return True
        return span_full

    def prepare_roi_commit(
        self,
        entry: RoiEntry,
        *,
        trace: Optional[Trace] = None,
        parent_frame=None,
        axis_names=None,
        default_profile_axis=None,
    ) -> Tuple[bool, PlotRequest]:
        """
        Validate an ROI commit and build its profile request.

        Parameters
        ----------
        entry : RoiEntry
            ROI entry to commit.
        trace : Trace, optional
            Parent 2D trace.
        parent_frame : PlotViewFrame, optional
            Parent frame for span-full expansion.
        axis_names : sequence of str, optional
            Axis names used in local-profile error hints.
        default_profile_axis : str or int, optional
            Fallback profile axis.

        Returns
        -------
        tuple
            ``(span_full, request)`` for the commit fetch.

        Raises
        ------
        ValueError
            If the ROI cannot be committed (missing view, local profile, etc.).
        """
        spec = self._cube_view_spec
        if spec is None:
            raise ValueError("Parent projection is unavailable")

        profile_axis = entry.operation.profile_storage_axis
        if profile_axis is None:
            profile_axis = default_profile_axis
        if profile_axis is None:
            raise ValueError("Profile axis is unavailable")
        profile_kind = classify_profile_kind(spec, profile_axis)
        if profile_kind == "local_profile":
            scan_axis = scan_profile_storage_axis(spec)
            names = tuple(axis_names or ())
            if scan_axis is not None and scan_axis < len(names):
                hint = names[scan_axis]
            else:
                hint = "the leading scan axis"
            raise ValueError(
                f"Select a profile along {hint} to save to Run Display"
            )

        span_full = self._commit_span_full(
            spec,
            profile_axis,
            entry.operation.span_full_profile_axis,
        )
        request = self.build_roi_profile_request(
            entry,
            trace=trace,
            parent_frame=parent_frame,
            span_full_override=span_full,
            default_profile_axis=default_profile_axis,
        )
        return span_full, request

    def preview_roi_profile(
        self,
        entry_id: Optional[str] = None,
        *,
        entry: Optional[RoiEntry] = None,
        parent_trace: Optional[Trace] = None,
        parent_frame=None,
        cached_plane: Optional["PlotBundle"] = None,
        span_full_override: Optional[bool] = None,
        default_profile_axis=None,
        request: Optional[PlotRequest] = None,
    ) -> "PlotBundle":
        """
        Preview an ROI profile for an entry on the parent trace.

        Parameters
        ----------
        entry_id : str, optional
            ROI entry id. Ignored when ``entry`` is provided.
        entry : RoiEntry, optional
            ROI entry. Defaults to resolving ``entry_id`` / selection.
        parent_trace : Trace, optional
            Parent 2D trace. Defaults to the sole visible 2D trace.
        parent_frame : PlotViewFrame, optional
            Parent frame used when building the request.
        cached_plane : PlotBundle, optional
            Plot plane already in memory. Defaults to the parent model's
            bundle when it still matches the session view.
        span_full_override : bool, optional
            Override span-full when building the request.
        default_profile_axis : str or int, optional
            Fallback profile axis.
        request : PlotRequest, optional
            Prebuilt request. When omitted, one is built from the entry.

        Returns
        -------
        PlotBundle
            1D ROI profile preview.
        """
        if entry is None and request is None:
            entry = self.resolve_roi_entry(entry_id)
        trace = parent_trace or self.resolve_single_visible_2d_trace()
        if trace is None:
            raise ValueError("Select a single 2D dataset")
        if request is None:
            request = self.build_roi_profile_request(
                entry,
                trace=trace,
                parent_frame=parent_frame,
                span_full_override=span_full_override,
                default_profile_axis=default_profile_axis,
            )
        if cached_plane is None:
            cached_plane = self.cached_parent_bundle_for_preview(trace)
        return trace.preview_roi_profile(
            request, cached_plane=cached_plane
        )

    def finalize_roi_commit(
        self,
        entry: RoiEntry,
        bundle: "PlotBundle",
        request: PlotRequest,
        *,
        parent_trace: Optional[Trace] = None,
        axis_names=None,
        cube_fingerprint=None,
        committed_xkey: Optional[str] = None,
    ) -> "FrozenSpectrum":
        """
        Build and register a frozen spectrum from a fetched ROI profile bundle.

        Parameters
        ----------
        entry : RoiEntry
            ROI entry used for labeling.
        bundle : PlotBundle
            Fetched 1D profile bundle.
        request : PlotRequest
            Request used for the fetch.
        parent_trace : Trace, optional
            Parent trace. Defaults to the sole visible 2D trace.
        axis_names : sequence of str, optional
            Storage axis names for default labels.
        cube_fingerprint : tuple, optional
            Slice / cube-view snapshot. Defaults to this plot's state.
        committed_xkey : str, optional
            X key at commit time. Defaults to the plot session x selection.

        Returns
        -------
        FrozenSpectrum
            Registered frozen spectrum.
        """
        trace = parent_trace or self.resolve_single_visible_2d_trace()
        if trace is None:
            raise ValueError("Select a single 2D dataset")
        names = tuple(axis_names or ())
        label = (
            entry.operation.label
            or entry.display_label
            or default_profile_label(
                request.mask_mode,
                request.spatial_reduce,
                request.profile_axis,
                names,
            )
        )
        if committed_xkey is None:
            default_x = self._selection.default.x
            committed_xkey = default_x[0] if default_x else ""
        if cube_fingerprint is None:
            cube_fingerprint = (
                tuple(self._slice) if self._slice else None,
                str(self._cube_view_spec),
            )
        frozen = trace.build_roi_frozen_spectrum(
            bundle,
            request,
            label=label,
            parent_spec=self._cube_view_spec,
            cube_fingerprint=cube_fingerprint,
            committed_xkey=committed_xkey,
        )
        trace.run.register_frozen_spectrum(frozen)
        return frozen

    def commit_roi_profile(
        self,
        entry_id: Optional[str] = None,
        *,
        entry: Optional[RoiEntry] = None,
        parent_trace: Optional[Trace] = None,
        parent_frame=None,
        cached_plane: Optional["PlotBundle"] = None,
        axis_names=None,
        default_profile_axis=None,
        cube_fingerprint=None,
        committed_xkey: Optional[str] = None,
    ) -> "FrozenSpectrum":
        """
        Preview, build, and register an ROI profile on the parent run.

        Parameters
        ----------
        entry_id : str, optional
            ROI entry id. Ignored when ``entry`` is provided.
        entry : RoiEntry, optional
            ROI entry. Defaults to resolving ``entry_id`` / selection.
        parent_trace : Trace, optional
            Parent 2D trace.
        parent_frame : PlotViewFrame, optional
            Parent frame for request construction.
        cached_plane : PlotBundle, optional
            Plot plane already in memory.
        axis_names : sequence of str, optional
            Axis names for default labels.
        default_profile_axis : str or int, optional
            Fallback profile axis.
        cube_fingerprint : tuple, optional
            Slice / cube-view snapshot.
        committed_xkey : str, optional
            X key at commit time.

        Returns
        -------
        FrozenSpectrum
            Registered frozen spectrum.

        Raises
        ------
        ValueError
            If the ROI cannot be committed (stale, local profile, etc.).
        """
        if entry is None:
            entry = self.resolve_roi_entry(entry_id)
        trace = parent_trace or self.resolve_single_visible_2d_trace()
        if trace is None:
            raise ValueError("Select a single 2D dataset")
        _span_full, request = self.prepare_roi_commit(
            entry,
            trace=trace,
            parent_frame=parent_frame,
            axis_names=axis_names,
            default_profile_axis=default_profile_axis,
        )
        bundle = self.preview_roi_profile(
            entry=entry,
            parent_trace=trace,
            cached_plane=cached_plane,
            request=request,
        )
        return self.finalize_roi_commit(
            entry,
            bundle,
            request,
            parent_trace=trace,
            axis_names=axis_names,
            cube_fingerprint=cube_fingerprint,
            committed_xkey=committed_xkey,
        )

    def _retained_trace_keys(self) -> Set[TraceKey]:
        """
        Return TraceKeys that should exist (membership × selection).

        Returns
        -------
        set of TraceKey
            Desired trace identities. Visibility is not applied here.
        """
        keys: Set[TraceKey] = set()
        for source in self.collection.sources():
            sel = self.selection_for(source.uid)
            if not (sel.x and sel.y):
                continue
            for xkey in sel.x:
                for ykey in sel.y:
                    keys.add(TraceKey(source.uid, xkey, ykey))
        return keys

    def _request_for(self, source: RunSource, key: TraceKey):
        """
        Build the current session PlotRequest for one TraceKey.

        Parameters
        ----------
        source : RunSource
            Source run.
        key : TraceKey
            Trace identity.

        Returns
        -------
        PlotRequest
            Request assembled from session view state.
        """
        sel = self.selection_for(source.uid)
        return self._build_plot_request(
            source,
            key.xkey,
            key.ykey,
            list(sel.norm),
        )

    def _dispose_trace(self, key: TraceKey) -> None:
        """
        Remove and clean up one trace.

        Parameters
        ----------
        key : TraceKey
            Entry to dispose.
        """
        self._traces.discard(key)

    def _refresh_held_requests(self) -> None:
        """
        Rewrite requests on every held trace from session view state.

        Used for view / crop / transform changes so ``ensure_trace``
        orphans (e.g. canvas-created keys) keep their identity — and with it
        the canvas artist filed under the same key — and pick up the new
        request. Membership pruning stays in :meth:`rebuild`.
        """
        for key, trace in list(self._traces.items()):
            source = self.collection.get(key.uid)
            if source is None:
                self._dispose_trace(key)
                continue
            trace.set_request(self._request_for(source, key))

    def rebuild(self) -> None:
        """
        Diff retained TraceKeys against the trace set and sync requests.

        Creates or updates traces for membership × selection; disposes extras.
        Visibility does not dispose — use :meth:`iter_visible_traces` for
        the draw set.
        """
        desired = self._retained_trace_keys()
        for key in set(self._traces) - desired:
            self._dispose_trace(key)
        for key in desired:
            source = self.collection.get(key.uid)
            if source is None:
                continue
            _trace, created = self._traces.ensure(
                source, self._request_for(source, key), key
            )
            if created:
                print_debug(
                    "PlotSession.rebuild",
                    f"create {key.xkey}/{key.ykey} uid={key.uid}",
                    category="plots",
                )

    def _attach_run_model(self, run_model: RunSource) -> None:
        if run_model.uid in self._connected_run_uids:
            return
        run_model.plot_update_needed.connect(self.request_plot_update)
        self._connected_run_uids.add(run_model.uid)

    def _detach_run_model(self, run_model: RunSource) -> None:
        if run_model.uid not in self._connected_run_uids:
            return
        try:
            run_model.plot_update_needed.disconnect(self.request_plot_update)
        except (TypeError, RuntimeError):
            pass
        self._connected_run_uids.discard(run_model.uid)

    def _on_available_keys_changed(self) -> None:
        available_keys = self.available_keys
        if not available_keys:
            if not self._retain_selection and len(self.collection) == 0:
                self.set_selected_keys([], [], [])
            return

        default = self._selection.default
        valid_x = [k for k in default.x if k in available_keys]
        valid_y = [k for k in default.y if k in available_keys]
        valid_norm = [k for k in default.norm if k in available_keys]
        if (
            tuple(valid_x) != default.x
            or tuple(valid_y) != default.y
            or tuple(valid_norm) != default.norm
        ):
            self.set_selected_keys(valid_x, valid_y, valid_norm)

    def _maybe_apply_default_selection(self) -> None:
        if self._retain_selection:
            return
        default = self._selection.default
        if default.x or default.y or default.norm:
            return
        models = self.available_models
        if len(models) != 1:
            return
        x_keys, y_keys, norm_keys = models[0].run.get_default_selection()
        self.set_selected_keys(x_keys, y_keys, norm_keys)

    def _discover_cache_progress_sources(self) -> Dict[int, ChunkCacheProgress]:
        sources: Dict[int, ChunkCacheProgress] = {}
        for model in self.available_models:
            run = getattr(model, "_run", None)
            if run is None:
                continue
            chunk_cache = getattr(run, "_chunk_cache", None)
            if chunk_cache is None:
                continue
            progress = getattr(chunk_cache, "progress", None)
            if progress is None:
                continue
            sources[id(progress)] = progress
        return sources

    def _refresh_cache_progress_connections(self, *_args) -> None:
        desired = self._discover_cache_progress_sources()
        desired_ids = set(desired)
        current_ids = set(self._progress_sources)

        for progress_id in current_ids - desired_ids:
            progress = self._progress_sources.pop(progress_id)
            try:
                progress.status_changed.disconnect(
                    self._on_cache_progress_status_changed
                )
            except (TypeError, RuntimeError):
                pass
            self._cache_statuses.pop(progress_id, None)

        for progress_id in desired_ids - current_ids:
            progress = desired[progress_id]
            progress.status_changed.connect(self._on_cache_progress_status_changed)
            self._progress_sources[progress_id] = progress

        self._emit_aggregated_cache_status()

    def _on_cache_progress_status_changed(self, status: TiledFetchStatus) -> None:
        progress = self.sender()
        if progress is None:
            return
        progress_id = id(progress)
        if progress_id not in self._progress_sources:
            return
        self._cache_statuses[progress_id] = status
        self._emit_aggregated_cache_status()

    def _emit_aggregated_cache_status(self) -> None:
        text = aggregate_tiled_fetch_label(self._cache_statuses.values())
        self.cache_status_changed.emit(text)
