from qtpy.QtWidgets import QHBoxLayout, QLabel, QCheckBox

from .base import PlotControlWidget


class RetainSelectionControl(PlotControlWidget):
    """
    Widget for controlling selection retention behavior.

    Controls whether plot selections are retained when runs change.

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
        self._retain_selection_box.setChecked(self.plotModel._retain_selection)

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # Retain selection toggle
        layout.addWidget(QLabel("Retain Selection"))
        self._retain_selection_box = QCheckBox()
        self._retain_selection_box.setChecked(False)
        self._retain_selection_box.setToolTip(
            "Keep current plot selections when runs change"
        )
        self._retain_selection_box.clicked.connect(self.state_changed)
        layout.addWidget(self._retain_selection_box)
        self.setLayout(layout)

    def get_state(self) -> dict:
        """
        Get the current retain selection state.

        Returns
        -------
        dict
            Dictionary with retain_selection state
        """
        return {"retain_selection": self._retain_selection_box.isChecked()}

    def set_state(self, state: dict) -> None:
        """
        Set the retain selection state.

        Parameters
        ----------
        state : dict
            Dictionary with retain_selection state
        """
        if "retain_selection" in state:
            self._retain_selection_box.setChecked(state["retain_selection"])

    def state_changed(self) -> None:
        """Handle state changes."""
        state = self.get_state()
        self.plotModel.set_retain_selection(state["retain_selection"])
