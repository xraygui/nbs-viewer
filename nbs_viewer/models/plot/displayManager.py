from typing import List, Optional, Union
from qtpy.QtCore import QObject, Signal
from ...models.plot.runListModel import RunListModel
from ...models.data.base import CatalogRun
from .displayRegistry import DisplayRegistry
from ...models.plot.runModel import RunModel


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
    display_renamed = Signal(str, str)  # display_id, new_name

    def __init__(self, display_registry: DisplayRegistry):
        super().__init__()
        self._run_list_models = {}  # display_id -> RunListModel
        self._run_assignments = {}  # run_uid -> display_id
        self._display_types = {}  # display_id -> display_type
        self._display_registry = display_registry

        # Create main display with auto-selection enabled
        self.register_display(is_main_display=True)

    ###########################################################################
    # Accessors and setters
    ###########################################################################

    def get_run_list_model(self, display_id: str) -> None:
        """
        Create a new display and PlotModel.

        Parameters
        ----------
        display_id : str
            Identifier for the display
        """
        return self._run_list_models[display_id]

    def get_display_ids(self) -> List[str]:
        """
        Get list of all display IDs.

        Returns
        -------
        List[str]
            List of display identifiers
        """
        return list(self._run_list_models.keys())

    def get_display_type(self, display_id: str) -> str:
        """Get the display type for a display."""
        return self._display_types.get(display_id, "matplotlib")

    def set_display_type(self, display_id: str, display_type: str):
        """Set the display type for a display."""
        if display_id in self._run_list_models:
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

    ###########################################################################
    # Display management
    ###########################################################################
    def rename_display(self, display_id: str, new_name: str) -> None:
        """
        Rename a display.
        """
        if display_id in self._display_types:
            display_type = self._display_types.pop(display_id)
            self._display_types[new_name] = display_type
        if display_id in self._run_list_models:
            run_list_model = self._run_list_models.pop(display_id)
            self._run_list_models[new_name] = run_list_model
        self.display_renamed.emit(display_id, new_name)

    def remove_display(self, display_id: str) -> None:
        """Remove a display if it exists and is not the main display."""
        if display_id != "main" and display_id in self._run_list_models:
            self._run_list_models.pop(display_id)
            if display_id in self._display_types:
                del self._display_types[display_id]
            self.display_removed.emit(display_id)

    def register_display(
        self,
        display_type: Optional[str] = None,
        display_id: Optional[str] = None,
        is_main_display: bool = False,
        single_selection_mode: bool = False,
    ) -> str:
        """
        Create a new display with specified display type.

        Parameters
        ----------
        display_type : str, optional
            display type to use for this display. If None, uses default.
        display_id : str, optional
            display id to use for this display. If None, uses default.
        is_main_display : bool, optional
            Whether this is the main display, by default False
        single_selection_mode : bool, optional
            Whether to enable single-selection mode for checkboxes, by default False
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

        if is_main_display:
            display_id = "main"
        elif display_id is None:
            display_id = f"display_{len(self._run_list_models)}"
        else:
            display_id = display_id

        self._display_types[display_id] = display_type

        run_list_model = RunListModel(
            is_main_display=is_main_display, single_selection_mode=single_selection_mode
        )
        self._run_list_models[display_id] = run_list_model
        self.display_added.emit(display_id, run_list_model)
        return display_id

    def create_display_with_runs(
        self, run_list: List[CatalogRun], display_type: str = "matplotlib"
    ) -> None:
        """
        Create a new display and add runs to it.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to add to the new display
        display_type : str
            Type of display to create
        """
        # Determine if this display type should use single-selection mode
        single_selection_displays = ["image_grid", "spiral"]
        single_selection_mode = display_type in single_selection_displays

        # Create new display
        display_id = self.register_display(
            display_type, single_selection_mode=single_selection_mode
        )
        self.add_runs_to_display(run_list, display_id)

    ###########################################################################
    # Run management
    ###########################################################################
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
        if display_id in self._run_list_models:
            run_list_model = self._run_list_models[display_id]
            for run in run_list:
                # Add to new display
                run_list_model.add_run(run)

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
        if display_id in self._run_list_models:
            run_list_model = self._run_list_models[display_id]
            run_list_model.add_run(run)

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
        if display_id in self._run_list_models:
            run_list_model = self._run_list_models[display_id]
            run_list_model.remove_run(run)
