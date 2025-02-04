from typing import Dict, List, Optional, Set
from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QCheckBox,
    QFrame,
    QPushButton,
    QButtonGroup,
    QScrollArea,
    QSizePolicy,
)


class ExclusiveCheckBoxGroup(QButtonGroup):
    """Group of checkboxes where only one can be checked at a time."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setExclusive(True)


class RunDisplayWidget(QWidget):
    """
    Widget for displaying and selecting run data keys.

    Displays available keys from one or more runs and manages selection
    state through their controllers.

    Parameters
    ----------
    parent : Optional[QWidget], optional
        Parent widget, by default None

    Signals
    -------
    selection_changed : Signal
        Emitted when key selection changes
    """

    selection_changed = Signal(list, list, list)

    def __init__(self, plotModel, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # State
        self.plotModel = plotModel
        self._all_keys: Set[str] = set()
        self._show_all = False
        # Track current selection state
        self._current_x_keys = []
        self._current_y_keys = []
        self._current_norm_keys = []

        # UI setup
        self._setup_ui()

        # Connect signals
        self.plotModel.available_keys_changed.connect(self._update_display)
        self.plotModel.run_models_changed.connect(self._update_header)
        self.selection_changed.connect(self.plotModel.selection_changed)
        self.plotModel.selection_changed.connect(self._on_selection_changed)

        # Initial update after all connections are set
        self._update_display()

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Header layout
        header_layout = QHBoxLayout()
        self._header_label = QLabel("No Runs Selected")
        header_layout.addWidget(self._header_label)
        layout.addLayout(header_layout)

        # Show all checkbox
        self._show_all_box = QCheckBox("Show All")
        self._show_all_box.setChecked(False)
        self._show_all_box.clicked.connect(self._on_show_all_changed)
        header_layout.addWidget(self._show_all_box)

        # Grid for key selection
        self._grid = QGridLayout()
        grid_widget = QWidget()
        grid_widget.setLayout(self._grid)

        # Put grid in a scroll area
        scroll = QScrollArea()
        scroll.setWidget(grid_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Set size policies to make scroll area expand
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        grid_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        # Add scroll to layout with a high stretch factor
        layout.addWidget(scroll, stretch=1)

        # Button layout at bottom
        button_layout = QHBoxLayout()

        # Update button
        self._update_button = QPushButton("Update Selection")
        self._update_button.clicked.connect(self._on_update_clicked)
        self._update_button.setEnabled(False)
        button_layout.addWidget(self._update_button)

        # Clear button
        self._clear_button = QPushButton("Clear Selection")
        self._clear_button.clicked.connect(self._on_clear_clicked)
        self._clear_button.setEnabled(False)
        button_layout.addWidget(self._clear_button)
        layout.addStretch(0)  # 0 means minimum stretch

        # Add button layout with some spacing
        layout.addSpacing(10)  # Add some space above buttons
        layout.addLayout(button_layout)
        layout.addSpacing(10)  # Add some space below buttons

        # Add vertical spacer with lower stretch factor

        self.setLayout(layout)

    def _update_header(self) -> None:
        """Update the header label with run info."""
        print("RunDisplayWidget update_header")
        self._header_label.setText(self.plotModel.getHeaderLabel())

    def _update_display(self) -> None:
        """Update the key selection grid."""
        # Clear existing grid
        self._clear_grid()

        # Get common keys across controllers
        available_keys = self.plotModel.available_keys
        # Ensure "time" is first if present
        if "time" in available_keys:
            available_keys = ["time"] + [k for k in available_keys if k != "time"]

        # Add column headers with alignment
        for i, label in enumerate(["", "X", "Y", "", "Norm"]):
            header = QLabel(label)
            header.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            if i in [1, 2, 4]:  # X, Y, and Norm columns
                header.setStyleSheet("QLabel { margin-left: 5px; }")
            self._grid.addWidget(header, 0, i)

        # Create checkbox groups
        self._x_group = QButtonGroup(self)
        self._x_group.setExclusive(True)
        self._y_group = QButtonGroup(self)
        self._y_group.setExclusive(False)
        self._norm_group = QButtonGroup(self)
        self._norm_group.setExclusive(False)

        # Create button to key mappings
        self._button_key_map = {}

        # Add key rows
        for i, key in enumerate(available_keys):
            # Key label with elided text if too long
            label = QLabel(key)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setMinimumWidth(100)  # Set minimum width
            label.setMaximumWidth(200)  # Set maximum width
            self._grid.addWidget(label, i + 1, 0)

            # X checkbox
            x_box = QCheckBox()
            x_box.setStyleSheet("QCheckBox { margin-left: 5px; }")
            x_box.setChecked(key in self._current_x_keys)
            self._grid.addWidget(x_box, i + 1, 1)
            self._x_group.addButton(x_box)
            self._button_key_map[x_box] = key

            # Y checkbox
            y_box = QCheckBox()
            y_box.setStyleSheet("QCheckBox { margin-left: 5px; }")
            y_box.setChecked(key in self._current_y_keys)
            self._grid.addWidget(y_box, i + 1, 2)
            self._y_group.addButton(y_box)
            self._button_key_map[y_box] = key

            # Separator
            line = QFrame()
            line.setFrameShape(QFrame.VLine)
            line.setFixedWidth(10)  # Set fixed width for separator
            self._grid.addWidget(line, i + 1, 3)

            # Norm checkbox
            norm_box = QCheckBox()
            norm_box.setStyleSheet("QCheckBox { margin-left: 5px; }")
            norm_box.setChecked(key in self._current_norm_keys)
            self._grid.addWidget(norm_box, i + 1, 4)
            self._norm_group.addButton(norm_box)
            self._button_key_map[norm_box] = key

            # Connect signals
            for box in [x_box, y_box, norm_box]:
                box.clicked.connect(self._on_checkbox_changed)

        # Set grid properties for compact layout
        self._grid.setVerticalSpacing(0)  # Remove vertical spacing
        self._grid.setHorizontalSpacing(2)  # Minimal horizontal spacing
        self._grid.setAlignment(Qt.AlignTop)  # Align to top

        # Set column stretch factors
        self._grid.setColumnStretch(0, 1)  # Key column gets more space
        self._grid.setColumnStretch(1, 0)  # Checkbox columns stay small
        self._grid.setColumnStretch(2, 0)
        self._grid.setColumnStretch(3, 0)  # Separator stays small
        self._grid.setColumnStretch(4, 0)

        # Enable buttons
        self._update_button.setEnabled(True)
        self._clear_button.setEnabled(True)

    def _clear_grid(self) -> None:
        """Clear all widgets from the grid."""
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_show_all_changed(self) -> None:
        """Handle show all checkbox changes."""
        self._show_all = self._show_all_box.isChecked()
        self._update_display()

    def _on_clear_clicked(self) -> None:
        """Handle clear button clicks."""
        # Clear all checkboxes
        for group in [self._x_group, self._y_group, self._norm_group]:
            for button in group.buttons():
                button.setChecked(False)

        # Update controllers without forcing plot update
        self._on_checkbox_changed()

    def _on_selection_changed(
        self, x_keys: List[str], y_keys: List[str], norm_keys: List[str]
    ) -> None:
        """Update checkbox states when selection changes externally."""
        print("RunDisplayWidget _on_selection_changed")
        print(x_keys, y_keys, norm_keys)

        # Update internal state
        self._current_x_keys = x_keys
        self._current_y_keys = y_keys
        self._current_norm_keys = norm_keys

        # If we have buttons, update their states
        if hasattr(self, "_x_group"):
            # Block signals to prevent recursive updates
            for group in [self._x_group, self._y_group, self._norm_group]:
                for button in group.buttons():
                    button.blockSignals(True)

            # Update checkbox states
            for button in self._x_group.buttons():
                key = self._button_key_map[button]
                button.setChecked(key in x_keys)

            for button in self._y_group.buttons():
                key = self._button_key_map[button]
                button.setChecked(key in y_keys)

            for button in self._norm_group.buttons():
                key = self._button_key_map[button]
                button.setChecked(key in norm_keys)

            # Unblock signals
            for group in [self._x_group, self._y_group, self._norm_group]:
                for button in group.buttons():
                    button.blockSignals(False)

    def _on_checkbox_changed(self) -> None:
        """Handle checkbox state changes without forcing plot updates."""
        # Get selected keys using the button-key mapping
        print("RunDisplayWidget _on_checkbox_changed")

        x_keys = [
            self._button_key_map[button]
            for button in self._x_group.buttons()
            if button.isChecked()
        ]

        y_keys = [
            self._button_key_map[button]
            for button in self._y_group.buttons()
            if button.isChecked()
        ]

        norm_keys = [
            self._button_key_map[button]
            for button in self._norm_group.buttons()
            if button.isChecked()
        ]

        # Update the plot model with the new selection (no force update)
        if hasattr(self.plotModel, "set_selection"):
            self.plotModel.set_selection(x_keys, y_keys, norm_keys, force_update=False)
        else:
            self.selection_changed.emit(x_keys, y_keys, norm_keys)

    def _on_update_clicked(self) -> None:
        """Handle Update Selection button clicks by forcing plot update."""
        # Get selected keys using the button-key mapping
        print("RunDisplayWidget _on_update_clicked")
        x_keys = [
            self._button_key_map[button]
            for button in self._x_group.buttons()
            if button.isChecked()
        ]

        y_keys = [
            self._button_key_map[button]
            for button in self._y_group.buttons()
            if button.isChecked()
        ]

        norm_keys = [
            self._button_key_map[button]
            for button in self._norm_group.buttons()
            if button.isChecked()
        ]

        # Force update the plot with current selection
        if hasattr(self.plotModel, "set_selection"):
            self.plotModel.set_selection(x_keys, y_keys, norm_keys, force_update=True)
        else:
            self.selection_changed.emit(x_keys, y_keys, norm_keys)
