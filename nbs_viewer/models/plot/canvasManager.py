from typing import List, Optional
from qtpy.QtCore import QObject, Signal
from ...models.plot.plotModel import PlotModel
from ...models.data.base import CatalogRun


class CanvasManager(QObject):
    """
    Model managing multiple plot canvases and their associated PlotModels.

    Signals
    -------
    canvas_added : Signal
        Emitted when a new canvas is created (canvas_id, plot_model)
    canvas_removed : Signal
        Emitted when a canvas is removed (canvas_id)
    widget_type_changed : Signal
        Emitted when widget type changes (canvas_id, widget_type)
    """

    canvas_added = Signal(str, object)  # canvas_id, plot_model
    canvas_removed = Signal(str)  # canvas_id
    widget_type_changed = Signal(str, str)  # canvas_id, widget_type

    def __init__(self):
        super().__init__()
        self._plot_models = {}  # canvas_id -> PlotModel
        self._run_assignments = {}  # run_uid -> canvas_id
        self._canvas_widget_types = {}  # canvas_id -> widget_type
        self._widget_registry = None  # Will be set by MainWidget

        # Create main canvas with auto-selection enabled
        self._create_new_canvas("main", is_main_canvas=True)

    def set_widget_registry(self, registry):
        """Set the widget registry for this canvas manager."""
        self._widget_registry = registry

    def add_run_to_canvas(self, run: CatalogRun, canvas_id: str) -> None:
        """
        Add a run to a specific canvas.

        Parameters
        ----------
        run : CatalogRun
            Run to add
        canvas_id : str
            Target canvas identifier
        """
        if canvas_id in self._plot_models:
            plot_model = self._plot_models[canvas_id]
            plot_model.add_run(run)
            self._run_assignments[run.uid] = canvas_id

    def remove_run_from_canvas(self, run: CatalogRun, canvas_id: str) -> None:
        """
        Remove a run from a specific canvas.

        Parameters
        ----------
        run : CatalogRun
            Run to remove
        canvas_id : str
            Source canvas identifier
        """
        if canvas_id in self._plot_models:
            plot_model = self._plot_models[canvas_id]
            plot_model.remove_run(run)
            if run.uid in self._run_assignments:
                del self._run_assignments[run.uid]

    def remove_canvas(self, canvas_id: str) -> None:
        """Remove a canvas if it exists and is not the main canvas."""
        if canvas_id != "main" and canvas_id in self._plot_models:
            # Remove all runs assigned to this canvas
            runs_to_remove = [
                uid for uid, cid in self._run_assignments.items() if cid == canvas_id
            ]
            for uid in runs_to_remove:
                del self._run_assignments[uid]

            self._plot_models.pop(canvas_id)
            if canvas_id in self._canvas_widget_types:
                del self._canvas_widget_types[canvas_id]
            self.canvas_removed.emit(canvas_id)

    def create_canvas(self, widget_type: Optional[str] = None) -> str:
        """
        Create a new canvas with specified widget type.

        Parameters
        ----------
        widget_type : str, optional
            Widget type to use for this canvas. If None, uses default.

        Returns
        -------
        str
            The canvas identifier
        """
        if widget_type is None and self._widget_registry:
            widget_type = self._widget_registry.get_default_widget()
        elif widget_type is None:
            widget_type = "matplotlib"  # Fallback default

        # Validate widget type if registry is available
        if self._widget_registry:
            available_widgets = self._widget_registry.get_available_widgets()
            if widget_type not in available_widgets:
                raise ValueError(f"Unknown widget type: {widget_type}")

        canvas_id = f"canvas_{len(self._plot_models)}"
        self._create_new_canvas(canvas_id, widget_type=widget_type)
        return canvas_id

    def _create_new_canvas(
        self,
        canvas_id: str,
        is_main_canvas: bool = False,
        widget_type: str = "matplotlib",
    ) -> None:
        """
        Create a new canvas and PlotModel.

        Parameters
        ----------
        canvas_id : str
            Identifier for the canvas
        is_main_canvas : bool, optional
            Whether this is the main canvas, by default False
        widget_type : str, optional
            Widget type for this canvas, by default "matplotlib"
        """
        plot_model = PlotModel(is_main_canvas=is_main_canvas)
        self._plot_models[canvas_id] = plot_model
        self._canvas_widget_types[canvas_id] = widget_type
        self.canvas_added.emit(canvas_id, plot_model)

    def get_canvas_widget_type(self, canvas_id: str) -> str:
        """Get the widget type for a canvas."""
        return self._canvas_widget_types.get(canvas_id, "matplotlib")

    def set_canvas_widget_type(self, canvas_id: str, widget_type: str):
        """Set the widget type for a canvas."""
        if canvas_id in self._plot_models:
            self._canvas_widget_types[canvas_id] = widget_type
            self.widget_type_changed.emit(canvas_id, widget_type)

    def get_available_widget_types(self) -> List[str]:
        """Get list of available widget types."""
        if self._widget_registry:
            return self._widget_registry.get_available_widgets()
        return ["matplotlib"]  # Fallback

    def get_widget_metadata(self, widget_type: str) -> dict:
        """Get metadata for a widget type."""
        if self._widget_registry:
            return self._widget_registry.get_widget_metadata(widget_type)
        return {"name": widget_type, "description": ""}  # Fallback

    def get_canvas_for_run(self, run_uid: str) -> Optional[str]:
        """
        Get the canvas ID that a run is assigned to.

        Parameters
        ----------
        run_uid : str
            Run identifier to look up

        Returns
        -------
        Optional[str]
            Canvas ID if found, None otherwise
        """
        return self._run_assignments.get(run_uid)

    @property
    def canvases(self):
        """Get dictionary of current canvases and their plot models."""
        return self._plot_models.copy()

    def create_canvas_with_runs(self, run_list: List[CatalogRun]) -> None:
        """
        Create a new canvas and add runs to it.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to add to the new canvas
        """
        # Create new canvas
        canvas_id = self.create_canvas()

        # Add runs to the new canvas
        self.add_runs_to_canvas(run_list, canvas_id)

    def add_runs_to_canvas(self, run_list: List[CatalogRun], canvas_id: str) -> None:
        """
        Add multiple runs to a specific canvas.

        Parameters
        ----------
        run_data_list : List[CatalogRun]
            Runs to add to the canvas
        canvas_id : str
            Target canvas identifier
        """
        if canvas_id in self._plot_models:
            plot_model = self._plot_models[canvas_id]
            for run in run_list:
                # Remove from current canvas if assigned
                current_canvas = self.get_canvas_for_run(run.uid)
                if current_canvas is not None:
                    self.remove_run_from_canvas(run, current_canvas)

                # Add to new canvas
                plot_model.add_run(run)
                self._run_assignments[run.uid] = canvas_id

    def get_canvas_ids(self) -> List[str]:
        """
        Get list of all canvas IDs.

        Returns
        -------
        List[str]
            List of canvas identifiers
        """
        return list(self._plot_models.keys())
