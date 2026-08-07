"""Run list model managing run membership, visibility, and available keys."""

from typing import List, Optional, Union, Set
from nbs_viewer.models.catalog.base import CatalogRun
from qtpy.QtCore import Signal, Qt
from qtpy.QtGui import QStandardItemModel, QStandardItem
from .runModel import RunModel
from .combinedRunModel import CombinedRunModel, CombinationMethod, CombineError
from .frozenRunModel import FrozenRunModel
from nbs_viewer.utils import print_debug


class RunListModel(QStandardItemModel):
    """
    Model for run membership, visibility, and the available key universe.

    Plot-session state (selected keys, transform, retain-selection, plot-data
    maps, cube/crop) lives on :class:`PlotModel`. Auto-add here only controls
    whether newly added runs become visible.
    """

    available_keys_changed = Signal()
    frozen_spectra_changed = Signal()
    run_added = Signal(object)
    run_removed = Signal(object)
    available_runs_changed = Signal(list)
    visible_runs_changed = Signal(set)
    add_runs_to_display = Signal(list, str)

    def __init__(self, is_main_display=False, single_selection_mode=False):
        """
        Initialize the run list model.

        Parameters
        ----------
        is_main_display : bool
            If True, all runs are automatically selected
        single_selection_mode : bool
            If True, only one run can be visible at a time (radio button behavior)
        """
        super().__init__()
        self._run_models = {}  # run_uid -> RunModel
        self._is_main_display = is_main_display
        self._single_selection_mode = single_selection_mode

        self.available_keys = list()
        self._auto_add = True
        self._visible_runs = set()

        self.run_added.connect(self._on_run_added)
        self.run_removed.connect(self._on_run_removed)
        self.visible_runs_changed.connect(self._on_visible_runs_changed)
        self.itemChanged.connect(self._on_item_changed)

        self._initialize_runs()

    def _initialize_runs(self):
        """Initialize the model with current runs from run_list_model."""
        self.clear()

        for run in self.available_runs:
            self._add_run_item(run)

    def _add_run_item(self, run: RunModel):
        """Add a run as a QStandardItem to the model."""
        item = QStandardItem(run.display_name)
        item.setData(run.uid, Qt.UserRole)
        item.setData(run, Qt.UserRole + 1)  # Store run object
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        item.setCheckState(
            Qt.Checked if run.uid in self._visible_runs else Qt.Unchecked
        )
        self.appendRow(item)

    def _on_run_added(self, run: RunModel):
        """Handle new run added to model."""
        self._add_run_item(run)

    def _on_run_removed(self, run: RunModel):
        """Handle run removed from model."""
        for row in range(self.rowCount()):
            item = self.item(row)
            if item.data(Qt.UserRole) == run.uid:
                self.removeRow(row)
                break

    def _on_visible_runs_changed(self, visible_runs):
        """Handle visible runs changed in model."""
        # Update checkbox states for all items
        for row in range(self.rowCount()):
            item = self.item(row)
            uid = item.data(Qt.UserRole)
            item.setCheckState(
                Qt.Checked if uid in self._visible_runs else Qt.Unchecked
            )

    def get_run_at_index(self, index):
        """
        Get the run object at the given index.

        Parameters
        ----------
        index : QModelIndex
            The model index

        Returns
        -------
        RunModel or None
            The run object or None if invalid index
        """
        if not index.isValid():
            return None
        item = self.itemFromIndex(index)
        if item:
            return item.data(Qt.UserRole + 1)
        return None

    def get_uid_at_index(self, index):
        """
        Get the UID at the given index.

        Parameters
        ----------
        index : QModelIndex
            The model index

        Returns
        -------
        str or None
            The UID or None if invalid index
        """
        if not index.isValid():
            return None
        item = self.itemFromIndex(index)
        if item:
            return item.data(Qt.UserRole)
        return None

    def find_index_by_uid(self, uid):
        """
        Find the model index for a given UID.

        Parameters
        ----------
        uid : str
            The UID to search for

        Returns
        -------
        QModelIndex
            The model index or invalid index if not found
        """
        for row in range(self.rowCount()):
            item = self.item(row)
            if item.data(Qt.UserRole) == uid:
                return self.indexFromItem(item)
        return self.index(-1, -1)  # Invalid index

    def get_first_run(self):
        index = self.index(0, 0)
        if not index.isValid():
            return None
        return self.get_run_at_index(index)

    def get_siblings_of_run(self, run):
        index = self.find_index_by_uid(run.uid)
        if not index.isValid():
            return [None, None]
        siblings = []
        for offset in [-1, 1]:
            sibling_index = index.sibling(index.row() + offset, index.column())
            if sibling_index.isValid():
                sibling = self.get_run_at_index(sibling_index)
                if sibling:
                    siblings.append(sibling)
                else:
                    siblings.append(None)
            else:
                siblings.append(None)
        return siblings

    def _on_item_changed(self, item):
        """Handle checkbox state changes."""
        uid = item.data(Qt.UserRole)
        if uid:
            is_visible = item.checkState() == Qt.Checked
            self.set_uids_visible([uid], is_visible)

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
        """
        Update the intersection of catalog keys among visible runs.
        """
        runs = self.visible_models
        if not runs:
            if self.available_keys:
                self.available_keys = []
                self.available_keys_changed.emit()
            return

        first_run = runs[0]
        print_debug(
            "RunListModel.update_available_keys",
            f"available_keys from first_run.uid {first_run.uid}: {first_run.available_keys}",
            "run",
        )
        available_keys = first_run.catalog_keys
        for run in runs:
            available_keys = [
                key for key in available_keys if key in run.catalog_keys
            ]

        if set(available_keys) != set(self.available_keys):
            self.available_keys = available_keys
            self.available_keys_changed.emit()

    @property
    def available_runs(self) -> List[CatalogRun]:
        """Get list of all available CatalogRun objects."""
        return [model._run for model in self._run_models.values()]

    @property
    def available_models(self) -> List[RunModel]:
        """Get list of all available RunModels."""
        return list(self._run_models.values())

    @property
    def available_uids(self):
        """Get list of all available CatalogRun UIDs."""
        return list(self._run_models.keys())

    @property
    def auto_add(self) -> bool:
        """Whether newly added runs are automatically made visible."""
        return self._auto_add

    def set_auto_add(self, enabled: bool) -> None:
        """
        Set whether newly added runs become visible automatically.

        Parameters
        ----------
        enabled : bool
            When True, new runs are checked/visible on add.
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
        for model in self._run_models.values():
            model.set_dynamic(enabled)

    @property
    def dynamic_update(self) -> bool:
        """Whether dynamic update is enabled."""
        return all(model.dynamic_update for model in self._run_models.values())

    def synthetic_display_entries(self):
        """
        Return frozen stack spectra for visible runs.

        Returns
        -------
        list of tuple
            ``(run_model, key, display_label)`` entries for Run Display.
        """
        entries = []
        runs = self.visible_models
        multi = len(runs) > 1
        for run_model in runs:
            for entry in run_model.frozen_spectra():
                if entry.kind != "stack_spectrum":
                    continue
                label = entry.label
                if multi:
                    label = f"{run_model.scan_id} · {label}"
                entries.append((run_model, entry.key, label))
        return entries

    def _connect_run_model(self, run_model: RunModel):
        """Connect signals from a RunModel."""
        run_model.available_keys_changed.connect(self.update_available_keys)
        run_model.frozen_spectra_changed.connect(self._on_frozen_spectra_changed)

    def _disconnect_run_model(self, run_model: RunModel):
        """Disconnect signals from a RunModel."""
        run_model.available_keys_changed.disconnect(self.update_available_keys)
        run_model.frozen_spectra_changed.disconnect(
            self._on_frozen_spectra_changed
        )

    def _on_frozen_spectra_changed(self):
        self.frozen_spectra_changed.emit()

    def add_runs(self, run_list: Union[List[CatalogRun], List[RunModel]]):
        """
        Add CatalogRun or RunModel instances to the list.

        Parameters
        ----------
        run_list : list of CatalogRun or RunModel
            Runs to add.
        """
        print_debug("RunListModel.add_runs", f"Adding {len(run_list)} runs", "run")
        run_list = sorted(run_list, key=lambda x: x.scan_id)
        uid_list = []
        for run in run_list:
            uid = run.uid
            uid_list.append(uid)
            if uid in self._run_models:
                print_debug(
                    "RunListModel.add_runs", f"Run {uid} already in model", "run"
                )
                continue

            if not isinstance(run, RunModel):
                run_model = RunModel(run)
            else:
                run_model = run
            self._connect_run_model(run_model)
            self._run_models[uid] = run_model
            self.run_added.emit(run_model)

        self.update_available_keys()

        if self._is_main_display or self._auto_add:
            self.set_uids_visible(uid_list, True)

        self.available_runs_changed.emit(self.available_runs)

    def add_run(self, run: Union[CatalogRun, RunModel]):
        """Add a single CatalogRun to the model."""
        self.add_runs([run])

    def validate_combine(self, runs: List[RunModel]) -> None:
        """
        Check whether runs can be combined.

        Parameters
        ----------
        runs : list of RunModel
            Candidate source runs.

        Raises
        ------
        CombineError
            If fewer than two runs are given, they share no keys, shapes
            disagree, or shape data cannot be read.
        """
        if len(runs) < 2:
            raise CombineError("Please select at least 2 runs to combine")

        try:
            common_keys = set(runs[0].available_keys)
            for run in runs[1:]:
                common_keys &= set(run.available_keys)

            if not common_keys:
                raise CombineError(
                    "Selected runs have no common data keys. Cannot combine "
                    "runs with completely different data structures."
                )

            preferred_keys = ["time"]
            test_key = None
            for key in preferred_keys:
                if key in common_keys:
                    test_key = key
                    break
            if test_key is None:
                test_key = list(common_keys)[0]

            shapes = []
            for run in runs:
                try:
                    shapes.append(run.get_shape(test_key))
                except Exception:
                    raise CombineError(
                        f"Could not access data for key '{test_key}' in one "
                        "or more runs."
                    ) from None

            if len(set(shapes)) > 1:
                raise CombineError(
                    f"Selected runs have different data shapes for key "
                    f"'{test_key}': {shapes}. All runs must have the same "
                    "data dimensions to be combined."
                )
        except CombineError:
            raise
        except Exception as e:
            raise CombineError(
                f"Error checking run compatibility: {str(e)}"
            ) from e

    def combine_runs(
        self,
        runs: List[RunModel],
        method: CombinationMethod = CombinationMethod.AVERAGE,
        expression: Optional[str] = None,
    ) -> CombinedRunModel:
        """
        Construct a CombinedRunModel from runs and add it to this list.

        Parameters
        ----------
        runs : list of RunModel
            Source runs to combine.
        method : CombinationMethod, optional
            Combination method, by default AVERAGE.
        expression : str, optional
            Expression used when method is EXPRESSION.

        Returns
        -------
        CombinedRunModel
            The combined run that was added.

        Raises
        ------
        CombineError
            If the runs fail ``validate_combine``.
        """
        self.validate_combine(runs)
        combined = CombinedRunModel(
            runs=runs, method=method, expression=expression
        )
        self.add_run(combined)
        return combined

    def freeze_runs(self, runs: List[RunModel]) -> List[FrozenRunModel]:
        """
        Create FrozenRunModel entries for each selected Y key on each run.

        Parameters
        ----------
        runs : list of RunModel
            Runs whose currently selected Y keys should be frozen.

        Returns
        -------
        list of FrozenRunModel
            Frozen runs that were added to this list.
        """
        to_freeze = []
        for model in runs:
            _, y_keys, _ = model.get_selected_keys()
            for key in list(y_keys):
                to_freeze.append((model.run, key))

        frozen_runs = [
            FrozenRunModel(catalog_run, key) for catalog_run, key in to_freeze
        ]
        if frozen_runs:
            self.add_runs(frozen_runs)
        return frozen_runs

    def remove_uids(self, uid_list):
        """
        Remove a list of runs from the model.

        Parameters
        ----------
        run_list : List[CatalogRun]
            Runs to remove from the model
        """
        print_debug(
            "RunListModel.remove_uids",
            f"Removing uids {uid_list}",
            category="runlist",
        )
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

    def remove_run(self, run: Union[CatalogRun, RunModel]):
        """Remove a single CatalogRun from the model via UID."""
        self.remove_uids([run.uid])

    def set_runs(self, run_list, display_id="main"):
        """Update the complete selection state.
        Takes a list of CatalogRun objects and updates the model to contain
        only these runs.
        """
        print_debug("RunListModel.set_runs", f"Setting runs {len(run_list)}", "run")
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
        uids : List[str]
            List of UIDs to set visibility for
        is_visible : bool
            Whether to make the runs visible
        """
        print_debug(
            "RunListModel.set_uids_visible",
            f"Setting uids {uids} to {is_visible}",
            category="runlist",
        )
        if self._single_selection_mode and is_visible and uids:
            # In single-selection mode, only the first UID should be visible
            # Set all runs to not visible first
            all_uids = list(self._run_models.keys())
            for uid in all_uids:
                if uid in self._visible_runs:
                    self._visible_runs.remove(uid)
                self._run_models[uid].set_visible(False)

            # Then set only the first UID to visible
            first_uid = uids[0]
            if first_uid in self._run_models:
                self._visible_runs.add(first_uid)
                self._run_models[first_uid].set_visible(True)
        else:
            # Normal behavior
            for uid in uids:
                if uid in self._run_models:
                    if is_visible:
                        self._visible_runs.add(uid)
                    elif uid in self._visible_runs:
                        self._visible_runs.remove(uid)
                    self._run_models[uid].set_visible(is_visible)

        self.update_available_keys()
        self.visible_runs_changed.emit(self.visible_runs)
        print_debug(
            "RunListModel.set_uids_visible",
            f"visible_runs_changed uids={uids} visible={is_visible}",
            category="plots",
        )

    def set_run_visible(self, run: Union[CatalogRun, RunModel], is_visible: bool):
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
    def visible_models(self) -> List[RunModel]:
        """
        Get currently selected RunModels.
        """
        return [
            model
            for model in self._run_models.values()
            if model.uid in self._visible_runs
        ]

    @property
    def visible_runs(self) -> Set[str]:
        """Get visible run UIDs"""
        if self._is_main_display:
            return set(self._run_models.keys())
        else:
            return self._visible_runs

    def cleanup_state(self):
        """Clean up any inconsistent state in the model."""
        # Remove any visible or selected runs that aren't in run_models
        valid_uids = set(self._run_models.keys())
        self._visible_runs.intersection_update(valid_uids)
