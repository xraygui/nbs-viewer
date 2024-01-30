from qtpy.QtWidgets import QApplication, QHBoxLayout, QWidget
from datasource import DataSelection
from runDisplay import DataDisplayWidget


class Viewer(QWidget):
    def __init__(self, parent=None):
        super(Viewer, self).__init__(parent)
        self.layout = QHBoxLayout(self)

        self.data_selection = DataSelection()
        self.layout.addWidget(self.data_selection)

        self.data_display = DataDisplayWidget()
        self.layout.addWidget(self.data_display)

        self.data_selection.add_rows_current_plot.connect(self.data_display.addRun)

        self.setLayout(self.layout)


if __name__ == "__main__":
    app = QApplication([])
    viewer = Viewer()
    viewer.show()
    app.exec_()
