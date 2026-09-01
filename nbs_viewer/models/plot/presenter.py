from typing import Dict, List, Optional, Union
from qtpy.QtCore import QObject, Signal
from ...models.plot.runListModel import RunListModel
from ...models.data.base import CatalogRun
from ...models.plot.plotModel import PlotModel
from ...models.plot.runModel import RunModel
from ...utils import print_debug


class PlotPresenter(QObject):
    """
    Coordinates one plot session (N=1).

    Owns a private :class:`RunListModel` and a 1:1 :class:`PlotModel`.
    Multi-view (N>1 sharing one run list) is deferred to Step 6c.
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
        self._run_list = RunListModel(
            is_main_display=is_main_display,
            single_selection_mode=single_selection_mode,
        )
        self._plot = PlotModel(self._run_list, parent=self)
        self._run_list.cache_status_changed.connect(self.status_changed.emit)

    @property
    def id(self) -> str:
        """Presenter / display identifier."""
        return self._id

    @id.setter
    def id(self, value: str) -> None:
        self._id = value

    @property
    def run_list(self) -> RunListModel:
        """Private run list for this session."""
        return self._run_list

    @property
    def plot(self) -> PlotModel:
        """Plot session bound to :attr:`run_list`."""
        return self._plot

    def add_run(self, run: Union[CatalogRun, RunModel]) -> None:
        """Add a run to this presenter's run list."""
        self._run_list.add_run(run)

    def add_runs(self, runs: List[CatalogRun]) -> None:
        """Add multiple runs to this presenter's run list."""
        for run in runs:
            self._run_list.add_run(run)

    def remove_run(self, run: CatalogRun) -> None:
        """Remove a run from this presenter's run list."""
        self._run_list.remove_run(run)