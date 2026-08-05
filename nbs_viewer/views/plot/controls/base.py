from qtpy.QtWidgets import QWidget, QSizePolicy, QLabel, QCheckBox, QFormLayout
from qtpy.QtCore import Signal

MIN_CONTROL_HEIGHT = 24


def apply_minimum_control_heights(*widgets):
    """
    Apply a consistent minimum height to input controls.

    Parameters
    ----------
    *widgets : QWidget
        Widgets such as combo boxes, line edits, and push buttons.
    """
    for widget in widgets:
        if widget is not None:
            widget.setMinimumHeight(MIN_CONTROL_HEIGHT)


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

    def __init__(self, run_list_model, parent=None):
        super().__init__(parent)
        self.run_list_model = run_list_model
        # Prefer to expand when the panel allows it; let layout manage height
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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


class CheckboxFormControl(PlotControlWidget):
    """
    Plot control that contributes a label/checkbox row to a form layout.

    Subclasses create ``_label`` and ``_checkbox`` in ``_setup_ui`` via
    :meth:`_create_form_checkbox`, then call :meth:`add_to_form` from the
    parent panel.
    """

    def _create_form_checkbox(self, label_text, checked=False, tooltip=None):
        """
        Create the label and checkbox widgets for a form row.

        Parameters
        ----------
        label_text : str
            Text for the left-hand form label.
        checked : bool, optional
            Initial checkbox state, by default False.
        tooltip : str, optional
            Shared tooltip for label and checkbox.

        Returns
        -------
        QCheckBox
            The created checkbox.
        """
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._label = QLabel(label_text)
        self._checkbox = QCheckBox()
        self._checkbox.setChecked(checked)
        if tooltip:
            self._label.setToolTip(tooltip)
            self._checkbox.setToolTip(tooltip)
        return self._checkbox

    def add_to_form(self, form_layout: QFormLayout) -> None:
        """
        Add this control's label and checkbox to a form layout.

        Parameters
        ----------
        form_layout : QFormLayout
            Destination form layout.
        """
        form_layout.addRow(self._label, self._checkbox)
