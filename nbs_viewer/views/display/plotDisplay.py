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
from ..runListView import RunListView
from ..plot.plotWidget import PlotWidget
from ..common.panel import CollapsiblePanel


class PlotDisplay(QWidget):
    """
    A tab containing a canvas run list and plot widget.

    This represents a single canvas view, with its run management and plot display.
    Uses collapsible panels for run list and plot controls to maximize plot space.
    """

    def __init__(self, run_list_model, canvas_manager, canvas_id, parent=None):
        """
        Initialize a canvas tab.

        Parameters
        ----------
        run_list_model : RunListModel
            Model managing the canvas data
        canvas_manager : CanvasManager
            Manager for all canvases
        canvas_id : str
            Identifier for this canvas
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)

        # Create widgets
        self.run_list = RunListView(run_list_model, canvas_manager, canvas_id)

        # Create plot widget based on canvas widget type
        self.plot_widget = self._create_plot_widget(
            run_list_model, canvas_manager, canvas_id
        )

        # Create collapsible panels for data management
        self.run_panel = CollapsiblePanel("Runs", self.run_list)

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

    def _create_plot_widget(self, run_list_model, canvas_manager, canvas_id):
        """
        Create the appropriate plot widget based on canvas widget type.

        Parameters
        ----------
        run_list_model : RunListModel
            The plot model for this canvas
        canvas_manager : CanvasManager
            The canvas manager
        canvas_id : str
            The canvas identifier

        Returns
        -------
        QWidget
            The created plot widget
        """
        # Get widget type for this canvas
        widget_type = canvas_manager.get_canvas_widget_type(canvas_id)

        # Get widget registry from canvas manager
        widget_registry = canvas_manager._widget_registry

        if widget_registry and widget_type in widget_registry.get_available_widgets():
            # Create widget using registry
            widget_class = widget_registry.get_widget(widget_type)
            return widget_class(run_list_model)
        else:
            # Fallback to default PlotWidget
            return PlotWidget(run_list_model)
