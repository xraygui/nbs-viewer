from typing import List
from qtpy.QtCore import QObject, Signal

from ...models.data.base import CatalogRun
from .run_data import RunData
from .run_line_model import RunLineModel
from .run_state_model import RunStateModel


class RunModelController(QObject):
    """
    Controller for managing run data and plot state.

    Coordinates between RunData service and RunStateModel to manage data
    selection and plotting.

    Parameters
    ----------
    run : CatalogRun
        The run to control
    dynamic : bool, optional
        Whether to update dynamically, by default False

    Signals
    -------
    data_updated : Signal
        Emitted when data needs to be plotted with (x_data, y_data, style_dict)
    line_removed : Signal
        Emitted when a line should be removed from plot with line_id
    """

    data_updated = Signal(object, object, dict)  # x_data, y_data, style_dict
    line_removed = Signal(str)  # line_id

    def __init__(self, run: CatalogRun, dynamic: bool = False):
        super().__init__()
        self._run = run
        self._run_data = RunData(run)
        self._state_model = RunStateModel(run, self._run_data)
        self._line_models: List[RunLineModel] = []
        self._dynamic = dynamic

        # Connect state model signals
        self._state_model.selection_changed.connect(self.update_plot)

    @property
    def run_data(self) -> RunData:
        """Get the run data service."""
        return self._run_data

    @property
    def state_model(self) -> RunStateModel:
        """Get the state model."""
        return self._state_model

    def update_plot(self) -> None:
        """Update plot with current selection."""
        # Get current selection
        x_keys = self._state_model.selected_x
        y_keys = self._state_model.selected_y
        norm_keys = self._state_model.selected_norm

        # Remove old lines
        for model in self._line_models:
            self.line_removed.emit(model.line_id)
        self._line_models.clear()

        # Create new line models for each y key
        for y_key in y_keys:
            # Get data
            x_data = self._run_data.get_data(x_keys[0]) if x_keys else None
            y_data = self._run_data.get_data(y_key)
            if norm_keys:
                norm_data = self._run_data.get_data(norm_keys[0])
                if norm_data is not None and y_data is not None:
                    y_data = y_data / norm_data

            # Create line model and emit data
            if x_data is not None and y_data is not None:
                line_model = RunLineModel(self._run, self._run_data)
                line_model.set_data(x_data, y_data)
                self._line_models.append(line_model)

                # Get style for this line
                style = line_model.get_key_style(y_key)

                # Emit data with style
                self.data_updated.emit(x_data, y_data, style)

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
            self._state_model.selection_changed.disconnect(self.update_plot)
        except (TypeError, RuntimeError):
            # Ignore if signal was not connected
            pass

        # Remove all lines
        for model in self._line_models:
            self.line_removed.emit(model.line_id)
        self._line_models.clear()
