from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLabel,
    QSizePolicy,
)
from .plotControl import PlotControls
from .mplCanvas.single_canvas import MplCanvas, NavigationToolbar


class PlotWidget(QWidget):
    """
    The main organizing widget that combines a plot, a list of Bluesky runs,
    and controls to add runs to the plot.

    Parameters
    ----------
    presenter : PlotPresenter
        Presenter coordinating run list and plot session state.
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, presenter, parent=None):
        super().__init__(parent)
        self.presenter = presenter

        self.plot_canvas = MplCanvas(
            self.presenter, self, 5, 4, 100
        )
        self.plot_toolbar = NavigationToolbar(self.plot_canvas, self)
        self.plot_controls = PlotControls(self.presenter, self.plot_canvas)

        self.cache_status_label = QLabel("")
        self.cache_status_label.setObjectName("cacheStatusLabel")
        self.cache_status_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.cache_status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        label_height = max(
            self.cache_status_label.sizeHint().height(),
            self.cache_status_label.fontMetrics().height() + 4,
        )
        self.cache_status_label.setFixedHeight(label_height)

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
        plot_layout.addWidget(self.cache_status_label, 0)

        self.presenter.status_changed.connect(self.cache_status_label.setText)
