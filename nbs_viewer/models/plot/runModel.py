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
    visibility_changed = Signal(object, bool)  # (artist, is_visible)

    def __init__(self, run_data: RunData):
        super().__init__()
        self._run_data = run_data

        # Selection state
        self._selected_x: List[str] = []
        self._selected_y: List[str] = []
        self._selected_norm: List[str] = []
        self._artists = {}

        # Initialize state
        self._set_default_selection()

        # Connect to RunData signals
        self._run_data.data_changed.connect(self._on_data_changed)

    @property
    def run(self) -> CatalogRun:
        """Get the underlying run object."""
        return self._run_data.run

    @property
    def available_keys(self) -> Set[str]:
        """Get the set of available keys."""
        return self._run_data.available_keys

    def _set_default_selection(self) -> None:
        """Set default key selection based on run hints."""
        x_keys, y_keys, norm_keys = self.run.get_default_selection()
        self.set_selection(x_keys, y_keys, norm_keys)

    def _on_data_changed(self) -> None:
        """Handle data changes from RunData service."""
        self.available_keys_changed.emit()
        self.update_plot()

    def update_plot(self):
        """Emit data for current selection."""
        x_keys = self.selected_x
        y_keys = self.selected_y
        norm_keys = self.selected_norm
        # print("Selected Keys")
        # print(x_keys, y_keys, norm_keys)

        should_draw = False
        for existing_x, existing_y in self._artists.keys():
            if existing_x in x_keys and existing_y in y_keys:
                pass
            else:
                self._artists[(existing_x, existing_y)].set_visible(False)
                should_draw = True

        if not x_keys or not y_keys:
            return

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
                    # Create label with y_key and scan_id
                    label = f"{y_key}.{self.run.scan_id}"
                    artist = PlotDataModel(x_data, y_data, x_key, label)
                    artist.artist_needed.connect(self.artist_needed)
                    artist.autoscale_requested.connect(self.autoscale_requested)
                    artist.draw_requested.connect(self.draw_requested)
                    artist.visibility_changed.connect(self.visibility_changed)
                    self._artists[(x_key, y_key)] = artist
                    artist.plot_data()

        if should_draw:
            self.draw_requested.emit()

    def set_transform(self, transform_state) -> None:
        """
        Set the transformation expression.

        Parameters
        ----------
        transform_state : dict
            Python expression for data transformation
        """
        self._run_data.set_transform(transform_state)

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

    def cleanup(self):
        """Clean up resources and remove all artists."""
        # Clean up all artists
        for artist in self._artists.values():
            artist.clear()
            try:
                artist.artist_needed.disconnect(self.artist_needed)
                artist.autoscale_requested.disconnect(self.autoscale_requested)
                artist.draw_requested.disconnect(self.draw_requested)
                artist.visibility_changed.disconnect(self.visibility_changed)
            except (TypeError, RuntimeError):
                pass

        self._artists.clear()

        # Disconnect RunData signals
        try:
            self._run_data.data_changed.disconnect(self._on_data_changed)
        except (TypeError, RuntimeError):
            pass

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
        force_update: bool = False,
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

            self._selected_x = [key for key in x_keys if key in self.available_keys]
            self._selected_y = [key for key in y_keys if key in self.available_keys]
            self._selected_norm = [
                key for key in norm_keys if key in self.available_keys
            ]
            if force_update:
                self.update_plot()
