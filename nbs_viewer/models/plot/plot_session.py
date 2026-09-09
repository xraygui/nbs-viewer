"""
Plot session: membership, visibility, selection, view, and the trace set.

Owns a :class:`RunCollection`, the visible-uid set, selected keys, transform,
view state, the :class:`TraceSet`, and the region child.
:class:`RunListItemModel` (in ``views/``) is a Qt facade that observes it.

``rebuild()`` is the sole mutator of trace *membership*. Retention is
membership × selection; visibility only filters drawing.

Key selection is a session :class:`Selection` (default + per-uid overrides).
Freeze and unlinked display read :meth:`selection_for`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Union

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
    TraceKey,
    build_plot_request,
)
from .region_controller import RegionController
from .run_collection import RunCollection
from .runSource import RunSource
from .selection import KeySelection, Selection
from .trace import Trace
from .trace_set import TraceSet
from .view_intent import ViewIntent
from .view_spec import (
    Projection,
)


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
        self._region = RegionController(self, parent=self)

        self._selection = Selection()
        self._retain_selection = False
        self._transform = {"enabled": False, "text": ""}

        self._intent = ViewIntent(plot_ndim=1, parent=self)

        self._traces = TraceSet(parent=self)
        self._connected_run_uids = set()

        self._progress_sources: Dict[int, ChunkCacheProgress] = {}
        self._cache_statuses: Dict[int, TiledFetchStatus] = {}


        self.available_keys_changed.connect(self._on_available_keys_changed)
        # The intent is a child that announces its own changes. Requests
        # must be rewritten before the refetch is scheduled, so the order
        # of these two connections is load-bearing.
        self._intent.changed.connect(self._refresh_held_requests)
        self._intent.changed.connect(self.request_plot_update.emit)
        # The region child reacts to the view directly. Both of these used
        # to be the session subscribing to its own signals, because there
        # was no second object to talk to.
        self._intent.orientation_changed.connect(
            self._region.sync_region_state_with_view
        )
        self._intent.plot_ndim_changed.connect(self._region.on_plot_ndim_changed)
        self.selected_keys_changed.connect(
            self._region.on_selected_keys_changed
        )
        # The crop rides on every request, so a crop change rewrites held
        # requests and repaints -- the half of `set_view_crop` the controller
        # cannot do, because it needs the trace set.
        self._region.view_crop_changed.connect(self._on_view_crop_changed)
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
        return self._intent.plot_ndim

    @property
    def view_intent(self) -> ViewIntent:
        """
        Rank-agnostic view state for this session.

        The single source of truth for plot dimensionality, axis order and
        reduce policy. Views read it and send gestures back; they do not
        hold a copy.
        """
        return self._intent

    def follow_x_selection(self) -> None:
        """
        Point the default axis order at the current X selection.

        Called when the selection changes. Picking a different X key is an
        explicit statement about which dimension is horizontal, so it
        supersedes a manual arrangement; picking the same one leaves the
        arrangement alone.
        """
        self._intent.follow_xkey(self._primary_xkey())

    def _primary_xkey(self) -> Optional[str]:
        """
        Return the X key the default axis order follows.

        The first X key of the first visible run, matching how
        :meth:`driving_axes` picks the key the dimension rows describe.

        Returns
        -------
        str or None
        """
        for run_model in self.visible_models:
            selection = self.selection_for(run_model.uid)
            if selection.x:
                return selection.x[0]
        return None

    def driving_axes(self):
        """
        Return the axis layout of the key the dimension rows describe.

        The highest-rank visible non-synthetic Y key, breaking ties on the
        larger extent. This decides only *which sliders are shown*: the fetch
        path projects the intent onto each key's own rank, so no trace
        depends on this choice.

        Returns
        -------
        tuple or None
            ``(run_model, ykey, AxisLayout)``, or None when nothing visible
            has more than one dimension.
        """
        best = None
        for run_model in self.visible_models:
            sel = self.selection_for(run_model.uid)
            x_keys = list(sel.x)
            for ykey in sel.y:
                if run_model.is_synthetic_key(ykey):
                    continue
                try:
                    layout = run_model.describe_axes(ykey, x_keys)
                except Exception:
                    continue
                shape = layout.shape
                if best is None:
                    best = (run_model, ykey, layout)
                    continue
                current = best[2].shape
                if len(shape) > len(current) or (
                    len(shape) == len(current)
                    and any(s > c for s, c in zip(shape, current))
                ):
                    best = (run_model, ykey, layout)
        if best is None or len(best[2].shape) <= 1:
            return None
        return best

    def driving_projection(self) -> Optional[Projection]:
        """
        Return the intent projected onto the key the dimension rows describe.

        Returns
        -------
        Projection or None
            None when no visible key has more than one dimension.
        """
        driving = self.driving_axes()
        if driving is None:
            return None
        _run_model, _ykey, layout = driving
        return self._intent.project(
            len(layout.shape), layout.shape, layout.names
        )

    def move_view_axis(self, row_index: int, direction: int) -> None:
        """
        Move one dimension row up or down, recording a manual arrangement.

        Parameters
        ----------
        row_index : int
            Position of the row in the displayed order.
        direction : int
            Negative to move outward, positive to move inward.
        """
        projection = self.driving_projection()
        driving = self.driving_axes()
        if projection is None or driving is None:
            return
        target = row_index if direction < 0 else row_index + 1
        if target < 1 or target > projection.ndim - 1:
            return
        swapped = projection.swap_rows(target)
        self._intent.set_axis_order(swapped.axis_order, driving[2].names)

    def set_axis_reduce(self, assignments) -> None:
        """
        Set the role and index of every slice/reduce axis at once.

        Parameters
        ----------
        assignments : mapping
            ``{storage_axis: (DimRole, index)}`` from the dimension rows.
        """
        edited = self.driving_projection()
        if edited is None:
            return
        for storage_axis, (role, index) in assignments.items():
            edited = edited.with_slice_role(storage_axis, role).with_index(
                storage_axis, index
            )
        self._intent.set_reduce_from(edited)

    def set_plot_ndim(self, plot_ndim: int) -> None:
        """
        Set plot dimensionality.

        Parameters
        ----------
        plot_ndim : int
            1 for line plots, 2 for image plots.
        """
        self._intent.set_plot_ndim(plot_ndim)











    @property
    def region(self) -> RegionController:
        """
        Crop, ROI geometry and the ROI preview / commit pipeline.

        Handed out rather than forwarded: views talk to ``session.region``
        and ``session.region.roi_set`` directly.
        """
        return self._region

    def _on_view_crop_changed(self, _crop) -> None:
        """
        Rebuild held requests and repaint after a crop change.

        The crop rides on every request, so this is the session's half of a
        crop edit; the controller owns the crop but not the traces.
        """
        self._refresh_held_requests()
        self.request_plot_update.emit()


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
            Frozen request for this trace.
        """
        trace_key = TraceKey(run_model.uid, xkey, ykey)
        shape = run_model.get_shape(ykey)
        try:
            names = run_model.describe_axes(ykey, [xkey] if xkey else []).names
        except Exception:
            names = None
        intent = self._intent
        # A key that cannot fill the session plot still plots on its own
        # terms rather than dropping out: a 1-D spectrum beside a 2-D image
        # is the mixed-rank case, not an error. Projecting at an overridden
        # rank avoids manufacturing a throwaway intent, which a mutable
        # model cannot supply.
        plot_ndim = (
            len(shape) if 0 < len(shape) < intent.plot_ndim else None
        )
        return build_plot_request(
            uid=run_model.uid,
            xkeys=[xkey] if xkey else (),
            ykey=ykey,
            norm_keys=norm_keys,
            projection=intent.project(
                len(shape),
                shape,
                names,
                crop=self._region.crop_for_trace(trace_key),
                plot_ndim=plot_ndim,
            ),
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
