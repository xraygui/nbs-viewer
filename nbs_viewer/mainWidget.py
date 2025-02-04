from .dataSourceManager import DataSourceManager
from .models.plot.plotModel import PlotModel
from .views.plot.plotWidget import PlotWidget
from .views.plot.plotControl import PlotControls
from qtpy.QtWidgets import QWidget, QHBoxLayout, QSplitter
from qtpy.QtCore import Qt


class MainWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.dataSourceManager = DataSourceManager()
        self.plotModel = PlotModel()

        self.dataSourceManager.itemsSelected.connect(self.plotModel.setRunModels)
        self.plotWidget = PlotWidget(self.plotModel)
        self.controlWidget = PlotControls(self.plotModel)

        self.layout = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Horizontal)
        self.layout.addWidget(self.splitter)

        # Add widgets to splitter
        self.splitter.addWidget(self.dataSourceManager)
        self.splitter.addWidget(self.plotWidget)
        self.splitter.addWidget(self.controlWidget)

        self.setLayout(self.layout)
