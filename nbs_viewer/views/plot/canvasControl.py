from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QMenu,
    QAction,
)
from qtpy.QtCore import Signal


class CanvasControlWidget(QWidget):
    """
    Widget for managing canvas assignments and creation.

    Provides a consistent interface for adding runs to new or existing canvases.
    Used by both CanvasRunList and DataSourceManager.
    """

    def __init__(self, canvas_manager, plot_model, parent=None):
        """
        Initialize the canvas control widget.

        Parameters
        ----------
        canvas_manager : CanvasManager
            Model managing available canvases
        plot_model : PlotModel
            Model managing plot data
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.canvas_manager = canvas_manager
        self.plot_model = plot_model

        # Create UI elements
        self.add_to_new_canvas_btn = QPushButton("New Canvas", self)
        self.add_to_canvas_btn = QPushButton("Add to Canvas", self)
        self.canvas_menu = QMenu(self)
        self.add_to_canvas_btn.setMenu(self.canvas_menu)

        # Layout
        layout = QHBoxLayout(self)
        layout.addWidget(self.add_to_new_canvas_btn)
        layout.addWidget(self.add_to_canvas_btn)
        self.setLayout(layout)

        # Connect signals
        self.add_to_new_canvas_btn.clicked.connect(self._on_new_canvas)
        self.canvas_manager.canvas_added.connect(self._update_canvas_menu)
        self.canvas_manager.canvas_removed.connect(self._update_canvas_menu)

        # Initial menu setup
        self._update_canvas_menu()

    def _update_canvas_menu(self):
        """Update the canvas menu with current canvases."""
        self.canvas_menu.clear()
        for canvas_id in self.canvas_manager.get_canvas_ids():
            if canvas_id != "main":  # Skip main canvas
                action = QAction(f"Canvas {canvas_id}", self)
                action.setData(canvas_id)
                action.triggered.connect(
                    lambda checked, cid=canvas_id: self._on_canvas_selected(cid)
                )
                self.canvas_menu.addAction(action)

        self.add_to_canvas_btn.setEnabled(len(self.canvas_menu.actions()) > 0)

    def _on_new_canvas(self):
        """Create new canvas with current selection."""
        selected_runs = self.plot_model.get_selected_runs()
        if selected_runs:
            # Create new canvas and add runs
            canvas_id = self.canvas_manager.create_canvas()
            self.canvas_manager.add_runs_to_canvas(selected_runs, canvas_id)

    def _on_canvas_selected(self, canvas_id):
        """Add current selection to existing canvas."""
        selected_runs = self.plot_model.get_selected_runs()
        if selected_runs:
            # Add runs to selected canvas
            self.canvas_manager.add_runs_to_canvas(selected_runs, canvas_id)
