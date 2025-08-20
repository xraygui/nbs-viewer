from .models.app_model import AppModel
from .views.display.plotDisplay import PlotDisplay
from .views.display.mainDisplay import MainDisplay
from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTabWidget,
    QSplitter,
    QTabBar,
    QMessageBox,
)
from qtpy.QtCore import Qt

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    tomllib = None  # Python <3.11 (we read via AppModel)


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
        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.tab_widget)
        self.setLayout(layout)

    def _connect_signals(self):
        """Connect signals between components."""
        # Connect to display manager signals
        self.display_manager.display_added.connect(self._on_display_added)
        self.display_manager.display_removed.connect(self._on_display_removed)

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
        display_id = self.display_manager.create_display(widget_type)
        current_display = self.get_current_display()
        # Auto-add selected runs from current catalog view
        runs = current_display.get_selected_runs()
        if runs:
            self.display_manager.add_runs_to_display(runs, display_id)
        return display_id

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
    def _on_display_added(self, display_id, plot_model):
        """Handle new display creation."""
        if display_id != "main":
            tab = PlotDisplay(self.app_model, display_id)
            self.tab_widget.addTab(tab, f"Display {display_id}")
            self.tab_widget.setCurrentWidget(tab)

    def _on_display_removed(self, display_id):
        """Handle display removal."""
        if display_id != "main":
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == f"Display {display_id}":
                    self.tab_widget.removeTab(i)
                    break

    def _on_tab_close(self, index):
        """Handle tab close request."""
        if self.tab_widget.tabText(index) != "Main":
            display_id = self.tab_widget.tabText(index).replace("Display ", "")
            self.display_manager.remove_display(display_id)
