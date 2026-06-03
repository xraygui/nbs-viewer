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
from qtpy.QtCore import Qt, QSize, Signal

# Fallback for maximum Qt widget size (not exported by qtpy)
QWIDGETSIZE_MAX = 16777215

HEADER_HEIGHT = 24
RESIZE_HANDLE_HEIGHT = 2
MIN_EXPANDABLE_CONTENT_HEIGHT = 80


def _widget_layout(widget):
    """
    Return a QWidget's layout manager.

    Some widgets store their layout in a ``layout`` attribute, which shadows
    ``QWidget.layout()`` and breaks a normal ``widget.layout()`` call.

    Parameters
    ----------
    widget : QWidget
        Widget that may own a layout.

    Returns
    -------
    QLayout or None
        The widget's layout, if one exists.
    """
    if widget is None:
        return None
    try:
        return QWidget.layout(widget)
    except (TypeError, RuntimeError):
        pass
    stored = widget.__dict__.get("layout")
    if stored is not None and hasattr(stored, "minimumSize"):
        return stored
    lay = getattr(widget, "layout", None)
    if callable(lay):
        return lay()
    if lay is not None and hasattr(lay, "minimumSize"):
        return lay
    return None


class CollapsiblePanel(QWidget):
    """
    A collapsible panel with a header and toggle functionality.

    Similar to Photoshop's collapsible tool panels.
    """

    collapsed_changed = Signal(bool)

    def __init__(
        self,
        title,
        widget,
        parent=None,
        can_expand=False,
        initially_expanded=False,
        resizable=False,
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
        resizable : bool, optional
            Whether the user can drag a handle to resize the panel height
        """
        super().__init__(parent)
        self.widget = widget
        self.can_expand = can_expand
        self.resizable = resizable
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
        header.setFixedHeight(HEADER_HEIGHT)
        # Make entire header clickable to toggle
        header.setCursor(Qt.PointingHandCursor)
        header.mousePressEvent = lambda event: self.toggle()

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
        # Remove any box around the text and keep it visually clean
        title_label.setStyleSheet(
            "font-weight: bold; color: #404040; font-size: 11px; border: none;"
            " background: transparent;"
        )
        # Let clicks pass through the label so header clicks still toggle
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        header_layout.addWidget(self.toggle_button)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # Add header to layout
        self.panel_layout.addWidget(header)

        # Store references
        self.header = header
        self.title_label = title_label

        # Content container provides consistent padding around all panel content
        self.content_container = QFrame()
        self.content_container.setObjectName("content_container")
        self.content_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        self.content_container.setStyleSheet(
            "#content_container { border: none; background: transparent; }"
        )
        content_layout = QVBoxLayout(self.content_container)
        # Consistent inner padding for all panels (left, top, right, bottom)
        content_layout.setContentsMargins(8, 6, 8, 6)
        content_layout.setSpacing(6)
        stretch = 1 if self.can_expand else 0
        content_layout.addWidget(self.widget, stretch)
        self._apply_content_size_constraints()

        self.resize_handle = None
        if self.resizable:
            self._setup_resize_handle()

        # Set initial icon based on initial state
        if self.is_collapsed:
            self.toggle_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
        else:
            self.toggle_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))

        # Set initial state
        self.update_collapsed_state()

    def _apply_content_size_constraints(self):
        """
        Keep non-expanding panels from vertically compressing their contents.
        """
        if self.can_expand:
            self.content_container.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
        else:
            self.content_container.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
            )
            self.widget.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
            )
        content_layout = self.content_container.layout()
        if content_layout is not None:
            content_layout.setStretchFactor(
                self.widget, 1 if self.can_expand else 0
            )

    def _content_vertical_margins(self):
        """
        Return top and bottom margin height for the content layout.

        Returns
        -------
        int
            Sum of top and bottom content margins.
        """
        layout = self.content_container.layout()
        if layout is None:
            return 0
        margins = layout.contentsMargins()
        return margins.top() + margins.bottom()

    def _minimum_content_height(self):
        """
        Minimum height required to show the panel's inner widget without clipping.

        Returns
        -------
        int
            Minimum content height in pixels.
        """
        self.widget.ensurePolished()
        hint = self.widget.minimumSizeHint().height()
        if hint <= 0:
            hint = self.widget.sizeHint().height()
        layout = _widget_layout(self.widget)
        if hint <= 0 and layout is not None:
            hint = layout.minimumSize().height()
        if self.can_expand:
            return max(hint, MIN_EXPANDABLE_CONTENT_HEIGHT)
        return max(hint, 1)

    def _minimum_expanded_height(self):
        """
        Minimum total panel height when expanded (header, content, handle).

        Returns
        -------
        int
            Minimum expanded panel height in pixels.
        """
        handle = RESIZE_HANDLE_HEIGHT if self.resizable else 0
        return (
            HEADER_HEIGHT
            + handle
            + self._content_vertical_margins()
            + self._minimum_content_height()
        )

    def _preferred_expanded_height(self):
        """
        Preferred expanded height from layout size hints.

        Returns
        -------
        int
            Preferred expanded panel height in pixels.
        """
        self.content_container.ensurePolished()
        content_height = self.content_container.sizeHint().height()
        if content_height <= 0:
            content_height = self._minimum_content_height() + self._content_vertical_margins()
        return max(self._minimum_expanded_height(), HEADER_HEIGHT + content_height)

    def sizeHint(self):
        """Return appropriate size based on collapsed state and expandability."""
        if self.is_collapsed:
            return QSize(200, HEADER_HEIGHT)
        return QSize(200, self._preferred_expanded_height())

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
            min_height = self._minimum_expanded_height()
            new_height = max(min_height, self._start_height + delta_y)
            self.setFixedHeight(new_height)

    def _handle_mouse_release(self, event):
        """Handle mouse release after resize."""
        if self._resizing:
            self._resizing = False
            self.setCursor(Qt.ArrowCursor)
            min_height = self._minimum_expanded_height()
            if self.height() < min_height:
                self.setFixedHeight(min_height)

    def toggle(self):
        """Toggle the collapsed state."""
        self.is_collapsed = not self.is_collapsed
        self.update_collapsed_state()
        self.collapsed_changed.emit(self.is_collapsed)

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
            # Remove content from layout to actually collapse
            self.panel_layout.removeWidget(self.content_container)
            self.content_container.hide()
            # Use Qt standard icon for collapsed state
            self.toggle_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
            # Set hard cap to header height so the layout can't stretch a collapsed panel
            self.setMinimumHeight(HEADER_HEIGHT)
            self.setMaximumHeight(HEADER_HEIGHT)
            self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            if self.resize_handle is not None:
                self.resize_handle.hide()
        else:
            # Add content back to layout
            stretch = 1 if self.can_expand else 0
            self.panel_layout.insertWidget(1, self.content_container, stretch)
            self.content_container.show()
            self._apply_content_size_constraints()
            # Use Qt standard icon for expanded state
            self.toggle_button.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
            min_height = self._minimum_expanded_height()
            preferred_height = self._preferred_expanded_height()
            if self.can_expand:
                self.setSizePolicy(
                    QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
                )
                self.setMinimumHeight(min_height)
                self.setMaximumHeight(QWIDGETSIZE_MAX)
            else:
                self.setSizePolicy(
                    QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
                )
                self.setMinimumHeight(min_height)
                self.setMaximumHeight(preferred_height)
            if self.resize_handle is not None:
                self.resize_handle.show()
            self.refresh_expanded_size()

    def refresh_expanded_size(self):
        """
        Recalculate height limits after the inner widget's content changes.

        No-op when collapsed or when the panel is allowed to grow freely.
        """
        if self.is_collapsed or self.can_expand:
            return
        min_height = self._minimum_expanded_height()
        preferred_height = self._preferred_expanded_height()
        self.setMinimumHeight(min_height)
        self.setMaximumHeight(preferred_height)
        self.updateGeometry()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().invalidate()
            parent.layout().activate()
