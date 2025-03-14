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

    available_keys_changed = Signal()
    selected_keys_changed = Signal(list, list, list)
    run_added = Signal(object)  # RunData added to model
    run_removed = Signal(object)  # RunData removed from model
    available_runs_changed = Signal(list)  # List of Run UIDs
    visible_runs_changed = Signal(set)  # Set of visible Run UIDs

    request_plot_update = Signal()

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
        self._is_main_canvas = is_main_canvas

        self.available_keys = list()
        self._current_x_keys = []
        self._current_y_keys = []
        self._current_norm_keys = []

        self._auto_add = True
        self._retain_selection = False
        self._transform = {"enabled": False, "text": ""}
        self._visible_runs = set()  # Track visible run UIDs

    def getHeaderLabel(self) -> str:
        models = self.visible_models
        if len(models) == 0:
            return "No Runs Selected"
        elif len(models) == 1:
            run = models[0]
            return f"Run: {run.plan_name} ({run.scan_id})"
        else:
            return f"Multiple Runs Selected ({len(models)})"

    def update_available_keys(self) -> None:
        """Update available keys and maintain selection state."""
        # print("Updating available keys in PlotModel")
        runs = self.visible_models
        if not runs:
            if not self._retain_selection:
                self.available_keys = []
                # Clear selection if not retaining
                self.set_selected_keys([], [], [], force_update=False)
            return

        # Get intersection of keys from all models
        first_run = runs[0]
        available_keys = first_run.available_keys
        for run in runs:
            available_keys = [
                key for key in available_keys if key in run.available_keys
            ]

        # Update if changed
        if set(available_keys) != set(self.available_keys):
            self.available_keys = available_keys

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
                self.set_selected_keys(valid_x, valid_y, valid_norm)

            self.available_keys_changed.emit()
        # print(f"Available keys changed {self._available_keys}")

    def set_retain_selection(self, enabled: bool) -> None:
        """
        Set whether to retain the current key selection when runs change.

        Parameters
        ----------
        enabled : bool
            Whether to retain the current selection when runs change
        """
        self._retain_selection = enabled

    @property
    def available_runs(self):
        """Get list of all available CatalogRun objects."""
        return [model._run for model in self._run_models.values()]

    @property
    def available_models(self):
        """Get list of all available RunModels."""
        return list(self._run_models.values())

    @property
    def available_uids(self):
        """Get list of all available CatalogRun UIDs."""
        return list(self._run_models.keys())

    @property
    def auto_add(self) -> bool:
        """Whether auto-add is enabled."""
        return self._auto_add

    def set_auto_add(self, enabled: bool) -> None:
        """
        Set auto-add state and update plots if needed.

        Parameters
        ----------
        enabled : bool
            Whether to automatically add new selections
        """
        self._auto_add = enabled
        if enabled and (self._current_x_keys and self._current_y_keys):
            # If enabling auto_add with existing selection, update all plots
            self.selected_keys_changed.emit(
                self._current_x_keys, self._current_y_keys, self._current_norm_keys
            )

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

    @property
    def dynamic_update(self) -> bool:
        """Whether dynamic update is enabled."""
        return all(model.dynamic_update for model in self._run_models.values())

    def set_transform(self, transform_state: dict) -> None:
        """Set transform state and update all plots."""
        self._transform = (
            transform_state.copy()
        )  # Make a copy to prevent external modification

        # Update transform in all run models
        for model in self._run_models.values():
            model.set_transform(self._transform)

        # Force plot update
        # self.request_plot_update.emit()

    @property
    def transform(self) -> dict:
        """Current transform state with default values if not set."""
        default_state = {"enabled": False, "text": ""}
        # Merge current state with defaults
        return {**default_state, **self._transform}

    @property
    def selected_keys(self) -> tuple:
        """Get current key selection state."""
        return (
            self._current_x_keys.copy(),
            self._current_y_keys.copy(),
            self._current_norm_keys.copy(),
        )

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

    def set_selected_keys(
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
            model.set_selected_keys(x_keys, y_keys, norm_keys)

        # Notify views of selection change
        self.selected_keys_changed.emit(
            self._current_x_keys, self._current_y_keys, self._current_norm_keys
        )

        # Update plot if auto_add is enabled or force_update is True
        # if self._auto_add or force_update:
        #     print("PlotModel set_selection calling _update_plot")
        #     self.request_plot_update.emit()

    def get_selected_keys(self):
        """Get selected keys from all run models."""
        return self._current_x_keys, self._current_y_keys, self._current_norm_keys

    def _connect_run_model(self, run_model):
        """Connect signals from a RunModel."""
        run_model.available_keys_changed.connect(self.update_available_keys)

    def _disconnect_run_model(self, run_model):
        """Disconnect signals from a RunModel."""
        run_model.available_keys_changed.disconnect(self.update_available_keys)

    def add_runs(self, run_list):
        """
        Add a list of CatalogRun to the model and handle key selection.

        Parameters
        ----------
        run : CatalogRun
            Run to add to the model
        """
        uid_list = []
        for run in run_list:
            uid = run.uid
            uid_list.append(uid)
            if uid in self._run_models:
                continue

            # Create and connect new run model
            if not isinstance(run, RunModel):
                run_model = RunModel(run)
            else:
                run_model = run
            self._connect_run_model(run_model)
            self._run_models[uid] = run_model
            self.run_added.emit(run)

            # Update available keys first
        self.update_available_keys()

        if self._is_main_canvas or self._auto_add:
            self.set_uids_visible(uid_list, True)
        # Determine key selection
        if len(self._run_models) == 1 and not self._retain_selection:
            # First run, get default selection
            x_keys, y_keys, norm_keys = run.get_default_selection()
            self.set_selected_keys(x_keys, y_keys, norm_keys)
        else:
            # Apply current selection and transform to new run
            self.set_selected_keys(
                self._current_x_keys, self._current_y_keys, self._current_norm_keys
            )

        # Emit signals in correct order

        # Handle main canvas auto-selection

        # Force plot update and legend refresh
        self.available_runs_changed.emit(self.available_runs)
        # self.request_plot_update.emit()

    def add_run(self, run):
        """Add a single CatalogRun to the model."""
        self.add_runs([run])

    def remove_uids(self, uid_list):
        """
        Remove a list of runs from the model.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to remove from the model
        """
        for uid in uid_list:
            if uid in self._run_models:
                run_model = self._run_models.pop(uid)
                self._disconnect_run_model(run_model)
                run_model.cleanup()
                # Update plot and notify views
                self.run_removed.emit(run_model)

            if uid in self._visible_runs:
                self._visible_runs.remove(uid)

        # self._update_plot_from_selection()
        self.update_available_keys()
        self.visible_runs_changed.emit(self.visible_runs)
        self.available_runs_changed.emit(self.available_runs)
        # self.request_plot_update.emit()

    def remove_run(self, run):
        """Remove a single CatalogRun from the model via UID."""
        self.remove_uids([run.uid])

    def set_runs(self, run_list, canvas_id="main"):
        """Update the complete selection state.
        Takes a list of CatalogRun objects and updates the model to contain
        only these runs.
        """
        current_uids = {run.uid for run in run_list}
        existing_uids = set(self._run_models.keys())

        # Remove RunModels that are no longer in list
        uids_to_remove = list(existing_uids - current_uids)
        self.remove_uids(uids_to_remove)

        # Add new RunModels
        self.add_runs(run_list)
        # Clean up any inconsistent state
        self.cleanup_state()

    def set_uids_visible(self, uids, is_visible: bool):
        """
        Select specific runs for plotting.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to select
        """
        for uid in uids:
            if uid in self._run_models:
                if is_visible:
                    self._visible_runs.add(uid)
                else:
                    self._visible_runs.remove(uid)
                self._run_models[uid].set_visible(is_visible)

        self.update_available_keys()
        self.visible_runs_changed.emit(self.visible_runs)
        # self.request_plot_update.emit()

    def set_run_visible(self, run, is_visible):
        """
        Update run visibility.

        Parameters
        ----------
        run : CatalogRun
            Run to update visibility for
        is_visible : bool
            New visibility state
        """
        self.set_uids_visible([run.uid], is_visible)

    @property
    def visible_models(self):
        """
        Get currently selected RunModels.
        """
        return [
            model
            for model in self._run_models.values()
            if model.uid in self._visible_runs
        ]

    @property
    def visible_runs(self):
        if self._is_main_canvas:
            return set(self._run_models.keys())
        else:
            return self._visible_runs

    def cleanup_state(self):
        """Clean up any inconsistent state in the model."""
        # Remove any visible or selected runs that aren't in run_models
        valid_uids = set(self._run_models.keys())
        self._visible_runs.intersection_update(valid_uids)
