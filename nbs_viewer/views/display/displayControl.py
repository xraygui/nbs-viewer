"""Widget for managing canvas assignments and creation."""

from qtpy.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QMenu,
    QAction,
    QComboBox,
    QLabel,
)
from ..display.displayRegistry import PlotDisplayRegistry


class DisplayControlWidget(QWidget):
    """
    Widget for managing canvas assignments and creation.

    Provides a consistent interface for adding runs to new or existing
    displays. Used by both runListView and DataSourceManager.
    """

    def __init__(self, canvas_manager, run_list_model, parent=None):
        """
        Initialize the canvas control widget.

        Parameters
        ----------
        canvas_manager : CanvasManager
            Model managing available canvases
        run_list_model : RunListModel
            Model managing plot data
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.canvas_manager = canvas_manager
        self.run_list_model = run_list_model

        # Initialize display registry
        self.display_registry = PlotDisplayRegistry()

        self.add_to_new_canvas_btn = QPushButton("New Canvas", self)
        self.add_to_new_canvas_btn.setToolTip(
            "Create a new canvas with the current selection"
        )
        self.add_to_canvas_btn = QPushButton("Add to Canvas", self)
        self.add_to_canvas_btn.setToolTip(
            "Add the current selection to an existing canvas"
        )
        self.clear_canvas_btn = QPushButton("Clear Canvas", self)
        self.clear_canvas_btn.setToolTip("Clear the current canvas")
        self.canvas_menu = QMenu(self)
        self.add_to_canvas_btn.setMenu(self.canvas_menu)
        self.display_menu = QMenu(self)
        self.add_to_new_canvas_btn.setMenu(self.display_menu)

        # Layout - add widget selector before the New Canvas button
        layout = QHBoxLayout(self)

        # layout.addWidget(QLabel("Widget:"))
        layout.addWidget(self.add_to_new_canvas_btn)
        layout.addWidget(self.add_to_canvas_btn)
        layout.addWidget(self.clear_canvas_btn)
        self.setLayout(layout)

        # Connect signals
        self.add_to_new_canvas_btn.clicked.connect(self._on_new_canvas)
        self.clear_canvas_btn.clicked.connect(self._on_clear_canvas)
        self.canvas_manager.canvas_added.connect(self._update_canvas_menu)
        self.canvas_manager.canvas_removed.connect(self._update_canvas_menu)

        # Initialize widget selector
        self._populate_widget_selector()

        # Initial menu setup
        self._update_canvas_menu()

    def _populate_widget_selector(self):
        """Populate the widget selector ComboBox."""
        self.display_menu.clear()

        available_displays = self.display_registry.get_available_displays()
        for display_id in available_displays:
            metadata = self.display_registry.get_display_metadata(display_id)
            display_name = metadata.get("name", display_id)
            action = QAction(display_name, self)
            action.setData(display_id)
            action.triggered.connect(
                lambda checked, did=display_id: self._on_new_canvas(did)
            )
            self.display_menu.addAction(action)
        has_actions = len(self.display_menu.actions()) > 0
        self.add_to_new_canvas_btn.setEnabled(has_actions)

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

        has_actions = len(self.canvas_menu.actions()) > 0
        self.add_to_canvas_btn.setEnabled(has_actions)

    def _on_new_canvas(self, display_id):
        """Create new canvas with current selection and selected display type."""
        visible_models = self.run_list_model.visible_models
        selected_runs = [model._run for model in visible_models]
        if selected_runs:
            # Get selected display type
            selected_display = display_id

            # Create new canvas with specified display type
            canvas_id = self.canvas_manager.create_canvas(display_type=selected_display)
            self.canvas_manager.add_runs_to_canvas(selected_runs, canvas_id)

    def _on_canvas_selected(self, canvas_id):
        """Add current selection to existing canvas."""
        visible_models = self.run_list_model.visible_models
        selected_runs = [model._run for model in visible_models]
        if selected_runs:
            # Add runs to selected canvas
            self.canvas_manager.add_runs_to_canvas(selected_runs, canvas_id)

    def _on_clear_canvas(self):
        """Clear the current plot model and deselect all runs."""
        # Clear visible runs from the plot model
        visible_uids = set(self.run_list_model.visible_runs)
        if visible_uids:
            self.run_list_model.set_uids_visible(visible_uids, False)
            # Reset key selection
            self.run_list_model.set_selected_keys([], [], [], force_update=True)
