import time as ttime
from typing import Optional, Set

from qtpy.QtCore import QThread, Signal

from nbs_viewer.models.plot.spec.request import PlotRequest
from nbs_viewer.utils import print_debug


def disconnect_plot_worker_signals(worker) -> None:
    """
    Disconnect all plot worker signals.

    Parameters
    ----------
    worker : PlotWorker
        Worker whose slots should be disconnected.
    """
    for signal in (worker.data_ready, worker.error_occurred, worker.finished):
        try:
            signal.disconnect()
        except (TypeError, RuntimeError):
            pass


def retire_plot_worker(worker, pending: Optional[Set] = None) -> None:
    """
    Disconnect a superseded worker and delete it only after the thread exits.

    Parameters
    ----------
    worker : PlotWorker or None
        Worker thread to retire. Must not be destroyed while ``run()`` is
        still executing; ``quit()`` does not interrupt a blocking fetch.
    pending : set, optional
        Strong references held until ``finished`` so the ``QThread`` is not
        garbage-collected while still running.
    """
    if worker is None:
        return
    disconnect_plot_worker_signals(worker)
    worker.requestInterruption()
    if pending is not None:
        pending.add(worker)
    if worker.isRunning():

        def _release():
            if pending is not None:
                pending.discard(worker)
            worker.deleteLater()

        worker.finished.connect(_release)
    else:
        if pending is not None:
            pending.discard(worker)
        worker.deleteLater()


class PlotWorker(QThread):
    """Worker thread for fetching and preparing plot data."""

    data_ready = Signal(object, object, object, int)
    error_occurred = Signal(str)

    def __init__(
        self,
        trace,
        plot_request: PlotRequest,
        generation,
        artist=None,
    ):
        """
        Parameters
        ----------
        trace : Trace
            Trace that owns the fetch.
        plot_request : PlotRequest
            Frozen description of what to fetch.
        generation : int
            Worker generation used to discard stale results.
        artist : object, optional
            Existing matplotlib artist to update.
        """
        super().__init__()
        self.trace = trace
        self.plot_request = plot_request
        self.generation = generation
        self.artist = artist

    def run(self):
        """Fetch and prepare the plot data."""
        try:
            if self.isInterruptionRequested():
                return
            t1 = ttime.time()
            bundle = self.trace.get_plot_bundle(
                plot_request=self.plot_request
            )
            if self.isInterruptionRequested():
                print_debug(
                    "PlotWorker",
                    "Fetch finished after interruption, discarding",
                    category="plots",
                )
                return
            print_debug(
                "PlotWorker.run",
                f"bundle ready label={self.trace.label} "
                f"mode={bundle.render_mode} y.shape={bundle.y.shape} "
                f"gen={self.generation} {ttime.time() - t1:.4f}s",
                category="plots",
            )
            self.data_ready.emit(
                bundle, self.trace, self.artist, self.generation
            )
        except Exception as e:
            if self.isInterruptionRequested():
                return
            error_msg = f"Error fetching plot data: {str(e)}"
            print_debug("PlotWorker", error_msg, category="plots")
            self.error_occurred.emit(error_msg)
