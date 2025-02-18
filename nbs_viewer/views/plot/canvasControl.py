from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QMenu,
)
from qtpy.QtCore import Signal


class CanvasControlWidget(QWidget):
    """
    Widget for managing canvas assignments and creation.

    Provides a consistent interface for adding runs to new or existing canvases.
    Used by both CanvasRunList and DataSourceManager.

    Signals
    -------
    add_to_new_canvas : Signal
        Emitted when runs should be added to a new canvas (List[RunData])
    add_to_canvas : Signal
        Emitted when runs should be added to existing canvas (List[RunData], canvas_id)
    """

    add_to_new_canvas = Signal(list)  # List[RunData]
    add_to_canvas = Signal(list, str)  # List[RunData], canvas_id

    def __init__(self, canvas_manager, parent=None):
        """
        Initialize the canvas control widget.

        Parameters
        ----------
        canvas_manager : CanvasManager
            Model managing available canvases
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.canvas_manager = canvas_manager

        # Create widgets
        self.new_canvas_btn = QPushButton("New Canvas")
        self.add_to_canvas_btn = QPushButton("Add to Canvas")

        # Create canvas menu
        self.canvas_menu = QMenu(self)
        self.add_to_canvas_btn.setMenu(self.canvas_menu)

        # Layout
        layout = QHBoxLayout(self)
        layout.addWidget(self.new_canvas_btn)
        layout.addWidget(self.add_to_canvas_btn)
        self.setLayout(layout)

        # Connect signals
        self.new_canvas_btn.clicked.connect(self._on_new_canvas)
        self.canvas_manager.canvas_added.connect(self._update_canvas_menu)
        self.canvas_manager.canvas_removed.connect(self._update_canvas_menu)
        self.add_to_new_canvas.connect(self.canvas_manager.create_canvas_with_runs)
        self.add_to_canvas.connect(self.canvas_manager.add_runs_to_canvas)

        # Initial menu setup
        self._update_canvas_menu()

    def _update_canvas_menu(self):
        """Update the canvas selection menu."""
        self.canvas_menu.clear()

        for canvas_id, plot_model in self.canvas_manager.canvases.items():
            if canvas_id != "main":  # Don't include main canvas
                action = self.canvas_menu.addAction(f"Canvas {canvas_id}")
                action.setData(canvas_id)
                action.triggered.connect(
                    lambda checked, cid=canvas_id: self._on_canvas_selected(cid)
                )

        self.add_to_canvas_btn.setEnabled(len(self.canvas_menu.actions()) > 0)

    def handle_run_selection(self, run_data_list):
        """
        Update widget state based on run selection.

        Parameters
        ----------
        run_data_list : List[RunData]
            Currently selected runs
        """
        has_selection = len(run_data_list) > 0
        self.new_canvas_btn.setEnabled(has_selection)
        self.add_to_canvas_btn.setEnabled(
            has_selection and len(self.canvas_menu.actions()) > 0
        )
        self._current_selection = run_data_list

    def _on_new_canvas(self):
        """Handle request to create new canvas with selected runs."""
        if hasattr(self, "_current_selection"):
            self.add_to_new_canvas.emit(self._current_selection)

    def _on_canvas_selected(self, canvas_id):
        """
        Handle request to add runs to existing canvas.

        Parameters
        ----------
        canvas_id : str
            Target canvas identifier
        """
        if hasattr(self, "_current_selection"):
            self.add_to_canvas.emit(self._current_selection, canvas_id)
