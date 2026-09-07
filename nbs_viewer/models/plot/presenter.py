from typing import List, Optional, Union
from qtpy.QtCore import QObject, Signal
from ...models.plot.runListModel import RunListModel
from ...models.data.base import CatalogRun
from ...models.plot.plotModel import PlotModel
from ...models.plot.runSource import RunSource


class PlotPresenter(QObject):
    """
    Coordinates one plot session (N=1).

    Owns a :class:`PlotModel` (session root) and a :class:`RunListModel`
    Qt facade. Multi-view stays deferred.
    """
    roi_region_changed = Signal(object)
    crop_region_changed = Signal(object)
    status_changed = Signal(str)

    def __init__(
        self,
        presenter_id: str,
        *,
        is_main_display: bool = False,
        single_selection_mode: bool = False,
        parent: Optional[QObject] = None,
    ):
        """
        Parameters
        ----------
        presenter_id : str
            Identifier for this presenter / display session.
        is_main_display : bool, optional
            Whether this is the main display run list.
        single_selection_mode : bool, optional
            If True, checking a run unchecks others (e.g. image grid).
        parent : QObject, optional
            Qt parent.
        """
        super().__init__(parent)
        self._id = presenter_id
        self._plot = PlotModel(
            is_main_display=is_main_display,
            single_selection_mode=single_selection_mode,
            parent=self,
        )
        self._run_list = RunListModel(self._plot)
        self._plot.cache_status_changed.connect(self.status_changed.emit)

    @property
    def id(self) -> str:
        """Presenter / display identifier."""
        return self._id

    @id.setter
    def id(self, value: str) -> None:
        self._id = value

    @property
    def run_list(self) -> RunListModel:
        """Qt run-list item model for this session."""
        return self._run_list

    @property
    def session(self) -> PlotModel:
        """
        Session root (alias of :attr:`plot`).

        Prefer this name in new code; ``plot`` remains for compatibility.
        """
        return self._plot

    def add_run(self, run: Union[CatalogRun, RunSource]) -> None:
        """Add a run to this presenter's session."""
        self.session.add_run(run)

    def add_runs(self, runs: List[CatalogRun]) -> None:
        """Add multiple runs to this presenter's session."""
        self.session.add_runs(runs)

    def remove_run(self, run: CatalogRun) -> None:
        """Remove a run from this presenter's session."""
        self.session.remove_run(run)
