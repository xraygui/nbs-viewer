from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QSizePolicy,
)

from ..common.panel import CollapsiblePanel
from .controls.run_display import RunDisplayWidget
from .controls.auto_add import AutoAddControl
from .controls.dynamic_update import DynamicUpdateControl
from .controls.transform import TransformControl
from .controls.retain_selection import RetainSelectionControl
from .plotDimensionWidget import PlotDimensionControl
from .roi_panel import RoiPanel
from .roi_controller import RoiController
from .derivative_controller import DerivativeController


class PlotControlTab(QWidget):
    """
    Plot Controls tab: settings, view axes, region, transform, and run display.

    Parameters
    ----------
    run_list_model : RunListModel
        Model for the active run list and plot settings
    plot_canvas : MplCanvas, optional
        Canvas for dimension and ROI controls; omitted when not applicable
    parent : QWidget, optional
        Parent widget, by default None
    """

    def __init__(self, run_list_model, plot_canvas=None, parent=None):
        super().__init__(parent)
        self.run_list_model = run_list_model
        self.plot_canvas = plot_canvas
        self.dimension_control = None
        self.roi_panel = None
        self.roi_controller = None
        self.derivative_controller = None
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        self._tab_layout = QVBoxLayout(self)
        self._tab_layout.setContentsMargins(0, 0, 0, 0)
        self._tab_layout.setSpacing(0)

        self._setup_panels()
        self._update_panel_layout()

    def _setup_panels(self):
        plot_settings_widget = QWidget()
        plot_settings_layout = QVBoxLayout(plot_settings_widget)
        plot_settings_layout.setContentsMargins(0, 0, 0, 0)
        plot_settings_layout.setSpacing(2)

        settings_controls_layout = QHBoxLayout()
        settings_controls_layout.setContentsMargins(0, 0, 0, 0)
        settings_controls_layout.setSpacing(4)

        self.auto_add = AutoAddControl(self.run_list_model)
        settings_controls_layout.addWidget(self.auto_add)

        self.dynamic_update = DynamicUpdateControl(self.run_list_model)
        settings_controls_layout.addWidget(self.dynamic_update)

        self.retain_selection = RetainSelectionControl(self.run_list_model)

        plot_settings_layout.addLayout(settings_controls_layout)
        plot_settings_layout.addWidget(self.retain_selection)

        plot_settings_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        settings_min_height = plot_settings_layout.minimumSize().height()
        if settings_min_height > 0:
            plot_settings_widget.setMinimumHeight(settings_min_height)

        self.plot_settings_panel = CollapsiblePanel(
            "Plot Settings", plot_settings_widget, can_expand=False, resizable=False
        )
        self._tab_layout.addWidget(self.plot_settings_panel, 0)

        if self.plot_canvas is not None:
            self._setup_canvas_panels()

        self.transform = TransformControl(self.run_list_model)
        self.transform_panel = CollapsiblePanel(
            "Transform", self.transform, can_expand=False, resizable=False
        )
        self._tab_layout.addWidget(self.transform_panel, 0)

        self.run_display = RunDisplayWidget(self.run_list_model)
        self.run_display_panel = CollapsiblePanel(
            "Run Display",
            self.run_display,
            can_expand=True,
            initially_expanded=True,
            resizable=False,
        )
        self._tab_layout.addWidget(self.run_display_panel, 0)

        self.spacer = self._tab_layout.addStretch(0)

    def _setup_canvas_panels(self):
        self.dimension_control = PlotDimensionControl(
            self.run_list_model, self.plot_canvas, self
        )
        self.dimension_control_panel = CollapsiblePanel(
            "Dimension Control",
            self.dimension_control,
            can_expand=False,
            resizable=False,
        )
        self._tab_layout.addWidget(self.dimension_control_panel, 0)

        self.roi_panel = RoiPanel(self)
        self.roi_panel_panel = CollapsiblePanel(
            "Region",
            self.roi_panel,
            can_expand=False,
            resizable=False,
        )
        self._tab_layout.addWidget(self.roi_panel_panel, 0)

        self.roi_controller = RoiController(
            self.plot_canvas,
            self.dimension_control,
            self.roi_panel,
            self.run_list_model,
            self,
        )
        self.derivative_controller = DerivativeController(
            self.plot_canvas,
            self.dimension_control,
            self.roi_panel,
            self,
        )

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

        self._tab_layout.setStretchFactor(self.plot_settings_panel, 0)
        self._tab_layout.setStretchFactor(self.transform_panel, 0)
        run_stretch = 0 if self.run_display_panel.is_collapsed else 1
        self._tab_layout.setStretchFactor(self.run_display_panel, run_stretch)

        spacer_stretch = 1 if collapsed_count == len(panels) else 0
        if self.spacer:
            self._tab_layout.removeItem(self.spacer)
            self.spacer = self._tab_layout.addStretch(spacer_stretch)

    def _update_spacer_stretch(self):
        """Called when a collapsible panel toggles; refresh layout stretch."""
        self._update_panel_layout()
