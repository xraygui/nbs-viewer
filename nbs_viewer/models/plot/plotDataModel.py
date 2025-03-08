from typing import Tuple
from qtpy.QtCore import Signal, Slot
from qtpy.QtWidgets import QWidget
import numpy as np


class PlotDataModel(QWidget):
    """
    A class to plot x, y data on a given MplCanvas instance and hold the
    resulting lines object.

    Attributes
    ----------
    canvas : MplCanvas
        The MplCanvas instance where the data will be plotted.
    artist : Line2D or None
        The matplotlib artist representing the plotted data.
    _x : list
        List of x data arrays.
    _y : array_like
        The y data array.
    _xkeys : list
        List of x axis keys.
    _label : str
        Label for the plot.
    _indices : tuple or None
        Current indices for slicing multidimensional data.
    x_dim : int
        Number of x dimensions to plot.
    """

    artist_needed = Signal(object)
    draw_requested = Signal()
    autoscale_requested = Signal()
    visibility_changed = Signal(object, bool)  # (artist, is_visible)
    data_changed = Signal(object)

    def __init__(
        self,
        run,
        xkey,
        ykey,
        norm_keys=None,
        label=None,
        indices=None,
        dimension=1,
        parent=None,
    ):
        """
        Initializes the DataPlotter with data and a canvas, and plots the data.

        Parameters
        ----------
        x : list of array_like
            The x data to plot.
        y : array_like
            The y data to plot.
        xkeys : list
            List of x axis keys.
        label : str
            Label for the plot.
        indices : tuple, optional
            Initial indices for slicing, by default None
        dimension : int, optional
            Number of dimensions to plot, by default 1.
        parent : QWidget, optional
            Parent widget, by default None.
        """
        super().__init__(parent=parent)
        self._key = (xkey, ykey, run.uid)
        self._xkey = xkey
        self._ykey = ykey
        self._run = run
        self._norm_keys = norm_keys
        self._xplot = None
        self._yplot = None
        self._label = label
        self._indices = indices
        self._dimension = dimension
        self.artist = None
        self._run.visibility_changed.connect(self.set_visible)
        self._run.transform_changed.connect(self._on_data_changed)
        self._run.data_changed.connect(self._on_data_changed)

    @property
    def label(self):
        return self._label or f"{self._ykey}.{self._run.scan_id}"

    def get_plot_data(self, indices=None, dimension=None):
        """
        Plots the given x, y data on the associated MplCanvas instance.

        Parameters
        ----------
        indices : tuple, optional
            Indices for slicing multidimensional data, by default None.

        Returns
        -------
        Artist
            The matplotlib artist representing the plotted data.
        """
        norm_keys = self._norm_keys
        xlist, y, xkeylist = self._run._run.get_plot_data(
            [self._xkey], [self._ykey], norm_keys, indices
        )
        y = y[0]
        xlist = xlist[0]
        """
        # Update indices if provided
        if indices is not None:
            self._indices = indices
        else:
            indices = self._indices

        # Create default indices if none provided
        if indices is None:
            # Default to first index for each dimension except the plot dimensions
            indices = tuple([0 for _ in range(len(y.shape) - dimension)])

        # Process x data

        xlistmod = []
        for x in xlist:
            if len(x.shape) > 1:
                # Slice multidimensional x data
                xlistmod.append(x[indices])
            else:
                # Keep 1D x data as is
                xlistmod.append(x)

        # Get y data with appropriate slicing
        if dimension == 1:
            # For 1D plots, slice to get a 1D array
            if len(y.shape) > 1:
                y = y[indices]

        elif dimension == 2:
            # For 2D plots, slice to get a 2D array
            if len(y.shape) > 2:
                # Need to slice off all but the last 2 dimensions
                y = y[indices]

        else:
            # Unsupported dimensions
            print(f"Unsupported plot dimensions: {dimension}")
            return None
        """
        # Select x dimensions based on plot dimensions
        x = xlist[-dimension:]
        return x, y

    def update_data_info(self, norm_keys=None, indices=None, dimension=None):
        changed = False
        if norm_keys is not None and set(norm_keys) != set(self._norm_keys):
            self._norm_keys = norm_keys
            changed = True
        if indices is not None and indices != self._indices:
            self._indices = indices
            changed = True
        if dimension is not None and dimension != self._dimension:
            self._dimension = dimension
            changed = True
        if changed:
            self.data_changed.emit(self)

    def set_norm_keys(self, norm_keys):
        if set(norm_keys) != set(self._norm_keys):
            self._norm_keys = norm_keys
            self.data_changed.emit(self)

    def set_visible(self, visible):
        """
        Set the visibility of the artist.

        Parameters
        ----------
        visible : bool
            Whether to show or hide the artist
        """
        if self.artist is not None:
            print(f"Setting {self.label} visible to {visible}")
            was_visible = self.artist.get_visible()
            if was_visible != visible:
                self.artist.set_visible(visible)
                self.visibility_changed.emit(self, visible)
                self.autoscale_requested.emit()
                self.draw_requested.emit()
        else:
            print(f"{self.label} has no artist")

    def _on_data_changed(self):
        """
        Handle data changes from the RunModel.
        """
        self.data_changed.emit(self)

    def set_artist(self, artist):
        """
        Set the artist for this model.

        Parameters
        ----------
        artist : Artist
            The matplotlib artist
        """
        self.artist = artist
        print(f"Setting {self.label} artist to {artist}")

    def clear(self):
        """
        Remove artist from plot and clean up.

        Handles both Line2D and QuadMesh artists appropriately.
        """
        if self.artist is not None:
            try:
                if self.artist.axes is not None:
                    # Remove from axes
                    self.artist.remove()

                # Clear data based on artist type
                if hasattr(self.artist, "set_data"):
                    # Line2D case
                    self.artist.set_data([], [])
                elif hasattr(self.artist, "set_array"):
                    # QuadMesh case
                    self.artist.set_array([])
            except Exception as e:
                print(f"[PlotDataModel.clear] Error cleaning up artist: {e}")
            finally:
                self.artist = None
                self.draw_requested.emit()
