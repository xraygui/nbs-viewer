"""
One trace: request identity plus the bundle last fetched for it.

A :class:`Trace` is model state only. It knows *what* should be drawn and
*whether* it should be drawn, never *how*: the matplotlib artist lives in a
canvas-side map keyed by :class:`TraceKey`, so a headless frontend can run a
full ``ensure_trace`` -> ``get_plot_bundle`` -> ``set_visible`` cycle with no
matplotlib import.
"""

import warnings
from dataclasses import replace
from typing import Optional
from uuid import uuid4

from qtpy.QtCore import QObject, Signal

from nbs_viewer.utils import print_debug

from .spec.projection import Projection
from .run.frozen_spectrum import FrozenSpectrum, SYNTHETIC_KEY_PREFIX, copy_plot_bundle
from .plane.orientation import RenderMode
from .spec.bundle import PlotBundle
from .spec.request import PlotRequest, TraceKey


class Trace(QObject):
    """
    Long-lived plot object for one :class:`TraceKey`.

    Holds a :class:`PlotRequest` describing the current fetch and the bundle
    that request last produced. Changing the request (crop, slice, transform,
    norm) reuses this object, and the canvas reuses the artist filed under
    :attr:`trace_key`.

    Attributes
    ----------
    last_bundle : PlotBundle or None
        Most recently prepared plot payload for :attr:`last_fetched_request`.
        Dropped when the underlying run reports new data.
    """

    visibility_changed = Signal(object, bool)
    data_changed = Signal(object)
    render_mode_changed = Signal(object, str)

    def __init__(
        self,
        run,
        request: PlotRequest,
        *,
        label=None,
        parent=None,
        trace_key: Optional[TraceKey] = None,
    ):
        """
        Initialize a trace for one trace key.

        Parameters
        ----------
        run : RunSource
            Run model providing data.
        request : PlotRequest
            Current fetch description.
        label : str, optional
            Plot label override.
        parent : QObject, optional
            Parent QObject.
        trace_key : TraceKey, optional
            Object identity. Defaults to ``request.trace_key()``.
        """
        super().__init__(parent=parent)
        self._run = run
        self._request = request
        self._trace_key = trace_key or request.trace_key()
        self._fetched_request: Optional[PlotRequest] = None
        self._label = label
        self.last_bundle: Optional[PlotBundle] = None
        self._render_mode: Optional[RenderMode] = None
        self._visible = True
        self._run.data_changed.connect(self._on_data_changed)

    @property
    def run(self):
        """
        Source run this trace reads from.
        """
        return self._run

    @property
    def request(self) -> PlotRequest:
        """
        Current fetch description.
        """
        return self._request

    @property
    def trace_key(self) -> TraceKey:
        """
        Object identity for this trace and its artist.
        """
        return self._trace_key

    @property
    def xkey(self) -> str:
        """
        Primary X key.
        """
        return self._trace_key.xkey

    @property
    def ykey(self) -> str:
        """
        Y data key.
        """
        return self._trace_key.ykey

    @property
    def projection(self) -> Optional[Projection]:
        """
        Rank-bound view of the plane this trace loads.
        """
        return self._request.view

    @property
    def last_fetched_request(self) -> Optional[PlotRequest]:
        """
        Request used to produce ``last_bundle``, if any.
        """
        return self._fetched_request

    @property
    def visible(self) -> bool:
        """
        Whether this trace should currently be drawn.
        """
        return self._visible

    def set_request(self, request: PlotRequest) -> bool:
        """
        Replace the current fetch description without changing object identity.

        Parameters
        ----------
        request : PlotRequest
            New fetch description. ``uid``, primary x key, and ``ykey`` must
            match :attr:`trace_key`.

        Returns
        -------
        bool
            True if the request changed.

        Raises
        ------
        ValueError
            If the request names a different trace.
        """
        incoming = request.trace_key(self._trace_key.fan_out_index)
        if (
            incoming.uid != self._trace_key.uid
            or incoming.xkey != self._trace_key.xkey
            or incoming.ykey != self._trace_key.ykey
        ):
            raise ValueError(
                f"request trace {incoming} does not match {self._trace_key}"
            )
        if request == self._request:
            return False
        self._request = request
        return True

    def needs_fetch(self) -> bool:
        """
        Return whether the held request still has to be fetched.

        Purely a question about model state: no bundle, or a bundle produced
        by a different request. A canvas that has lost its artist but still
        holds a matching bundle asks for a redraw, not a refetch.

        This deliberately compares whole requests rather than their
        :class:`FetchPlan`s. A transform edit leaves the plan identical, so a
        plan comparison would suppress the rebuild as well as the read and
        the trace would keep serving the old transform. What makes the
        rebuild cheap is that ``RunSource`` holds the loaded block: this
        returns True, the fetch runs, and no database read happens.

        Returns
        -------
        bool
            True if a worker should fetch for the current request.
        """
        if self.last_bundle is None:
            return True
        return self._fetched_request != self._request

    @property
    def label(self):
        if self._label:
            return self._label
        return self._run.legend_label_for_ykey(self.ykey)

    @property
    def axis_names(self):
        if self.last_bundle is not None:
            return self.last_bundle.axis_names
        return []

    @property
    def render_mode(self) -> Optional[RenderMode]:
        return self._render_mode

    def get_plot_bundle(
        self, plot_request: Optional[PlotRequest] = None
    ) -> PlotBundle:
        """
        Fetch and prepare plot data as a PlotBundle.

        Parameters
        ----------
        plot_request : PlotRequest, optional
            Override for this fetch. Defaults to the held request.

        Returns
        -------
        PlotBundle
            Prepared plot payload.
        """
        request = plot_request if plot_request is not None else self._request
        bundle = self._run.fetch.get_plot_bundle(request)
        self._fetched_request = request
        self._update_render_mode(bundle)
        self.last_bundle = bundle
        return bundle

    def preview_roi_profile(
        self,
        request: PlotRequest,
        *,
        cached_plane: Optional[PlotBundle] = None,
        label: str = "",
    ) -> PlotBundle:
        """
        Fetch an ROI profile bundle without disturbing this trace's state.

        A preview is a different request against the same run, so it must not
        overwrite ``last_bundle`` or the fetched-request fingerprint the way
        :meth:`get_plot_bundle` does.

        Parameters
        ----------
        request : PlotRequest
            Profile request: the parent plane plus region, profile axis, and
            spatial reduce.
        cached_plane : PlotBundle, optional
            Parent plane already in memory. The session decides whether the
            cached plane still matches the request; passing None always reads
            from the database.
        label : str
            Optional display label for the profile.

        Returns
        -------
        PlotBundle
            1D ROI profile payload.
        """
        return self._run.fetch.get_plot_bundle(
            request, cached_plane=cached_plane, label=label
        )

    def build_roi_frozen_spectrum(
        self,
        bundle: PlotBundle,
        request: PlotRequest,
        *,
        label: str,
        parent_spec: Optional[Projection] = None,
        cube_fingerprint=None,
        committed_xkey: Optional[str] = None,
    ) -> FrozenSpectrum:
        """
        Build a :class:`FrozenSpectrum` from a committed ROI profile bundle.

        Does not register the spectrum on the run; callers (typically
        :class:`PlotSession`) perform registration.

        Parameters
        ----------
        bundle : PlotBundle
            1D line profile bundle to freeze.
        request : PlotRequest
            Provenance request used for the profile.
        label : str
            Display label for Run Display.
        parent_spec : Projection, optional
            Parent projection used to classify profile kind.
        cube_fingerprint : tuple, optional
            Slice / cube-view snapshot at commit time.
        committed_xkey : str, optional
            X key selected at save time. Defaults to this trace's x key.

        Returns
        -------
        FrozenSpectrum
            Unregistered frozen spectrum entry.

        Raises
        ------
        ValueError
            If the bundle is not a 1D line profile.
        """
        if bundle.render_mode != "line" or bundle.ndim != 1:
            raise ValueError("Saved ROI profiles must be 1D line profiles")
        spec = parent_spec if parent_spec is not None else self.projection
        kind = "stack_spectrum"
        if spec is not None and request.profile_axis is not None:
            kind = spec.profile_kind(request.profile_axis)
        if committed_xkey is None:
            committed_xkey = self.xkey
        return FrozenSpectrum(
            key=f"{SYNTHETIC_KEY_PREFIX}{uuid4()}",
            label=label,
            bundle=copy_plot_bundle(bundle),
            kind=kind,
            source_ykey=self.ykey,
            committed_xkey=committed_xkey or "",
            request=request,
            source_key=self._trace_key.as_tuple(),
            cube_fingerprint=cube_fingerprint,
        )

    def _update_render_mode(self, bundle: PlotBundle) -> None:
        if bundle.render_mode != self._render_mode:
            self._render_mode = bundle.render_mode
            self.render_mode_changed.emit(self, bundle.render_mode)

    def set_projection(self, projection: Projection, emit: bool = True) -> bool:
        """
        Replace the view on the held request.

        Parameters
        ----------
        projection : Projection
            Rank-bound view for this key.
        emit : bool, optional
            If True (default), emit ``data_changed`` when the request changed
            so the canvas refetches. Callers that start a worker themselves
            pass False.

        Returns
        -------
        bool
            True if plot data should be refreshed.
        """
        changed = self.last_bundle is None
        if self.set_request(replace(self._request, view=projection)):
            changed = True
        if not self._visible:
            changed = False
        if changed:
            print_debug(
                "Trace.set_projection",
                f"changed for {self.label} emit={emit}",
                category="plots",
            )
            if emit:
                self.data_changed.emit(self)
        return changed

    def set_norm_keys(self, norm_keys):
        request = replace(self._request, norm_keys=tuple(norm_keys or ()))
        if self.set_request(request):
            self.data_changed.emit(self)

    def set_visible(self, visible):
        """
        Record whether this trace should be drawn.

        Session intent only. The canvas listens on ``visibility_changed`` and
        applies it to the artist; nothing here touches matplotlib, and a
        hidden trace keeps ``last_bundle`` so showing it again is free.

        Parameters
        ----------
        visible : bool
            Whether the trace should be drawn.
        """
        visible = bool(visible)
        if visible == self._visible:
            return
        print_debug(
            "Trace.set_visible",
            f"{self.label} {self._visible} -> {visible}",
            category="plots",
        )
        self._visible = visible
        self.visibility_changed.emit(self, visible)

    def invalidate_bundle(self) -> None:
        """
        Drop the cached bundle so the next :meth:`needs_fetch` asks for a read.

        Called when the run's data changes underneath a request that has not
        itself changed — live scans, and cache fills. Without it a hidden
        trace would come back showing the arrays as they stood when it was
        hidden.
        """
        self.last_bundle = None
        self._fetched_request = None

    def dispose(self) -> None:
        """
        Detach from the run before this trace leaves the set.

        A trace outlives individual requests but not membership; without the
        disconnect a dropped trace keeps waking on every fetch its old run
        makes.

        Its own signals go too. Removal is announced by key, so a subscriber
        never gets the trace back and cannot unsubscribe itself; the trace is
        a child of the set and so survives its own removal in Qt.
        """
        try:
            self._run.data_changed.disconnect(self._on_data_changed)
        except (TypeError, RuntimeError):
            pass
        # A bare disconnect() warns rather than raises when nothing is
        # connected, and PySide6's receivers() takes a signature string, not
        # the signal, so there is no cheap way to ask first.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for signal in (
                self.data_changed,
                self.visibility_changed,
                self.render_mode_changed,
            ):
                try:
                    signal.disconnect()
                except (TypeError, RuntimeError):
                    pass

    def _on_data_changed(self, *args):
        self.invalidate_bundle()
        if self._visible:
            print_debug(
                "Trace._on_data_changed",
                f"data_changed for {self.label}",
                category="plots",
            )
            self.data_changed.emit(self)
