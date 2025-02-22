from typing import Dict, List
from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QTreeWidget,
    QHBoxLayout,
)

from .controls.run_display import RunDisplayWidget
from .controls.auto_add import AutoAddControl
from .controls.dynamic_update import DynamicUpdateControl
from .controls.transform import TransformControl
from .controls.retain_selection import RetainSelectionControl
from .metadataView import MetadataViewer


class PlotControls(QWidget):
    """
    A widget for interactive plotting controls.

    Manages multiple runs and their display settings through RunModels.
    Includes transform options and metadata display.

    Parameters
    ----------
    plot : MPLCanvas or similar
        The plotting canvas where the data will be displayed
    parent : QWidget, optional
        The parent widget, by default None
    """

    def __init__(self, plotModel, parent=None):
        super().__init__(parent)
        self.plotModel = plotModel

        # Create the tab widget
        self.tab_widget = QTabWidget()

        # Create the plot control tab
        self.plot_control_tab = QWidget()
        self.plot_control_layout = QVBoxLayout(self.plot_control_tab)

        # Create the metadata tab
        self.metadata_tab = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_tab)
        self.metadata_viewer = MetadataViewer(plotModel)
        self.metadata_layout.addWidget(self.metadata_viewer)

        # Add tabs to the tab widget
        self.tab_widget.addTab(self.plot_control_tab, "Plot Controls")
        self.tab_widget.addTab(self.metadata_tab, "Metadata")

        # Main layout
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.tab_widget)

        self.setup_plot_control_tab()

    def setup_plot_control_tab(self):
        """Setup the plot control tab with all its widgets."""
        # Create horizontal layout for controls
        controls_layout = QHBoxLayout()

        # Auto add control
        self.auto_add = AutoAddControl(self.plotModel)
        controls_layout.addWidget(self.auto_add)

        # Dynamic update control
        self.dynamic_update = DynamicUpdateControl(self.plotModel)
        controls_layout.addWidget(self.dynamic_update)

        # Retain selection control
        self.retain_selection = RetainSelectionControl(self.plotModel)

        self.plot_control_layout.addLayout(controls_layout)
        self.plot_control_layout.addWidget(self.retain_selection)

        # Transform control
        self.transform = TransformControl(self.plotModel)
        self.plot_control_layout.addWidget(self.transform)

        # Run display widget
        self.run_display = RunDisplayWidget(self.plotModel)
        self.plot_control_layout.addWidget(self.run_display)
