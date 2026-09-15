"""
Geometry drawn on the current 2-D plot plane, and whether it is still valid.

Crop and ROI are one lifecycle under two names. Both are storage indices or
coordinates on the *sole visible 2-D plane*; both are invalidated by the same
view changes; both are validated against the same view fingerprint; and
:meth:`sync_region_state_with_view` and :meth:`invalidate_all_region_state`
each already act on both. Holding them apart is what produced two
fingerprint implementations, one of them in a canvas.

:class:`RoiSetModel` is *used* here, not wrapped. Of its public members only
``mark_stale_for_fingerprint`` has no consumer outside this controller; the
rest are read directly by ``roi/window.py`` and ``single_canvas.py``, so
re-exporting them would rebuild the forwarding layer this refactor exists to
remove. Views reach the store as ``session.region.roi_set``.

What this controller borrows from its session is deliberately small:
``resolve_single_visible_2d_trace`` -- a join over the trace set and
visibility that no single child can answer -- and the session-default X keys
when a commit has to name one. Everything the session needs back travels as a
signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from qtpy.QtCore import QObject, Signal


from .fetch.request import PlotRequest, TraceKey, crop_from_region, roi_profile_request
from .geometry import (
    PlotViewFrame,
    RectRegion,
    RegionDefinition,
    expand_region_for_profile,
    frame_from_bundle,
    view_fingerprint_from_bundle,
)
from .roi import RoiEntry, RoiSetModel
from .trace import Trace
from .view import Projection, ViewCrop
from .roi import default_profile_label

if TYPE_CHECKING:  # pragma: no cover
    from .run.frozen_spectrum import FrozenSpectrum
    from .geometry import PlotBundle
    from .session import PlotSession


class RegionController(QObject):
    """
    Crop, ROI geometry, staleness, and the ROI preview / commit pipeline.

    Owned by :class:`PlotSession` as ``session.region``.

    Signals
    -------
    view_crop_changed : Signal(object)
        The persistent crop was set or cleared. Carries a :class:`ViewCrop`
        or ``None`` -- a value, never this controller. The session rebuilds
        held requests from it, because the crop rides on every request.
    region_status_changed : Signal(str)
        Human-readable note about geometry that was cleared or staled.
    region_invalidation_requested : Signal(str)
        All crop and ROI state was force-cleared; views should drop overlays.
    roi_draw_enabled_changed : Signal(bool)
        The ROI drawing tool was toggled.
    ellipse_circle_locked_changed : Signal(bool)
        The ellipse tool was locked to circles.
    roi_live_region_sync_requested : Signal()
        Ask the canvas to push the live selector geometry back before a
        preview reads it.

    Parameters
    ----------
    session : PlotSession
        Owning session, used only for the two joins named in the module
        docstring.
    parent : QObject, optional
        Qt parent.
    """

    view_crop_changed = Signal(object)
    region_status_changed = Signal(str)
    region_invalidation_requested = Signal(str)
    roi_draw_enabled_changed = Signal(bool)
    ellipse_circle_locked_changed = Signal(bool)
    roi_live_region_sync_requested = Signal()

    def __init__(self, session: "PlotSession", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._session = session
        self._roi_set = RoiSetModel(parent=self)
        self._view_crop: Optional[ViewCrop] = None
        self._view_crop_key: Optional[tuple] = None
        self._roi_draw_enabled = False
        self._ellipse_circle_locked = False

    def _resolve_trace(self) -> Optional[Trace]:
        """
        Return the sole visible 2-D trace, or None.

        The one join this controller cannot make itself: it spans the trace
        set and run visibility, so the session owns it.
        """
        return self._session.resolve_single_visible_2d_trace()

    @property
    def roi_set(self) -> RoiSetModel:
        """
        Return the ROI set owned by this plot session.
        """
        return self._roi_set

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
    ) -> bool:
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

        Returns
        -------
        bool
            True when the crop actually changed. Pass ``None`` to clear.

        Notes
        -----
        Guards on real change, so setting the crop it already has announces
        nothing. That guard is why ``clear_view_crop`` no longer exists: it
        was a null check wrapped around ``set_view_crop(None)``, which is
        what this now does itself.
        """
        source_key = source_key if crop is not None else None
        if crop == self._view_crop and source_key == self._view_crop_key:
            return False
        self._view_crop = crop
        self._view_crop_key = source_key
        # Announced, not performed: the crop rides on every request, so the
        # session rewrites held requests and schedules the repaint. Doing it
        # here would need the trace set, which belongs to the session.
        self.view_crop_changed.emit(crop)
        return True

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

        trace = trace or self._resolve_trace()
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
        trace = self._resolve_trace()
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
        trace = self._resolve_trace()
        if trace is None or trace.trace_key.as_tuple() != self._view_crop_key:
            self.set_view_crop(None)
            return "dataset changed"
        parent_spec = trace.request.view
        if parent_spec is None or parent_spec.plot_ndim != 2:
            self.set_view_crop(None)
            return "view no longer available"
        plot_order = parent_spec.plot_axis_order()
        if (plot_order[-2], plot_order[-1]) != (
            crop.plot_y_axis,
            crop.plot_x_axis,
        ):
            self.set_view_crop(None)
            return "plot axes changed"
        return None

    def crop_for_trace(self, trace_key: TraceKey):
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

    def resolve_current_view_fingerprint(self) -> Optional[tuple]:
        """
        Return a fingerprint for the sole visible 2D plot coordinate frame.

        Returns
        -------
        tuple or None
            View fingerprint from the active plot bundle, if available.
        """
        trace = self._resolve_trace()
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
            self.set_view_crop(None)

        had_rois = len(self._roi_set) > 0
        if had_rois:
            self._roi_set.mark_stale_for_fingerprint(None)

        self.region_invalidation_requested.emit(reason)

        if had_crop:
            self.region_status_changed.emit(f"Crop cleared: {reason}")
        if had_rois and self._view_crop is None:
            self.region_status_changed.emit(f"ROI marked stale: {reason}")

    def on_selected_keys_changed(
        self,
        _xkeys=None,
        _ykeys=None,
        _normkeys=None,
    ) -> None:
        """
        Drop all geometry when the plotted fields change.

        A different Y key is a different plane, so nothing drawn on the old
        one survives. This was the session subscribing to its own
        ``selected_keys_changed``; it is now a connection between two
        objects, which is why the arguments are optional -- it is also
        callable directly.
        """
        self.invalidate_all_region_state("field selection changed")

    def on_plot_ndim_changed(self, plot_ndim: int) -> None:
        """
        Invalidate everything when the session stops showing a 2-D plane.

        Crop and ROI geometry live on that plane, so leaving it invalidates
        both. Entering it does not: there is no stale geometry to clear.

        Parameters
        ----------
        plot_ndim : int
            The session's new plot rank.
        """
        if plot_ndim != 2:
            self.invalidate_all_region_state("switched out of 2D mode")

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
        trace = trace or self._resolve_trace()
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

        Notes
        -----
        This used to rebuild the session request and compare its projection
        against the trace's, returning None when they differed. That test can
        no longer fail: ``PlotSession._refresh_held_requests`` is wired to
        every signal that moves the session view -- the intent's ``changed``,
        the transform, and this controller's ``view_crop_changed`` -- so a
        held request is rewritten before anything can observe it as stale.
        Verified against axis-order, slider, crop, plot-rank, selection and
        transform changes before the comparison was dropped.
        """
        bundle = trace.last_bundle
        if bundle is None or bundle.ndim != 2:
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
        trace = trace or self._resolve_trace()
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
        parent_spec: Projection,
        profile_storage_axis: int,
        span_full: bool,
    ) -> bool:
        if parent_spec.profile_kind(profile_storage_axis) != "stack_spectrum":
            return span_full
        if parent_spec.is_plot_plane_axis(profile_storage_axis):
            return True
        return span_full

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
        trace = parent_trace or self._resolve_trace()
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
        trace = trace or self._resolve_trace()
        spec = trace.request.view if trace is not None else None
        if spec is None:
            raise ValueError("Parent projection is unavailable")

        profile_axis = entry.operation.profile_storage_axis
        if profile_axis is None:
            profile_axis = default_profile_axis
        if profile_axis is None:
            raise ValueError("Profile axis is unavailable")
        profile_kind = spec.profile_kind(profile_axis)
        if profile_kind == "local_profile":
            scan_axis = spec.scan_axis
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
        trace = parent_trace or self._resolve_trace()
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
            default_x = self._session.selection.get_selected_keys()[0]
            committed_xkey = default_x[0] if default_x else ""
        parent_spec = trace.request.view
        if cube_fingerprint is None:
            base = parent_spec.base_slice() if parent_spec else None
            cube_fingerprint = (base, str(parent_spec))
        frozen = trace.build_roi_frozen_spectrum(
            bundle,
            request,
            label=label,
            parent_spec=parent_spec,
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
        trace = parent_trace or self._resolve_trace()
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
