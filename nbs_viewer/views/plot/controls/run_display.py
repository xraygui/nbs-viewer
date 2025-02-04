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

        # UI setup
        self._setup_ui()
        self.plotModel.available_keys_changed.connect(self._update_display)
        self.plotModel.run_models_changed.connect(self._update_header)
        self.selection_changed.connect(self.plotModel.selection_changed)

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        layout = QVBoxLayout(self)

        # Header for showing run info
        self._header_label = QLabel(self.plotModel.getHeaderLabel())
        layout.addWidget(self._header_label)

        # Show all keys toggle
        show_all_layout = QHBoxLayout()
        show_all_layout.addWidget(QLabel("Show all keys"))
        self._show_all_box = QCheckBox()
        self._show_all_box.setChecked(False)
        self._show_all_box.clicked.connect(self._on_show_all_changed)
        show_all_layout.addWidget(self._show_all_box)
        layout.addLayout(show_all_layout)

        # Grid for key selection
        self._grid = QGridLayout()
        self._grid.setColumnStretch(0, 1)  # Give more space to labels
        layout.addLayout(self._grid)

        # Update and clear buttons
        self._update_button = QPushButton("Update Selection")
        self._update_button.clicked.connect(self._update_selection)
        self._update_button.setEnabled(False)
        layout.addWidget(self._update_button)

        self._clear_button = QPushButton("Clear Selection")
        self._clear_button.clicked.connect(self._on_clear_clicked)
        self._clear_button.setEnabled(False)
        layout.addWidget(self._clear_button)

    def _update_header(self) -> None:
        """Update the header label with run info."""
        print("RunDisplayWidget update_header")
        self._header_label.setText(self.plotModel.getHeaderLabel())

    # Update for plotModel
    def _update_display(self) -> None:
        """Update the key selection grid."""
        # Clear existing grid
        print("RunDisplayWidget update_display")

        self._clear_grid()

        # Get common keys across controllers
        available_keys = self.plotModel.available_keys
        # Ensure "time" is first if present
        if "time" in available_keys:
            available_keys = ["time"] + [k for k in available_keys if k != "time"]

        # Add column headers with alignment
        for i, label in enumerate(["", "X", "Y", "", "Norm"]):
            header = QLabel(label)
            header.setAlignment(Qt.AlignCenter)
            if i in [1, 2, 4]:  # X, Y, and Norm columns
                header.setStyleSheet("QLabel { margin-left: 50%; }")
            self._grid.addWidget(header, 0, i)

        # Create checkbox groups
        self._x_group = QButtonGroup(self)  # Changed from ExclusiveCheckBoxGroup
        self._x_group.setExclusive(True)
        self._y_group = QButtonGroup(self)
        self._y_group.setExclusive(False)
        self._norm_group = QButtonGroup(self)
        self._norm_group.setExclusive(False)

        # Create button to key mappings
        self._button_key_map = {}

        # Add key rows
        for i, key in enumerate(available_keys):
            # Key label
            label = QLabel(key)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._grid.addWidget(label, i + 1, 0)

            # X checkbox
            x_box = QCheckBox()
            x_box.setStyleSheet("QCheckBox { margin-left: 50%; }")
            self._grid.addWidget(x_box, i + 1, 1)
            self._x_group.addButton(x_box)
            self._button_key_map[x_box] = key

            # Y checkbox
            y_box = QCheckBox()
            y_box.setStyleSheet("QCheckBox { margin-left: 50%; }")
            self._grid.addWidget(y_box, i + 1, 2)
            self._y_group.addButton(y_box)
            self._button_key_map[y_box] = key

            # Separator
            line = QFrame()
            line.setFrameShape(QFrame.VLine)
            self._grid.addWidget(line, i + 1, 3)

            # Norm checkbox
            norm_box = QCheckBox()
            norm_box.setStyleSheet("QCheckBox { margin-left: 50%; }")
            self._grid.addWidget(norm_box, i + 1, 4)
            self._norm_group.addButton(norm_box)
            self._button_key_map[norm_box] = key

            # Connect signals
            for box in [x_box, y_box, norm_box]:
                box.clicked.connect(self._update_selection)

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

        # Update controllers
        self._update_selection()

    # Update for plotModel
    def _update_selection(self) -> None:
        """Update all controllers with current selection."""
        # Get selected keys using the button-key mapping
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

        self.selection_changed.emit(x_keys, y_keys, norm_keys)
