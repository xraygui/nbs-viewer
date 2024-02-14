from qtpy.QtWidgets import QApplication, QHBoxLayout, QWidget, QTabWidget
from datasource import DataSelection
from runDisplay import DataDisplayWidget
from imageDisplay import ImageDisplay


class Viewer(QWidget):
    def __init__(self, parent=None):
        super(Viewer, self).__init__(parent)
        self.layout = QHBoxLayout(self)

        self.data_selection = DataSelection()
        self.layout.addWidget(self.data_selection)

        #self.data_tabs = QTabWidget()
        self.data_display = DataDisplayWidget()
        #self.image_display = ImageDisplay()
        #self.data_tabs.addTab(self.data_display, "Run Display")
        #self.data_tabs.addTab(self.image_display, "Image Display")
        self.layout.addWidget(self.data_display)
        #self.layout.addWidget(self.data_tabs)
        self.data_selection.add_rows_current_plot.connect(self.data_display.addPlotItem)

        self.setLayout(self.layout)


if __name__ == "__main__":
    app = QApplication([])
    viewer = Viewer()
    viewer.show()
    app.exec_()
