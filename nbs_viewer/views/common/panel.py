from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
)
from qtpy.QtCore import Qt


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

        # Toggle button with Qt standard icons
        self.toggle_button = QPushButton()
        self.toggle_button.setFixedSize(16, 16)
        self.toggle_button.setStyleSheet(
            """
            QPushButton {
                border: none;
                background: transparent;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
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

        # Set initial icon (expanded state)
        self.toggle_button.setIcon(self.style().standardIcon(self.style().SP_ArrowDown))

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
            new_height = max(50, self._start_height + delta_y)  # Min height
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
            # Use Qt standard icon for collapsed state
            self.toggle_button.setIcon(
                self.style().standardIcon(self.style().SP_ArrowRight)
            )
            # Set fixed height when collapsed (just header height)
            self.setFixedHeight(30)
            # Hide resize handle when collapsed
            self.resize_handle.hide()
        else:
            # Add widget back to layout
            self.panel_layout.insertWidget(1, self.widget)  # After header
            self.widget.show()
            # Use Qt standard icon for expanded state
            self.toggle_button.setIcon(
                self.style().standardIcon(self.style().SP_ArrowDown)
            )
            # Allow resizing when expanded
            self.setFixedHeight(self.sizeHint().height())
            self.resize_handle.show()
