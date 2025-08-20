from .plotDisplay import PlotDisplay
from qtpy.QtWidgets import QWidget, QSplitter, QVBoxLayout
from qtpy.QtCore import Qt

from nbs_viewer.views.dataSourceSwitcher import DataSourceSwitcher
from nbs_viewer.views.plot.plotWidget import PlotWidget


class MainDisplay(PlotDisplay):
    def __init__(self, app_model, display_id="main", parent=None):
        super().__init__(app_model, "main", parent)

        # Create main tab widgets

    def setup_models(self):
        run_list_model = self.display_manager.run_list_models["main"]
        self.data_source = DataSourceSwitcher(self.app_model, run_list_model)
        self.plot_widget = PlotWidget(run_list_model)

        # Create main tab layout with three panels

    def setup_ui(self):

        # Create horizontal splitter for the three panels
        splitter = QSplitter(Qt.Horizontal)

        # Left panel: Data source
        splitter.addWidget(self.data_source)

        # Center panel: Plot widget
        splitter.addWidget(self.plot_widget)

        # Right panel: Plot controls
        if hasattr(self.plot_widget, "plot_controls"):
            splitter.addWidget(self.plot_widget.plot_controls)

        # Set initial sizes (data:30%, plot:50%, controls:20%)
        splitter.setSizes([300, 500, 200])

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        self.setLayout(layout)
