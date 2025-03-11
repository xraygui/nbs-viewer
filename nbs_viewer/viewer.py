import argparse
from qtpy.QtWidgets import QApplication, QVBoxLayout, QWidget, QTabWidget
from qtpy.QtCore import Qt
from .mainWidget import MainWidget
from .utils import turn_on_debugging, turn_off_debugging

# import logging

# logging.basicConfig(
#    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
# )


class Viewer(QWidget):
    def __init__(self, config_file=None, parent=None):
        super(Viewer, self).__init__(parent)
        self.layout = QVBoxLayout(self)

        # Create a QTabWidget

        self.mainWidget = MainWidget(self, config_file=config_file)
        self.layout.addWidget(self.mainWidget)
        self.setLayout(self.layout)


def main():
    parser = argparse.ArgumentParser(description="NBS Viewer")
    parser.add_argument("-f", "--config", help="Path to the catalog config file")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()
    if args.debug:
        print("Debug statements on")
        turn_on_debugging()
    else:
        turn_off_debugging()
    print("Starting Viewer Main")
    app = QApplication([])
    viewer = Viewer(config_file=args.config)
    viewer.show()
    app.exec_()


if __name__ == "__main__":
    main()
