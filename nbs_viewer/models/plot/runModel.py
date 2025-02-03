from typing import List, Optional, Set
from qtpy.QtCore import QObject, Signal

from ..data.base import CatalogRun
from .runData import RunData
from .plotDataModel import PlotDataModel


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
    plot_data_changed = Signal(object)
    artist_needed = Signal(object)
    draw_requested = Signal()
    autoscale_requested = Signal()

    def __init__(self, run: CatalogRun, dynamic: bool = False):
        super().__init__()
        self._run = run
        self._run_data = RunData(run, dynamic)

        # Selection state
        self._available_keys: Set[str] = set()
        self._selected_x: List[str] = []
        self._selected_y: List[str] = []
        self._selected_norm: List[str] = []
        self._artists = {}

        # Initialize state
        self._initialize_keys()
        self._set_default_selection()

        # Connect to RunData signals
        self._run_data.data_changed.connect(self._on_data_changed)

    def _initialize_keys(self) -> None:
        """Initialize the list of available keys from the run."""
        # Get all keys from run
        xkeys, ykeys = self._run.getRunKeys()

        # Collect all keys from both dictionaries while preserving order
        all_keys = []
        for keys in xkeys.values():
            for key in keys:
                if key not in all_keys:
                    all_keys.append(key)
        for keys in ykeys.values():
            for key in keys:
                if key not in all_keys:
                    all_keys.append(key)

        self._available_keys = all_keys
        self.available_keys_changed.emit()

    def _set_default_selection(self) -> None:
        """Set default key selection based on run hints."""
        x_keys, y_keys, norm_keys = self._run.get_default_selection()
        self.set_selection(x_keys, y_keys, norm_keys)

    def _on_data_changed(self) -> None:
        """Handle data changes from RunData service."""
        self._initialize_keys()
        self.update_plot()

    def update_plot(self):
        """Emit data for current selection."""
        x_keys = self.selected_x
        y_keys = self.selected_y
        norm_keys = self.selected_norm
        print("Selected Keys")
        print(x_keys, y_keys, norm_keys)

        should_draw = False
        for existing_x, existing_y in self._artists.keys():
            if existing_x in x_keys and existing_y in y_keys:
                pass
            else:
                self._artists[(existing_x, existing_y)].set_visible(False)
                should_draw = True
        xdatalist, ydatalist, xkeylist = self._run_data.get_plot_data(
            x_keys, y_keys, norm_keys
        )
        for n, y_key in enumerate(y_keys):
            x_data = xdatalist[n]
            y_data = ydatalist[n]
            x_key = xkeylist[n][0]
            if x_data is not None and y_data is not None:
                should_draw = True
                artist = self._artists.get((x_key, y_key), None)
                if artist is not None:
                    artist.update_data(x_data, y_data)
                    artist.set_visible(True)
                else:
                    artist = PlotDataModel(x_data, y_data, x_key, y_key)
                    artist.artist_needed.connect(self.artist_needed)
                    artist.autoscale_requested.connect(self.autoscale_requested)
                    self._artists[(x_key, y_key)] = artist
                    artist.plot_data()

        if should_draw:
            self.draw_requested.emit()

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
        # Check if any selections have changed
        if (
            x_keys != self._selected_x
            or y_keys != self._selected_y
            or (norm_keys or []) != self._selected_norm
        ):

            self._selected_x = x_keys
            self._selected_y = y_keys
            self._selected_norm = norm_keys or []
            self.update_plot()
