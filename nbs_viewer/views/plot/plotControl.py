from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QHBoxLayout,
    QSizePolicy,
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
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        # Create the tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        # Create the plot control tab
        self.plot_control_tab = QWidget()
        self.plot_control_tab.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self.plot_control_layout = QVBoxLayout(self.plot_control_tab)
        self.plot_control_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_control_layout.setSpacing(1)

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
        self.layout.addWidget(self.tab_widget, 1)

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

        plot_settings_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        settings_min_height = plot_settings_layout.minimumSize().height()
        if settings_min_height > 0:
            plot_settings_widget.setMinimumHeight(settings_min_height)

        # Create collapsible plot settings panel (fixed size)
        self.plot_settings_panel = CollapsiblePanel(
            "Plot Settings", plot_settings_widget, can_expand=False, resizable=False
        )
        self.plot_control_layout.addWidget(self.plot_settings_panel, 0)

        self.transform = TransformControl(self.run_list_model)
        self.transform_panel = CollapsiblePanel(
            "Transform", self.transform, can_expand=False, resizable=False
        )
        self.plot_control_layout.addWidget(self.transform_panel, 0)

        self.run_display = RunDisplayWidget(self.run_list_model)
        self.run_display_panel = CollapsiblePanel(
            "Run Display",
            self.run_display,
            can_expand=True,
            initially_expanded=True,
            resizable=False,
        )
        self.plot_control_layout.addWidget(self.run_display_panel, 0)

        self.spacer = self.plot_control_layout.addStretch(0)
        self._update_panel_layout()

    def _update_panel_layout(self):
        """
        Distribute vertical space: Run Display grows when expanded; spacer
        only absorbs slack when every panel is collapsed.
        """
        panels = [
            self.plot_settings_panel,
            self.transform_panel,
            self.run_display_panel,
        ]
        collapsed_count = sum(1 for panel in panels if panel.is_collapsed)

        self.plot_control_layout.setStretchFactor(self.plot_settings_panel, 0)
        self.plot_control_layout.setStretchFactor(self.transform_panel, 0)
        run_stretch = 0 if self.run_display_panel.is_collapsed else 1
        self.plot_control_layout.setStretchFactor(self.run_display_panel, run_stretch)

        spacer_stretch = 1 if collapsed_count == len(panels) else 0
        if self.spacer:
            self.plot_control_layout.removeItem(self.spacer)
            self.spacer = self.plot_control_layout.addStretch(spacer_stretch)

    def _update_spacer_stretch(self):
        """Called when a collapsible panel toggles; refresh layout stretch."""
        self._update_panel_layout()
