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
        self.plot_widget = PlotWidget(plot_model)

        # Create splitter for resizable panels
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.run_list)
        self.splitter.addWidget(self.plot_widget)

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.splitter)
        self.setLayout(layout)
