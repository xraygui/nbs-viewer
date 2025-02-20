from .views.dataSourceSwitcher import DataSourceSwitcher
from .models.plot.canvasManager import CanvasManager
from .views.plot.canvasTab import CanvasTab
from .views.plot.plotWidget import PlotWidget
from qtpy.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QSplitter, QTabBar
from qtpy.QtCore import Qt


class MainWidget(QWidget):
    """Widget managing multiple canvas views in tabs."""

    def __init__(self, parent=None):
        """
        Initialize the multi-canvas widget.

        Parameters
        ----------
        canvas_manager : CanvasManager
            Model managing all canvases
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.canvas_manager = CanvasManager()

        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)  # Enable close buttons by default
        self.tab_widget.tabCloseRequested.connect(self._on_tab_close)

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.tab_widget)
        self.setLayout(layout)

        # Connect to canvas manager signals
        self.canvas_manager.canvas_added.connect(self._on_canvas_added)
        self.canvas_manager.canvas_removed.connect(self._on_canvas_removed)

        # Create main tab
        self._create_main_tab()

    def _create_main_tab(self):
        """Create the main tab with data source manager."""
        main_model = self.canvas_manager.canvases["main"]

        # Create main tab widgets
        data_source = DataSourceSwitcher(main_model, self.canvas_manager)
        plot_widget = PlotWidget(main_model)

        # Create main tab layout
        main_tab = QWidget()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(data_source)
        splitter.addWidget(plot_widget)

        layout = QVBoxLayout(main_tab)
        layout.addWidget(splitter)
        main_tab.setLayout(layout)

        # Add to tab widget and disable close button for main tab only
        index = self.tab_widget.addTab(main_tab, "Main")
        self.tab_widget.tabBar().setTabButton(index, QTabBar.RightSide, None)

    def _on_canvas_added(self, canvas_id, plot_model):
        """Handle new canvas creation."""
        if canvas_id != "main":
            tab = CanvasTab(plot_model, self.canvas_manager, canvas_id)
            self.tab_widget.addTab(tab, f"Canvas {canvas_id}")
            # No need to set closable since the tab widget is already closable
            self.tab_widget.setCurrentWidget(tab)

    def _on_canvas_removed(self, canvas_id):
        """Handle canvas removal."""
        if canvas_id != "main":
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == f"Canvas {canvas_id}":
                    self.tab_widget.removeTab(i)
                    break

    def _on_tab_close(self, index):
        """Handle tab close request."""
        if self.tab_widget.tabText(index) != "Main":
            canvas_id = self.tab_widget.tabText(index).replace("Canvas ", "")
            self.canvas_manager.remove_canvas(canvas_id)
