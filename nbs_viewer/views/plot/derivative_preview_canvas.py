"""
Small matplotlib canvas for derivative dialog preview.
"""

from __future__ import annotations

import time
import matplotlib

matplotlib.use("qtagg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from qtpy.QtWidgets import QSizePolicy
from qtpy.QtCore import QThread, Signal

from ...models.plot.cube_view import CubeViewSpec, MaterializeRequest
from ...models.plot.plot_geometry import PlotBundle
from .mpl_renderers import ImageRenderer, LineRenderer, MeshRenderer, remove_2d_artists

from nbs_viewer.models.plot.derived_fetch import fetch_derivative_preview
from nbs_viewer.utils import print_debug


class DerivativePreviewWorker(QThread):
    """
    Compute a derivative :class:`PlotBundle` off the GUI thread.

    Signals
    -------
    preview_ready : object
        Emitted with the preview :class:`PlotBundle` and generation id.
    error_occurred : str
        Emitted with an error message and generation id.
    """

    preview_ready = Signal(object, int)
    error_occurred = Signal(str, int)

    def __init__(
        self,
        plot_model,
        request: MaterializeRequest,
        generation: int,
        parent=None,
        *,
        parent_spec: CubeViewSpec | None = None,
        parent_bundle: PlotBundle | None = None,
    ):
        super().__init__(parent)
        self.plot_model = plot_model
        self.request = request
        self.parent_spec = parent_spec
        self.parent_bundle = parent_bundle
        self.generation = generation

    def run(self):
        """
        Fetch the derivative preview bundle.
        """
        try:
            if self.isInterruptionRequested():
                return
            t0 = time.perf_counter()
            parent_bundle = self.parent_bundle
            cached = parent_bundle is not None
            bundle = fetch_derivative_preview(
                self.plot_model,
                self.request,
                parent_spec=self.parent_spec,
                parent_bundle=parent_bundle,
            )
            elapsed = time.perf_counter() - t0
            print_debug(
                "DerivativePreviewWorker",
                f"preview ready in {elapsed:.3f}s "
                f"(cached_parent={cached}, "
                f"plot_ndim={self.request.spec.plot_ndim}, "
                f"shape={getattr(bundle.y, 'shape', None)})",
                category="DEBUG_PLOTS",
            )
            if self.isInterruptionRequested():
                return
            self.preview_ready.emit(bundle, self.generation)
        except Exception as exc:
            if self.isInterruptionRequested():
                return
            print_debug(
                "DerivativePreviewWorker",
                str(exc),
                category="DEBUG_PLOTS",
            )
            self.error_occurred.emit(str(exc), self.generation)


class DerivativePreviewCanvas(FigureCanvasQTAgg):
    """
    Single-axes canvas that renders a preview :class:`PlotBundle`.
    """

    def __init__(self, parent=None, width=4, height=3, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi, constrained_layout=True)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)
        self._colorbar_state = {}
        self._line_artist = None
        self._image_artist = None
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMinimumHeight(200)
        self.show_message("Waiting for preview…")

    def show_message(self, text: str):
        """
        Show a centered message instead of plot data.
        """
        self.axes.clear()
        remove_2d_artists(self.axes, self._colorbar_state, self.fig)
        self._line_artist = None
        self._image_artist = None
        self.axes.text(
            0.5,
            0.5,
            text,
            transform=self.axes.transAxes,
            ha="center",
            va="center",
            wrap=True,
        )
        self.axes.set_xticks([])
        self.axes.set_yticks([])
        self.draw()

    def show_bundle(self, bundle: PlotBundle):
        """
        Render a preview bundle on the canvas.
        """
        self.axes.clear()
        remove_2d_artists(self.axes, self._colorbar_state, self.fig)
        self._line_artist = None
        self._image_artist = None

        label = bundle.axis_names[0] if bundle.axis_names else "preview"
        if bundle.render_mode == "line":
            self._line_artist = LineRenderer.create(
                self.axes, bundle, label
            )
            LineRenderer.set_labels(self.axes, bundle)
        elif bundle.render_mode == "image":
            self._image_artist, _ = ImageRenderer.create(
                self.axes,
                self.fig,
                bundle,
                label,
                self._colorbar_state,
            )
        elif bundle.render_mode == "mesh":
            self._image_artist, _ = MeshRenderer.create(
                self.axes,
                self.fig,
                bundle,
                label,
                self._colorbar_state,
            )
        self._set_preview_limits(bundle)
        self.draw()

    def _set_preview_limits(self, bundle: PlotBundle):
        """
        Set axis limits from bundle coordinates without autoscale on NaNs.
        """
        if bundle.render_mode == "mesh":
            MeshRenderer._set_limits(self.axes, bundle)
            return
        if bundle.render_mode == "image" and bundle.extent is not None:
            left, right, bottom, top = bundle.extent
            self.axes.set_xlim(left, right)
            self.axes.set_ylim(bottom, top)
            return
        self.axes.relim()
        self.axes.autoscale_view()
