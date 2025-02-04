from qtpy.QtWidgets import QHBoxLayout, QLabel, QCheckBox

from .base import PlotControlWidget


class DynamicUpdateControl(PlotControlWidget):
    """
    Widget for controlling dynamic updates.

    Controls whether data updates are automatically reflected in the plot.

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
        self._dynamic_box.setChecked(self.plotModel.dynamic_update)

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Dynamic update toggle
        layout.addWidget(QLabel("Dynamic Update"))
        self._dynamic_box = QCheckBox()
        self._dynamic_box.setChecked(False)
        self._dynamic_box.clicked.connect(self.state_changed)
        layout.addWidget(self._dynamic_box)
        self.setLayout(layout)

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

    def state_changed(self) -> None:
        """Handle state changes."""
        state = self.get_state()
        self.plotModel.set_dynamic_update(state["dynamic"])
