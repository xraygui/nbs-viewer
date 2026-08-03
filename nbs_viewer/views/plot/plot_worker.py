import time as ttime
from typing import Optional, Set

from qtpy.QtCore import QThread, Signal

from nbs_viewer.utils import print_debug, time_function


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
        plot_data,
        slice_info,
        dimension,
        generation,
        artist=None,
        cube_view_spec=None,
        view_crop=None,
    ):
        super().__init__()
        self.plot_data = plot_data
        self.slice_info = slice_info
        self.cube_view_spec = cube_view_spec
        self.view_crop = view_crop
        self.dimension = dimension
        self.generation = generation
        self.artist = artist
        print_debug("PlotWorker", "Created new worker", category="DEBUG_PLOTS")

    @time_function(function_name="PlotWorker.run", category="DEBUG_PLOTS")
    def run(self):
        """Fetch and prepare the plot data."""
        try:
            if self.isInterruptionRequested():
                return
            print_debug("PlotWorker", "Starting data fetch", category="DEBUG_PLOTS")
            t1 = ttime.time()
            bundle = self.plot_data.get_plot_bundle(
                self.slice_info,
                self.dimension,
                cube_view_spec=self.cube_view_spec,
                view_crop=self.view_crop,
            )
            if self.isInterruptionRequested():
                print_debug(
                    "PlotWorker",
                    "Fetch finished after interruption, discarding",
                    category="DEBUG_PLOTS",
                )
                return
            t2 = ttime.time()
            print_debug(
                "PlotWorker",
                f"Data fetch complete - mode={bundle.render_mode}, "
                f"y shape={bundle.y.shape}, time: {t2 - t1:.2f}s",
                category="DEBUG_PLOTS",
            )
            self.data_ready.emit(
                bundle, self.plot_data, self.artist, self.generation
            )
        except Exception as e:
            if self.isInterruptionRequested():
                return
            error_msg = f"Error fetching plot data: {str(e)}"
            print_debug("PlotWorker", error_msg, category="DEBUG_PLOTS")
            self.error_occurred.emit(error_msg)
