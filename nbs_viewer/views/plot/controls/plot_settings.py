from qtpy.QtWidgets import QWidget, QFormLayout, QSizePolicy, QLabel, QCheckBox
from qtpy.QtCore import Qt


def _add_checkbox_row(form, label_text, checked, on_changed, tooltip=None):
    """
    Add a labeled checkbox row to a form layout.

    Parameters
    ----------
    form : QFormLayout
        Destination form layout.
    label_text : str
        Left-hand label text.
    checked : bool
        Initial checkbox state.
    on_changed : callable
        Called with the new checked state when the checkbox toggles.
    tooltip : str, optional
        Tooltip for the label and checkbox.

    Returns
    -------
    QCheckBox
        The created checkbox.
    """
    label = QLabel(label_text)
    checkbox = QCheckBox()
    checkbox.setChecked(checked)
    if tooltip:
        label.setToolTip(tooltip)
        checkbox.setToolTip(tooltip)
    checkbox.checkStateChanged.connect(
        lambda _state: on_changed(checkbox.isChecked())
    )
    form.addRow(label, checkbox)
    return checkbox


class PlotSettingsWidget(QWidget):
    """
    Plot settings form: auto-add, dynamic update, lock aspect, retain selection.

    Parameters
    ----------
    presenter : PlotPresenter
        Plot session presenter.
    plot_canvas : MplCanvas, optional
        Canvas for lock-aspect control; omitted when not applicable.
    parent : QWidget, optional
        Parent widget, by default None.
    """

    def __init__(self, presenter, plot_canvas=None, parent=None):
        super().__init__(parent)
        self.presenter = presenter
        self.plot_canvas = plot_canvas
        run_list_model = presenter.run_list
        plot_model = presenter.plot

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(2)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        form.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
        )

        self.auto_add_checkbox = _add_checkbox_row(
            form,
            "Auto Add",
            run_list_model.auto_add,
            run_list_model.set_auto_add,
        )

        self.dynamic_update_checkbox = _add_checkbox_row(
            form,
            "Dynamic Update",
            run_list_model.dynamic_update,
            run_list_model.set_dynamic_update,
        )

        self.lock_aspect_checkbox = None
        if plot_canvas is not None:
            self.lock_aspect_checkbox = _add_checkbox_row(
                form,
                "Lock Aspect",
                plot_canvas.lock_aspect,
                plot_canvas.set_lock_aspect,
                tooltip=(
                    "Keep equal data aspect for image plots "
                    "(square pixels / true scale)"
                ),
            )

        self.retain_selection_checkbox = _add_checkbox_row(
            form,
            "Retain Selection",
            plot_model.retain_selection,
            plot_model.set_retain_selection,
            tooltip="Keep current plot selections when runs change",
        )

        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        settings_min_height = form.minimumSize().height()
        if settings_min_height > 0:
            self.setMinimumHeight(settings_min_height)
