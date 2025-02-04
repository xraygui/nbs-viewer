from qtpy.QtWidgets import QWidget
from qtpy.QtCore import Signal


class PlotControlWidget(QWidget):
    """
    Base class for plot control widgets.

    All plot control widgets should inherit from this class and emit
    state_changed when their state changes.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget, by default None

    Signals
    -------
    state_changed : Signal
        Emitted when the widget's state changes
    """

    state_changed = Signal()

    def __init__(self, plotModel, parent=None):
        super().__init__(parent)
        self.plotModel = plotModel
        self._setup_ui()

    def _setup_ui(self) -> None:
        """
        Setup the widget UI.

        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def get_state(self) -> dict:
        """
        Get the current state of the widget.

        Must be implemented by subclasses.

        Returns
        -------
        dict
            The current state
        """
        raise NotImplementedError

    def set_state(self, state: dict) -> None:
        """
        Set the widget state.

        Must be implemented by subclasses.

        Parameters
        ----------
        state : dict
            The state to set
        """
        raise NotImplementedError
