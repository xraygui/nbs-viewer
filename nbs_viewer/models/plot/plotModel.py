"""Plot model managing run controllers and their associated plot artists."""

from typing import Dict, List, Optional, Tuple
from qtpy.QtCore import QObject, Signal
import numpy as np


class PlotArtistManager:
    """
    Manages the mapping between controllers and their artists.

    This class maintains only the relationships between controllers
    and artists, with no knowledge of the actual data or updates.
    """

    def __init__(self):
        """Initialize the manager."""
        self._controller_artists: Dict[QObject, List[Tuple[object, dict]]] = {}
        self._artist_controllers: Dict[object, QObject] = {}

    def register_artist(
        self, controller: QObject, artist: object, config: dict
    ) -> None:
        """
        Register a new artist for a controller.

        Parameters
        ----------
        controller : QObject
            The run controller owning the data.
        artist : object
            The matplotlib artist object.
        config : dict
            Configuration for the artist (e.g., x/y keys).
        """
        if controller not in self._controller_artists:
            self._controller_artists[controller] = []
        self._controller_artists[controller].append((artist, config))
        self._artist_controllers[artist] = controller

    def remove_controller(self, controller: QObject) -> List[object]:
        """
        Remove all artists for a controller.

        Parameters
        ----------
        controller : QObject
            The controller to remove.

        Returns
        -------
        List[object]
            List of artists that were removed.
        """
        artists = []
        if controller in self._controller_artists:
            for artist, _ in self._controller_artists[controller]:
                artists.append(artist)
                del self._artist_controllers[artist]
            del self._controller_artists[controller]
        return artists

    def get_artists(self, controller: QObject) -> List[Tuple[object, dict]]:
        """
        Get all artists for a controller.

        Parameters
        ----------
        controller : QObject
            The controller to get artists for.

        Returns
        -------
        List[Tuple[object, dict]]
            List of (artist, config) pairs.
        """
        return self._controller_artists.get(controller, [])

    def get_controller(self, artist: object) -> Optional[QObject]:
        """
        Get the controller for an artist.

        Parameters
        ----------
        artist : object
            The artist to get the controller for.

        Returns
        -------
        QObject or None
            The associated controller, or None if not found.
        """
        return self._artist_controllers.get(artist)


class PlotModel(QObject):
    """
    Model coordinating between run controllers and plot artists.

    This class handles the high-level coordination between data sources
    and their visual representation, delegating actual artist management
    to PlotArtistManager.
    """

    # Signals for view to create/update/remove artists
    artist_needed = Signal(object, dict)  # (controller, config) for new artist
    artist_removed = Signal(object)  # artist to remove
    artist_data_updated = Signal(object, np.ndarray, np.ndarray)  # artist, x, y
    available_keys_changed = Signal()

    def __init__(self):
        """Initialize the plot model."""
        super().__init__()
        self.runControllers = []
        self._available_keys = set()
        self._artist_manager = PlotArtistManager()

    def addRunController(self, runController: QObject) -> None:
        """
        Add a new run controller and connect its signals.

        Parameters
        ----------
        runController : QObject
            The controller to add.
        """
        # Connect to data updates
        runController.data_updated.connect(
            lambda data, metadata: self._handle_data_update(
                runController, data, metadata
            )
        )

        # Connect to selection changes
        runController.state_model.selection_changed.connect(
            lambda: self._handle_selection_change(runController)
        )

        # Connect to available keys changes
        runController.state_model.available_keys_changed.connect(
            self.update_available_keys
        )

        self.runControllers.append(runController)

    def removeRunController(self, runController: QObject) -> None:
        """
        Remove a run controller and its artists.

        Parameters
        ----------
        runController : QObject
            The controller to remove.
        """
        self.runControllers.remove(runController)
        runController.data_updated.disconnect()
        runController.state_model.available_keys_changed.disconnect()

        # Remove associated artists
        removed_artists = self._artist_manager.remove_controller(runController)
        for artist in removed_artists:
            self.artist_removed.emit(artist)

    def register_artist(
        self, controller: QObject, artist: object, config: dict
    ) -> None:
        """
        Register a new artist created by the view.

        Parameters
        ----------
        controller : QObject
            The run controller owning the data.
        artist : object
            The matplotlib artist object.
        config : dict
            Configuration for the artist.
        """
        self._artist_manager.register_artist(controller, artist, config)

    def _handle_selection_change(self, controller: QObject) -> None:
        """
        Handle changes in run controller selection state.

        Parameters
        ----------
        controller : QObject
            The controller whose selection changed.
        """
        # Get current selection from state model
        x_keys = controller.state_model.selected_x
        y_keys = controller.state_model.selected_y

        # Get existing artists for this controller
        existing_artists = self._artist_manager.get_artists(controller)

        # Create/update artists based on selection
        for y_key in y_keys:
            if not x_keys:
                continue

            config = {"x_key": x_keys[0], "y_key": y_key}

            # Try to find existing artist with this config
            artist = self._find_artist_for_config(existing_artists, config)

            if not artist:
                # Need new artist
                self.artist_needed.emit(controller, config)

    def _handle_data_update(
        self, controller: QObject, data: np.ndarray, metadata: dict
    ) -> None:
        """
        Handle data updates from run controllers.

        Parameters
        ----------
        controller : QObject
            The controller with new data.
        data : np.ndarray
            The new data.
        metadata : dict
            Metadata about the update.
        """
        # Find artists that need updating based on metadata
        for artist, config in self._artist_manager.get_artists(controller):
            x_key = config.get("x_key")
            y_key = config.get("y_key")
            if x_key in metadata and y_key in metadata:
                x_data = metadata[x_key]
                y_data = metadata[y_key]
                self.artist_data_updated.emit(artist, x_data, y_data)

    def _find_artist_for_config(
        self, artists: List[Tuple[object, dict]], config: dict
    ) -> Optional[object]:
        """
        Find an existing artist matching the given config.

        Parameters
        ----------
        artists : List[Tuple[object, dict]]
            List of (artist, config) pairs to search.
        config : dict
            Configuration to match.

        Returns
        -------
        object or None
            Matching artist if found, None otherwise.
        """
        for artist, artist_config in artists:
            if (
                artist_config.get("x_key") == config["x_key"]
                and artist_config.get("y_key") == config["y_key"]
            ):
                return artist
        return None

    @property
    def available_keys(self) -> set:
        """Get available data keys."""
        return self._available_keys

    def update_available_keys(self) -> None:
        """Update the set of available data keys."""
        available_keys = set()
        for runController in self.runControllers:
            available_keys.update(runController.state_model.available_keys)
        self._available_keys = available_keys
        self.available_keys_changed.emit()
