from .base import CheckboxFormControl


class LockAspectControl(CheckboxFormControl):
    """
    Widget for locking image aspect ratio.

    When enabled, image-mode plots use equal data aspect so pixels keep their
    scale. Mesh and line plots always use automatic aspect.

    Parameters
    ----------
    presenter : PlotPresenter
        Plot session presenter.
    plot_canvas : MplCanvas
        Canvas whose image aspect is controlled.
    parent : QWidget, optional
        Parent widget, by default None.
    """

    def __init__(self, presenter, plot_canvas, parent=None):
        self.plot_canvas = plot_canvas
        super().__init__(presenter, parent)
        self._checkbox.setChecked(self.plot_canvas.lock_aspect)

    def _setup_ui(self) -> None:
        """Setup the widget UI."""
        checkbox = self._create_form_checkbox(
            "Lock Aspect",
            checked=True,
            tooltip=(
                "Keep equal data aspect for image plots "
                "(square pixels / true scale)"
            ),
        )
        checkbox.checkStateChanged.connect(self._on_checkbox_changed)

    def get_state(self) -> dict:
        """
        Get the current lock-aspect state.

        Returns
        -------
        dict
            Dictionary with lock_aspect state.
        """
        return {"lock_aspect": self._checkbox.isChecked()}

    def set_state(self, state: dict) -> None:
        """
        Set the lock-aspect state.

        Parameters
        ----------
        state : dict
            Dictionary with lock_aspect state.
        """
        if "lock_aspect" in state:
            self._checkbox.setChecked(state["lock_aspect"])

    def _on_checkbox_changed(self, checkState) -> None:
        """Handle checkbox state changes."""
        self.plot_canvas.set_lock_aspect(self._checkbox.isChecked())
