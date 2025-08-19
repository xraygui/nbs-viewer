from typing import List, Optional
from qtpy.QtCore import QObject, Signal
from ...models.plot.runListModel import RunListModel
from ...models.data.base import CatalogRun


# TODO: Remove plot_models from this class
class DisplayManager(QObject):
    """
    Model managing multiple plot displays and their associated RunListModels.

    Signals
    -------
    display_added : Signal
        Emitted when a new display is created (display_id, run_list_model)
    display_removed : Signal
        Emitted when a display is removed (display_id)
    display_type_changed : Signal
        Emitted when display type changes (display_id, display_type)
    """

    display_added = Signal(str, object)  # display_id, run_list_model
    display_removed = Signal(str)  # display_id
    display_type_changed = Signal(str, str)  # display_id, display_type

    def __init__(self):
        super().__init__()
        self._plot_models = {}  # display_id -> PlotModel
        self._run_assignments = {}  # run_uid -> display_id
        self._display_types = {}  # display_id -> display_type
        self._display_registry = None  # Will be set by MainWidget

        # Create main display with auto-selection enabled
        self._create_new_display("main", is_main_display=True)

    def set_display_registry(self, registry):
        """Set the display registry for this display manager."""
        self._display_registry = registry

    def add_run_to_display(self, run: CatalogRun, display_id: str) -> None:
        """
        Add a run to a specific display.

        Parameters
        ----------
        run : CatalogRun
            Run to add
        display_id : str
            Target display identifier
        """
        if display_id in self._plot_models:
            plot_model = self._plot_models[display_id]
            plot_model.add_run(run)
            self._run_assignments[run.uid] = display_id

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
        if display_id in self._plot_models:
            plot_model = self._plot_models[display_id]
            plot_model.remove_run(run)
            if run.uid in self._run_assignments:
                del self._run_assignments[run.uid]

    def remove_display(self, display_id: str) -> None:
        """Remove a display if it exists and is not the main display."""
        if display_id != "main" and display_id in self._plot_models:
            # Remove all runs assigned to this display
            runs_to_remove = [
                uid for uid, cid in self._run_assignments.items() if cid == display_id
            ]
            for uid in runs_to_remove:
                del self._run_assignments[uid]

            self._plot_models.pop(display_id)
            if display_id in self._display_types:
                del self._display_types[display_id]
            self.display_removed.emit(display_id)

    def create_display(self, display_type: Optional[str] = None) -> str:
        """
        Create a new display with specified display type.

        Parameters
        ----------
        display_type : str, optional
            display type to use for this display. If None, uses default.

        Returns
        -------
        str
            The display identifier
        """
        if display_type is None and self._display_registry:
            display_type = self._display_registry.get_default_display()
        elif display_type is None:
            display_type = "matplotlib"  # Fallback default

        # Validate display type if registry is available
        if self._display_registry:
            available_displays = self._display_registry.get_available_displays()
            if display_type not in available_displays:
                raise ValueError(f"Unknown display type: {display_type}")

        display_id = f"display_{len(self._plot_models)}"
        self._create_new_display(display_id, display_type=display_type)
        return display_id

    def _create_new_display(
        self,
        display_id: str,
        is_main_display: bool = False,
        display_type: str = "matplotlib",
    ) -> None:
        """
        Create a new display and PlotModel.

        Parameters
        ----------
        display_id : str
            Identifier for the display
        is_main_display : bool, optional
            Whether this is the main display, by default False
        display_type : str, optional
            display type for this display, by default "matplotlib"
        """
        run_list_model = RunListModel(is_main_display=is_main_display)
        self._plot_models[display_id] = run_list_model
        self._display_types[display_id] = display_type
        self.display_added.emit(display_id, run_list_model)

    def get_display_type(self, display_id: str) -> str:
        """Get the display type for a display."""
        return self._display_types.get(display_id, "matplotlib")

    def set_display_type(self, display_id: str, display_type: str):
        """Set the display type for a display."""
        if display_id in self._plot_models:
            self._display_types[display_id] = display_type
            self.display_type_changed.emit(display_id, display_type)

    def get_available_display_types(self) -> List[str]:
        """Get list of available display types."""
        if self._display_registry:
            return self._display_registry.get_available_displays()
        return ["matplotlib"]  # Fallback

    def get_display_metadata(self, display_type: str) -> dict:
        """Get metadata for a display type."""
        if self._display_registry:
            return self._display_registry.get_display_metadata(display_type)
        return {"name": display_type, "description": ""}  # Fallback

    def get_display_for_run(self, run_uid: str) -> Optional[str]:
        """
        Get the display ID that a run is assigned to.

        Parameters
        ----------
        run_uid : str
            Run identifier to look up

        Returns
        -------
        Optional[str]
            Display ID if found, None otherwise
        """
        return self._run_assignments.get(run_uid)

    # TODO: What is this for? Why does it return plot models?
    @property
    def canvases(self):
        """Get dictionary of current canvases and their plot models."""
        return self._plot_models.copy()

    def create_display_with_runs(self, run_list: List[CatalogRun]) -> None:
        """
        Create a new display and add runs to it.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to add to the new display
        """
        # Create new display
        display_id = self.create_display()

        # Add runs to the new display
        self.add_runs_to_display(run_list, display_id)

    def add_runs_to_display(self, run_list: List[CatalogRun], display_id: str) -> None:
        """
        Add multiple runs to a specific display.

        Parameters
        ----------
        run_data_list : List[CatalogRun]
            Runs to add to the display
        display_id : str
            Target display identifier
        """
        # TODO: Display class should have  the add_runs method
        if display_id in self._plot_models:
            run_list_model = self._plot_models[display_id]
            for run in run_list:
                # Remove from current display if assigned
                current_display = self.get_display_for_run(run.uid)
                if current_display is not None:
                    self.remove_run_from_display(run, current_display)

                # Add to new display
                run_list_model.add_run(run)
                self._run_assignments[run.uid] = display_id

    def get_display_ids(self) -> List[str]:
        """
        Get list of all display IDs.

        Returns
        -------
        List[str]
            List of display identifiers
        """
        return list(self._plot_models.keys())
