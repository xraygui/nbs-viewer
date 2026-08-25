from typing import Optional
from uuid import uuid4

from qtpy.QtCore import QObject, Signal
from qtpy.QtWidgets import QWidget
import numpy as np

from nbs_viewer.utils import print_debug
from matplotlib.image import AxesImage

from .cube_view import (
    CubeViewSpec,
    MaterializeRequest,
    classify_profile_kind,
    profile_storage_axis,
)
from .derived_fetch import fetch_roi_preview
from .frozen_spectrum import (
    SYNTHETIC_KEY_PREFIX,
    FrozenSpectrum,
    copy_plot_bundle,
)
from .plot_geometry import PlotBundle, RenderMode
from .view_crop import ViewCrop


class PlotDataModel(QObject):
    """
    A class to plot x, y data on a given MplCanvas instance and hold the
    resulting lines object.

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
        xkey,
        ykey,
        norm_keys=None,
        label=None,
        indices=None,
        cube_view_spec=None,
        dimension=1,
        parent=None,
    ):
        """
        Initialize plot data model for one x/y pair on a run.

        Parameters
        ----------
        run : RunModel
            Run model providing data.
        xkey : str
            X axis key.
        ykey : str
            Y data key.
        norm_keys : list of str, optional
            Normalization keys.
        label : str, optional
            Plot label override.
        indices : tuple, optional
            Legacy slice indices for multidimensional data.
        cube_view_spec : CubeViewSpec, optional
            N-D cube view for slice, reduce, and axis assignment.
        dimension : int, optional
            Plot dimensionality (1 or 2).
        parent : QWidget, optional
            Parent QObject.
        """
        super().__init__(parent=parent)
        self._key = (xkey, ykey, run.uid)
        self._xkey = xkey
        self._ykey = ykey
        self._run = run
        self._norm_keys = norm_keys
        self._label = label
        self._indices = indices
        self._cube_view_spec = cube_view_spec
        self._dimension = dimension
        self.artist = None
        self.last_bundle: Optional[PlotBundle] = None
        self._render_mode: Optional[RenderMode] = None
        self._visible = self._run._is_visible
        self._run.visibility_changed.connect(self._on_run_visibility_changed)
        self._run.selected_keys_changed.connect(self._on_keys_changed)
        self._run.transform_changed.connect(self._on_data_changed)
        self._run.data_changed.connect(self._on_data_changed)

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
        self,
        indices=None,
        dimension=None,
        cube_view_spec=None,
        view_crop: Optional[ViewCrop] = None,
    ) -> PlotBundle:
        """
        Fetch and prepare plot data as a PlotBundle.

        Parameters
        ----------
        indices : tuple, optional
            Legacy slice indices for multidimensional data.
        dimension : int, optional
            Plot dimension count (unused; kept for API compatibility).
        cube_view_spec : CubeViewSpec, optional
            N-D cube view specification.
        view_crop : ViewCrop, optional
            Persistent spatial crop for plot-plane load slices.

        Returns
        -------
        PlotBundle
            Prepared plot payload.
        """
        spec = cube_view_spec if cube_view_spec is not None else self._cube_view_spec
        bundle = self._run.get_plot_bundle(
            [self._xkey],
            self._ykey,
            self._norm_keys,
            slice_info=indices,
            cube_view_spec=spec,
            view_crop=view_crop,
        )
        self._update_render_mode(bundle)
        self.last_bundle = bundle
        return bundle

    def preview_roi_profile(
        self,
        request: MaterializeRequest,
        *,
        parent_spec: Optional[CubeViewSpec] = None,
        parent_bundle: Optional[PlotBundle] = None,
        view_crop: Optional[ViewCrop] = None,
    ) -> PlotBundle:
        """
        Fetch an ROI profile preview bundle for this parent plot-data model.

        Parameters
        ----------
        request : MaterializeRequest
            Profile materialize request including ROI geometry.
        parent_spec : CubeViewSpec, optional
            Parent cube view. Defaults to this model's cube view.
        parent_bundle : PlotBundle, optional
            Cached parent 2D bundle. Defaults to ``last_bundle``.
        view_crop : ViewCrop, optional
            Active main-display crop for ND loads.

        Returns
        -------
        PlotBundle
            1D ROI profile preview payload.
        """
        return fetch_roi_preview(
            self,
            request,
            parent_spec=(
                parent_spec if parent_spec is not None else self._cube_view_spec
            ),
            parent_bundle=parent_bundle,
            view_crop=view_crop,
        )

    def build_roi_frozen_spectrum(
        self,
        bundle: PlotBundle,
        request: MaterializeRequest,
        *,
        label: str,
        parent_spec: Optional[CubeViewSpec] = None,
        cube_fingerprint=None,
        committed_xkey: Optional[str] = None,
    ) -> FrozenSpectrum:
        """
        Build a :class:`FrozenSpectrum` from a committed ROI profile bundle.

        Does not register the spectrum on the run; callers (typically
        :class:`PlotModel`) perform registration.

        Parameters
        ----------
        bundle : PlotBundle
            1D line profile bundle to freeze.
        request : MaterializeRequest
            Provenance request used for the profile.
        label : str
            Display label for Run Display.
        parent_spec : CubeViewSpec, optional
            Parent cube view used to classify profile kind.
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
        try:
            profile_axis = profile_storage_axis(request.spec)
        except Exception:
            profile_axis = None
        if spec is not None and profile_axis is not None:
            kind = classify_profile_kind(spec, profile_axis)
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

    def get_plot_data(self, indices=None, dimension=None):
        """
        Backward-compatible API returning raw x list and y array.

        Parameters
        ----------
        indices : tuple, optional
            Slice indices.
        dimension : int, optional
            Plot dimension count.

        Returns
        -------
        tuple
            (xlist, y) for legacy callers.
        """
        bundle = self.get_plot_bundle(indices, dimension)
        if bundle.ndim == 1:
            return [bundle.x_line], bundle.y
        return [], bundle.y

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
        cube_view_spec : CubeViewSpec, optional
            N-D cube view specification.
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
        if norm_keys is not None and set(norm_keys) != set(self._norm_keys or []):
            self._norm_keys = norm_keys
            changed = True
        if indices is not None and indices != self._indices:
            self._indices = indices
            changed = True
        if cube_view_spec is not None and cube_view_spec != self._cube_view_spec:
            self._cube_view_spec = cube_view_spec
            changed = True
        if dimension is not None and dimension != self._dimension:
            self._dimension = dimension
            changed = True
        if not self._run._is_visible:
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

    def _on_run_visibility_changed(self, visible):
        xkeys, ykeys, normkeys = self._run.get_selected_keys()
        if self._xkey not in xkeys or self._ykey not in ykeys:
            self.set_visible(False)
        else:
            self.set_visible(visible)

    def set_norm_keys(self, norm_keys):
        if set(norm_keys) != set(self._norm_keys):
            self._norm_keys = norm_keys
            self.data_changed.emit(self)

    def set_visible(self, visible):
        """
        Set the visibility of the artist.

        Parameters
        ----------
        visible : bool
            Whether to show or hide the artist.
        """
        visible = visible and self._run._is_visible
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

    def _on_keys_changed(self, xkeys, ykeys, normkeys):
        if self._xkey not in xkeys or self._ykey not in ykeys:
            self.set_visible(False)
        else:
            self.set_visible(True)

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
