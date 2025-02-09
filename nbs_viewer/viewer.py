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
        self.tab_widget = QTabWidget(self)
        # Set the tab position to the left (vertical tabs)
        self.tab_widget.setTabPosition(QTabWidget.West)
        self.mainWidget = MainWidget(self)
        self.tab_widget.addTab(self.mainWidget, "Main")
        """
        # Create the plot managers
        self.data_list_manager = PlotManagerWithDataList(config_file, self)
        self.bluesky_list_manager = PlotManagerWithBlueskyList(self)

        # Add the plot managers to the tab widget
        self.tab_widget.addTab(self.data_list_manager, "Data List")
        self.tab_widget.addTab(self.bluesky_list_manager, "Bluesky List")

        # Connect the signals
        self.data_list_manager.addToPlot.connect(
            self.bluesky_list_manager.list_widget.addPlotItem
        )
        """

        # Add the tab widget to the main layout
        self.layout.addWidget(self.tab_widget)

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
