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

from ...models.plot.run_controller import RunModelController


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

    selection_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        # State
        self._controllers: List[RunModelController] = []
        self._all_keys: Set[str] = set()
        self._show_all = False

        # UI setup
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        layout = QVBoxLayout(self)

        # Header for showing run info
        self._header_label = QLabel()
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
        layout.addLayout(self._grid)

        # Update and clear buttons
        self._update_button = QPushButton("Update Selection")
        self._update_button.clicked.connect(self._on_update_clicked)
        self._update_button.setEnabled(False)
        layout.addWidget(self._update_button)

        self._clear_button = QPushButton("Clear Selection")
        self._clear_button.clicked.connect(self._on_clear_clicked)
        self._clear_button.setEnabled(False)
        layout.addWidget(self._clear_button)

    def set_controllers(self, controllers: List[RunModelController]) -> None:
        """
        Set the controllers to display.

        Parameters
        ----------
        controllers : List[RunModelController]
            List of controllers to display keys for
        """
        # Cleanup old controllers
        self._controllers = controllers

        # Update header
        if len(controllers) == 1:
            run = controllers[0].run_data.run
            self._header_label.setText(f"Run: {run.name} ({run.scan_id})")
        else:
            self._header_label.setText(f"Multiple Runs Selected ({len(controllers)})")

        # Update display
        self._update_display()

    def _update_display(self) -> None:
        """Update the key selection grid."""
        # Clear existing grid
        self._clear_grid()

        if not self._controllers:
            self._update_button.setEnabled(False)
            self._clear_button.setEnabled(False)
            return

        # Get common keys across controllers
        available_keys = set.intersection(
            *[controller.state_model.available_keys for controller in self._controllers]
        )

        # Add column headers with alignment
        for i, label in enumerate(["", "X", "Y", "", "Norm"]):
            if label:  # Skip empty separator
                header = QLabel(label)
                header.setAlignment(Qt.AlignCenter)
                self._grid.addWidget(header, 0, i)

        # Create checkbox groups
        self._x_group = ExclusiveCheckBoxGroup(self)
        self._y_group = QButtonGroup(self)  # Multiple Y allowed
        self._y_group.setExclusive(False)
        self._norm_group = ExclusiveCheckBoxGroup(self)

        # Sort keys but put time first if present
        sorted_keys = sorted(available_keys)
        if "time" in sorted_keys:
            sorted_keys.remove("time")
            sorted_keys.insert(0, "time")

        # Add key rows
        for i, key in enumerate(sorted_keys):
            # Key label
            label = QLabel(key)
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._grid.addWidget(label, i + 1, 0)

            # X checkbox
            x_box = QCheckBox()
            x_box.setStyleSheet("QCheckBox { margin-left: 50%; }")
            self._grid.addWidget(x_box, i + 1, 1)
            self._x_group.addButton(x_box)

            # Y checkbox
            y_box = QCheckBox()
            y_box.setStyleSheet("QCheckBox { margin-left: 50%; }")
            self._grid.addWidget(y_box, i + 1, 2)
            self._y_group.addButton(y_box)

            # Separator
            line = QFrame()
            line.setFrameShape(QFrame.VLine)
            self._grid.addWidget(line, i + 1, 3)

            # Norm checkbox
            norm_box = QCheckBox()
            norm_box.setStyleSheet("QCheckBox { margin-left: 50%; }")
            self._grid.addWidget(norm_box, i + 1, 4)
            self._norm_group.addButton(norm_box)

            # Connect signals
            for box in [x_box, y_box, norm_box]:
                box.clicked.connect(self._on_selection_changed)

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

    def _on_selection_changed(self) -> None:
        """Handle checkbox selection changes."""
        self.selection_changed.emit()

    def _on_update_clicked(self) -> None:
        """Handle update button clicks."""
        self._update_controllers()

    def _on_clear_clicked(self) -> None:
        """Handle clear button clicks."""
        # Clear all checkboxes
        for group in [self._x_group, self._y_group, self._norm_group]:
            for button in group.buttons():
                button.setChecked(False)

        # Update controllers
        self._update_controllers()

    def _update_controllers(self) -> None:
        """Update all controllers with current selection."""
        if not self._controllers:
            return

        # Get selected keys
        x_keys = []
        y_keys = []
        norm_keys = []

        # Helper to get key from button
        def get_key(button) -> str:
            return (
                self._grid.itemAtPosition(self._grid.indexOf(button) // 5 + 1, 0)
                .widget()
                .text()
            )

        # Collect selected keys
        for button in self._x_group.buttons():
            if button.isChecked():
                x_keys.append(get_key(button))

        for button in self._y_group.buttons():
            if button.isChecked():
                y_keys.append(get_key(button))

        for button in self._norm_group.buttons():
            if button.isChecked():
                norm_keys.append(get_key(button))

        # Update all controllers
        for controller in self._controllers:
            controller.state_model.set_selection(x_keys, y_keys, norm_keys)
