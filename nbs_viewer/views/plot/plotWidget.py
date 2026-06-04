from qtpy.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QSizePolicy,
)
from .plotDimensionWidget import PlotDimensionControl
from .plotControl import PlotControls
from .mpl_canvas import MplCanvas, NavigationToolbar
from .roi_panel import RoiPanel
from .roi_controller import RoiController
from .derivative_controller import DerivativeController
from nbs_viewer.utils import DEBUG_VARIABLES
from ..common.panel import CollapsiblePanel



class PlotWidget(QWidget):
    """
    The main organizing widget that combines a plot, a list of Bluesky runs,
    and controls to add runs to the plot.

    Parameters
    ----------
    run_list_model : RunListModel
        Model managing runs for this display.
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, run_list_model, parent=None):
        super().__init__(parent)
        self.run_list_model = run_list_model

        self.plot_canvas = MplCanvas(self.run_list_model, self, 5, 4, 100)
        self.plot_toolbar = NavigationToolbar(self.plot_canvas, self)
        self.dimension_control = PlotDimensionControl(
            self.run_list_model, self.plot_canvas, self
        )
        self.dimension_control_panel = CollapsiblePanel(
            "Dimension Control",
            self.dimension_control,
            can_expand=False,
            resizable=False,
        )
        self.roi_panel = RoiPanel(self)
        self.roi_panel_panel = CollapsiblePanel(
            "Region",
            self.roi_panel,
            can_expand=False,
            resizable=False,
        )
        self.roi_controller = RoiController(
            self.plot_canvas,
            self.dimension_control,
            self.roi_panel,
            self.run_list_model,
            self,
        )
        self.derivative_controller = DerivativeController(
            self.plot_canvas,
            self.dimension_control,
            self.roi_panel,
            self,
        )
        self.plot_controls = PlotControls(self.run_list_model)

        if DEBUG_VARIABLES["PRINT_DEBUG"]:
            self.debug_button = QPushButton("Debug Plot State")
            self.debug_button.clicked.connect(self._debug_plot_state)
        else:
            self.debug_button = None

        plot_pane = QWidget()
        plot_pane_layout = QVBoxLayout(plot_pane)
        plot_pane_layout.setContentsMargins(0, 0, 0, 0)
        plot_pane_layout.setSpacing(0)
        plot_pane_layout.addWidget(self.plot_toolbar)
        plot_pane_layout.addWidget(self.plot_canvas, stretch=1)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plot_layout = QVBoxLayout(self)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)
        plot_layout.addWidget(plot_pane, 1)
        plot_layout.addWidget(self.dimension_control_panel, 0)
        plot_layout.addWidget(self.roi_panel_panel, 0)
        if self.debug_button:
            plot_layout.addWidget(self.debug_button, 0)

    def _debug_plot_state(self):
        self.plot_canvas._debug_plot_state()
