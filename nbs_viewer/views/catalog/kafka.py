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
        self.autoPlotCheckBox.setChecked(False)
        self.autoPlotCheckBox.setToolTip("Automatically plot new runs as they arrive")

        # Auto-remove controls
        self.autoRemoveCheckBox = QCheckBox("Auto-remove old runs", self)
        self.autoRemoveCheckBox.setChecked(False)
        self.autoRemoveCheckBox.setEnabled(False)  # Initially disabled
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

        layout = QVBoxLayout()
        layout.addLayout(filterLayout)
        layout.addLayout(controls_layout)
        layout.addLayout(scrollLayout)
        layout.addWidget(self.invertButton)
        layout.addWidget(self.data_view)
        self.setLayout(layout)

        # Connect to catalog's new run signal
        if hasattr(self._catalog, "new_run_available"):
            print("Connecting to new_run_available signal")
            self._catalog.new_run_available.connect(self._handle_new_run)

    def refresh_filters(self):
        self.setupModelAndView(self._catalog)

    def _handle_new_run(self, run_uid: str):
        """Handle new run from Kafka stream."""
        print("KafkaView _handle_new_run")
        if not self.autoPlotCheckBox.isChecked():
            print("Auto-plotting is not enabled")
            return

        print("Auto-plotting new run")
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
                print(f"Checking for run {run_uid} (attempt {attempts[0] + 1})")
                for row in range(source_model.rowCount()):
                    key = source_model.get_key(row)
                    print(f"Got Row Key: {key}")
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
                        print(f"Auto-selected new run: {run_uid}")
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
