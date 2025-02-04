from qtpy.QtWidgets import (
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

from .base import PlotControlWidget


class TransformControl(PlotControlWidget):
    """
    Widget for controlling data transforms.

    Provides UI for selecting and configuring data transforms.
    Includes predefined transforms and custom transform input.

    Parameters
    ----------
    plot_model : PlotModel
        The plot model to control
    parent : QWidget, optional
        Parent widget, by default None
    """

    DEFAULT_TRANSFORMS = {
        "No Transform": "",
        "Invert (1/y)": "1/y",
        "Normalize to Max": "y/max(y)",
        "Normalize to Min": "y/min(y)",
        "Normalize to Pre/Post edge": (
            "(y - mean(y[:10]))/(mean(y[-10:]) - mean(y[:10]))"
        ),
        "Normalize to Sum": "y/sum(y)",
        "Log Scale": "log(y)",
        "Log(1/y)": "log(1/y)",
    }

    def __init__(self, plotModel, parent=None):
        """
        Initialize the widget.

        Parameters
        ----------
        plot_model : PlotModel
            The plot model to control
        parent : QWidget, optional
            Parent widget, by default None
        """
        self._transforms = self.DEFAULT_TRANSFORMS.copy()
        super().__init__(plotModel, parent)
        # Set initial state from model
        transform_state = self.plotModel.transform
        self._transform_box.setChecked(transform_state["enabled"])
        if transform_state["text"]:
            self._transform_text_edit.setText(transform_state["text"])

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Transform frame
        transform_frame = QFrame()
        transform_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        transform_layout = QVBoxLayout(transform_frame)

        # Transform header
        transform_header = QHBoxLayout()
        transform_header.addWidget(QLabel("Transform"))
        self._transform_box = QCheckBox()
        self._transform_box.setChecked(False)
        self._transform_box.clicked.connect(self._on_transform_state_changed)
        transform_header.addWidget(self._transform_box)
        transform_layout.addLayout(transform_header)

        # Transform combo box
        self._transform_combo = QComboBox()
        self._transform_combo.setEnabled(False)
        self._transform_combo.addItems(self._transforms.keys())
        self._transform_combo.currentTextChanged.connect(self._on_transform_selected)
        transform_layout.addWidget(self._transform_combo)

        # Custom transform input
        custom_transform_layout = QHBoxLayout()
        self._transform_text_edit = QLineEdit()
        self._transform_text_edit.setEnabled(False)
        self._transform_text_edit.setPlaceholderText(
            "Enter custom transform (e.g., y/max(y))"
        )
        self._transform_text_edit.editingFinished.connect(
            self._on_custom_transform_changed
        )
        custom_transform_layout.addWidget(self._transform_text_edit)

        save_transform_btn = QPushButton("Save")
        save_transform_btn.clicked.connect(self._save_custom_transform)
        custom_transform_layout.addWidget(save_transform_btn)

        transform_layout.addLayout(custom_transform_layout)
        layout.addWidget(transform_frame)
        self.setLayout(layout)

    def _on_transform_state_changed(self) -> None:
        """Handle transform checkbox state change."""
        is_checked = self._transform_box.isChecked()
        self._transform_combo.setEnabled(is_checked)
        self._transform_text_edit.setEnabled(is_checked)
        if not is_checked:
            self._transform_combo.setCurrentText("No Transform")
            self._transform_text_edit.clear()
        self.state_changed()

    def _on_transform_selected(self, transform_name: str) -> None:
        """Handle transform selection from combo box."""
        if transform_name in self._transforms:
            self._transform_text_edit.setText(self._transforms[transform_name])
            self.state_changed()

    def _on_custom_transform_changed(self) -> None:
        """Handle custom transform text changes."""
        if self._transform_combo.currentText() != "Custom":
            self._transform_combo.setCurrentText("Custom")
        self.state_changed()

    def _save_custom_transform(self) -> None:
        """Save current custom transform to the combo box."""
        custom_text = self._transform_text_edit.text().strip()
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
                self._transform_combo.itemText(i)
                for i in range(self._transform_combo.count())
            ]
            if name not in current_items:
                self._transform_combo.addItem(name)
            self._transform_combo.setCurrentText(name)

    def get_state(self) -> dict:
        """
        Get the current transform state.

        Returns
        -------
        dict
            Dictionary with transform state
        """
        return {
            "enabled": self._transform_box.isChecked(),
            "text": self._transform_text_edit.text(),
        }

    def set_state(self, state: dict) -> None:
        """
        Set the transform state.

        Parameters
        ----------
        state : dict
            Dictionary with transform state
        """
        if "enabled" in state:
            self._transform_box.setChecked(state["enabled"])
            self._transform_combo.setEnabled(state["enabled"])
            self._transform_text_edit.setEnabled(state["enabled"])

        if "text" in state:
            self._transform_text_edit.setText(state["text"])

    def state_changed(self) -> None:
        """Handle state changes."""
        state = self.get_state()
        self.plotModel.set_transform(state)
