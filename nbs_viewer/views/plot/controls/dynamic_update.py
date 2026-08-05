from .base import CheckboxFormControl


class DynamicUpdateControl(CheckboxFormControl):
    """
    Widget for controlling dynamic updates.

    Controls whether data updates are automatically reflected in the plot.

    Parameters
    ----------
    run_list_model : RunListModel
        The plot model to control
    parent : QWidget, optional
        Parent widget, by default None
    """

    def __init__(self, run_list_model, parent=None):
        super().__init__(run_list_model, parent)
        self._checkbox.setChecked(self.run_list_model.dynamic_update)

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        checkbox = self._create_form_checkbox("Dynamic Update", checked=False)
        checkbox.checkStateChanged.connect(self._on_state_changed)

    def get_state(self) -> dict:
        """
        Get the current dynamic update state.

        Returns
        -------
        dict
            Dictionary with dynamic state
        """
        return {"dynamic": self._checkbox.isChecked()}

    def set_state(self, state: dict) -> None:
        """
        Set the dynamic update state.

        Parameters
        ----------
        state : dict
            Dictionary with dynamic state
        """
        if "dynamic" in state:
            self._checkbox.setChecked(state["dynamic"])

    def _on_state_changed(self, checkState) -> None:
        """Handle state changes."""
        self.run_list_model.set_dynamic_update(self._checkbox.isChecked())
