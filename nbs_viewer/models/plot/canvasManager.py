from typing import List, Dict, Optional
from qtpy.QtCore import QObject, Signal
from ...models.plot.plotModel import PlotModel
from ...models.plot.runData import RunData


class CanvasManager(QObject):
    """
    Model managing multiple plot canvases and their associated PlotModels.

    Signals
    -------
    canvas_added : Signal
        Emitted when a new canvas is created (canvas_id, plot_model)
    canvas_removed : Signal
        Emitted when a canvas is removed (canvas_id)
    """

    canvas_added = Signal(str, object)  # canvas_id, plot_model
    canvas_removed = Signal(str)  # canvas_id

    def __init__(self):
        super().__init__()
        self._plot_models = {}  # canvas_id -> PlotModel
        self._run_assignments = {}  # run_uid -> canvas_id

        # Create main canvas with auto-selection enabled
        self._create_new_canvas("main", is_main_canvas=True)

    def add_run_to_canvas(self, run_data: RunData, canvas_id: str) -> None:
        """
        Add a run to a specific canvas.

        Parameters
        ----------
        run_data : RunData
            Run to add
        canvas_id : str
            Target canvas identifier
        """
        if canvas_id in self._plot_models:
            plot_model = self._plot_models[canvas_id]
            plot_model.add_run(run_data)
            self._run_assignments[run_data.run.uid] = canvas_id

    def remove_run_from_canvas(self, run_data: RunData, canvas_id: str) -> None:
        """
        Remove a run from a specific canvas.

        Parameters
        ----------
        run_data : RunData
            Run to remove
        canvas_id : str
            Source canvas identifier
        """
        if canvas_id in self._plot_models:
            plot_model = self._plot_models[canvas_id]
            plot_model.remove_run(run_data)
            if run_data.run.uid in self._run_assignments:
                del self._run_assignments[run_data.run.uid]

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
            self.canvas_removed.emit(canvas_id)

    def create_canvas(self) -> str:
        """
        Create a new canvas.

        Returns
        -------
        str
            ID of the new canvas
        """
        canvas_id = str(len(self._plot_models))
        while canvas_id in self._plot_models:
            canvas_id = str(int(canvas_id) + 1)

        self._create_new_canvas(canvas_id)
        return canvas_id

    def _create_new_canvas(self, canvas_id: str, is_main_canvas: bool = False) -> None:
        """
        Create a new canvas and PlotModel.

        Parameters
        ----------
        canvas_id : str
            Identifier for the new canvas
        is_main_canvas : bool, optional
            Whether this is the main canvas, by default False
        """
        plot_model = PlotModel(is_main_canvas=is_main_canvas)
        self._plot_models[canvas_id] = plot_model
        self.canvas_added.emit(canvas_id, plot_model)

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
    def canvases(self) -> Dict[str, PlotModel]:
        """Get dictionary of current canvases and their plot models."""
        return self._plot_models.copy()

    def create_canvas_with_runs(self, run_data_list: List[RunData]) -> None:
        """
        Create a new canvas and add runs to it.

        Parameters
        ----------
        run_data_list : List[RunData]
            Runs to add to the new canvas
        """
        # Create new canvas
        canvas_id = self.create_canvas()

        # Add runs to the new canvas
        self.add_runs_to_canvas(run_data_list, canvas_id)

    def add_runs_to_canvas(self, run_data_list: List[RunData], canvas_id: str) -> None:
        """
        Add multiple runs to a specific canvas.

        Parameters
        ----------
        run_data_list : List[RunData]
            Runs to add to the canvas
        canvas_id : str
            Target canvas identifier
        """
        if canvas_id in self._plot_models:
            plot_model = self._plot_models[canvas_id]
            for run_data in run_data_list:
                # Remove from current canvas if assigned
                current_canvas = self.get_canvas_for_run(run_data.run.uid)
                if current_canvas is not None:
                    self.remove_run_from_canvas(run_data, current_canvas)

                # Add to new canvas
                plot_model.add_run(run_data)
                self._run_assignments[run_data.run.uid] = canvas_id
