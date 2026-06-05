from qtpy.QtCore import QTimer
from qtpy.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QLabel,
    QSizePolicy,
)
from .plotControl import PlotControls
from .mpl_canvas import MplCanvas, NavigationToolbar
from nbs_viewer.utils import DEBUG_VARIABLES


class PlotWidget(QWidget):
    """
    The main organizing widget that combines a plot, a list of Bluesky runs,
    and controls to add runs to the plot.

    Parameters
    ----------
    run_list_model : RunListModel
        Model managing runs for this display.
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, run_list_model, parent=None):
        super().__init__(parent)
        self.run_list_model = run_list_model
        self._cache_progress_source = None

        self.plot_canvas = MplCanvas(self.run_list_model, self, 5, 4, 100)
        self.plot_toolbar = NavigationToolbar(self.plot_canvas, self)
        self.plot_controls = PlotControls(self.run_list_model, self.plot_canvas)

        tab = self.plot_controls.plot_control_tab
        self.dimension_control = tab.dimension_control
        self.roi_panel = tab.roi_panel
        self.roi_controller = tab.roi_controller
        self.derivative_controller = tab.derivative_controller

        self.cache_status_label = QLabel("")
        self.cache_status_label.setObjectName("cacheStatusLabel")
        self.cache_status_label.hide()

        self.cache_debug_button = QPushButton("Cache Stats")
        self.cache_debug_button.clicked.connect(self._debug_cache_state)
        self.flush_l1_button = QPushButton("Flush L1 → L2")
        self.flush_l1_button.clicked.connect(self._flush_l1_cache)

        if DEBUG_VARIABLES["PRINT_DEBUG"]:
            self.debug_button = QPushButton("Debug Plot State")
            self.debug_button.clicked.connect(self._debug_plot_state)
        else:
            self.debug_button = None

        plot_pane = QWidget()
        plot_pane_layout = QVBoxLayout(plot_pane)
        plot_pane_layout.setContentsMargins(0, 0, 0, 0)
        plot_pane_layout.setSpacing(0)
        plot_pane_layout.addWidget(self.plot_toolbar)
        plot_pane_layout.addWidget(self.plot_canvas, stretch=1)

        debug_row = QHBoxLayout()
        debug_row.setContentsMargins(0, 0, 0, 0)
        debug_row.addWidget(self.cache_debug_button)
        debug_row.addWidget(self.flush_l1_button)
        if self.debug_button:
            debug_row.addWidget(self.debug_button)
        debug_row.addStretch(1)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plot_layout = QVBoxLayout(self)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)
        plot_layout.addWidget(plot_pane, 1)
        plot_layout.addWidget(self.cache_status_label, 0)
        plot_layout.addLayout(debug_row, 0)

        self.run_list_model.run_added.connect(self._connect_cache_progress)
        self.run_list_model.run_removed.connect(self._on_cache_progress_run_removed)
        self._connect_cache_progress()

    def _resolve_chunk_cache(self):
        """
        Return the shared catalog chunk cache, if available.
        """
        for model in self.run_list_model.available_models:
            run = getattr(model, "_run", None)
            chunk_cache = getattr(run, "_chunk_cache", None)
            if chunk_cache is not None:
                return chunk_cache
        return None

    def _resolve_cache_progress(self):
        """
        Return the shared chunk cache progress notifier, if available.
        """
        chunk_cache = self._resolve_chunk_cache()
        if chunk_cache is None:
            return None
        return getattr(chunk_cache, "progress", None)

    def _connect_cache_progress(self, *_args):
        """
        Connect the cache status label to the catalog chunk cache signal.
        """
        progress = self._resolve_cache_progress()
        if progress is None:
            return
        if progress is self._cache_progress_source:
            return
        if self._cache_progress_source is not None:
            try:
                self._cache_progress_source.status_changed.disconnect(
                    self._on_cache_status_changed
                )
            except (TypeError, RuntimeError):
                pass
        progress.status_changed.connect(self._on_cache_status_changed)
        self._cache_progress_source = progress

    def _on_cache_progress_run_removed(self, *_args):
        """
        Hide cache status when no runs remain; reconnect if runs are left.
        """
        if self.run_list_model.available_models:
            self._connect_cache_progress()
            return
        self.cache_status_label.clear()
        self.cache_status_label.hide()
        self._cache_progress_source = None

    def _on_cache_status_changed(self, status):
        """
        Update the cache status label from a Tiled fetch status snapshot.
        """
        text = status.label_text() if hasattr(status, "label_text") else ""
        self.cache_status_label.setText(text)
        self.cache_status_label.setVisible(bool(text))

    def _debug_cache_state(self):
        """
        Print chunk cache and L2 statistics for visible plot datasets.
        """
        chunk_cache = self._resolve_chunk_cache()
        if chunk_cache is None:
            print("\n=== ChunkCache stats ===")
            print("  (no chunk cache available)")
            return

        datasets = []
        for model in self.run_list_model.visible_models:
            run_uid = model.uid
            _xkeys, ykeys, _normkeys = model.get_selected_keys()
            for key in ykeys:
                datasets.append((run_uid, key))

        print()
        print(chunk_cache.format_debug_report(datasets=datasets or None))

    def _flush_l1_cache(self):
        """
        Spill all L1 tiles to L2 on a background thread and print the result.
        """
        chunk_cache = self._resolve_chunk_cache()
        if chunk_cache is None:
            print("\n=== Flush L1 → L2 ===")
            print("  (no chunk cache available)")
            return

        self.flush_l1_button.setEnabled(False)
        self.cache_status_label.setText("Flushing L1 tiles to L2...")
        self.cache_status_label.show()

        future = chunk_cache.background_pool.submit(chunk_cache.flush_l1_to_l2)
        future.add_done_callback(
            lambda _f: QTimer.singleShot(0, lambda: self._on_flush_l1_done(future))
        )

    def _on_flush_l1_done(self, future):
        """
        Report L1 flush results on the Qt main thread.
        """
        chunk_cache = self._resolve_chunk_cache()
        try:
            result = future.result()
        except Exception as exc:
            print(f"\n=== Flush L1 → L2 failed ===\n  {exc}")
        else:
            print("\n=== Flush L1 → L2 ===")
            for name, value in result.items():
                print(f"  {name}: {value}")
            if chunk_cache is not None:
                print(chunk_cache.format_debug_report())
        finally:
            self.flush_l1_button.setEnabled(True)
            self.cache_status_label.clear()
            self.cache_status_label.hide()

    def _debug_plot_state(self):
        self.plot_canvas._debug_plot_state()
