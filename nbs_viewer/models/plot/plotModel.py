"""Plot model managing run controllers and their associated plot artists."""

from typing import List, Optional
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
        self._auto_add = True  # Default to True for better UX
        self._dynamic_update = True
        self._transform = {"enabled": False, "text": ""}
        self._retain_selection = True  # New flag to retain selection
        # Add current selection state
        self._current_x_keys = []
        self._current_y_keys = []
        self._current_norm_keys = []

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
        # print("PlotModel update_available_keys")
        if not self.runModels:
            if not self._retain_selection:
                self._available_keys = []
            # If retaining selection, keep the old available_keys
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
        """Set the run models and handle selection retention."""
        # Store current selection if retaining
        current_selection = None
        if self._retain_selection and not runModels:
            current_selection = (
                self._current_x_keys.copy(),
                self._current_y_keys.copy(),
                self._current_norm_keys.copy(),
            )

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

        # Restore selection if needed, ensuring compatibility with new runs
        if current_selection and self._retain_selection and runModels:
            x_keys, y_keys, norm_keys = current_selection

            # Get intersection of available keys from all models
            available_keys = set(runModels[0].available_keys)
            for model in runModels[1:]:
                available_keys &= set(model.available_keys)

            # Filter selections to only include available keys
            x_keys = [key for key in x_keys if key in available_keys]
            y_keys = [key for key in y_keys if key in available_keys]
            norm_keys = [key for key in norm_keys if key in available_keys]

            # Only update if we have valid keys to plot
            if x_keys or y_keys:
                self.set_selection(x_keys, y_keys, norm_keys, force_update=True)
            else:
                # If no compatible keys, clear the selection
                self.set_selection([], [], [], force_update=True)
                print("No compatible keys found in new run for retained selection")

    def set_auto_add(self, enabled: bool) -> None:
        """
        Set auto-add state and update plots if needed.

        Parameters
        ----------
        enabled : bool
            Whether to automatically add new selections
        """
        self._auto_add = enabled
        if enabled and (self._current_x_keys or self._current_y_keys):
            # If enabling auto_add with existing selection, update all plots
            self._update_plot()

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

    def set_selection(
        self,
        x_keys: List[str],
        y_keys: List[str],
        norm_keys: Optional[List[str]] = None,
        force_update: bool = False,
    ) -> None:
        """
        Set selection for all run models and handle plotting.

        This is the central method for handling all selection changes.
        It updates the internal state, synchronizes all run models,
        and handles plotting based on auto_add and force_update settings.

        Parameters
        ----------
        x_keys : List[str]
            Keys to select for x-axis
        y_keys : List[str]
            Keys to select for y-axis
        norm_keys : Optional[List[str]], optional
            Keys to select for normalization
        force_update : bool, optional
            Whether to force update the plot regardless of auto_add setting
        """
        # print("PlotModel set_selection")
        # Always update internal state
        self._current_x_keys = x_keys
        self._current_y_keys = y_keys
        self._current_norm_keys = norm_keys or []

        # Update selection in all run models (without triggering plot updates)
        for model in self.runModels:
            model.set_selection(x_keys, y_keys, norm_keys, force_update=False)

        # Notify views of selection change
        self.selection_changed.emit(x_keys, y_keys, norm_keys)

        # Update plot if auto_add is enabled or force_update is True
        if self._auto_add or force_update:
            # print("PlotModel set_selection calling _update_plot")
            self._update_plot()

    def _update_plot(self) -> None:
        """
        Update all run models and trigger plot redraw.
        """
        for model in self.runModels:
            model.update_plot()
        self.draw_requested.emit()

    def addRunModel(self, runModel: QObject) -> None:
        """
        Add a new run model and connect its signals.

        Parameters
        ----------
        runModel : QObject
            The model to add.
        """
        # Set initial states
        runModel.set_dynamic(self._dynamic_update)
        runModel.set_transform(self._transform)

        # Connect signals before adding to list to prevent premature updates
        runModel.available_keys_changed.connect(self.update_available_keys)
        runModel.artist_needed.connect(self.artist_needed)
        runModel.draw_requested.connect(self.draw_requested)
        runModel.autoscale_requested.connect(self.autoscale_requested)
        runModel.visibility_changed.connect(self.visibility_changed)

        # Add to list and notify of change
        self.runModels.append(runModel)
        self.run_models_changed.emit(self.runModels)

        # Handle selection synchronization
        has_selection = (
            self._current_x_keys or self._current_y_keys or self._current_norm_keys
        )
        retain_selection = self._retain_selection and has_selection
        if not retain_selection and len(self.runModels) == 1:
            # First model and not retaining - adopt its selection if it has one
            x_keys = runModel.selected_x
            y_keys = runModel.selected_y
            norm_keys = runModel.selected_norm
            if x_keys or y_keys or norm_keys:
                # Use set_selection to properly handle the initial selection
                self.set_selection(
                    x_keys, y_keys, norm_keys, force_update=self._auto_add
                )
        elif self._current_x_keys or self._current_y_keys:
            # Apply current selection to new model
            runModel.set_selection(
                self._current_x_keys, self._current_y_keys, self._current_norm_keys
            )
            # Only update plot if auto_add is enabled
            if self._auto_add:
                runModel.update_plot()
                self.draw_requested.emit()

        # Update available keys
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

    def set_retain_selection(self, enabled: bool) -> None:
        """
        Set whether to retain the current key selection when runs change.

        Parameters
        ----------
        enabled : bool
            Whether to retain the current selection when runs change
        """
        self._retain_selection = enabled
