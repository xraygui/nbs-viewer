#!/usr/bin/env python3
"""
Test application for logarithmic colormap implementation.
This follows the exact same pattern as PyQtGraphSpiralWidget.
"""

import sys
import numpy as np
import pyqtgraph as pg
from qtpy.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget


class TestMainWindow(QMainWindow):
    """Minimal test application following PyQtGraphSpiralWidget pattern."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Log Colormap Test")
        self.setGeometry(100, 100, 800, 600)

        # PyQtGraph configuration (same as PyQtGraphSpiralWidget)
        pg.setConfigOptions(imageAxisOrder="row-major")
        self.contrastLimits = [1e-1, 1e6]
        self.limitsInboardOutboardDownUp = [0, 61.7, 0, 61.4]

        self._setup_ui()
        self._create_test_data()
        self._create_test_plot()

    def _setup_ui(self):
        """Set up the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Create layout
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create horizontal layout for two plots side by side
        hbox = QHBoxLayout()

        # Create two plot widgets
        self.plot_widget1 = self._create_plot_widget("Log Colormap")
        self.plot_widget2 = self._create_plot_widget("Log Data")

        hbox.addWidget(self.plot_widget1)
        hbox.addWidget(self.plot_widget2)

        layout.addLayout(hbox)

    def _create_plot_widget(self, title):
        """Create a plot widget with consistent styling."""
        plot_widget = pg.PlotWidget()
        plot_widget.setAspectLocked(False)
        plot_widget.setMouseEnabled(x=False, y=False)

        # Style the plot (same as _style_pyqtgraph_plot)
        plot_widget.setFixedSize(400, 400)
        plot_widget.getPlotItem().hideButtons()
        plot_widget.getPlotItem().showAxes(True)
        plot_widget.setBackground("w")

        # Set axis labels
        plot_widget.setLabel("bottom", "Outboard-inboard (mm)")
        plot_widget.setLabel("left", "Down-up (mm)")

        # Set axis limits
        plot_widget.setXRange(
            self.limitsInboardOutboardDownUp[0], self.limitsInboardOutboardDownUp[1]
        )
        plot_widget.setYRange(
            self.limitsInboardOutboardDownUp[2], self.limitsInboardOutboardDownUp[3]
        )

        # Style axes
        for axis_name in ["left", "bottom", "top", "right"]:
            axis = plot_widget.getAxis(axis_name)
            axis.setPen(pg.mkPen(color="k", width=1))
            axis.setStyle(maxTickLevel=0, tickLength=4)

        # Set title
        plot_widget.setTitle(title, size="12pt", color="k")

        return plot_widget

    def _create_test_data(self):
        """Create test data with sine pattern in X direction."""
        # Create a test image with sine pattern
        x = np.linspace(0, 100, 100)
        y = np.linspace(0, 100, 100)
        X, Y = np.meshgrid(x, y)

        # Create sine pattern in X direction with some variation in Y
        self.test_data = self.contrastLimits[1] / 2 + self.contrastLimits[
            1
        ] / 2.1 * np.sin(2 * np.pi * X / 20) * np.cos(np.pi * Y / 50)

        print(f"Test data shape: {self.test_data.shape}")
        print(f"Test data type: {self.test_data.dtype}")
        print(f"Test data range: {self.test_data.min()} to {self.test_data.max()}")

    def _create_test_plot(self):
        """Create two test plots: one with log colormap, one with log data."""
        # Plot 1: Original data with log colormap
        image_item1 = self._create_image_item(self.test_data)
        self.plot_widget1.addItem(image_item1)

        # Plot 2: Log-transformed data with linear colormap
        image_item2 = self._create_image_item_log_data(self.test_data)
        self.plot_widget2.addItem(image_item2)

        print("Two test plots created successfully!")
        print("Left: Original data with log colormap")
        print("Right: Log-transformed data with linear colormap")

    def _create_image_item(self, image_data):
        """Create and configure an ImageItem with common settings.
        This is the exact same method as in PyQtGraphSpiralWidget.
        """
        # Create standard ImageItem with original data (no transformations)
        image_item = pg.ImageItem(np.maximum(image_data, self.contrastLimits[0]))

        # Set image bounds (same as PyQtGraphSpiralWidget)
        x_min, x_max = (
            self.limitsInboardOutboardDownUp[0],
            self.limitsInboardOutboardDownUp[1],
        )
        y_min, y_max = (
            self.limitsInboardOutboardDownUp[2],
            self.limitsInboardOutboardDownUp[3],
        )
        image_item.setRect(pg.QtCore.QRectF(x_min, y_min, x_max - x_min, y_max - y_min))

        # Set levels for original data
        image_item.setLevels([self.contrastLimits[0], self.contrastLimits[1]])

        # Get base colormap
        base_colormap = pg.colormap.get("RdYlBu_r", source="matplotlib")
        base_colors = base_colormap.getColors()
        num_colors = len(base_colors)

        # Create logarithmic colormap using logspace positions
        print(f"Creating log colormap with {num_colors} colors")

        cvalues = np.maximum(
            np.linspace(0, self.contrastLimits[1], 256), self.contrastLimits[0]
        )
        logcvals = np.log10(cvalues)
        relog = (logcvals - min(logcvals)) / (max(logcvals) - min(logcvals))
        lut = [base_colormap[v].getRgb() for v in relog]

        image_item.setLookupTable(lut)
        return image_item

    def _create_image_item_log_data(self, image_data):
        """Create and configure an ImageItem with common settings.
        This is the exact same method as in PyQtGraphSpiralWidget.
        """
        # Create standard ImageItem with original data (no transformations)
        image_item = pg.ImageItem(
            np.log10(np.maximum(image_data, self.contrastLimits[0]))
        )

        # Set image bounds (same as PyQtGraphSpiralWidget)
        x_min, x_max = (
            self.limitsInboardOutboardDownUp[0],
            self.limitsInboardOutboardDownUp[1],
        )
        y_min, y_max = (
            self.limitsInboardOutboardDownUp[2],
            self.limitsInboardOutboardDownUp[3],
        )
        image_item.setRect(pg.QtCore.QRectF(x_min, y_min, x_max - x_min, y_max - y_min))

        # Set levels for original data
        image_item.setLevels(
            [np.log10(self.contrastLimits[0]), np.log10(self.contrastLimits[1])]
        )

        # Get base colormap
        colormap = pg.colormap.get("RdYlBu_r", source="matplotlib")
        base_colors = colormap.getColors()
        num_colors = len(base_colors)
        print(f"Using linear colormap with {num_colors} colors")

        image_item.setColorMap(colormap)
        return image_item


def main():
    """Main function to run the test application."""
    app = QApplication(sys.argv)

    # Create and show the main window
    window = TestMainWindow()
    window.show()

    print("Test application started. Close the window to exit.")

    # Start the event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
