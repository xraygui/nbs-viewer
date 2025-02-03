from typing import List, Dict, Tuple
from qtpy.QtCore import QObject, Signal

from ...models.data.base import CatalogRun
from .runData import RunData
from .runModel import RunStateModel


class RunModelController(QObject):
    """Controls run data and selection state."""

    data_updated = Signal(object, object, dict)  # controller, data, metadata

    def __init__(self, run: CatalogRun, dynamic: bool = False):
        self._run = run
        self.run_data = RunData(run)
        self.state_model = RunStateModel(run, self.run_data)
        self._dynamic = dynamic

    def update_plot(self):
        """Emit data for current selection."""
        x_keys = self.state_model.selected_x
        y_keys = self.state_model.selected_y
        norm_keys = self.state_model.selected_norm

        for y_key in y_keys:
            x_data = self.run_data.get_data(x_keys[0]) if x_keys else None
            y_data = self.run_data.get_data(y_key)
            if norm_keys:
                norm_data = self.run_data.get_data(norm_keys[0])
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
        self.run_data.set_dynamic(enabled)

    def cleanup(self) -> None:
        """Clean up resources."""
        # Disconnect signals
        try:
            self.state_model.selection_changed.disconnect(self.update_plot)
        except (TypeError, RuntimeError):
            # Ignore if signal was not connected
            pass
