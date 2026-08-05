from .base import CheckboxFormControl


class RetainSelectionControl(CheckboxFormControl):
    """
    Widget for controlling selection retention behavior.

    Controls whether plot selections are retained when runs change.

    Parameters
    ----------
    run_list_model : RunListModel
        The plot model to control
    parent : QWidget, optional
        Parent widget, by default None
    """

    def __init__(self, run_list_model, parent=None):
        super().__init__(run_list_model, parent)
        self._checkbox.setChecked(self.run_list_model._retain_selection)

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        checkbox = self._create_form_checkbox(
            "Retain Selection",
            checked=False,
            tooltip="Keep current plot selections when runs change",
        )
        checkbox.checkStateChanged.connect(self._on_checkbox_changed)

    def get_state(self) -> dict:
        """
        Get the current retain selection state.

        Returns
        -------
        dict
            Dictionary with retain_selection state
        """
        return {"retain_selection": self._checkbox.isChecked()}

    def set_state(self, state: dict) -> None:
        """
        Set the retain selection state.

        Parameters
        ----------
        state : dict
            Dictionary with retain_selection state
        """
        if "retain_selection" in state:
            self._checkbox.setChecked(state["retain_selection"])

    def _on_checkbox_changed(self, checkState) -> None:
        """Handle state changes."""
        self.run_list_model.set_retain_selection(self._checkbox.isChecked())
