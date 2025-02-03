from typing import List, Optional, Set
from qtpy.QtCore import QObject, Signal

from ..data.base import CatalogRun
from .runData import RunData


class RunModel(QObject):
    """
    Model for managing run data selection and filtering state.

    Manages available keys, key selection, and filtering options for a run.
    Uses RunData service for data access while maintaining its own selection
    state.

    Parameters
    ----------
    run : CatalogRun
        The run object providing the data
    run_data : RunData
        The RunData service for data access and transformation

    Signals
    -------
    available_keys_changed : Signal
        Emitted when the set of available keys changes
    selection_changed : Signal
        Emitted when the selected keys change
    """

    available_keys_changed = Signal()
    selection_changed = Signal()

    def __init__(self, run: CatalogRun, run_data: RunData):
        super().__init__()
        self._run = run
        self._run_data = run_data

        # Selection state
        self._available_keys: Set[str] = set()
        self._selected_x: List[str] = []
        self._selected_y: List[str] = []
        self._selected_norm: List[str] = []

        # Initialize state
        self._initialize_keys()
        self._set_default_selection()

        # Connect to RunData signals
        self._run_data.data_changed.connect(self._on_data_changed)

    def _initialize_keys(self) -> None:
        """Initialize the set of available keys from the run."""
        # Get all keys from run
        xkeys, ykeys = self._run.getRunKeys()

        # Collect all keys from both dictionaries
        all_keys = set()
        for keys in xkeys.values():
            all_keys.update(keys)
        for keys in ykeys.values():
            all_keys.update(keys)

        self._available_keys = all_keys
        self.available_keys_changed.emit()

    def _set_default_selection(self) -> None:
        """Set default key selection based on run hints."""
        x_keys, y_keys, norm_keys = self._run.get_default_selection()
        self.set_selection(x_keys, y_keys, norm_keys)

    def _on_data_changed(self) -> None:
        """Handle data changes from RunData service."""
        self._initialize_keys()

    def update_plot(self):
        """Emit data for current selection."""
        x_keys = self.selected_x
        y_keys = self.selected_y
        norm_keys = self.selected_norm

        for y_key in y_keys:
            x_data = self._run_data.get_data(x_keys[0]) if x_keys else None
            y_data = self._run_data.get_data(y_key)
            if norm_keys:
                norm_data = self._run_data.get_data(norm_keys[0])
                if norm_data is not None and y_data is not None:
                    y_data = y_data / norm_data

            if x_data is not None and y_data is not None:
                metadata = {"x_key": x_keys[0], "y_key": y_key, "run_id": self._run.uid}
                self.data_updated.emit(x_data, y_data, metadata)

    def set_dynamic(self, enabled: bool) -> None:
        """
        Enable/disable dynamic updates.

        Parameters
        ----------
        enabled : bool
            Whether to enable dynamic updates
        """
        self._dynamic = enabled
        self._run_data.set_dynamic(enabled)

    def cleanup(self) -> None:
        """Clean up resources."""
        # Disconnect signals
        try:
            self._run_data.data_changed.disconnect(self.update_plot)
        except (TypeError, RuntimeError):
            # Ignore if signal was not connected
            pass

    @property
    def available_keys(self) -> Set[str]:
        """Get the set of available keys."""
        return self._available_keys.copy()

    @property
    def selected_x(self) -> List[str]:
        """Get selected x-axis keys."""
        return self._selected_x.copy()

    @property
    def selected_y(self) -> List[str]:
        """Get selected y-axis keys."""
        return self._selected_y.copy()

    @property
    def selected_norm(self) -> List[str]:
        """Get selected normalization keys."""
        return self._selected_norm.copy()

    def set_selection(
        self,
        x_keys: List[str],
        y_keys: List[str],
        norm_keys: Optional[List[str]] = None,
    ) -> None:
        """
        Set the current key selection.

        Parameters
        ----------
        x_keys : List[str]
            Keys to select for x-axis
        y_keys : List[str]
            Keys to select for y-axis
        norm_keys : Optional[List[str]], optional
            Keys to select for normalization, by default None
        """
        self._selected_x = x_keys
        self._selected_y = y_keys
        self._selected_norm = norm_keys or []
        self.selection_changed.emit()
