from qtpy.QtWidgets import QHBoxLayout, QLabel, QCheckBox

from .base import PlotControlWidget


class DynamicUpdateControl(PlotControlWidget):
    """
    Widget for controlling dynamic updates.

    Controls whether data updates are automatically reflected in the plot.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget, by default None
    """

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Dynamic update toggle
        layout.addWidget(QLabel("Dynamic Update"))
        self._dynamic_box = QCheckBox()
        self._dynamic_box.setChecked(False)
        self._dynamic_box.clicked.connect(self.state_changed)
        layout.addWidget(self._dynamic_box)

    def get_state(self) -> dict:
        """
        Get the current dynamic update state.

        Returns
        -------
        dict
            Dictionary with dynamic state
        """
        return {"dynamic": self._dynamic_box.isChecked()}

    def set_state(self, state: dict) -> None:
        """
        Set the dynamic update state.

        Parameters
        ----------
        state : dict
            Dictionary with dynamic state
        """
        if "dynamic" in state:
            self._dynamic_box.setChecked(state["dynamic"])
