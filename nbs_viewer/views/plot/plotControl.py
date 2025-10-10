from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QHBoxLayout,
)

from ..common.panel import CollapsiblePanel
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

    def __init__(self, run_list_model, parent=None):
        super().__init__(parent)
        self.run_list_model = run_list_model

        # Create the tab widget
        self.tab_widget = QTabWidget()

        # Create the plot control tab
        self.plot_control_tab = QWidget()
        self.plot_control_layout = QVBoxLayout(self.plot_control_tab)
        self.plot_control_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_control_layout.setSpacing(1)  # Minimal spacing between panels

        # Create the metadata tab
        self.metadata_tab = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_tab)
        self.metadata_viewer = MetadataViewer(run_list_model)
        self.metadata_layout.addWidget(self.metadata_viewer)

        # Add tabs to the tab widget
        self.tab_widget.addTab(self.plot_control_tab, "Plot Controls")
        self.tab_widget.addTab(self.metadata_tab, "Metadata")

        # Main layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.addWidget(self.tab_widget)

        self.setup_plot_control_tab()

    def setup_plot_control_tab(self):
        """Setup the plot control tab with all its widgets."""

        # Plot Settings Panel (collapsible)
        plot_settings_widget = QWidget()
        plot_settings_layout = QVBoxLayout(plot_settings_widget)
        plot_settings_layout.setContentsMargins(0, 0, 0, 0)

        # Create horizontal layout for plot settings controls
        settings_controls_layout = QHBoxLayout()

        # Auto add control
        self.auto_add = AutoAddControl(self.run_list_model)
        settings_controls_layout.addWidget(self.auto_add)

        # Dynamic update control
        self.dynamic_update = DynamicUpdateControl(self.run_list_model)
        settings_controls_layout.addWidget(self.dynamic_update)

        # Retain selection control (in its own row for better layout)
        self.retain_selection = RetainSelectionControl(self.run_list_model)

        plot_settings_layout.addLayout(settings_controls_layout)
        plot_settings_layout.addWidget(self.retain_selection)

        # Create collapsible plot settings panel (fixed size)
        self.plot_settings_panel = CollapsiblePanel(
            "Plot Settings", plot_settings_widget, can_expand=False
        )
        self.plot_control_layout.addWidget(self.plot_settings_panel)

        # Transform Panel (collapsible, fixed size)
        self.transform = TransformControl(self.run_list_model)
        self.transform_panel = CollapsiblePanel(
            "Transform", self.transform, can_expand=False
        )
        self.plot_control_layout.addWidget(self.transform_panel)

        # Run Display Panel (collapsible, expanding, starts expanded)
        self.run_display = RunDisplayWidget(self.run_list_model)
        self.run_display_panel = CollapsiblePanel(
            "Run Display", self.run_display, can_expand=True, initially_expanded=True
        )
        self.plot_control_layout.addWidget(self.run_display_panel)

        # Using size-policy-only approach - no stretch factors needed

        # Add stretchable spacer at the bottom to push headers to top when collapsed
        # Use stretch factor 0 so it doesn't compete with expanding panels
        # self.plot_control_layout.addStretch(0)
