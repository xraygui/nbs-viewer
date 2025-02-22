"""Plot model managing run controllers and their associated plot artists."""

from typing import List, Optional
from qtpy.QtCore import QObject, Signal
import numpy as np
from .runModel import RunModel


class PlotModel(QObject):
    """
    Model coordinating between run data and plot artists.

    This class handles the high-level coordination between data sources
    and their visual representation, managing RunModels and delegating
    actual artist management to PlotDataModel.
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
    run_added = Signal(object)  # RunData added to model
    run_removed = Signal(object)  # RunData removed from model
    run_selection_changed = Signal(list)  # Currently selected RunData list

    def __init__(self, is_main_canvas=False):
        """
        Initialize the plot model.

        Parameters
        ----------
        is_main_canvas : bool
            If True, all runs are automatically selected
        """
        super().__init__()
        self._run_models = {}  # run_uid -> RunModel
        # self._selected_runs = set()  # Set of selected run UIDs
        self._is_main_canvas = is_main_canvas
        self._available_keys = set()
        self._current_x_keys = []
        self._current_y_keys = []
        self._current_norm_keys = []
        self._auto_add = True
        self._retain_selection = False
        self._transform = {"enabled": False, "text": ""}
        self._visible_runs = set()  # Track visible run UIDs

    def getHeaderLabel(self) -> str:
        if len(self._run_models) == 0:
            return "No Runs Selected"
        elif len(self._run_models) == 1:
            run = next(iter(self._run_models.values()))._run
            return f"Run: {run.plan_name} ({run.scan_id})"
        else:
            return f"Multiple Runs Selected ({len(self._run_models)})"

    @property
    def available_keys(self) -> set:
        """Get available data keys."""
        return self._available_keys

    def update_indices(self, indices):
        self._indices = indices
        self.indices_update.emit()

    def update_available_keys(self) -> None:
        """Update available keys and maintain selection state."""
        if not self._run_models:
            if not self._retain_selection:
                self._available_keys = []
                # Clear selection if not retaining
                self.set_selection([], [], [], force_update=False)
            return

        # Get intersection of keys from all models
        first_model = next(iter(self._run_models.values()))
        available_keys = list(first_model.available_keys)
        for model in self._run_models.values():
            available_keys = [
                key for key in available_keys if key in model.available_keys
            ]

        # Update if changed
        if set(available_keys) != set(self._available_keys):
            self._available_keys = available_keys

            # Filter current selection to valid keys
            valid_x = [k for k in self._current_x_keys if k in available_keys]
            valid_y = [k for k in self._current_y_keys if k in available_keys]
            valid_norm = [k for k in self._current_norm_keys if k in available_keys]

            if (
                valid_x != self._current_x_keys
                or valid_y != self._current_y_keys
                or valid_norm != self._current_norm_keys
            ):
                # Update selection if keys were removed
                self.set_selection(valid_x, valid_y, valid_norm, force_update=False)

            self.available_keys_changed.emit()
        # print(f"Available keys changed {self._available_keys}")

    def update_selection(self, run_list, canvas_id="main"):
        """Update the complete selection state."""
        current_uids = {run.uid for run in run_list}
        existing_uids = set(self._run_models.keys())

        # Remove RunModels that are no longer in list
        for uid in existing_uids - current_uids:
            run_model = self._run_models.pop(uid)
            self._disconnect_run_model(run_model)
            run_model.cleanup()

        # Add new RunModels
        for run in run_list:
            uid = run.uid
            if uid not in self._run_models:
                run_model = RunModel(run)
                self._connect_run_model(run_model)
                self._run_models[uid] = run_model
                self._visible_runs.add(uid)  # New runs are visible by default

        # Clean up any inconsistent state
        self.cleanup_state()

        # Update plot based on selection
        self._update_plot_from_selection()
        self.run_selection_changed.emit(self.selected_runs)

    def select_runs(self, run_list):
        """
        Select specific runs for plotting.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to select
        """
        for run in run_list:
            uid = run.uid
            if uid in self._run_models:
                self._visible_runs.add(uid)

        self._update_plot_from_selection()
        self.run_selection_changed.emit(self.selected_runs)

    def deselect_runs(self, run_list):
        """
        Deselect specific runs from plotting.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to deselect
        """
        for run in run_list:
            uid = run.uid
            if uid in self._visible_runs:
                self._visible_runs.remove(uid)

        self._update_plot_from_selection()
        self.run_selection_changed.emit(self.selected_runs)

    def _update_plot_from_selection(self):
        """Update plot based on current run selection."""
        if self._is_main_canvas:
            # All runs are selected
            selected_models = list(self._run_models.values())
        else:
            # Only plot selected runs
            selected_models = [
                model
                for uid, model in self._run_models.items()
                if uid in self._visible_runs
            ]

        self.run_models_changed.emit(selected_models)
        self._update_plot()

    @property
    def selected_runs(self):
        """Get list of currently selected RunData objects."""
        return [
            self._run_models[uid]._run
            for uid in self._visible_runs
            if uid in self._run_models
        ]

    @property
    def available_runs(self):
        """Get list of all available CatalogRun objects."""
        return [model._run for model in self._run_models.values()]

    def _connect_run_model(self, run_model):
        """Connect signals from a RunModel."""
        run_model.available_keys_changed.connect(self.update_available_keys)
        run_model.artist_needed.connect(self.artist_needed)
        run_model.draw_requested.connect(self.draw_requested)
        run_model.autoscale_requested.connect(self.autoscale_requested)
        run_model.visibility_changed.connect(self.visibility_changed)

    def _disconnect_run_model(self, run_model):
        """Disconnect signals from a RunModel."""
        run_model.available_keys_changed.disconnect(self.update_available_keys)
        run_model.artist_needed.disconnect(self.artist_needed)
        run_model.draw_requested.disconnect(self.draw_requested)
        run_model.autoscale_requested.disconnect(self.autoscale_requested)
        run_model.visibility_changed.disconnect(self.visibility_changed)

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
        for model in self._run_models.values():
            model.set_dynamic(enabled)

    def set_transform(self, transform_state: dict) -> None:
        """Set transform state and update all plots."""
        self._transform = (
            transform_state.copy()
        )  # Make a copy to prevent external modification

        # Update transform in all run models
        for model in self._run_models.values():
            model.set_transform(self._transform)

        # Force plot update
        self._update_plot()
        self.draw_requested.emit()
        self.legend_update_requested.emit()  # Legend may need updating if transform changes labels

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
        for model in self._run_models.values():
            model.set_selection(x_keys, y_keys, norm_keys, force_update=False)

        # Notify views of selection change
        self.selection_changed.emit(
            self._current_x_keys, self._current_y_keys, self._current_norm_keys
        )

        # Update plot if auto_add is enabled or force_update is True
        if self._auto_add or force_update:
            # print("PlotModel set_selection calling _update_plot")
            self._update_plot()

    def get_selected_keys(self):
        """Get selected keys from all run models."""
        return self._current_x_keys, self._current_y_keys, self._current_norm_keys

    def _update_plot(self) -> None:
        """
        Update all run models and trigger plot redraw.
        """
        for model in self._run_models.values():
            model.update_plot()
        self.draw_requested.emit()

    @property
    def auto_add(self) -> bool:
        """Whether auto-add is enabled."""
        return self._auto_add

    @property
    def dynamic_update(self) -> bool:
        """Whether dynamic update is enabled."""
        return all(model.dynamic_update for model in self._run_models.values())

    @property
    def transform(self) -> dict:
        """Current transform state with default values if not set."""
        default_state = {"enabled": False, "text": ""}
        # Merge current state with defaults
        return {**default_state, **self._transform}

    def set_retain_selection(self, enabled: bool) -> None:
        """
        Set whether to retain the current key selection when runs change.

        Parameters
        ----------
        enabled : bool
            Whether to retain the current selection when runs change
        """
        self._retain_selection = enabled

    def add_run(self, run):
        """
        Add a single run to the model and handle key selection.

        Parameters
        ----------
        run : CatalogRun
            Run to add to the model
        """
        uid = run.uid
        if uid in self._run_models:
            return

        # Create and connect new run model
        run_model = RunModel(run)
        self._connect_run_model(run_model)
        self._run_models[uid] = run_model
        # Update available keys first
        self.update_available_keys()

        # Determine key selection
        if len(self._run_models) == 1 and not self._retain_selection:
            # First run, get default selection
            x_keys, y_keys, norm_keys = run.get_default_selection()
            self.set_selection(x_keys, y_keys, norm_keys, force_update=False)
        else:
            # Apply current selection and transform to new run
            run_model.set_selection(
                self._current_x_keys,
                self._current_y_keys,
                self._current_norm_keys,
                force_update=False,
            )
            # Apply current transform state
            if self._transform["enabled"]:
                run_model.set_transform(self._transform)

        # Emit signals in correct order
        self.run_added.emit(run)

        # Handle main canvas auto-selection
        if self._is_main_canvas or self._auto_add:
            # self._selected_runs.add(uid)
            self.update_visibility(run, True)
            self._update_plot_from_selection()

        # Force plot update and legend refresh
        self._update_plot()
        self.legend_update_requested.emit()

    def remove_run(self, run):
        """
        Remove a single run from the model.

        Parameters
        ----------
        run : CatalogRun
            Run to remove from the model
        """
        uid = run.uid
        if uid in self._run_models:
            run_model = self._run_models.pop(uid)
            self._disconnect_run_model(run_model)
            run_model.cleanup()

            # Clean up all references to this run
            # if uid in self._selected_runs:
            #    self._selected_runs.remove(uid)
            if uid in self._visible_runs:  # Add this cleanup
                self._visible_runs.remove(uid)

            # Update plot and notify views
            self._update_plot_from_selection()
            self.run_removed.emit(run)
            self.run_selection_changed.emit(self.selected_runs)
            self.legend_update_requested.emit()
            self.update_available_keys()

    def update_visibility(self, run, is_visible):
        """
        Update run visibility.

        Parameters
        ----------
        run : CatalogRun
            Run to update visibility for
        is_visible : bool
            New visibility state
        """
        uid = run.uid
        if uid in self._run_models:
            run_model = self._run_models[uid]
            if is_visible:
                self._visible_runs.add(uid)
            else:
                self._visible_runs.discard(uid)
            run_model.set_visible(is_visible)
            self.run_selection_changed.emit(self.selected_runs)

    @property
    def current_selection(self) -> tuple:
        """Get current key selection state."""
        return (
            self._current_x_keys.copy(),
            self._current_y_keys.copy(),
            self._current_norm_keys.copy(),
        )

    @property
    def selected_keys(self) -> dict:
        """Get dictionary of selected keys by type."""
        return {
            "x": self._current_x_keys.copy(),
            "y": self._current_y_keys.copy(),
            "norm": self._current_norm_keys.copy(),
        }

    def is_key_selected(self, key: str, axis: str) -> bool:
        """
        Check if a key is selected for a given axis.

        Parameters
        ----------
        key : str
            The key to check
        axis : str
            The axis type ('x', 'y', or 'norm')
        """
        if axis == "x":
            return key in self._current_x_keys
        elif axis == "y":
            return key in self._current_y_keys
        elif axis == "norm":
            return key in self._current_norm_keys
        return False

    def get_selected_runs(self):
        """
        Get currently selected CatalogRun. Objects (not RunModels!)

        Returns
        -------
        List[CatalogRun]
            List of selected run objects
        """
        # Convert run models back to catalog runs
        return [
            model._run
            for model in self._run_models.values()
            if model._run.uid in self._visible_runs
        ]

    def get_selected_models(self):
        """
        Get currently selected RunModels.
        """
        return [
            model
            for model in self._run_models.values()
            if model._run.uid in self._visible_runs
        ]

    def cleanup_state(self):
        """Clean up any inconsistent state in the model."""
        # Remove any visible or selected runs that aren't in run_models
        valid_uids = set(self._run_models.keys())
        self._visible_runs.intersection_update(valid_uids)
        # self._selected_runs.intersection_update(valid_uids)
