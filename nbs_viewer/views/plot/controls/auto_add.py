from .base import CheckboxFormControl


class AutoAddControl(CheckboxFormControl):
    """
    Widget for controlling auto-add behavior.

    Controls whether new selections are automatically added to the plot.

    Parameters
    ----------
    run_list_model : RunListModel
        The plot model to control
    parent : QWidget, optional
        Parent widget, by default None
    """

    def __init__(self, run_list_model, parent=None):
        super().__init__(run_list_model, parent)
        self._checkbox.setChecked(self.run_list_model.auto_add)

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        checkbox = self._create_form_checkbox("Auto Add", checked=True)
        checkbox.checkStateChanged.connect(self._on_checkbox_changed)

    def get_state(self) -> dict:
        """
        Get the current auto-add state.

        Returns
        -------
        dict
            Dictionary with auto_add state
        """
        return {"auto_add": self._checkbox.isChecked()}

    def set_state(self, state: dict) -> None:
        """
        Set the auto-add state.

        Parameters
        ----------
        state : dict
            Dictionary with auto_add state
        """
        if "auto_add" in state:
            self._checkbox.setChecked(state["auto_add"])

    def _on_checkbox_changed(self, checkState) -> None:
        """Handle checkbox state changes."""
        self.run_list_model.set_auto_add(self._checkbox.isChecked())
