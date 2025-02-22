from typing import List, Optional, Set
from qtpy.QtCore import QObject, Signal

from ..data.base import CatalogRun
from .plotDataModel import PlotDataModel


class RunModel(QObject):
    """
    Model for managing run data selection and filtering state.

    Manages available keys, key selection, and filtering options for a run.

    Parameters
    ----------
    run : CatalogRun
        The run to manage state for
    """

    available_keys_changed = Signal()
    plot_data_changed = Signal(object)
    artist_needed = Signal(object)
    draw_requested = Signal()
    autoscale_requested = Signal()
    visibility_changed = Signal(object, bool)  # (artist, is_visible)

    def __init__(self, run: CatalogRun):
        super().__init__()
        self._run = run

        # Selection state
        self._selected_x: List[str] = []
        self._selected_y: List[str] = []
        self._selected_norm: List[str] = []
        self._artists = {}
        self._is_visible = True  # Track overall visibility state
        self._available_keys = set()  # Track our own copy of available keys

        # Initialize state
        self._update_available_keys()  # Initial key setup
        self._set_default_selection()

        # Connect to run signals
        self._run.data_changed.connect(self._on_data_changed)

    @property
    def run(self) -> CatalogRun:
        """Get the underlying run object."""
        return self._run

    @property
    def available_keys(self) -> Set[str]:
        """Get the set of available keys."""
        return self._available_keys

    def _update_available_keys(self) -> None:
        """Update internal available keys from run."""
        new_keys = set(self._run.available_keys)
        if new_keys != self._available_keys:
            self._available_keys = new_keys
            self.available_keys_changed.emit()

    def _set_default_selection(self) -> None:
        """Set default key selection based on run hints."""
        x_keys, y_keys, norm_keys = self.run.get_default_selection()
        self.set_selection(x_keys, y_keys, norm_keys)

    def _on_data_changed(self) -> None:
        """Handle data changes from RunData service."""
        self._update_available_keys()
        self.update_plot()

    def update_plot(self):
        """Emit data for current selection."""
        x_keys = self.selected_x_keys
        y_keys = self.selected_y_keys
        norm_keys = self.selected_norm_keys

        should_draw = False
        for existing_x, existing_y in self._artists.keys():
            if existing_x in x_keys and existing_y in y_keys:
                pass
            else:
                self._artists[(existing_x, existing_y)].set_visible(False)
                should_draw = True

        if not x_keys or not y_keys:
            return

        xdatalist, ydatalist, xkeylist = self._run.get_plot_data(
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
                    artist.set_visible(self._is_visible)  # Use saved visibility state
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
                    artist.set_visible(self._is_visible)  # Set initial visibility

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
        self._run.set_transform(transform_state)

    def set_dynamic(self, enabled: bool) -> None:
        """
        Enable/disable dynamic updates.

        Parameters
        ----------
        enabled : bool
            Whether to enable dynamic updates
        """
        self._dynamic = enabled
        self._run.set_dynamic(enabled)

    def cleanup(self):
        """Clean up resources and remove all artists."""
        # Clean up all artists
        for artist in list(self._artists.values()):  # Make copy of values
            try:
                # Clear the artist
                artist.clear()
                # Disconnect all signals
                artist.artist_needed.disconnect(self.artist_needed)
                artist.autoscale_requested.disconnect(self.autoscale_requested)
                artist.draw_requested.disconnect(self.draw_requested)
                artist.visibility_changed.disconnect(self.visibility_changed)
            except Exception as e:
                print(f"Warning: Error cleaning up artist signals: {e}")

        # Clear artist dictionary
        self._artists.clear()

        # Disconnect RunData signals
        try:
            self._run.data_changed.disconnect(self._on_data_changed)
        except Exception as e:
            print(f"Warning: Error disconnecting run signals: {e}")

        # Clear selection state
        self._selected_x.clear()
        self._selected_y.clear()
        self._selected_norm.clear()

    @property
    def selected_x_keys(self) -> List[str]:
        """Get selected x-axis keys."""
        return self._selected_x.copy()

    @property
    def selected_y_keys(self) -> List[str]:
        """Get selected y-axis keys."""
        return self._selected_y.copy()

    @property
    def selected_norm_keys(self) -> List[str]:
        """Get selected normalization keys."""
        return self._selected_norm.copy()

    def get_selected_keys(self):
        return self.selected_x_keys, self.selected_y_keys, self.selected_norm_keys

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

    def set_visible(self, is_visible):
        """
        Set visibility for all artists.

        Parameters
        ----------
        is_visible : bool
            New visibility state
        """
        self._is_visible = is_visible  # Save visibility state
        self.update_plot()
