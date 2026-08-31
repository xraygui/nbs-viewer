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
    presenter : PlotPresenter
        Plot session presenter.
    plot_canvas : MplCanvas, optional
        Canvas passed to the plot control tab for dimension and ROI widgets.
    parent : QWidget, optional
        The parent widget, by default None
    """

    def __init__(self, presenter, plot_canvas=None, parent=None):
        super().__init__(parent)
        self.presenter = presenter
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        self.tab_widget = QTabWidget()
        self.tab_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        self.plot_control_tab = PlotControlTab(presenter, plot_canvas)

        self.metadata_tab = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_tab)
        self.metadata_viewer = MetadataViewer(presenter)
        self.metadata_layout.addWidget(self.metadata_viewer)

        self.tab_widget.addTab(self.plot_control_tab, "Plot Controls")
        self.tab_widget.addTab(self.metadata_tab, "Metadata")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.addWidget(self.tab_widget, 1)
