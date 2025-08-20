from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSplitter,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
)
from qtpy.QtCore import Qt
from qtpy.QtGui import QIcon
from ..dataSource.runListView import RunListView
from ..plot.plotWidget import PlotWidget
from ..common.panel import CollapsiblePanel


class PlotDisplay(QWidget):
    """
    A tab containing a display run list and plot widget.

    This represents a single display view, with its run management and plot display.
    Uses collapsible panels for run list and plot controls to maximize plot space.
    """

    def __init__(self, app_model, display_id, parent=None):
        """
        Initialize a display tab.

        Parameters
        ----------
        app_model : AppModel
            Model managing the application data
        display_id : str
            Identifier for this display
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.app_model = app_model
        self.display_id = display_id
        self.display_manager = self.app_model.display_manager
        self.setup_models()
        self.setup_ui()

    def setup_models(self):
        # Create widgets
        run_list_model = self.app_model.display_manager.run_list_models[self.display_id]
        display_manager = self.app_model.display_manager
        self.data_source = RunListView(run_list_model, display_manager, self.display_id)

        # Create plot widget based on display widget type
        self.plot_widget = self._create_plot_widget(
            run_list_model, display_manager, self.display_id
        )

        # Create collapsible panels for data management
        self.run_panel = CollapsiblePanel("Runs", self.data_source)

        # Create plot controls panel if available
        if hasattr(self.plot_widget, "plot_controls"):
            self.plot_controls_panel = CollapsiblePanel(
                "Plot Controls", self.plot_widget.plot_controls
            )
        else:
            self.plot_controls_panel = None

        # Create debug panel if available
        if hasattr(self.plot_widget, "debug_button") and self.plot_widget.debug_button:
            self.debug_panel = CollapsiblePanel("Debug", self.plot_widget.debug_button)
        else:
            self.debug_panel = None

    def setup_ui(self):
        # Create sidebar with stacked panels
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(2)

        # Add panels in order
        sidebar_layout.addWidget(self.run_panel)
        if self.plot_controls_panel:
            sidebar_layout.addWidget(self.plot_controls_panel)
        if self.debug_panel:
            sidebar_layout.addWidget(self.debug_panel)
        sidebar_layout.addStretch()  # Push panels to top

        # Create splitter for resizable panels
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(sidebar_widget)
        self.splitter.addWidget(self.plot_widget)  # Plot widget handles its own layout

        # Set initial splitter sizes (sidebar: 20%, plot: 80%)
        self.splitter.setSizes([200, 800])

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)
        self.setLayout(layout)

    def get_selected_runs(self):
        """Get the currently selected runs."""
        return self.data_source.get_selected_runs()

    def _create_plot_widget(self, run_list_model, display_manager, display_id):
        """
        Create the appropriate plot widget based on display widget type.

        Parameters
        ----------
        run_list_model : RunListModel
            The plot model for this display
        display_manager : DisplayManager
            The display manager
        display_id : str
            The display identifier

        Returns
        -------
        QWidget
            The created plot widget
        """
        # Get widget type for this display
        display_type = display_manager.get_display_type(display_id)

        # Get widget registry from display manager
        display_registry = display_manager._display_registry

        if (
            display_registry
            and display_type in display_registry.get_available_displays()
        ):
            # Create widget using registry
            display_class = display_registry.get_display(display_type)
            return display_class(run_list_model)
        else:
            # Fallback to default PlotWidget
            return PlotWidget(run_list_model)
