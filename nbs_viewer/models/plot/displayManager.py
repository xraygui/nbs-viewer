from typing import Dict, List, Optional, Union
from qtpy.QtCore import QObject, Signal
from ...models.plot.runListModel import RunListModel
from ...models.data.base import CatalogRun
from .displayRegistry import DisplayRegistry
from ...models.plot.plotModel import PlotModel
from ...models.plot.runModel import RunModel
from ...utils import print_debug


class PlotPresenter(QObject):
    """
    Coordinates one plot session (N=1).

    Owns a private :class:`RunListModel` and a 1:1 :class:`PlotModel`.
    Multi-view (N>1 sharing one run list) is deferred to Step 6c.
    """

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


class DisplayManager(QObject):
    """
    Manager of :class:`PlotPresenter` sessions.

    Keeps display-type strings as a frontend hint for which widget to load
    (until Step 6b moves the registry out of models). Run-list policy such as
    ``single_selection_mode`` is set explicitly on the presenter, not inferred
    from a hardcoded display-type list.

    Signals
    -------
    display_added : Signal
        Emitted when a new presenter is created (display_id, run_list_model)
    display_removed : Signal
        Emitted when a presenter is removed (display_id)
    display_type_changed : Signal
        Emitted when display type changes (display_id, display_type)
    display_renamed : Signal
        Emitted when a presenter is renamed (old_id, new_id)
    """

    display_added = Signal(str, object)  # display_id, run_list_model
    display_removed = Signal(str)  # display_id
    display_type_changed = Signal(str, str)  # display_id, display_type
    display_renamed = Signal(str, str)  # display_id, new_name

    def __init__(self, display_registry: DisplayRegistry):
        super().__init__()
        self._presenters: Dict[str, PlotPresenter] = {}
        self._display_types: Dict[str, str] = {}
        self._display_registry = display_registry

        self.register_display(is_main_display=True)

    ###########################################################################
    # Accessors and setters
    ###########################################################################

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

    def get_run_list_model(self, display_id: str) -> RunListModel:
        """
        Return the run list model for a display.

        Parameters
        ----------
        display_id : str
            Identifier for the display

        Returns
        -------
        RunListModel
            Run list for the display.
        """
        return self._presenters[display_id].run_list

    def get_plot_model(self, display_id: str) -> PlotModel:
        """
        Return the plot session model for a display.

        Parameters
        ----------
        display_id : str
            Identifier for the display

        Returns
        -------
        PlotModel
            Plot session bound to the display's run list.
        """
        return self._presenters[display_id].plot

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
        """Get the display type for a display."""
        return self._display_types.get(display_id, "matplotlib")

    def set_display_type(self, display_id: str, display_type: str):
        """Set the display type for a display."""
        if display_id in self._presenters:
            self._display_types[display_id] = display_type
            self.display_type_changed.emit(display_id, display_type)

    def get_available_display_types(self) -> List[str]:
        """Get list of available display types."""
        if self._display_registry:
            return self._display_registry.get_available_displays()
        return ["matplotlib"]

    def get_display_metadata(self, display_type: str) -> dict:
        """Get metadata for a display type."""
        if self._display_registry:
            return self._display_registry.get_display_metadata(display_type)
        return {"name": display_type, "description": ""}

    def single_selection_mode_for_type(self, display_type: str) -> bool:
        """
        Read ``single_selection_mode`` from frontend display metadata.

        Parameters
        ----------
        display_type : str
            Registered display / widget type id.

        Returns
        -------
        bool
            Policy declared on the frontend class, default False.
        """
        return bool(
            self.get_display_metadata(display_type).get("single_selection_mode", False)
        )

    ###########################################################################
    # Display management
    ###########################################################################
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
            Frontend widget type hint. If None, uses default.
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
        if display_type is None and self._display_registry:
            display_type = self._display_registry.get_default_display()
        elif display_type is None:
            display_type = "matplotlib"

        if self._display_registry:
            available_displays = self._display_registry.get_available_displays()
            if display_type not in available_displays:
                raise ValueError(f"Unknown display type: {display_type}")

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
        self.display_added.emit(display_id, presenter.run_list)
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
            Frontend widget type hint
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

    ###########################################################################
    # Run management
    ###########################################################################
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
            self._presenters[display_id].add_runs(run_list)

    def add_run_to_display(
        self, run: Union[CatalogRun, RunModel], display_id: str
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
            self._presenters[display_id].add_run(run)

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
            self._presenters[display_id].remove_run(run)
