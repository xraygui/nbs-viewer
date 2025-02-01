from qtpy.QtWidgets import QHBoxLayout, QLabel, QCheckBox

from .base import PlotControlWidget


class AutoAddControl(PlotControlWidget):
    """
    Widget for controlling auto-add behavior.

    Controls whether new selections are automatically added to the plot.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget, by default None
    """

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Auto add toggle
        layout.addWidget(QLabel("Auto Add"))
        self._auto_add_box = QCheckBox()
        self._auto_add_box.setChecked(True)
        self._auto_add_box.clicked.connect(self.state_changed)
        layout.addWidget(self._auto_add_box)

    def get_state(self) -> dict:
        """
        Get the current auto-add state.

        Returns
        -------
        dict
            Dictionary with auto_add state
        """
        return {"auto_add": self._auto_add_box.isChecked()}

    def set_state(self, state: dict) -> None:
        """
        Set the auto-add state.

        Parameters
        ----------
        state : dict
            Dictionary with auto_add state
        """
        if "auto_add" in state:
            self._auto_add_box.setChecked(state["auto_add"])
