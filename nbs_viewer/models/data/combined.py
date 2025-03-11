from enum import Enum
from typing import List, Optional, Dict, Any, Tuple
import uuid
import numpy as np

from .base import CatalogRun


class CombinationMethod(Enum):
    """Methods for combining multiple runs."""

    AVERAGE = "average"
    SUM = "sum"
    SUBTRACT = "subtract"  # First run - others
    DIVIDE = "divide"  # First run / others


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


class CombinedRun(CatalogRun):
    """
    Represents multiple runs combined into a single virtual run.

    Parameters
    ----------
    runs : List[CatalogRun]
        List of runs to combine
    method : CombinationMethod, optional
        Method to use for combining runs, by default AVERAGE
    """

    def __init__(
        self,
        runs: List[CatalogRun],
        method: CombinationMethod = CombinationMethod.AVERAGE,
        parent=None,
    ):
        # Generate a unique ID for this combined run
        uid = str(uuid.uuid4())
        # Use first run's metadata for display but with our generated uid
        first_run = runs[0] if runs else None
        super().__init__(first_run, uid, parent=parent)
        self._source_runs = runs
        self._method = method

        # Initialize available keys as intersection of all source runs
        self._available_keys = self._compute_common_keys()

        # Connect to source run signals
        scan_ids = []
        for run in self._source_runs:
            run.data_changed.connect(self.data_changed)
            run.transform_changed.connect(self.transform_changed)
            scan_ids.append(run.scan_id)

        # Set metadata from first run
        if first_run:
            self.metadata = {
                "source_runs": [run.uid for run in runs],
                "combination_method": method.value,
                **first_run.metadata,
            }
        else:
            self.metadata = {"source_runs": [], "combination_method": method.value}
        self.scan_id = make_scan_id(scan_ids)
        self.plan_name = f"{len(scan_ids)} Combined"
        self.start = self._source_runs[0].start

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

    def get_dims(
        self, ykey: str, xkeys: List[str]
    ) -> Tuple[Tuple[str, ...], Dict[str, Tuple[str, ...]]]:
        """Get dimensions of a given key."""
        return self._source_runs[0].get_dims(ykey, xkeys)

    def getData(self, key: str, slice_info=None) -> np.ndarray:
        """
        Get combined data for a given key.

        Parameters
        ----------
        key : str
            The key to get data for

        Returns
        -------
        np.ndarray
            The combined data for the given key
        """
        data_list = [run.getData(key, slice_info) for run in self._source_runs]
        if not data_list:
            return np.array([])

        # Stack and combine
        data_stack = np.stack(data_list)
        if self._method == CombinationMethod.AVERAGE:
            return np.mean(data_stack, axis=0)
        elif self._method == CombinationMethod.SUM:
            return np.sum(data_stack, axis=0)
        elif self._method == CombinationMethod.SUBTRACT:
            return data_stack[0] - np.sum(data_stack[1:], axis=0)
        elif self._method == CombinationMethod.DIVIDE:
            return data_stack[0] / np.prod(data_stack[1:], axis=0)

    def getShape(self, key: str) -> Tuple[int, ...]:
        """Get shape from first run (shapes must match for combining)."""
        if self._source_runs:
            return self._source_runs[0].getShape(key)
        return tuple()

    def getRunKeys(self) -> Tuple[Dict[int, List[str]], Dict[int, List[str]]]:
        """Use first run's key organization."""
        if self._source_runs:
            return self._source_runs[0].getRunKeys()
        return {}, {}

    def get_plot_data(
        self, x_keys, y_keys, norm_keys=None, slice_info=None
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
            return [], [], []

        # Collect normalized data from all runs
        run_data = []
        for run in self._source_runs:
            try:
                x_data, y_data, x_key_list = run.get_plot_data(
                    x_keys, y_keys, norm_keys, slice_info
                )
                if y_data:  # Only add if we got y data
                    run_data.append((x_data, y_data))
            except Exception as e:
                print(f"Error getting plot data from run {run.uid}: {str(e)}")
                continue

        if not run_data:  # If no valid data collected
            return [], [], x_key_list

        # Combine according to method
        return self._combine_data(run_data, x_key_list)

    def _combine_data(self, run_data, x_keys):
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
            return [], [], x_keys

        # Separate x and y data
        x_lists, y_lists = zip(*run_data)

        # For now, use x data from first run
        x_data = x_lists[0]

        # Filter out empty y_lists
        y_lists = [yl for yl in y_lists if len(yl) > 0]
        if not y_lists:
            return x_data, [], x_keys

        # Verify all remaining y_lists have same length
        y_lengths = [len(y_list) for y_list in y_lists]
        if not all(length == y_lengths[0] for length in y_lengths):
            print(f"Warning: Inconsistent y_list lengths: {y_lengths}")
            return x_data, [], x_keys

        # Stack y data for combining
        combined_y_data = []
        try:
            for y_idx in range(y_lengths[0]):
                try:
                    y_stack = np.stack([y_list[y_idx] for y_list in y_lists])

                    # Apply combination method
                    if self._method == CombinationMethod.AVERAGE:
                        y_combined = np.mean(y_stack, axis=0)
                    elif self._method == CombinationMethod.SUM:
                        y_combined = np.sum(y_stack, axis=0)
                    elif self._method == CombinationMethod.SUBTRACT:
                        y_combined = y_stack[0] - np.sum(y_stack[1:], axis=0)
                    elif self._method == CombinationMethod.DIVIDE:
                        y_combined = y_stack[0] / np.prod(y_stack[1:], axis=0)

                    combined_y_data.append(y_combined)
                except Exception as e:
                    print(f"Error combining y data at index {y_idx}")
                    print(f"y_lists structure: {[len(yl) for yl in y_lists]}")
                    continue  # Skip this y data on error

        except Exception as e:
            print("Error in _combine_data:")
            print(f"x_lists shape: {[x.shape for x in x_lists]}")
            print(f"y_lists structure: {[len(yl) for yl in y_lists]}")
            return x_data, [], x_keys

        return x_data, combined_y_data, x_keys

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
    def source_runs(self) -> List[CatalogRun]:
        """Get list of source runs being combined."""
        return self._source_runs.copy()

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

    def cleanup(self):
        """Clean up signal connections."""
        for run in self._source_runs:
            run.data_changed.disconnect(self.data_changed)
            run.transform_changed.disconnect(self.transform_changed)
        super().cleanup()

    @property
    def uid(self) -> str:
        """Get unique identifier for this combined run."""
        return self._key  # This is set by CatalogRun.__init__
