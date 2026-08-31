from qtpy.QtWidgets import QVBoxLayout, QWidget, QSizePolicy

from ..common.panel import CollapsiblePanel
from .controls.plot_settings import PlotSettingsWidget
from .controls.run_display import RunDisplayWidget
from .controls.transform import TransformControl
from .plotDimensionWidget import PlotDimensionControl
from .roi.crop_control import CropControlWidget


class PlotControlTab(QWidget):
    """
    Plot Controls tab: settings, view axes, region, transform, and run display.

    Parameters
    ----------
    presenter : PlotPresenter
        Plot session presenter.
    plot_canvas : MplCanvas, optional
        Canvas for dimension and ROI controls; omitted when not applicable.
    parent : QWidget, optional
        Parent widget, by default None.
    """

    def __init__(self, presenter, plot_canvas=None, parent=None):
        super().__init__(parent)
        self.presenter = presenter
        self.plot_canvas = plot_canvas
        self.dimension_control = None
        self.crop_control = None
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

        if plot_canvas is not None:
            self.dimension_control = PlotDimensionControl(presenter, plot_canvas)
            self.dimension_control_panel = CollapsiblePanel(
                "Dimension Control",
                self.dimension_control,
                can_expand=False,
                resizable=False,
            )
            self._tab_layout.addWidget(self.dimension_control_panel, 0)

            self.crop_control = CropControlWidget(
                presenter, plot_canvas, self.dimension_control
            )
            self.crop_control_panel = CollapsiblePanel(
                "Crop",
                self.crop_control,
                can_expand=False,
                resizable=False,
            )
            self._tab_layout.addWidget(self.crop_control_panel, 0)

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
        if self.plot_canvas is not None:
            panels[1:1] = [
                self.dimension_control_panel,
                self.crop_control_panel,
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
