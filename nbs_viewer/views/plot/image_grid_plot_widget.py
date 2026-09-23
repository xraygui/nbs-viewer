from .mplCanvas.image_grid_canvas import ImageGridCanvas
from .mplCanvas.image_grid_panel import ImageGridPanel
from .plotWidget import BasePlotWidget


class ImageGridPlotWidget(BasePlotWidget):
    """
    N-D image grid display with paginated subplot view.

    Parameters
    ----------
    presenter : PlotPresenter
        Plot session presenter.
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, presenter, parent=None):
        plot_canvas = ImageGridCanvas(presenter, None)
        panel = ImageGridPanel(plot_canvas, None)
        super().__init__(
            presenter,
            panel,
            plot_canvas=None,
            enable_spatial_controls=False,
            parent=parent,
        )
