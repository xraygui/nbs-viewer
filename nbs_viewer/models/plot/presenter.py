from typing import Optional
from qtpy.QtCore import QObject, Signal
from ...models.plot.plot_session import PlotSession


class PlotPresenter(QObject):
    """
    Coordinates one plot session (N=1).

    Owns a :class:`PlotSession` (session root). The sidebar item model is
    a view adapter and is built by :class:`RunListView`. Multi-view stays
    deferred.
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
        self._plot = PlotSession(
            is_main_display=is_main_display,
            single_selection_mode=single_selection_mode,
            parent=self,
        )
        self._plot.cache_status_changed.connect(self.status_changed.emit)

    @property
    def id(self) -> str:
        """Presenter / display identifier."""
        return self._id

    @id.setter
    def id(self, value: str) -> None:
        self._id = value

    @property
    def session(self) -> PlotSession:
        """Session root for this presenter."""
        return self._plot
