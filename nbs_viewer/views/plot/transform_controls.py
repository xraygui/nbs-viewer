from typing import Dict
from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QFrame,
    QPushButton,
    QLineEdit,
    QComboBox,
    QMessageBox,
    QInputDialog,
)


class TransformControls(QWidget):
    """
    Widget for controlling data transforms.

    Provides UI for selecting and configuring data transforms.
    Includes predefined transforms and custom transform input.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget, by default None
    """

    DEFAULT_TRANSFORMS = {
        "No Transform": "",
        "Invert (1/y)": "1/y",
        "Normalize to Max": "y/max(y)",
        "Normalize to Min": "y/min(y)",
        "Normalize to Pre/Post edge": "(y - mean(y[:10]))/(mean(y[-10:]) - mean(y[:10]))",
        "Normalize to Sum": "y/sum(y)",
        "Log Scale": "log(y)",
        "Log(1/y)": "log(1/y)",
    }

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._transforms = self.DEFAULT_TRANSFORMS.copy()
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        # Main layout
        layout = QVBoxLayout(self)

        # Transform frame
        transform_frame = QFrame()
        transform_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        transform_layout = QVBoxLayout(transform_frame)

        # Transform header
        transform_header = QHBoxLayout()
        transform_header.addWidget(QLabel("Transform"))
        self.transform_box = QCheckBox()
        self.transform_box.setChecked(False)
        self.transform_box.clicked.connect(self._on_transform_state_changed)
        transform_header.addWidget(self.transform_box)
        transform_layout.addLayout(transform_header)

        # Transform combo box
        self.transform_combo = QComboBox()
        self.transform_combo.setEnabled(False)
        self.transform_combo.addItems(self._transforms.keys())
        self.transform_combo.currentTextChanged.connect(self._on_transform_selected)
        transform_layout.addWidget(self.transform_combo)

        # Custom transform input
        custom_transform_layout = QHBoxLayout()
        self.transform_text_edit = QLineEdit()
        self.transform_text_edit.setEnabled(False)
        self.transform_text_edit.setPlaceholderText(
            "Enter custom transform (e.g., y/max(y))"
        )
        self.transform_text_edit.editingFinished.connect(
            self._on_custom_transform_changed
        )
        custom_transform_layout.addWidget(self.transform_text_edit)

        save_transform_btn = QPushButton("Save")
        save_transform_btn.clicked.connect(self._save_custom_transform)
        custom_transform_layout.addWidget(save_transform_btn)

        transform_layout.addLayout(custom_transform_layout)
        layout.addWidget(transform_frame)

    def _on_transform_state_changed(self) -> None:
        """Handle transform checkbox state change."""
        is_checked = self.transform_box.isChecked()
        self.transform_combo.setEnabled(is_checked)
        self.transform_text_edit.setEnabled(is_checked)
        if not is_checked:
            self.transform_combo.setCurrentText("No Transform")
            self.transform_text_edit.clear()

    def _on_transform_selected(self, transform_name: str) -> None:
        """Handle transform selection from combo box."""
        if transform_name in self._transforms:
            self.transform_text_edit.setText(self._transforms[transform_name])

    def _on_custom_transform_changed(self) -> None:
        """Handle custom transform text changes."""
        if self.transform_combo.currentText() != "Custom":
            self.transform_combo.setCurrentText("Custom")

    def _save_custom_transform(self) -> None:
        """Save current custom transform to the combo box."""
        custom_text = self.transform_text_edit.text().strip()
        if not custom_text:
            return

        name, ok = QInputDialog.getText(
            self, "Save Transform", "Enter a name for this transform:"
        )
        if ok and name:
            name = name.strip()
            if name in self._transforms:
                reply = QMessageBox.question(
                    self,
                    "Transform exists",
                    f"Transform '{name}' already exists. Overwrite?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    return

            self._transforms[name] = custom_text
            current_items = [
                self.transform_combo.itemText(i)
                for i in range(self.transform_combo.count())
            ]
            if name not in current_items:
                self.transform_combo.addItem(name)
            self.transform_combo.setCurrentText(name)

    @property
    def transform_text(self) -> str:
        """Get the current transform text."""
        return self.transform_text_edit.text() if self.transform_box.isChecked() else ""
