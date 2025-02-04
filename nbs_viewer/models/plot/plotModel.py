"""Plot model managing run controllers and their associated plot artists."""

from typing import List
from qtpy.QtCore import QObject, Signal
import numpy as np


class PlotModel(QObject):
    """
    Model coordinating between run controllers and plot artists.

    This class handles the high-level coordination between data sources
    and their visual representation, delegating actual artist management
    to PlotArtistManager.
    """

    # Signals for view to create/update/remove artists
    artist_needed = Signal(object)  # (model, config) for new artist
    artist_removed = Signal(object)  # artist to remove
    artist_data_updated = Signal(object, np.ndarray, np.ndarray)
    available_keys_changed = Signal()
    indices_update = Signal()
    selection_changed = Signal(list, list, list)
    run_models_changed = Signal(list)
    draw_requested = Signal()
    autoscale_requested = Signal()
    visibility_changed = Signal(object, bool)  # (artist, is_visible)
    legend_update_requested = Signal()  # New signal for legend updates

    def __init__(self, parent=None):
        """Initialize the plot model."""
        super().__init__(parent)
        self.runModels = []
        self._available_keys = set()
        self._indices = None
        self._auto_add = True
        self._dynamic_update = False
        self._transform = {"enabled": False, "text": ""}

    def getHeaderLabel(self) -> str:
        if len(self.runModels) == 0:
            return "No Runs Selected"
        elif len(self.runModels) == 1:
            run = self.runModels[0]._run_data.run
            return f"Run: {run.plan_name} ({run.scan_id})"
        else:
            return f"Multiple Runs Selected ({len(self.runModels)})"

    @property
    def available_keys(self) -> set:
        """Get available data keys."""
        return self._available_keys

    def update_indices(self, indices):
        self._indices = indices
        self.indices_update.emit()

    def update_available_keys(self) -> None:
        """Update the list of available data keys."""
        print("PlotModel update_available_keys")
        if not self.runModels:
            self._available_keys = []
        else:
            # Initialize with ordered keys from first model
            available_keys = list(self.runModels[0].available_keys)

            # Get intersection with other models
            for runModel in self.runModels[1:]:
                available_keys = [
                    key for key in available_keys if key in runModel.available_keys
                ]

            self._available_keys = available_keys
        self.available_keys_changed.emit()

    def setRunModels(self, runModels: List[QObject]) -> None:
        # Get sets of current and new run model IDs
        current_model_ids = {id(model) for model in self.runModels}
        new_model_ids = {id(model) for model in runModels}

        # Remove models that are not in the new list
        models_to_remove = [
            model for model in self.runModels if id(model) not in new_model_ids
        ]
        for model in models_to_remove:
            self.removeRunModel(model)

        # Add models that are not in the current list
        models_to_add = [
            model for model in runModels if id(model) not in current_model_ids
        ]
        for model in models_to_add:
            self.addRunModel(model)

    def set_auto_add(self, enabled: bool) -> None:
        """
        Set auto-add state.

        Parameters
        ----------
        enabled : bool
            Whether to automatically add new selections
        """
        self._auto_add = enabled

    def set_dynamic_update(self, enabled: bool) -> None:
        """
        Set dynamic update state.

        Parameters
        ----------
        enabled : bool
            Whether to enable dynamic updates
        """
        self._dynamic_update = enabled
        for model in self.runModels:
            model.set_dynamic(enabled)

    def set_transform(self, state: dict) -> None:
        """
        Set transform state.

        Parameters
        ----------
        state : dict
            Dictionary with transform state (enabled and text)
        """
        self._transform = state.copy()
        for model in self.runModels:
            model.set_transform(state)

    def addRunModel(self, runModel: QObject) -> None:
        """
        Add a new run model and connect its signals.

        Parameters
        ----------
        runModel : QObject
            The model to add.
        """
        # Set initial states from current control settings
        runModel.set_dynamic(self._dynamic_update)
        runModel.set_transform(self._transform)

        # Connect to data updates
        self.runModels.append(runModel)
        self.run_models_changed.emit(self.runModels)

        runModel.available_keys_changed.connect(self.update_available_keys)
        runModel.artist_needed.connect(self.artist_needed)
        runModel.draw_requested.connect(self.draw_requested)
        runModel.autoscale_requested.connect(self.autoscale_requested)
        runModel.visibility_changed.connect(self.visibility_changed)
        # Connect to selection changes
        self.selection_changed.connect(runModel.set_selection)

        # Connect to available keys changes
        self.update_available_keys()

    def removeRunModel(self, runModel: QObject) -> None:
        """
        Remove a run model and its artists.

        Parameters
        ----------
        runModel : QObject
            The model to remove.
        """
        if runModel in self.runModels:
            self.runModels.remove(runModel)
            runModel.cleanup()

            # Disconnect all signals with specific slots
            try:
                runModel.available_keys_changed.disconnect(self.update_available_keys)
                runModel.autoscale_requested.disconnect(self.autoscale_requested)
                runModel.draw_requested.disconnect(self.draw_requested)
                runModel.artist_needed.disconnect(self.artist_needed)
                runModel.visibility_changed.disconnect(self.visibility_changed)
            except (TypeError, RuntimeError):
                pass

            # Clean up the run model (which will clean up its artists)

            # Emit changes
            self.run_models_changed.emit(self.runModels)
            self.update_available_keys()
            self.draw_requested.emit()

    @property
    def auto_add(self) -> bool:
        """Whether auto-add is enabled."""
        return self._auto_add

    @property
    def dynamic_update(self) -> bool:
        """Whether dynamic update is enabled."""
        return self._dynamic_update

    @property
    def transform(self) -> dict:
        """Current transform state."""
        return self._transform.copy()
