"""Widget for managing canvas assignments and creation."""

from qtpy.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QPushButton,
    QMenu,
    QAction,
    QComboBox,
    QLabel,
)
from .widget_registry import PlotWidgetRegistry


class CanvasControlWidget(QWidget):
    """
    Widget for managing canvas assignments and creation.

    Provides a consistent interface for adding runs to new or existing
    canvases. Used by both CanvasRunList and DataSourceManager.
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

        # Initialize widget registry
        self.widget_registry = PlotWidgetRegistry()

        # Create UI elements
        self.widget_selector = QComboBox(self)
        self.widget_selector.setToolTip("Select plot widget type for new canvas")
        self.widget_selector.setMinimumWidth(120)

        self.add_to_new_canvas_btn = QPushButton("New Canvas", self)
        self.add_to_canvas_btn = QPushButton("Add to Canvas", self)
        self.clear_canvas_btn = QPushButton("Clear Canvas", self)
        self.canvas_menu = QMenu(self)
        self.add_to_canvas_btn.setMenu(self.canvas_menu)

        # Layout - add widget selector before the New Canvas button
        layout = QHBoxLayout(self)
        layout.addWidget(QLabel("Widget:"))
        layout.addWidget(self.widget_selector)
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
        self.widget_selector.clear()

        available_widgets = self.widget_registry.get_available_widgets()
        for widget_id in available_widgets:
            metadata = self.widget_registry.get_widget_metadata(widget_id)
            display_name = metadata.get("name", widget_id)
            self.widget_selector.addItem(display_name, widget_id)

        # Set default selection
        default_widget = self.widget_registry.get_default_widget()
        index = self.widget_selector.findData(default_widget)
        if index >= 0:
            self.widget_selector.setCurrentIndex(index)

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

    def _on_new_canvas(self):
        """Create new canvas with current selection and selected widget type."""
        visible_models = self.plot_model.visible_models
        selected_runs = [model._run for model in visible_models]
        if selected_runs:
            # Get selected widget type
            selected_widget = self.widget_selector.currentData()

            # Create new canvas with specified widget type
            canvas_id = self.canvas_manager.create_canvas(widget_type=selected_widget)
            self.canvas_manager.add_runs_to_canvas(selected_runs, canvas_id)

    def _on_canvas_selected(self, canvas_id):
        """Add current selection to existing canvas."""
        visible_models = self.plot_model.visible_models
        selected_runs = [model._run for model in visible_models]
        if selected_runs:
            # Add runs to selected canvas
            self.canvas_manager.add_runs_to_canvas(selected_runs, canvas_id)

    def _on_clear_canvas(self):
        """Clear the current plot model and deselect all runs."""
        # Clear visible runs from the plot model
        visible_uids = self.plot_model.visible_runs
        if visible_uids:
            self.plot_model.set_uids_visible(visible_uids, False)
            # Reset key selection
            self.plot_model.set_selected_keys([], [], [], force_update=True)
