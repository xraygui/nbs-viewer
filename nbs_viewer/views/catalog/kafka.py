from qtpy.QtWidgets import (
    QHeaderView,
    QMenu,
    QAction,
    QTableView,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLineEdit,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QMessageBox,
)
from qtpy.QtCore import Qt, QItemSelectionModel, QTimer
from .base import CatalogTableView, CustomHeaderView


class KafkaView(CatalogTableView):
    """Widget for displaying and managing Kafka streams.

    Parameters
    ----------
    dispatcher : object
        The Kafka document dispatcher
    topics : list
        List of Kafka topics to subscribe to
    parent : QWidget, optional
        Parent widget, by default None
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dynamic = True
        # Update these signal connections to use catalog signals
        self._catalog.selection_changed.connect(self._update_button_states)

    def _setup_ui(self):
        """
        Set up the user interface components.
        """
        self.data_view = QTableView(self)
        data_header = CustomHeaderView(Qt.Horizontal, self.data_view)
        self.data_view.setHorizontalHeader(data_header)
        self.data_view.setSelectionBehavior(QTableView.SelectRows)
        self.data_view.setSelectionMode(QTableView.ExtendedSelection)

        self.invertButton = QPushButton("Reverse Data", self)
        self.invertButton.setEnabled(False)

        self.scrollToBottomButton = QPushButton("Scroll to Bottom", self)
        self.scrollToBottomButton.clicked.connect(self.data_view.scrollToBottom)

        self.scrollToTopButton = QPushButton("Scroll to Top", self)
        self.scrollToTopButton.clicked.connect(self.data_view.scrollToTop)

        self.filterLineEdit = QLineEdit(self)
        self.filterComboBox = QComboBox(self)

        filterLayout = QHBoxLayout()
        filterLayout.addWidget(QLabel("RegEx Filter"))
        filterLayout.addWidget(self.filterLineEdit)
        filterLayout.addWidget(self.filterComboBox)

        scrollLayout = QHBoxLayout()
        scrollLayout.addWidget(self.scrollToTopButton)
        scrollLayout.addWidget(self.scrollToBottomButton)

        # Auto-plot controls
        self.autoPlotCheckBox = QCheckBox("Auto-plot new runs", self)
        self.autoPlotCheckBox.setChecked(True)
        self.autoPlotCheckBox.setToolTip("Automatically plot new runs as they arrive")

        # Auto-remove controls
        self.autoRemoveCheckBox = QCheckBox("Auto-unplot old runs", self)
        self.autoRemoveCheckBox.setChecked(False)
        self.autoRemoveCheckBox.setEnabled(True)  # Initially disabled
        self.autoRemoveCheckBox.setToolTip(
            "Remove previously plotted runs when a new run arrives"
        )

        # Connect auto-plot checkbox to enable/disable auto-remove
        self.autoPlotCheckBox.toggled.connect(self.autoRemoveCheckBox.setEnabled)

        # Top controls layout
        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.autoPlotCheckBox)
        controls_layout.addWidget(self.autoRemoveCheckBox)
        controls_layout.addStretch()

        # Add remove buttons layout
        remove_layout = QHBoxLayout()

        # Remove selected button
        self.removeSelectedButton = QPushButton("Remove Selected", self)
        self.removeSelectedButton.clicked.connect(self._on_remove_selected)
        self.removeSelectedButton.setEnabled(False)
        remove_layout.addWidget(self.removeSelectedButton)

        # Remove all button
        self.removeAllButton = QPushButton("Remove All", self)
        self.removeAllButton.clicked.connect(self._on_remove_all)
        self.removeAllButton.setEnabled(False)  # Initially disabled
        remove_layout.addWidget(self.removeAllButton)

        layout = QVBoxLayout()
        layout.addLayout(filterLayout)
        layout.addLayout(controls_layout)
        layout.addLayout(remove_layout)
        layout.addLayout(scrollLayout)
        layout.addWidget(self.invertButton)
        layout.addWidget(self.data_view)
        self.setLayout(layout)

        # Connect to catalog's new run signal
        if hasattr(self._catalog, "new_run_available"):
            # print("Connecting to new_run_available signal")
            self._catalog.new_run_available.connect(self._handle_new_run)

        # Connect to catalog's data updated signal to manage button states
        self._catalog.data_updated.connect(self._update_button_states)

    def _update_button_states(self, selected_runs=None):
        """Update button states based on current data."""
        has_runs = len(self._catalog) > 0
        self.removeAllButton.setEnabled(has_runs)

        # Update remove selected button based on both selection and having runs
        selected = (
            bool(selected_runs)
            if selected_runs is not None
            else (
                bool(self.data_view.selectionModel().selectedRows())
                if has_runs
                else False
            )
        )
        self.removeSelectedButton.setEnabled(selected)

    def setupModelAndView(self, catalog):
        """Set up the model and view."""
        super().setupModelAndView(catalog)
        # Update button states after model setup
        self._update_button_states()

    def refresh_filters(self):
        self.setupModelAndView(self._catalog)

    def _handle_new_run(self, run_uid: str):
        """Handle new run from Kafka stream."""
        # print("KafkaView _handle_new_run")
        if not self.autoPlotCheckBox.isChecked():
            # print("Auto-plotting is not enabled")
            return

        # print("Auto-plotting new run")
        try:
            # Store currently selected indices if we need to deselect them later
            old_selection = (
                self.data_view.selectionModel().selectedRows()
                if self.autoRemoveCheckBox.isChecked()
                else []
            )

            # Get the proxy and source models
            proxy_model = self.data_view.model()
            source_model = proxy_model.sourceModel()

            # Create a timer to check for the key periodically
            timer = QTimer(self)
            attempts = [0]
            max_attempts = 10

            def check_for_key():
                # print(f"Checking for run {run_uid} (attempt {attempts[0] + 1})")
                for row in range(source_model.rowCount()):
                    key = source_model.get_key(row)
                    # print(f"Got Row Key: {key}")
                    if key == run_uid:
                        # Found the row, select it
                        source_index = source_model.createIndex(row, 0)
                        proxy_index = proxy_model.mapFromSource(source_index)

                        # If auto-remove is enabled, deselect old rows first
                        if self.autoRemoveCheckBox.isChecked() and old_selection:
                            # Clear old selection - this will trigger on_selection_changed
                            self.data_view.selectionModel().clearSelection()

                        # Select the new run - this will trigger on_selection_changed
                        self.data_view.selectionModel().select(
                            proxy_index,
                            QItemSelectionModel.Select | QItemSelectionModel.Rows,
                        )
                        self.data_view.scrollTo(proxy_index)
                        # print(f"Auto-selected new run: {run_uid}")
                        timer.stop()
                        return

                attempts[0] += 1
                if attempts[0] >= max_attempts:
                    print(f"Failed to find run {run_uid} after {max_attempts} attempts")
                    timer.stop()

            timer.timeout.connect(check_for_key)
            timer.start(100)  # Check every 100ms

        except Exception as e:
            print(f"Error setting up auto-selection for run {run_uid}: {str(e)}")

    def _show_remove_warning(self, count: int) -> bool:
        """Show warning dialog before removing runs.

        Parameters
        ----------
        count : int
            Number of runs to be removed

        Returns
        -------
        bool
            True if user confirms removal, False otherwise
        """
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Confirm Removal")
        msg.setText(f"Remove {count} run{'s' if count > 1 else ''}?")
        msg.setInformativeText("Removed runs cannot be re-added.")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Cancel)
        return msg.exec_() == QMessageBox.Yes

    def _on_remove_selected(self):
        """Handle removal of selected runs."""
        selected_indexes = self.data_view.selectionModel().selectedRows()
        if not selected_indexes:
            return

        if not self._show_remove_warning(len(selected_indexes)):
            return

        # Get UIDs of selected runs
        selected_uids = []
        proxy_model = self.data_view.model()
        source_model = proxy_model.sourceModel()

        for proxy_index in selected_indexes:
            # Map proxy index to source index
            source_index = proxy_model.mapToSource(proxy_index)
            key = source_model.get_key(source_index.row())

            # Get the run from the catalog using the row index
            selected_uids.append(key)

        # print(f"Removing runs with UIDs: {selected_uids}")  # Debug print
        self.data_view.selectionModel().clearSelection()

        # Remove from catalog
        self._catalog.remove_runs(selected_uids)

    def _on_remove_all(self):
        """Handle removal of all runs."""
        run_count = len(self._catalog.get_runs())
        if run_count == 0:
            return

        if not self._show_remove_warning(run_count):
            return

        self.data_view.selectionModel().clearSelection()

        self._catalog.remove_all_runs()

    def cleanup(self):
        """Additional cleanup for Kafka view."""
        # Disable auto-plotting before cleanup
        self.autoPlotCheckBox.setChecked(False)

        # Call parent cleanup
        super().cleanup()
