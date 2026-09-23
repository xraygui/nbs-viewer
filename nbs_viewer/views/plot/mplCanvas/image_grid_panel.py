from qtpy.QtCore import Signal
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT


class ImageGridPagingControls(QWidget):
    """
    Paging controls for an :class:`ImageGridCanvas`.

    Parameters
    ----------
    images_per_page : int, optional
        Initial images-per-page value.
    parent : QWidget, optional
        Parent widget.
    """

    page_changed = Signal(int)
    images_per_page_changed = Signal(int)

    def __init__(self, images_per_page=9, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Images per page:"))
        self.images_per_page_spinbox = QSpinBox()
        self.images_per_page_spinbox.setMinimum(1)
        self.images_per_page_spinbox.setMaximum(100)
        self.images_per_page_spinbox.setValue(images_per_page)
        self.images_per_page_spinbox.valueChanged.connect(
            self.images_per_page_changed.emit
        )
        layout.addWidget(self.images_per_page_spinbox)

        layout.addWidget(QLabel("Page:"))
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setValue(1)
        self.page_spinbox.valueChanged.connect(self.page_changed.emit)
        layout.addWidget(self.page_spinbox)

        self.total_images_label = QLabel("Total: 0 images")
        layout.addWidget(self.total_images_label)

        layout.addStretch()

    def update_limits(self, total_images, max_pages, current_page, images_per_page):
        """
        Synchronize paging widgets with canvas state.

        Parameters
        ----------
        total_images : int
            Total number of images in the grid.
        max_pages : int
            Maximum page count.
        current_page : int
            Current one-based page index.
        images_per_page : int
            Current images-per-page setting.
        """
        self.total_images_label.setText(f"Total: {total_images} images")

        self.page_spinbox.blockSignals(True)
        self.page_spinbox.setMaximum(max(1, max_pages))
        self.page_spinbox.setValue(current_page)
        self.page_spinbox.blockSignals(False)

        self.images_per_page_spinbox.blockSignals(True)
        self.images_per_page_spinbox.setValue(images_per_page)
        self.images_per_page_spinbox.blockSignals(False)


class ImageGridPanel(QWidget):
    """
    Viewport chrome for an :class:`ImageGridCanvas`.

    Uses the stock matplotlib navigation toolbar; autoscale and legend actions
    from :class:`NavigationToolbar` are not applicable to multi-subplot grids.

    Parameters
    ----------
    canvas : ImageGridCanvas
        Image grid canvas.
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        self.toolbar = NavigationToolbar2QT(canvas, self)
        self.paging_controls = ImageGridPagingControls(
            canvas.images_per_page, self
        )

        self.paging_controls.page_changed.connect(canvas.set_page)
        self.paging_controls.images_per_page_changed.connect(
            canvas.set_images_per_page
        )
        canvas.paging_limits_changed.connect(self._on_paging_limits_changed)

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(canvas, 1)
        layout.addWidget(self.paging_controls)

    def _on_paging_limits_changed(self, total_images, max_pages):
        self.paging_controls.update_limits(
            total_images,
            max_pages,
            self.canvas._current_page,
            self.canvas.images_per_page,
        )
