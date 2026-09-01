from qtpy.QtWidgets import QVBoxLayout, QWidget, QSizePolicy

from .single_canvas import NavigationToolbar


class MplPanel(QWidget):
    """
    Matplotlib viewport chrome for a single :class:`MplCanvas`.

    Parameters
    ----------
    canvas : MplCanvas
        Plot canvas.
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.toolbar = NavigationToolbar(canvas, self)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(canvas, 1)
