"""
Plot session model bound to a run list.

Owns plot-local state such as the ROI set. Key selection, plot-data maps, and
related policy move here in a later step; this module starts as a thin shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from qtpy.QtCore import QObject

from .roi_set import RoiSetModel

if TYPE_CHECKING:
    from .runListModel import RunListModel


class PlotModel(QObject):
    """
    One plot session associated with a :class:`RunListModel`.

    Parameters
    ----------
    run_list_model : RunListModel
        Run collection and visibility source for this plot.
    parent : QObject, optional
        Qt parent.
    """

    def __init__(self, run_list_model: "RunListModel", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._run_list_model = run_list_model
        self._roi_set = RoiSetModel(parent=self)

    @property
    def run_list_model(self) -> "RunListModel":
        """
        Return the bound run list model.
        """
        return self._run_list_model

    @property
    def roi_set(self) -> RoiSetModel:
        """
        Return the ROI set owned by this plot session.
        """
        return self._roi_set
