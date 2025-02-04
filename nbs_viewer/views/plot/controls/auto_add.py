from qtpy.QtWidgets import QHBoxLayout, QLabel, QCheckBox

from .base import PlotControlWidget


class AutoAddControl(PlotControlWidget):
    """
    Widget for controlling auto-add behavior.

    Controls whether new selections are automatically added to the plot.

    Parameters
    ----------
    plot_model : PlotModel
        The plot model to control
    parent : QWidget, optional
        Parent widget, by default None
    """

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
        super().__init__(plotModel, parent)
        # Set initial state from model
        self._auto_add_box.setChecked(self.plotModel.auto_add)

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Auto add toggle
        layout.addWidget(QLabel("Auto Add"))
        self._auto_add_box = QCheckBox()
        self._auto_add_box.setChecked(True)
        self._auto_add_box.clicked.connect(self.state_changed)
        layout.addWidget(self._auto_add_box)
        self.setLayout(layout)

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

    def state_changed(self) -> None:
        """Handle state changes."""
        state = self.get_state()
        self.plotModel.set_auto_add(state["auto_add"])
