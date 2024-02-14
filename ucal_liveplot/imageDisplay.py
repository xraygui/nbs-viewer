from qtpy.QtWidgets import QWidget, QApplication, QVBoxLayout, QLabel, QHBoxLayout, QMainWindow
from skimage import data
from napari.components import ViewerModel
from napari.qt import QtViewer, QtViewerButtons, Window


class ImageDisplay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        viewModel = ViewerModel("Test Napari Viewer")
        testWindow = Window(viewModel)
        layout.addWidget(testWindow._qt_window)
        testWindow.qt_viewer.viewer.add_image(data.cell())
        #layout.addWidget(viewWidget)
        
        self.setLayout(layout)
