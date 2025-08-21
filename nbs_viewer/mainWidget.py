from .models.app_model import AppModel
from .views.display.mainDisplay import MainDisplay
from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QTabBar,
    QMessageBox,
    QLineEdit,
)
from qtpy.QtCore import Qt


try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    tomllib = None  # Python <3.11 (we read via AppModel)


class RenameableTabBar(QTabBar):
    """Custom tab bar that allows renaming tabs by double-clicking."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.editor = None
        self.editing_index = -1
        self.setTabsClosable(True)  # Enable close buttons on this tab bar

    def mouseDoubleClickEvent(self, event):
        """Handle double-click events to rename tabs."""
        index = self.tabAt(event.pos())
        if index >= 0:
            self._start_editing(index)
        else:
            super().mouseDoubleClickEvent(event)

    def _start_editing(self, index):
        """Start inline editing for the tab at the given index."""
        current_text = self.tabText(index)

        # Don't allow renaming the main tab
        if current_text == "Main":
            QMessageBox.warning(self, "Cannot Rename", "Cannot rename the main display")
            return

        # Create inline editor
        self.editor = QLineEdit(self)
        self.editor.setText(current_text)
        self.editor.selectAll()

        # Position the editor over the tab
        rect = self.tabRect(index)
        self.editor.setGeometry(rect)
        self.editor.show()
        self.editor.setFocus()

        # Connect signals
        self.editor.editingFinished.connect(lambda: self._finish_editing(index))
        self.editor.returnPressed.connect(lambda: self._finish_editing(index))

        # Install event filter to handle Escape key
        self.editor.installEventFilter(self)

        self.editing_index = index

    def _finish_editing(self, index):
        """Finish editing and apply the new name."""
        if self.editor:
            new_name = self.editor.text().strip()
            old_name = self.tabText(index)

            if new_name and new_name != old_name:
                # Call rename method on parent
                if hasattr(self.parent(), "rename_tab"):
                    self.parent().rename_tab(index, new_name)
                elif hasattr(self.parent().parent(), "rename_tab"):
                    self.parent().parent().rename_tab(index, new_name)

            self._cleanup_editor()

    def _cancel_editing(self):
        """Cancel editing without applying changes."""
        self._cleanup_editor()

    def _cleanup_editor(self):
        """Clean up the editor widget."""
        if self.editor:
            self.editor.deleteLater()
            self.editor = None
            self.editing_index = -1

    def eventFilter(self, obj, event):
        """Handle events for the inline editor."""
        if obj == self.editor and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._cancel_editing()
                return True
        return super().eventFilter(obj, event)


class MainWidget(QWidget):
    """Widget managing multiple display views in tabs."""

    def __init__(self, parent=None, config_file=None, app_model: AppModel = None):
        """
        Initialize the multi-display widget.

        Parameters
        ----------
        parent : QWidget, optional
            Parent widget, by default None
        config_file : str, optional
            Path to configuration file, by default None
        """
        super().__init__(parent)
        self.config_file = config_file
        self.app_model = app_model

        # Setup models before UI/signals
        self._setup_models()

        # Setup UI components
        self._setup_ui()

        # Connect signals
        self._connect_signals()

        # Create main tab
        self._create_main_tab()

    def _setup_models(self):
        """Setup models"""
        # Use app-level model components
        self.display_manager = self.app_model.display_manager

    def _setup_ui(self):
        """Setup UI components and layout."""
        # Create tab widget with custom tab bar
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabBar(RenameableTabBar(self.tab_widget))

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.tab_widget)
        self.setLayout(layout)

    def _connect_signals(self):
        """Connect signals between components."""
        # Connect to display manager signals
        self.display_manager.display_added.connect(self._on_display_added)
        self.display_manager.display_removed.connect(self._on_display_removed)
        self.display_manager.display_renamed.connect(self._on_display_renamed)

        # Connect tab close signal
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close)

    def _create_main_tab(self):
        """Create the main tab with data source manager."""
        # TODO: Move this into a separate class
        self.main_display = MainDisplay(self.app_model, "main")

        # Add to tab widget and disable close button for main tab only
        index = self.tab_widget.addTab(self.main_display, "Main")
        self.tab_widget.tabBar().setTabButton(index, QTabBar.RightSide, None)

    # Controller methods for menu actions
    def create_display(self, widget_type=None):
        """Create a new display with optional widget type."""
        current_display = self.get_current_display()
        # Auto-add selected runs from current catalog view
        runs = current_display.get_selected_runs()
        self.display_manager.create_display_with_runs(runs, widget_type)

    def create_matplotlib_display(self):
        """Create a new matplotlib display."""
        return self.create_display("matplotlib")

    def create_image_grid_display(self):
        """Create a new image grid display."""
        return self.create_display("image_grid")

    def close_current_display(self):
        """Close the currently active display."""
        current_index = self.tab_widget.currentIndex()
        if current_index > 0:  # Don't close main tab
            self._on_tab_close(current_index)
        else:
            QMessageBox.warning(self, "Cannot Close", "Cannot close the main display")

    def duplicate_current_display(self):
        """Duplicate the currently active display."""
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, "plot_model"):
            # TODO: Implement display duplication logic
            print("Display duplication not implemented yet")

    def get_current_display(self):
        """Get the currently active display widget."""
        return self.tab_widget.currentWidget()

    def save_display_layout(self, filename):
        """Save the current display layout to a file."""
        # TODO: Implement layout saving
        print(f"Save display layout to {filename} - not implemented yet")

    def apply_display_settings(self, settings):
        """Apply settings to the current display."""
        # TODO: Implement settings application
        print("Apply display settings - not implemented yet")

    # Signal handlers
    def _on_display_added(self, display_id):
        """Handle new display creation."""
        if display_id != "main":
            widget_type = self.display_manager.get_display_type(display_id)
            DisplayClass = self.app_model.display_registry.get_display(widget_type)
            tab = DisplayClass(self.app_model, display_id)
            self.tab_widget.addTab(tab, f"{display_id}")
            # Close button will be automatically created since setTabsClosable(True) is set
            self.tab_widget.setCurrentWidget(tab)

    def _on_display_removed(self, display_id):
        """Handle display removal."""
        if display_id != "main":
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == f"{display_id}":
                    self.tab_widget.removeTab(i)
                    break

    def _on_tab_close(self, index):
        """Handle tab close request."""
        if self.tab_widget.tabText(index) != "Main":
            display_id = self.tab_widget.tabText(index)
            self.display_manager.remove_display(display_id)

    def rename_tab(self, index, new_name):
        """Rename a tab at the given index."""
        if index == 0:  # Main tab
            QMessageBox.warning(self, "Cannot Rename", "Cannot rename the main display")
            return

        old_name = self.tab_widget.tabText(index)
        if old_name != new_name:
            # Update the display manager - this will trigger signals to update everything
            self.display_manager.rename_display(old_name, new_name)

    def _on_display_renamed(self, old_name, new_name):
        """Handle display renaming."""
        if old_name != "main":
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == f"{old_name}":
                    widget = self.tab_widget.widget(i)
                    if hasattr(widget, "rename_display"):
                        widget.rename_display(new_name)
                    self.tab_widget.setTabText(i, f"{new_name}")
                    break
        else:
            QMessageBox.warning(self, "Cannot Rename", "Cannot rename the main display")
