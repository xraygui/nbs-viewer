"""
Background worker for derivative dialog preview fetch.
"""

from __future__ import annotations

import time

from qtpy.QtCore import QThread, Signal

from nbs_viewer.models.plot.derived_fetch import fetch_derivative_preview_bundle
from nbs_viewer.models.plot.region import RectRegion
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
        slice_info,
        cube_view_spec,
        region: RectRegion,
        spec,
        generation: int,
        parent=None,
    ):
        super().__init__(parent)
        self.plot_model = plot_model
        self.slice_info = slice_info
        self.cube_view_spec = cube_view_spec
        self.region = region
        self.spec = spec
        self.generation = generation

    def run(self):
        """
        Fetch the derivative preview bundle.
        """
        try:
            if self.isInterruptionRequested():
                return
            t0 = time.perf_counter()
            parent_bundle = self.plot_model.last_bundle
            cached = parent_bundle is not None
            bundle = fetch_derivative_preview_bundle(
                self.plot_model,
                self.slice_info,
                self.cube_view_spec,
                self.region,
                self.spec,
                parent_bundle=parent_bundle,
            )
            elapsed = time.perf_counter() - t0
            print_debug(
                "DerivativePreviewWorker",
                f"preview ready in {elapsed:.3f}s "
                f"(cached_parent={cached}, "
                f"output={self.spec.output_kind}, "
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
