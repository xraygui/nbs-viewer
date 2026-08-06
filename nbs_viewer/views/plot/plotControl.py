from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QSizePolicy,
)

from .metadataView import MetadataViewer
from .plot_control_tab import PlotControlTab


class PlotControls(QWidget):
    """
    A widget for interactive plotting controls.

    Manages multiple runs and their display settings through RunModels.
    Includes transform options and metadata display.

    Parameters
    ----------
    run_list_model : RunListModel
        Model for the active run list and plot settings
    plot_canvas : MplCanvas, optional
        Canvas passed to the plot control tab for dimension and ROI widgets
    plot_model : PlotModel, optional
        Plot session model; required when ``plot_canvas`` is set
    parent : QWidget, optional
        The parent widget, by default None
    """

    def __init__(
        self, run_list_model, plot_canvas=None, plot_model=None, parent=None
    ):
        super().__init__(parent)
        self.run_list_model = run_list_model
        self.plot_model = plot_model
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        self.tab_widget = QTabWidget()
        self.tab_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        self.plot_control_tab = PlotControlTab(
            run_list_model, plot_canvas, plot_model=plot_model
        )

        self.metadata_tab = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_tab)
        self.metadata_viewer = MetadataViewer(run_list_model)
        self.metadata_layout.addWidget(self.metadata_viewer)

        self.tab_widget.addTab(self.plot_control_tab, "Plot Controls")
        self.tab_widget.addTab(self.metadata_tab, "Metadata")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.addWidget(self.tab_widget, 1)
