from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLabel,
    QSizePolicy,
    QTabWidget,
)
from .metadataView import MetadataViewer
from .controls.control_panel import ControlPanel
from .mplCanvas.mpl_panel import MplPanel
from .mplCanvas.single_canvas import MplCanvas


class BasePlotWidget(QWidget):
    """
    Shared plot display shell: viewport panel, control tabs, and status line.

    Parameters
    ----------
    presenter : PlotPresenter
        Plot session presenter.
    panel : QWidget
        Viewport panel (e.g. :class:`MplPanel` or :class:`ImageGridPanel`).
    plot_canvas : MplCanvas, optional
        Canvas passed to plot settings when applicable.
    enable_spatial_controls : bool, optional
        Whether dimension and region control panels are included.
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(
        self,
        presenter,
        panel,
        plot_canvas=None,
        enable_spatial_controls=False,
        parent=None,
    ):
        super().__init__(parent)
        self.presenter = presenter
        self.panel = panel
        self.plot_canvas = plot_canvas
        self.plot_controls = self._create_plot_controls(
            plot_canvas, enable_spatial_controls
        )

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

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plot_layout = QVBoxLayout(self)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)
        plot_layout.addWidget(panel, 1)
        plot_layout.addWidget(self.cache_status_label, 0)

        self.presenter.status_changed.connect(self.cache_status_label.setText)

    def _create_plot_controls(self, plot_canvas, enable_spatial_controls):
        """
        Create the plot controls and metadata tab panel.
        """
        panel = QWidget()
        panel.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        tab_widget = QTabWidget()
        tab_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        control_tab = ControlPanel(
            self.presenter,
            plot_canvas=plot_canvas,
            enable_spatial_controls=enable_spatial_controls,
        )

        metadata_tab = MetadataViewer(self.presenter)

        tab_widget.addTab(control_tab, "Plot Controls")
        tab_widget.addTab(metadata_tab, "Metadata")

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        panel_layout.addWidget(tab_widget, 1)

        return panel


class PlotWidget(BasePlotWidget):
    """
    Standard 1D/2D plot display with :class:`MplCanvas`.

    Parameters
    ----------
    presenter : PlotPresenter
        Plot session presenter.
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, presenter, parent=None):
        plot_canvas = MplCanvas(presenter, None, 5, 4, 100)
        panel = MplPanel(plot_canvas, None)
        super().__init__(
            presenter,
            panel,
            plot_canvas=plot_canvas,
            enable_spatial_controls=True,
            parent=parent,
        )
