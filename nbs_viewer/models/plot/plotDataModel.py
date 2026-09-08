from dataclasses import replace
from typing import Optional
from uuid import uuid4

from qtpy.QtCore import QObject, Signal
import numpy as np

from nbs_viewer.utils import print_debug
from matplotlib.image import AxesImage

from .view_spec import Projection, classify_profile_kind
from .frozen_spectrum import (
    SYNTHETIC_KEY_PREFIX,
    FrozenSpectrum,
    copy_plot_bundle,
)
from .plot_geometry import PlotBundle, RenderMode
from .plot_request import PlotRequest, TraceKey, build_plot_request


class PlotDataModel(QObject):
    """
    Long-lived plot object for one :class:`TraceKey`.

    Holds a :class:`PlotRequest` describing the current fetch. Changing the
    request (crop, slice, transform, norm) reuses this model and its artist.

    Attributes
    ----------
    artist : matplotlib Artist or None
        The matplotlib artist representing the plotted data.
    last_bundle : PlotBundle or None
        Most recently prepared plot payload.
    """

    artist_needed = Signal(object)
    draw_requested = Signal()
    autoscale_requested = Signal()
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
        Initialize plot data model for one trace key.

        Parameters
        ----------
        run : RunSource
            Run model providing data.
        request : PlotRequest
            Current fetch description.
        label : str, optional
            Plot label override.
        parent : QWidget, optional
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
        self.artist = None
        self.last_bundle: Optional[PlotBundle] = None
        self._render_mode: Optional[RenderMode] = None
        self._visible = True
        self._run.data_changed.connect(self._on_data_changed)

    @property
    def request(self) -> PlotRequest:
        """
        Current fetch description.
        """
        return self._request

    @property
    def trace_key(self) -> TraceKey:
        """
        Object identity for this model / artist.
        """
        return self._trace_key

    @property
    def last_fetched_request(self) -> Optional[PlotRequest]:
        """
        Request used to produce ``last_bundle``, if any.
        """
        return self._fetched_request

    @property
    def _key(self):
        return self._trace_key.as_tuple()

    @property
    def _xkey(self):
        return self._trace_key.xkey

    @property
    def _ykey(self):
        return self._trace_key.ykey

    @property
    def _norm_keys(self):
        return list(self._request.norm_keys)

    @property
    def _indices(self):
        return self._request.view.base_slice()

    @property
    def _cube_view_spec(self):
        return self._request.view

    @property
    def _dimension(self):
        return self._request.view.plot_ndim

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
        Return whether a worker should fetch for the current request.

        Returns
        -------
        bool
            True if there is no artist or the held request has not been
            fetched yet.
        """
        if self.artist is None:
            return True
        return self._fetched_request != self._request

    @property
    def label(self):
        if self._label:
            return self._label
        return self._run.legend_label_for_ykey(self._ykey)

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
        bundle = self._run.get_plot_bundle(request)
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
        return self._run.get_plot_bundle(
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
            X key selected at save time. Defaults to this model's x key.

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
        spec = parent_spec if parent_spec is not None else self._cube_view_spec
        kind = "stack_spectrum"
        if spec is not None and request.profile_axis is not None:
            kind = classify_profile_kind(spec, request.profile_axis)
        if committed_xkey is None:
            committed_xkey = self._xkey
        return FrozenSpectrum(
            key=f"{SYNTHETIC_KEY_PREFIX}{uuid4()}",
            label=label,
            bundle=copy_plot_bundle(bundle),
            kind=kind,
            source_ykey=self._ykey,
            committed_xkey=committed_xkey or "",
            request=request,
            source_key=self._key,
            cube_fingerprint=cube_fingerprint,
        )

    def _update_render_mode(self, bundle: PlotBundle) -> None:
        if bundle.render_mode != self._render_mode:
            self._render_mode = bundle.render_mode
            self.render_mode_changed.emit(self, bundle.render_mode)

    def update_data_info(
        self,
        norm_keys=None,
        indices=None,
        cube_view_spec=None,
        dimension=None,
        emit=True,
    ):
        """
        Update slice, norm, cube-view, or dimension metadata.

        Parameters
        ----------
        norm_keys : list of str, optional
            Normalization keys.
        indices : tuple, optional
            Legacy slice indices.
        cube_view_spec : Projection, optional
            N-D projection.
        dimension : int, optional
            Plot dimensionality.
        emit : bool, optional
            If True (default), emit ``data_changed`` when values change so the
            artist bus can refetch. List-owned updates pass False and start
            workers explicitly.

        Returns
        -------
        bool
            True if plot data should be refreshed.
        """
        changed = False
        if self.artist is None:
            changed = True
        if (
            norm_keys is not None
            or indices is not None
            or cube_view_spec is not None
            or dimension is not None
        ):
            shape = self._run.get_shape(self._ykey)
            request = build_plot_request(
                uid=self._run.uid,
                xkeys=[self._xkey] if self._xkey else (),
                ykey=self._ykey,
                shape=shape,
                norm_keys=(
                    norm_keys if norm_keys is not None else self._norm_keys
                ),
                plot_ndim=(
                    dimension if dimension is not None else self._dimension
                ),
                projection=(
                    cube_view_spec
                    if cube_view_spec is not None
                    else self._cube_view_spec
                ),
                slice_info=(
                    indices if indices is not None else self._indices
                ),
                crop=self._request.view.crop,
                transform=self._request.transform,
            )
            if self.set_request(request):
                changed = True
        if not self._visible:
            changed = False
        if changed:
            print_debug(
                "PlotDataModel.update_data_info",
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
        Set the visibility of the artist.

        Parameters
        ----------
        visible : bool
            Whether to show or hide the artist.
        """
        self._visible = visible
        if self.artist is not None:
            was_visible = self.artist.get_visible()
            if was_visible != visible:
                print_debug(
                    "PlotDataModel.set_visible",
                    f"{self.label} {was_visible} -> {visible}",
                    category="plots",
                )
                self.artist.set_visible(visible)
                self.visibility_changed.emit(self, visible)
                self.autoscale_requested.emit()
                self.draw_requested.emit()

    def _on_data_changed(self, *args):
        if self._visible:
            print_debug(
                "PlotDataModel._on_data_changed",
                f"data_changed for {self.label}",
                category="plots",
            )
            self.data_changed.emit(self)

    def set_artist(self, artist):
        """
        Set the artist for this model.

        Parameters
        ----------
        artist : Artist
            The matplotlib artist.
        """
        self.artist = artist

    def clear(self):
        """
        Remove artist from plot and clean up.
        """
        print_debug(
            "PlotDataModel.clear",
            f"Clearing {self.label}",
            category="plots",
        )
        if self.artist is not None:
            try:
                if self.artist.axes is not None:
                    self.artist.remove()

                if isinstance(self.artist, AxesImage):
                    self.artist.set_data([[]])
                elif hasattr(self.artist, "set_data"):
                    self.artist.set_data([], [])
                elif hasattr(self.artist, "set_array"):
                    self.artist.set_array([])
            except Exception as e:
                print(f"[PlotDataModel.clear] Error cleaning up artist: {e}")
            finally:
                self.artist = None
                self.draw_requested.emit()

    def remove_artist_from_axes(self):
        if self.artist is not None and self.artist.axes is not None:
            self.artist.remove()
            self.draw_requested.emit()

    def add_artist_to_axes(self, axes):
        if self.artist is not None:
            axes.add_artist(self.artist)
            self.draw_requested.emit()

    def move_artist_to_axes(self, axes):
        if self.artist is not None and self.artist.axes != axes:
            if self.artist.axes is not None:
                self.artist.remove()
            axes.add_artist(self.artist)
            self.draw_requested.emit()
