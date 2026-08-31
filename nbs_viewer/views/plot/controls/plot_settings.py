from qtpy.QtWidgets import QWidget, QFormLayout, QSizePolicy
from qtpy.QtCore import Qt

from .auto_add import AutoAddControl
from .dynamic_update import DynamicUpdateControl
from .lock_aspect import LockAspectControl
from .retain_selection import RetainSelectionControl


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

        self.auto_add = AutoAddControl(presenter, self)
        self.auto_add.add_to_form(form)

        self.dynamic_update = DynamicUpdateControl(presenter, self)
        self.dynamic_update.add_to_form(form)

        self.lock_aspect = None
        if plot_canvas is not None:
            self.lock_aspect = LockAspectControl(presenter, plot_canvas, self)
            self.lock_aspect.add_to_form(form)

        self.retain_selection = RetainSelectionControl(presenter, self)
        self.retain_selection.add_to_form(form)

        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        settings_min_height = form.minimumSize().height()
        if settings_min_height > 0:
            self.setMinimumHeight(settings_min_height)
