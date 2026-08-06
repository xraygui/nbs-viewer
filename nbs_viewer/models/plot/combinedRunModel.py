from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
import numpy as np
import uuid
from ..data.base import CatalogRun
from .runModel import RunModel
from asteval import Interpreter


class CombinationMethod(Enum):
    """Methods for combining multiple runs."""

    AVERAGE = "average"
    SUM = "sum"
    EXPRESSION = "expression"


class CombineError(Exception):
    """Raised when runs cannot be combined."""


def make_scan_id(scan_ids: List[int]) -> str:
    """
    Make a scan ID from a list of scan IDs.

    Parameters
    ----------
    scan_ids : List[int]
        List of scan IDs to combine

    Returns
    -------
    str
        Combined scan ID string, truncated if more than 3 IDs
    """
    sorted_ids = sorted(scan_ids)
    if len(sorted_ids) <= 3:
        return ", ".join(map(str, sorted_ids))
    else:
        return f"{sorted_ids[0]}...{sorted_ids[-1]}"


class CombinedRunModel(RunModel):
    """
    Represents multiple runs combined into a single virtual run.

    Parameters
    ----------
    runs : List[RunModel]
        List of runs to combine
    method : CombinationMethod, optional
        Method to use for combining runs, by default AVERAGE
    """

    def __init__(
        self,
        runs: List[RunModel],
        method: CombinationMethod = CombinationMethod.AVERAGE,
        expression: str = None,
    ):
        first_run = runs[0] if runs else None

        # Use first run's metadata for display but with our generated uid
        self._source_runs = runs
        self._method = method
        self._expression = expression

        scan_ids = []
        for run in self._source_runs:
            run.data_changed.connect(self._on_data_changed)
            scan_ids.append(run.scan_id)

        # Set metadata from first run
        self._metadata = {
            "source_runs": [run.uid for run in runs],
            "combination_method": method.value,
        }
        if method == CombinationMethod.EXPRESSION:
            self._metadata["expression"] = expression
        for run in runs:
            self._metadata[f"Run {run.scan_id}"] = {}
            self._metadata[f"Run {run.scan_id}"].update(run.metadata)
        self._scan_id = make_scan_id(scan_ids)
        self._plan_name = f"{len(scan_ids)} Combined"
        self._start = self._source_runs[0].run.start
        self._uid = str(uuid.uuid4())

        super().__init__(first_run.run)

    def _connect_run(self):
        for run in self._source_runs:
            run.data_changed.connect(self._on_data_changed)

    def _disconnect_run(self):
        """Disconnect RunData signals."""
        for run in self._source_runs:
            run.data_changed.disconnect(self._on_data_changed)

    @property
    def run(self) -> CatalogRun:
        return self._source_runs[0].run

    @property
    def metadata(self):
        return self._metadata

    @property
    def uid(self) -> str:
        """Get unique identifier for this combined run."""
        return self._uid  # This is set by CatalogRun.__init__

    @property
    def scan_id(self) -> str:
        """Get the scan ID for the run."""
        return self._scan_id

    @property
    def plan_name(self) -> str:
        """Get the plan name for the run."""
        return self._plan_name

    def _update_available_keys(self) -> None:
        """Update internal available keys from source runs."""
        new_keys = self._compute_common_keys()
        if set(new_keys) != set(self._catalog_keys):
            self._catalog_keys = new_keys
            self.available_keys_changed.emit()

    def _compute_common_keys(self) -> List[str]:
        """Find keys common to all source runs."""
        if not self._source_runs:
            return []

        # Start with keys from first run
        common_keys = set(self._source_runs[0].available_keys)

        # Intersect with keys from other runs
        for run in self._source_runs[1:]:
            common_keys &= set(run.available_keys)

        return sorted(list(common_keys))

    def get_plot_data(
        self, xkeys, ykey, norm_keys=None, slice_info=None
    ) -> Tuple[List[np.ndarray], List[np.ndarray], List[str]]:
        """
        Get combined plot data from source runs.

        Parameters
        ----------
        x_keys : List[str]
            Keys for x-axis data
        y_keys : List[str]
            Keys for y-axis data
        norm_keys : List[str], optional
            Keys for normalization, by default None

        Returns
        -------
        Tuple[List[np.ndarray], List[np.ndarray], List[str]]
            Combined (x_data, y_data, x_keys)
        """
        if not self._source_runs:
            return [], []

        # Collect normalized data from all runs
        run_data = []
        for run in self._source_runs:
            try:
                xlist, y = run.get_plot_data(
                    xkeys, ykey, norm_keys, slice_info, transform=False
                )
                run_data.append((xlist, y))
            except Exception as e:
                print(f"Error getting plot data from run {run.uid}: {str(e)}")
                continue

        if not run_data:  # If no valid data collected
            return [], []

        # Combine according to method
        xcomb, ycomb = self._combine_data(run_data)
        x, y = self.transform_data(xcomb, ycomb)
        return x, y

    def _combine_data(self, run_data):
        """
        Combine data according to selected method.

        Parameters
        ----------
        run_data : List[Tuple[List[np.ndarray], List[np.ndarray]]]
            List of (x_data, y_data) tuples from each run
        x_keys : List[str]
            Keys for x-axis data

        Returns
        -------
        Tuple[List[np.ndarray], List[np.ndarray], List[str]]
            Combined (x_data, y_data, x_keys)
        """
        if not run_data:
            return [], []

        # Separate x and y data
        x_lists, y_lists = zip(*run_data)

        # For now, use x data from first run
        x_data = x_lists[0]

        # Verify all remaining y_lists have same length
        y_shapes = [y.shape for y in y_lists]
        if not all(shape == y_shapes[0] for shape in y_shapes):
            print(f"Warning: Inconsistent y shapes: {y_shapes}")
            return x_data, []

        # Stack y data for combining
        if self._method == CombinationMethod.EXPRESSION:
            combinator = Interpreter()
            combinator.symtable["runlist"] = y_lists
            y_combined = combinator(self._expression)
        else:
            try:
                y_stack = np.stack(y_lists)
                # Apply combination method
                if self._method == CombinationMethod.AVERAGE:
                    y_combined = np.mean(y_stack, axis=0)
                elif self._method == CombinationMethod.SUM:
                    y_combined = np.sum(y_stack, axis=0)
            except Exception as e:
                print(f"Error in _combine_data: {e}")
                print(f"x_lists shape: {[x.shape for x in x_lists]}")
                print(f"y_lists structure: {[len(yl) for yl in y_lists]}")
                return x_data, []

        return x_data, y_combined

    @property
    def display_name(self) -> str:
        """Get descriptive name for the combined run."""
        method_str = self._method.value.capitalize()
        n_runs = len(self._source_runs)
        return f"{method_str} of {n_runs} runs"

    @property
    def combination_method(self) -> CombinationMethod:
        """Get current combination method."""
        return self._method

    @property
    def source_runs(self) -> List[RunModel]:
        """Get list of source runs being combined."""
        return self._source_runs.copy()

    def set_dynamic(self, enabled: bool) -> None:
        """
        Enable/disable dynamic updates.

        Parameters
        ----------
        enabled : bool
            Whether to enable dynamic updates
        """
        pass  # TODO: Implement, no concept of dynamic updates for combined runs

    def set_combination_method(self, method: CombinationMethod):
        """
        Change the combination method.

        Parameters
        ----------
        method : CombinationMethod
            New method to use for combining runs
        """
        if method != self._method:
            self._method = method
            self.data_changed.emit()
