from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QStyle,
    QSizePolicy,
)
from qtpy.QtCore import Qt, QSize

# Fallback for maximum Qt widget size (not exported by qtpy)
QWIDGETSIZE_MAX = 16777215


class CollapsiblePanel(QWidget):
    """
    A collapsible panel with a header and toggle functionality.

    Similar to Photoshop's collapsible tool panels.
    """

    def __init__(
        self, title, widget, parent=None, can_expand=False, initially_expanded=False
    ):
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
        can_expand : bool, optional
            Whether this panel can expand to fill available space
        initially_expanded : bool, optional
            Whether the panel should start expanded (default: False)
        """
        super().__init__(parent)
        self.widget = widget
        self.can_expand = can_expand
        self.is_collapsed = (
            not initially_expanded
        )  # Start collapsed or expanded based on parameter

        # Create layout
        self.panel_layout = QVBoxLayout(self)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_layout.setSpacing(0)

        # Set size policy based on expandability
        if can_expand:
            self.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
            )
        else:
            self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)

        # Create header
        header = QFrame()
        header.setFrameStyle(QFrame.StyledPanel)
        header.setStyleSheet(
            "QFrame { background-color: #f0f0f0; border: 1px solid #c0c0c0; }"
        )
        header.setFixedHeight(24)  # Compact header height

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(3, 1, 3, 1)  # More compact margins

        # Toggle button with Qt standard icons
        self.toggle_button = QPushButton()
        self.toggle_button.setFixedSize(14, 14)  # Smaller button for compactness
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
        title_label.setStyleSheet("font-weight: bold; color: #404040; font-size: 11px;")

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

        # Set initial icon based on initial state
        if self.is_collapsed:
            self.toggle_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
        else:
            self.toggle_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))

        # Set initial state
        self.update_collapsed_state()

    def sizeHint(self):
        """Return appropriate size based on collapsed state and expandability."""
        if self.is_collapsed:
            # Collapsed: just header height
            return QSize(200, 24)  # Width doesn't matter much for vertical layout
        else:
            if self.can_expand:
                # Expanded and can expand: return large height to fill space
                return QSize(200, 1000)  # Large height to encourage expansion
            else:
                # Expanded but fixed size: return natural size
                content_height = self.widget.sizeHint().height() if self.widget else 0
                return QSize(200, 24 + content_height)

    # Important: Avoid forcing the child's height. Let the layout manage it.
    # Over-managing sizes here fights Qt's layout negotiation and can leave
    # the panel stuck at 0 height when re-expanded. Removing this prevents
    # stale fixed heights from persisting across toggles.

    def _setup_resize_handle(self):
        """Add a resize handle to make the panel resizable."""
        # Create a thin frame that acts as a resize handle
        self.resize_handle = QFrame()
        self.resize_handle.setFixedHeight(2)  # More compact
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

        # Force parent layout recalculation and update spacer
        self.updateGeometry()
        parent = self.parent()
        if parent:
            parent.update()
            parent.updateGeometry()
            if hasattr(parent, "layout") and parent.layout():
                parent.layout().invalidate()
                parent.layout().activate()
            # Update spacer stretch factor if parent has this method
            if hasattr(parent, "_update_spacer_stretch"):
                parent._update_spacer_stretch()

    def update_collapsed_state(self):
        """Update the visual state based on collapsed status."""
        if self.is_collapsed:
            # Remove widget from layout to actually collapse
            self.panel_layout.removeWidget(self.widget)
            self.widget.hide()
            # Use Qt standard icon for collapsed state
            self.toggle_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
            # Set hard cap to header height so the layout can't stretch a collapsed panel
            self.setMinimumHeight(24)
            self.setMaximumHeight(24)
            self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            # Hide resize handle when collapsed
            self.resize_handle.hide()
        else:
            # Add widget back to layout
            self.panel_layout.insertWidget(1, self.widget)  # After header
            self.widget.show()
            # Use Qt standard icon for expanded state
            self.toggle_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
            # Clear any previous hard caps from collapsed state
            self.setMinimumHeight(24)
            self.setMaximumHeight(QWIDGETSIZE_MAX)
            # Set size policy and constraints based on expandability
            if self.can_expand:
                self.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                )
                # No fixed height for content; let the layout stretch it
            else:
                self.setSizePolicy(
                    QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum
                )
                # For fixed panels, set both minimum and maximum to natural size
                content_height = self.widget.sizeHint().height() if self.widget else 0
                natural_height = 24 + content_height
                self.setMinimumHeight(natural_height)
                self.setMaximumHeight(natural_height)
            self.resize_handle.show()
