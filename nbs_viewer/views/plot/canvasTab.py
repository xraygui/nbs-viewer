from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSplitter,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
)
from qtpy.QtCore import Qt
from qtpy.QtGui import QIcon
from ..canvasRunList import CanvasRunList
from .plotWidget import PlotWidget


class CollapsiblePanel(QWidget):
    """
    A collapsible panel with a header and toggle functionality.

    Similar to Photoshop's collapsible tool panels.
    """

    def __init__(self, title, widget, parent=None):
        """
        Initialize a collapsible panel.

        Parameters
        ----------
        title : str
            Title for the panel header
        widget : QWidget
            The widget to show/hide
        parent : QWidget, optional
            Parent widget
        """
        super().__init__(parent)
        self.widget = widget
        self.is_collapsed = False

        # Create layout
        self.panel_layout = QVBoxLayout(self)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_layout.setSpacing(0)

        # Create header
        header = QFrame()
        header.setFrameStyle(QFrame.StyledPanel)
        header.setStyleSheet(
            "QFrame { background-color: #f0f0f0; border: 1px solid #c0c0c0; }"
        )

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 2, 5, 2)

        # Toggle button
        self.toggle_button = QPushButton("▼")
        self.toggle_button.setFixedSize(16, 16)
        self.toggle_button.setStyleSheet(
            """
            QPushButton {
                border: none;
                background: transparent;
                font-weight: bold;
                color: #404040;
            }
            QPushButton:hover {
                color: #000000;
            }
        """
        )
        self.toggle_button.clicked.connect(self.toggle)

        # Title label
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; color: #404040;")

        header_layout.addWidget(self.toggle_button)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # Add header to layout
        self.panel_layout.addWidget(header)

        # Store references
        self.header = header
        self.title_label = title_label

        # Make panel resizable by adding a splitter handle
        self._setup_resize_handle()

        # Set initial state
        self.update_collapsed_state()

    def _setup_resize_handle(self):
        """Add a resize handle to make the panel resizable."""
        # Create a thin frame that acts as a resize handle
        self.resize_handle = QFrame()
        self.resize_handle.setFixedHeight(3)
        self.resize_handle.setStyleSheet(
            """
            QFrame {
                background-color: #c0c0c0;
                border: none;
            }
            QFrame:hover {
                background-color: #808080;
            }
        """
        )

        # Add mouse event handling for resizing
        self.resize_handle.mousePressEvent = self._handle_mouse_press
        self.resize_handle.mouseMoveEvent = self._handle_mouse_move
        self.resize_handle.mouseReleaseEvent = self._handle_mouse_release

        # Add to layout
        self.panel_layout.addWidget(self.resize_handle)

        # Resize state
        self._resizing = False
        self._start_height = 0
        self._start_y = 0

    def _handle_mouse_press(self, event):
        """Handle mouse press on resize handle."""
        if event.button() == Qt.LeftButton:
            self._resizing = True
            self._start_height = self.height()
            self._start_y = event.globalY()
            self.setCursor(Qt.SizeVerCursor)

    def _handle_mouse_move(self, event):
        """Handle mouse move during resize."""
        if self._resizing:
            delta_y = event.globalY() - self._start_y
            new_height = max(50, self._start_height + delta_y)  # Minimum height
            self.setFixedHeight(new_height)

    def _handle_mouse_release(self, event):
        """Handle mouse release after resize."""
        if self._resizing:
            self._resizing = False
            self.setCursor(Qt.ArrowCursor)

    def toggle(self):
        """Toggle the collapsed state."""
        self.is_collapsed = not self.is_collapsed
        self.update_collapsed_state()

    def update_collapsed_state(self):
        """Update the visual state based on collapsed status."""
        if self.is_collapsed:
            # Remove widget from layout to actually collapse
            self.panel_layout.removeWidget(self.widget)
            self.widget.hide()
            self.toggle_button.setText("▶")
            # Set fixed height when collapsed (just header height)
            self.setFixedHeight(30)
            # Hide resize handle when collapsed
            self.resize_handle.hide()
        else:
            # Add widget back to layout
            self.panel_layout.insertWidget(1, self.widget)  # Insert after header
            self.widget.show()
            self.toggle_button.setText("▼")
            # Allow resizing when expanded
            self.setFixedHeight(self.sizeHint().height())
            self.resize_handle.show()


class CanvasTab(QWidget):
    """
    A tab containing a canvas run list and plot widget.

    This represents a single canvas view, with its run management and plot display.
    Uses collapsible panels for run list and plot controls to maximize plot space.
    """

    def __init__(self, plot_model, canvas_manager, canvas_id, parent=None):
        """
        Initialize a canvas tab.

        Parameters
        ----------
        plot_model : PlotModel
            Model managing the canvas data
        canvas_manager : CanvasManager
            Manager for all canvases
        canvas_id : str
            Identifier for this canvas
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)

        # Create widgets
        self.run_list = CanvasRunList(plot_model, canvas_manager, canvas_id)

        # Create plot widget based on canvas widget type
        self.plot_widget = self._create_plot_widget(
            plot_model, canvas_manager, canvas_id
        )

        # Create collapsible panels for data management
        self.run_panel = CollapsiblePanel("Runs", self.run_list)

        # Create plot controls panel if available
        if hasattr(self.plot_widget, "plot_controls"):
            self.plot_controls_panel = CollapsiblePanel(
                "Plot Controls", self.plot_widget.plot_controls
            )
        else:
            self.plot_controls_panel = None

        # Create debug panel if available
        if hasattr(self.plot_widget, "debug_button") and self.plot_widget.debug_button:
            self.debug_panel = CollapsiblePanel("Debug", self.plot_widget.debug_button)
        else:
            self.debug_panel = None

        # Create sidebar with stacked panels
        sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(2)

        # Add panels in order
        sidebar_layout.addWidget(self.run_panel)
        if self.plot_controls_panel:
            sidebar_layout.addWidget(self.plot_controls_panel)
        if self.debug_panel:
            sidebar_layout.addWidget(self.debug_panel)
        sidebar_layout.addStretch()  # Push panels to top

        # Create splitter for resizable panels
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(sidebar_widget)
        self.splitter.addWidget(self.plot_widget)  # Plot widget handles its own layout

        # Set initial splitter sizes (sidebar: 20%, plot: 80%)
        self.splitter.setSizes([200, 800])

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)
        self.setLayout(layout)

    def _create_plot_widget(self, plot_model, canvas_manager, canvas_id):
        """
        Create the appropriate plot widget based on canvas widget type.

        Parameters
        ----------
        plot_model : PlotModel
            The plot model for this canvas
        canvas_manager : CanvasManager
            The canvas manager
        canvas_id : str
            The canvas identifier

        Returns
        -------
        QWidget
            The created plot widget
        """
        # Get widget type for this canvas
        widget_type = canvas_manager.get_canvas_widget_type(canvas_id)

        # Get widget registry from canvas manager
        widget_registry = canvas_manager._widget_registry

        if widget_registry and widget_type in widget_registry.get_available_widgets():
            # Create widget using registry
            widget_class = widget_registry.get_widget(widget_type)
            return widget_class(plot_model)
        else:
            # Fallback to default PlotWidget
            return PlotWidget(plot_model)
