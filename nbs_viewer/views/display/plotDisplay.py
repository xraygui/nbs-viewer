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
from ..plot.imageGridWidget import ImageGridWidget
from ..common.panel import CollapsiblePanel


class PlotDisplay(QWidget):
    """
    A tab containing a display run list and plot widget.

    This represents a single display view, with its run management and plot display.
    Uses collapsible panels for run list and plot controls to maximize plot space.
    """

    __widget_name__ = "Plot"
    __widget_description__ = "Display data as a plot"
    __widget_capabilities__ = ["1d", "2d"]
    __widget_version__ = "1.0.0"
    __widget_author__ = "NBS Viewer Team"

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

    def rename_display(self, new_name: str):
        self.display_id = new_name
        self.data_source.display_id = new_name

    def setup_models(self):
        # Create widgets
        self.run_list_model = self.display_manager.get_run_list_model(self.display_id)
        self.data_source = RunListView(
            self.run_list_model, self.display_manager, self.display_id
        )

        # Create plot widget based on display widget type
        self.plot_widget = self._create_plot_widget()

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

    def _create_plot_widget(self):
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
        return PlotWidget(self.run_list_model)


class ImageGridDisplay(PlotDisplay):
    __widget_name__ = "Image Grid"
    __widget_description__ = "Display N-D data as a grid of 2D images"
    __widget_capabilities__ = ["2d", "3d", "4d"]
    __widget_version__ = "1.0.0"
    __widget_author__ = "NBS Viewer Team"

    def setup_models(self):
        super().setup_models()

        # Enable single-selection mode for image grid displays
        self.run_list_model._single_selection_mode = True

    def _create_plot_widget(self):
        return ImageGridWidget(self.run_list_model)
