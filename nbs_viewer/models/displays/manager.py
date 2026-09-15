from typing import Dict, List, Optional, Union
from qtpy.QtCore import QObject, Signal
from ...models.data.base import CatalogRun
from ..plot.session import PlotSession
from ..plot.run.source import RunSource
from ...utils import print_debug
from .presenter import PlotPresenter


class DisplayManager(QObject):
    """
    Manager of :class:`PlotPresenter` sessions.

    Does not own or load plot frontend widgets. An optional opaque
    ``display_type`` string may be stored as a hint for the GUI shell
    (which frontend tab to open). Widget discovery lives in
    ``views.display.frontendRegistry``.

    Signals
    -------
    display_added : Signal
        Emitted when a new presenter is created (display_id)
    display_removed : Signal
        Emitted when a presenter is removed (display_id)
    display_type_changed : Signal
        Emitted when display type hint changes (display_id, display_type)
    display_renamed : Signal
        Emitted when a presenter is renamed (old_id, new_id)
    """

    display_added = Signal(str)  # display_id
    display_removed = Signal(str)  # display_id
    display_type_changed = Signal(str, str)  # display_id, display_type
    display_renamed = Signal(str, str)  # display_id, new_name

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._presenters: Dict[str, PlotPresenter] = {}
        self._display_types: Dict[str, str] = {}

        self.register_display(is_main_display=True)

    def get_presenter(self, display_id: str) -> PlotPresenter:
        """
        Return the presenter for a display id.

        Parameters
        ----------
        display_id : str
            Identifier for the display / presenter.

        Returns
        -------
        PlotPresenter
            Presenter owning run list and plot model.
        """
        return self._presenters[display_id]

    def get_session(self, display_id: str) -> PlotSession:
        """
        Return the plot session model for a display.

        Parameters
        ----------
        display_id : str
            Identifier for the display

        Returns
        -------
        PlotSession
            Plot session bound to the display's run list.
        """
        return self._presenters[display_id].session

    def get_display_ids(self) -> List[str]:
        """
        Get list of all display IDs.

        Returns
        -------
        List[str]
            List of display identifiers
        """
        return list(self._presenters.keys())

    def get_display_type(self, display_id: str) -> str:
        """Get the frontend type hint for a display."""
        return self._display_types.get(display_id, "matplotlib")

    def set_display_type(self, display_id: str, display_type: str):
        """Set the frontend type hint for a display."""
        if display_id in self._presenters:
            self._display_types[display_id] = display_type
            self.display_type_changed.emit(display_id, display_type)

    def rename_display(self, display_id: str, new_name: str) -> None:
        """
        Rename a display / presenter.

        Parameters
        ----------
        display_id : str
            Current identifier.
        new_name : str
            New identifier.
        """
        if display_id not in self._presenters:
            return
        if display_id in self._display_types:
            display_type = self._display_types.pop(display_id)
            self._display_types[new_name] = display_type
        presenter = self._presenters.pop(display_id)
        presenter.id = new_name
        self._presenters[new_name] = presenter
        self.display_renamed.emit(display_id, new_name)

    def remove_display(self, display_id: str) -> None:
        """Remove a display if it exists and is not the main display."""
        if display_id != "main" and display_id in self._presenters:
            self._presenters.pop(display_id)
            self._display_types.pop(display_id, None)
            self.display_removed.emit(display_id)

    def register_display(
        self,
        display_type: Optional[str] = None,
        display_id: Optional[str] = None,
        is_main_display: bool = False,
        single_selection_mode: bool = False,
    ) -> str:
        """
        Create a new presenter with a private run list and plot model.

        Parameters
        ----------
        display_type : str, optional
            Opaque frontend hint for the GUI shell. Defaults to
            ``"matplotlib"``. Not validated against widget entry points.
        display_id : str, optional
            Presenter id. If None, uses a generated id (or ``"main"``).
        is_main_display : bool, optional
            Whether this is the main display, by default False
        single_selection_mode : bool, optional
            Run-list checkbox policy for this presenter.

        Returns
        -------
        str
            The display identifier
        """
        if display_type is None:
            display_type = "matplotlib"

        if is_main_display:
            display_id = "main"
        elif display_id is None:
            display_id = f"display_{len(self._presenters)}"
        else:
            display_id = display_id

        self._display_types[display_id] = display_type

        presenter = PlotPresenter(
            display_id,
            is_main_display=is_main_display,
            single_selection_mode=single_selection_mode,
            parent=self,
        )
        self._presenters[display_id] = presenter
        self.display_added.emit(display_id)
        return display_id

    def create_display_with_runs(
        self,
        run_list: List[CatalogRun],
        display_type: str = "matplotlib",
        *,
        single_selection_mode: bool = False,
    ) -> str:
        """
        Create a new presenter and add runs to it.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to add to the new display
        display_type : str
            Opaque frontend hint for the GUI shell
        single_selection_mode : bool, optional
            Explicit run-list policy (do not infer from display_type here)

        Returns
        -------
        str
            New display identifier
        """
        display_id = self.register_display(
            display_type, single_selection_mode=single_selection_mode
        )
        self.add_runs_to_display(run_list, display_id)
        return display_id

    def add_runs_to_display(self, run_list: List[CatalogRun], display_id: str) -> None:
        """
        Add multiple runs to a specific display.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to add to the display
        display_id : str
            Target display identifier
        """
        if display_id in self._presenters:
            self._presenters[display_id].session.collection.add_runs(run_list)

    def add_run_to_display(
        self, run: Union[CatalogRun, RunSource], display_id: str
    ) -> None:
        """
        Add a run to a specific display.

        Parameters
        ----------
        run : CatalogRun
            Run to add
        display_id : str
            Target display identifier
        """
        print_debug(
            "DisplayManager.add_run_to_display",
            f"Adding run {run.uid} to display {display_id}",
            category="display",
        )
        if display_id in self._presenters:
            self._presenters[display_id].session.collection.add_runs([run])

    def remove_run_from_display(self, run: CatalogRun, display_id: str) -> None:
        """
        Remove a run from a specific display.

        Parameters
        ----------
        run : CatalogRun
            Run to remove
        display_id : str
            Source display identifier
        """
        print_debug(
            "DisplayManager.remove_run_from_display",
            f"Removing run {run.uid} from display {display_id}",
            category="display",
        )
        if display_id in self._presenters:
            self._presenters[display_id].session.collection.remove_uids([run.uid])
