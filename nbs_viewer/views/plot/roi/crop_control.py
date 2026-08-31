from qtpy.QtWidgets import QVBoxLayout, QWidget

from .panel import RoiPanel


class CropControlWidget(QWidget):
    """
    Crop panel for inline region controls and ROI workbench launcher.

    Parameters
    ----------
    presenter : PlotPresenter
        Plot session presenter.
    plot_canvas : MplCanvas
        Canvas receiving crop interactions.
    dimension_control : PlotDimensionControl
        Dimension editor used to resolve plot-plane geometry.
    parent : QWidget, optional
        Parent widget, by default None.
    """

    def __init__(self, presenter, plot_canvas, dimension_control, parent=None):
        super().__init__(parent)
        self.presenter = presenter
        self.plot_canvas = plot_canvas
        self.dimension_control = dimension_control

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.panel = RoiPanel(
            presenter,
            plot_canvas,
            dimension_control=dimension_control,
            parent=self,
        )
        layout.addWidget(self.panel)
