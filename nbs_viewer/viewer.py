import argparse
from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget, QTabWidget
from qtpy.QtCore import Qt
from .mainWidget import MainWidget

# import logging

# logging.basicConfig(
#    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
# )


class Viewer(QWidget):
    def __init__(self, config_file=None, parent=None):
        super(Viewer, self).__init__(parent)
        self.layout = QVBoxLayout(self)

        # Create a QTabWidget

        self.mainWidget = MainWidget(self)
        self.layout.addWidget(self.mainWidget)
        self.setLayout(self.layout)


def main():
    parser = argparse.ArgumentParser(description="NBS Viewer")
    parser.add_argument("-f", "--config", help="Path to the catalog config file")
    args = parser.parse_args()
    print("Starting Viewer Main")
    app = QApplication([])
    viewer = Viewer(config_file=args.config)
    viewer.show()
    app.exec_()


if __name__ == "__main__":
    main()
