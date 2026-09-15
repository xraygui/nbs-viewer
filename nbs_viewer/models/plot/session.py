"""
Plot session: the coordinator that joins membership, selection and view.

Owns four children and connects them: a :class:`RunCollection` (membership
and visibility), a :class:`Selection` (default and per-run keys), a
:class:`ViewIntent` (rank, axis order and reduce policy), and a
:class:`RegionController` (crop and ROI). What it keeps for itself is the
work no single child can do — building a :class:`PlotRequest` out of all
four, and holding the :class:`TraceSet` that results.

Views take the child they need. The session does not re-export them: a
method earns a place here only if it joins two children, announces on a
child's behalf, or enforces an invariant neither child can.

``rebuild()`` is the sole mutator of trace *membership*. Retention is
membership x selection; visibility only filters drawing.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from qtpy.QtCore import QObject, Signal

from nbs_viewer.utils import print_debug

from nbs_viewer.models.cache.chunk_cache_progress import (
    ChunkCacheProgress,
    TiledFetchStatus,
    aggregate_tiled_fetch_label,
)

from .fetch.request import TraceKey, build_plot_request
from .region_controller import RegionController
from .run.collection import RunCollection
from .run.source import RunSource
from .run.selection import Selection
from .trace import Trace
from .trace_set import TraceSet
from .view_intent import ViewIntent
from .view import Projection


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

    transform_changed = Signal(dict)
    request_plot_update = Signal()
    frozen_spectra_changed = Signal()
    cache_status_changed = Signal(str)

    def __init__(
        self,
        is_main_display: bool = False,
        single_selection_mode: bool = False,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._collection = RunCollection(
            is_main_display=is_main_display,
            single_selection_mode=single_selection_mode,
            parent=self,
        )
        # Constructed before anything else subscribes, so the selection
        # settles against new membership before the session rebuilds on it.
        self._selection = Selection(self._collection, parent=self)
        self._intent = ViewIntent(plot_ndim=1, parent=self)
        self._region = RegionController(self, parent=self)
        self._traces = TraceSet(parent=self)

        self._transform = {"enabled": False, "text": ""}
        self._connected_run_uids = set()
        self._progress_sources: Dict[int, ChunkCacheProgress] = {}
        self._cache_statuses: Dict[int, TiledFetchStatus] = {}

        # Membership and selection each change what traces should exist;
        # visibility only changes what is drawn.
        self._collection.run_added.connect(self._on_run_added)
        self._collection.run_removed.connect(self._on_run_removed)
        self._collection.available_runs_changed.connect(self._on_membership_changed)
        self._collection.visible_runs_changed.connect(self._on_visibility_changed)
        self._selection.selected_keys_changed.connect(self._on_selection_changed)
        self._selection.selected_keys_changed.connect(
            self._region.on_selected_keys_changed
        )
        # The intent is a child that announces its own changes. Requests
        # must be rewritten before the refetch is scheduled, so the order
        # of these two connections is load-bearing.
        self._intent.changed.connect(self._refresh_held_requests)
        self._intent.changed.connect(self.request_plot_update.emit)
        # The region child reacts to the view directly.
        self._intent.orientation_changed.connect(
            self._region.sync_region_state_with_view
        )
        self._intent.plot_ndim_changed.connect(self._region.on_plot_ndim_changed)
        # The crop rides on every request, so a crop change rewrites held
        # requests and repaints -- the half of `set_view_crop` the controller
        # cannot do, because it needs the trace set.
        self._region.view_crop_changed.connect(self._on_view_crop_changed)

    @property
    def collection(self) -> RunCollection:
        """
        Membership, visibility, and the available-key universe.

        Handed out rather than forwarded: views that manage runs talk to
        ``session.collection`` directly.
        """
        return self._collection

    @property
    def selection(self) -> Selection:
        """
        The default and per-run key selection.

        Handed out rather than forwarded, as :attr:`collection` is.
        """
        return self._selection

    def _on_run_added(self, run_model: RunSource) -> None:
        """
        Subscribe to one new member's session-level signals.

        The collection owns the run's *key* signals, because it owns the
        key universe. What is left is the two things only the session can
        answer: a repaint, and the frozen-spectra rebuild.
        """
        self._attach_run_model(run_model)
        run_model.frozen_spectra_changed.connect(self._on_frozen_spectra_changed)
        self._refresh_cache_progress_connections()

    def _on_run_removed(self, run_model: RunSource) -> None:
        self._detach_run_model(run_model)
        try:
            run_model.frozen_spectra_changed.disconnect(
                self._on_frozen_spectra_changed
            )
        except (TypeError, RuntimeError):
            pass
        self._refresh_cache_progress_connections()

    def _on_membership_changed(self) -> None:
        """
        Sync the trace set after runs joined or left.
        """
        self.rebuild()
        self.request_plot_update.emit()

    def _on_visibility_changed(self, _visible_uids: Set[str]) -> None:
        """
        Repaint after a visibility change.

        Visibility is not membership: the traces of a hidden run stay, with
        their bundles, so there is nothing to rebuild here.
        """
        self.request_plot_update.emit()

    def _on_selection_changed(self, x_keys, y_keys, norm_keys) -> None:
        """
        Sync the trace set after the selected keys changed.
        """
        self.rebuild()
        print_debug(
            "PlotSession._on_selection_changed",
            f"request_plot_update x={x_keys} y={y_keys} norm={norm_keys}",
            category="plots",
        )
        self.request_plot_update.emit()

    def _on_frozen_spectra_changed(self) -> None:
        self.frozen_spectra_changed.emit()
        self.rebuild()
        self.request_plot_update.emit()

    def freeze_runs(self, runs: List[RunSource]) -> List[RunSource]:
        """
        Capture the selected Y keys of each run as immutable frozen runs.

        A join: the capture is the collection's, but which Y keys to freeze
        is the selection's answer.

        Parameters
        ----------
        runs : list of RunSource
            Runs whose currently selected Y keys should be frozen.

        Returns
        -------
        list of RunSource
            Frozen runs that were added.
        """
        to_freeze = []
        for model in runs:
            sel = self._selection.selection_for(model.uid)
            for key in sel.y:
                to_freeze.append((model, key))
        frozen_runs = self._collection.freeze(to_freeze)
        if frozen_runs:
            self._collection.add_runs(frozen_runs)
        return frozen_runs

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
    def traces(self) -> TraceSet:
        """
        Return the live :class:`TraceSet`, keyed by :class:`TraceKey`.
        """
        return self._traces

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
        for run_model in self._collection.visible_models:
            selection = self._selection.selection_for(run_model.uid)
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
            ``(run_model, ykey, KeyInfo, axis_names)``, or None when nothing
            visible has more than one dimension. The names come separately
            from the description because they are not the same question: the
            description is static, while the displayed names follow the X
            selection. Carried together so neither caller re-derives the
            other's half.
        """
        best = None
        for run_model in self._collection.visible_models:
            sel = self._selection.selection_for(run_model.uid)
            x_keys = list(sel.x)
            for ykey in sel.y:
                if run_model.is_synthetic_key(ykey):
                    continue
                try:
                    layout = run_model.describe(ykey)
                    names = run_model.plot_axis_names(ykey, x_keys)
                except Exception:
                    continue
                shape = layout.shape
                if best is None:
                    best = (run_model, ykey, layout, names)
                    continue
                current = best[2].shape
                if len(shape) > len(current) or (
                    len(shape) == len(current)
                    and any(s > c for s, c in zip(shape, current))
                ):
                    best = (run_model, ykey, layout, names)
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
        _run_model, _ykey, layout, names = driving
        return self._intent.project(len(layout.shape), layout.shape, names)

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
        self._intent.set_axis_order(swapped.axis_order, driving[3])

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
        names = run_model.plot_axis_names(ykey, [xkey] if xkey else [])
        intent = self._intent
        # A key that cannot fill the session plot still plots on its own
        # terms rather than dropping out: a 1-D spectrum beside a 2-D image
        # is the mixed-rank case, not an error. Projecting at an overridden
        # rank avoids manufacturing a throwaway intent, which a mutable
        # model cannot supply.
        plot_ndim = len(shape) if 0 < len(shape) < intent.plot_ndim else None
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
            dims=names,
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

    def iter_visible_traces(self):
        """
        Yield traces whose run uid is currently visible.
        """
        visible = self._collection.visible_uids
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
        for source in self._collection.sources():
            sel = self._selection.selection_for(source.uid)
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
        sel = self._selection.selection_for(source.uid)
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
            source = self._collection.get(key.uid)
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
            source = self._collection.get(key.uid)
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

    def _discover_cache_progress_sources(self) -> Dict[int, ChunkCacheProgress]:
        sources: Dict[int, ChunkCacheProgress] = {}
        for model in self._collection.available_models:
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
