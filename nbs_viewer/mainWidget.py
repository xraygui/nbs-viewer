from .views.dataSourceSwitcher import DataSourceSwitcher
from .models.app_model import AppModel
from .views.display.plotDisplay import PlotDisplay
from .views.plot.plotWidget import PlotWidget
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
    """Widget managing multiple canvas views in tabs."""

    def __init__(self, parent=None, config_file=None, app_model: AppModel = None):
        """
        Initialize the multi-canvas widget.

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
        # Fallback for direct use in tests
        if self.app_model is None:
            from .models.app_model import AppModel as _AM

            self.app_model = _AM(config_file)

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
        self.canvas_manager = self.app_model.canvases
        self.widget_registry = self.app_model.widgets
        # Apply config defaults (e.g., default widget)
        self._apply_config_defaults()

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
        # Connect to canvas manager signals
        self.canvas_manager.canvas_added.connect(self._on_canvas_added)
        self.canvas_manager.canvas_removed.connect(self._on_canvas_removed)

        # Connect tab close signal
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close)

    def _apply_config_defaults(self):
        """Apply defaults from config to registry."""
        try:
            default_widget = self.app_model.config.get("plot_widgets.default_widget")
            if default_widget:
                self.widget_registry.set_default_widget(default_widget)
        except Exception as e:
            print(f"Failed to apply widget defaults: {e}")

    def _create_main_tab(self):
        """Create the main tab with data source manager."""
        main_model = self.canvas_manager.canvases["main"]

        # Create main tab widgets
        self.data_source = DataSourceSwitcher(
            main_model,
            self.canvas_manager,
            self.config_file,
            self.app_model,
        )
        self.plot_widget = PlotWidget(main_model)

        # Create main tab layout with three panels
        main_tab = QWidget()

        # Create horizontal splitter for the three panels
        splitter = QSplitter(Qt.Horizontal)

        # Left panel: Data source
        splitter.addWidget(self.data_source)

        # Center panel: Plot widget
        splitter.addWidget(self.plot_widget)

        # Right panel: Plot controls
        if hasattr(self.plot_widget, "plot_controls"):
            splitter.addWidget(self.plot_widget.plot_controls)

        # Set initial sizes (data:30%, plot:50%, controls:20%)
        splitter.setSizes([300, 500, 200])

        layout = QVBoxLayout(main_tab)
        layout.addWidget(splitter)
        main_tab.setLayout(layout)

        # Add to tab widget and disable close button for main tab only
        index = self.tab_widget.addTab(main_tab, "Main")
        self.tab_widget.tabBar().setTabButton(index, QTabBar.RightSide, None)

    # Controller methods for menu actions
    def create_canvas(self, widget_type=None):
        """Create a new canvas with optional widget type."""
        canvas_id = self.canvas_manager.create_canvas(widget_type)
        # Auto-add selected runs from current catalog view
        if hasattr(self, "data_source") and self.data_source is not None:
            runs = self.data_source.get_selected_runs()
            if runs:
                self.canvas_manager.add_runs_to_canvas(runs, canvas_id)
        return canvas_id

    def create_matplotlib_canvas(self):
        """Create a new matplotlib canvas."""
        return self.create_canvas("matplotlib")

    def create_image_grid_canvas(self):
        """Create a new image grid canvas."""
        return self.create_canvas("image_grid")

    def close_current_canvas(self):
        """Close the currently active canvas."""
        current_index = self.tab_widget.currentIndex()
        if current_index > 0:  # Don't close main tab
            self._on_tab_close(current_index)
        else:
            QMessageBox.warning(self, "Cannot Close", "Cannot close the main canvas")

    def duplicate_current_canvas(self):
        """Duplicate the currently active canvas."""
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, "plot_model"):
            # TODO: Implement canvas duplication logic
            print("Canvas duplication not implemented yet")

    def get_current_canvas(self):
        """Get the currently active canvas model."""
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, "plot_model"):
            return current_tab.plot_model
        return None

    def get_current_canvas_widget(self):
        """Get the currently active canvas widget."""
        return self.tab_widget.currentWidget()

    def save_canvas_layout(self, filename):
        """Save the current canvas layout to a file."""
        # TODO: Implement layout saving
        print(f"Save canvas layout to {filename} - not implemented yet")

    def apply_canvas_settings(self, settings):
        """Apply settings to the current canvas."""
        # TODO: Implement settings application
        print("Apply canvas settings - not implemented yet")

    # Signal handlers
    def _on_canvas_added(self, canvas_id, plot_model):
        """Handle new canvas creation."""
        if canvas_id != "main":
            tab = PlotDisplay(plot_model, self.canvas_manager, canvas_id)
            self.tab_widget.addTab(tab, f"Canvas {canvas_id}")
            self.tab_widget.setCurrentWidget(tab)

    def _on_canvas_removed(self, canvas_id):
        """Handle canvas removal."""
        if canvas_id != "main":
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == f"Canvas {canvas_id}":
                    self.tab_widget.removeTab(i)
                    break

    def _on_tab_close(self, index):
        """Handle tab close request."""
        if self.tab_widget.tabText(index) != "Main":
            canvas_id = self.tab_widget.tabText(index).replace("Canvas ", "")
            self.canvas_manager.remove_canvas(canvas_id)
