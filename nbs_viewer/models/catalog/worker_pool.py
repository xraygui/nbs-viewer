from __future__ import annotations

from typing import Optional
import logging

from qtpy.QtCore import QObject, QRunnable, QThreadPool, QTimer
from nbs_viewer.utils import print_debug


class _KeyInitTask(QRunnable):
    def __init__(self, run_obj):
        super().__init__()
        self._run = run_obj

    def run(self) -> None:  # type: ignore[override]
        try:
            # Compute keys in background thread
            keys = self._run._initialize_keys()
            # Signal back to main thread to apply results
            print_debug(
                "KeyInitTask.run",
                f"Keys ready for {self._run.uid}: {keys}",
                "pool",
            )
            # self._run.keys_ready.emit(keys)
        except Exception as exc:
            logging.getLogger("nbs_viewer.catalog").exception(
                "Key initialization failed"
            )
            self._run.keys_error.emit(str(exc))


class CatalogWorkerPool(QObject):
    """Per-catalog worker pool for background tasks.

    Currently supports background key initialization for runs.
    """

    def __init__(self, parent: Optional[QObject] = None, max_threads: int = 8):
        super().__init__(parent)
        self._pool = QThreadPool()
        # Cap threads to avoid overloading servers
        self._pool.setMaxThreadCount(max_threads)

    def submit_key_init(self, run_obj) -> None:
        print_debug("CatalogWorkerPool.submit_key_init", "Submitting key init", "pool")
        # Prevent duplicate submissions if keys already started/initialized
        if getattr(run_obj, "_keys_initialized", False) or getattr(
            run_obj, "_keys_init_started", False
        ):
            return
        # Mark as started to avoid re-submission races
        try:
            run_obj._keys_init_started = True
        except Exception:
            pass
        # Schedule background computation of keys.
        task = _KeyInitTask(run_obj)
        self._pool.start(task)
