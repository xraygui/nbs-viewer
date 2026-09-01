from qtpy.QtWidgets import QVBoxLayout, QWidget, QSizePolicy

from nbs_viewer.views.common.panel import CollapsiblePanel
from .plot_settings import PlotSettingsWidget
from .run_display import RunDisplayWidget
from .transform import TransformControl
from .dimension import DimensionControl
from .region_control import RegionControlWidget


class ControlPanel(QWidget):
    """
    Plot Controls tab: settings, view axes, region, transform, and run display.

    Parameters
    ----------
    presenter : PlotPresenter
        Plot session presenter.
    plot_canvas : MplCanvas, optional
        Canvas for plot settings and spatial controls.
    enable_spatial_controls : bool, optional
        When True, include dimension and region panels. Requires
        ``plot_canvas``. This flag is interim; a capability-based or
        plug-in control layout would be cleaner long term.
    parent : QWidget, optional
        Parent widget, by default None.
    """

    def __init__(
        self,
        presenter,
        plot_canvas=None,
        enable_spatial_controls=False,
        parent=None,
    ):
        super().__init__(parent)
        self.presenter = presenter
        self.plot_canvas = plot_canvas
        self._enable_spatial_controls = enable_spatial_controls
        if enable_spatial_controls and plot_canvas is None:
            raise ValueError(
                "plot_canvas is required when enable_spatial_controls is True"
            )
        self.dimension_control = None
        self.region_control = None
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        self._tab_layout = QVBoxLayout(self)
        self._tab_layout.setContentsMargins(0, 0, 0, 0)
        self._tab_layout.setSpacing(0)

        self.plot_settings = PlotSettingsWidget(presenter, plot_canvas)
        self.plot_settings_panel = CollapsiblePanel(
            "Plot Settings",
            self.plot_settings,
            can_expand=False,
            resizable=False,
        )
        self._tab_layout.addWidget(self.plot_settings_panel, 0)

        if enable_spatial_controls:
            self.dimension_control = DimensionControl(presenter, plot_canvas)
            self.dimension_control_panel = CollapsiblePanel(
                "Dimension Control",
                self.dimension_control,
                can_expand=False,
                resizable=False,
            )
            self._tab_layout.addWidget(self.dimension_control_panel, 0)

            self.region_control = RegionControlWidget(
                presenter, plot_canvas, self.dimension_control
            )
            self.region_control_panel = CollapsiblePanel(
                "Region",
                self.region_control,
                can_expand=False,
                resizable=False,
            )
            self._tab_layout.addWidget(self.region_control_panel, 0)

        self.transform = TransformControl(presenter)
        self.transform_panel = CollapsiblePanel(
            "Transform", self.transform, can_expand=False, resizable=False
        )
        self._tab_layout.addWidget(self.transform_panel, 0)

        self.run_display = RunDisplayWidget(presenter)
        self.run_display_panel = CollapsiblePanel(
            "Run Display",
            self.run_display,
            can_expand=True,
            initially_expanded=True,
            resizable=False,
        )
        self._tab_layout.addWidget(self.run_display_panel, 0)

        self.spacer = self._tab_layout.addStretch(0)

        for panel in self._stretch_panels():
            panel.collapsed_changed.connect(self._update_spacer_stretch)

        self._update_panel_layout()

    def _stretch_panels(self):
        """
        Return collapsible panels participating in vertical stretch logic.
        """
        panels = [
            self.plot_settings_panel,
            self.transform_panel,
            self.run_display_panel,
        ]
        if self._enable_spatial_controls:
            panels[1:1] = [
                self.dimension_control_panel,
                self.region_control_panel,
            ]
        return panels

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
