from qtpy.QtWidgets import QWidget, QVBoxLayout, QSplitter
from qtpy.QtCore import Qt
from ..canvasRunList import CanvasRunList
from .plotWidget import PlotWidget


class CanvasTab(QWidget):
    """
    A tab containing a canvas run list and plot widget.

    This represents a single canvas view, with its run management and plot display.
    """

    def __init__(self, plot_model, canvas_manager, canvas_id, parent=None):
        """
        Initialize a canvas tab.

        Parameters
        ----------
        plot_model : PlotModel
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
        self.run_list = CanvasRunList(plot_model, canvas_manager, canvas_id)

        # Create plot widget based on canvas widget type
        self.plot_widget = self._create_plot_widget(
            plot_model, canvas_manager, canvas_id
        )

        # Create splitter for resizable panels
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.run_list)
        self.splitter.addWidget(self.plot_widget)

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.splitter)
        self.setLayout(layout)

    def _create_plot_widget(self, plot_model, canvas_manager, canvas_id):
        """
        Create the appropriate plot widget based on canvas widget type.

        Parameters
        ----------
        plot_model : PlotModel
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
            return widget_class(plot_model)
        else:
            # Fallback to default PlotWidget
            return PlotWidget(plot_model)
