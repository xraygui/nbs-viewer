"""
Small matplotlib canvas for derivative dialog preview.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("qtagg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from qtpy.QtWidgets import QSizePolicy

from ...models.plot.plot_geometry import PlotBundle
from .mpl_renderers import ImageRenderer, LineRenderer, MeshRenderer, remove_2d_artists


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
