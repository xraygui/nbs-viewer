"""Widget for managing display assignments and creation."""

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


class DisplayControlWidget(QWidget):
    """
    Widget for managing display assignments and creation.

    Provides a consistent interface for adding runs to new or existing
    displays. Used by both runListView and DataSourceManager.
    """

    def __init__(self, display_manager, run_list_model, parent=None):
        """
        Initialize the display control widget.

        Parameters
        ----------
        display_manager : DisplayManager
            Model managing available displays
        run_list_model : RunListModel
            Model managing plot data
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.display_manager = display_manager
        self.run_list_model = run_list_model

        self.add_to_new_display_btn = QPushButton("New Display", self)
        self.add_to_new_display_btn.setToolTip(
            "Create a new display with the current selection"
        )
        self.add_to_display_btn = QPushButton("Add to Display", self)
        self.add_to_display_btn.setToolTip(
            "Add the current selection to an existing display"
        )
        self.clear_display_btn = QPushButton("Clear Display", self)
        self.clear_display_btn.setToolTip("Clear the current display")
        self.display_menu = QMenu(self)
        self.add_to_display_btn.setMenu(self.display_menu)
        self.display_creation_menu = QMenu(self)
        self.add_to_new_display_btn.setMenu(self.display_creation_menu)

        # Layout - add widget selector before the New Display button
        layout = QHBoxLayout(self)

        # layout.addWidget(QLabel("Widget:"))
        layout.addWidget(self.add_to_new_display_btn)
        layout.addWidget(self.add_to_display_btn)
        layout.addWidget(self.clear_display_btn)
        self.setLayout(layout)

        # Connect signals
        self.add_to_new_display_btn.clicked.connect(self._on_new_display)
        self.clear_display_btn.clicked.connect(self._on_clear_display)
        self.display_manager.display_added.connect(self._update_display_menu)
        self.display_manager.display_removed.connect(self._update_display_menu)

        # Initialize widget selector
        self._populate_widget_selector()

        # Initial menu setup
        self._update_display_menu()

    def _populate_widget_selector(self):
        """Populate the widget selector ComboBox."""
        self.display_creation_menu.clear()

        available_displays = self.display_manager.get_available_display_types()
        for display_type in available_displays:
            metadata = self.display_manager.get_display_metadata(display_type)
            display_name = metadata.get("name", display_type)
            action = QAction(display_name, self)
            action.setData(display_type)
            action.triggered.connect(
                lambda checked, disp_type=display_type: self._on_new_display(disp_type)
            )
            self.display_creation_menu.addAction(action)
        has_actions = len(self.display_creation_menu.actions()) > 0
        self.add_to_new_display_btn.setEnabled(has_actions)

    def _update_display_menu(self):
        """Update the display menu with current displays."""
        self.display_menu.clear()
        for display_id in self.display_manager.get_display_ids():
            if display_id != "main":  # Skip main display
                action = QAction(f"Display {display_id}", self)
                action.setData(display_id)
                action.triggered.connect(
                    lambda checked, cid=display_id: self._on_display_selected(cid)
                )
                self.display_menu.addAction(action)

        has_actions = len(self.display_menu.actions()) > 0
        self.add_to_display_btn.setEnabled(has_actions)

    def _on_new_display(self, display_type):
        """Create new display with current selection and selected display type."""
        visible_models = self.run_list_model.visible_models
        selected_runs = [model._run for model in visible_models]
        # Create new display with specified display type
        display_id = self.display_manager.create_display_with_runs(
            selected_runs, display_type=display_type
        )

    def _on_display_selected(self, display_id):
        """Add current selection to existing display."""
        visible_models = self.run_list_model.visible_models
        selected_runs = [model._run for model in visible_models]
        if selected_runs:
            # Add runs to selected display
            self.display_manager.add_runs_to_display(selected_runs, display_id)

    def _on_clear_display(self):
        """Clear the current plot model and deselect all runs."""
        # Clear visible runs from the plot model
        visible_uids = set(self.run_list_model.visible_runs)
        if visible_uids:
            self.run_list_model.set_uids_visible(visible_uids, False)
            # Reset key selection
            self.run_list_model.set_selected_keys([], [], [], force_update=True)
