import argparse
from qtpy.QtWidgets import QApplication, QHBoxLayout, QWidget, QSplitter
from qtpy.QtCore import Qt
from .datasource import DataSelection
from .runDisplay import DataDisplayWidget


class Viewer(QWidget):
    def __init__(self, config_file=None, parent=None):
        super(Viewer, self).__init__(parent)
        self.layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)

        self.data_selection = DataSelection(config_file)
        splitter.addWidget(self.data_selection)

        self.data_display = DataDisplayWidget()
        splitter.addWidget(self.data_display)

        self.layout.addWidget(splitter)
        self.data_selection.add_rows_current_plot.connect(self.data_display.addPlotItem)

        self.setLayout(self.layout)


def main():
    parser = argparse.ArgumentParser(description="NBS Viewer")
    parser.add_argument("-f", "--config", help="Path to the catalog config file")
    args = parser.parse_args()

    app = QApplication([])
    viewer = Viewer(config_file=args.config)
    viewer.show()
    app.exec_()


if __name__ == "__main__":
    main()
