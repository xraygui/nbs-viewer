from typing import Dict, List, Optional, Tuple
from qtpy.QtCore import QObject, Signal, Slot
from qtpy.QtWidgets import QWidget


class PlotDataModel(QWidget):
    """
    A class to plot x, y data on a given MplCanvas instance and hold the resulting lines object.

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

    def __init__(self, x, y, xkeys, label, indices=None, dimension=1, parent=None):
        """
        Initializes the DataPlotter with data and a canvas, and plots the data.

        Parameters
        ----------
        parent : QWidget
            Parent widget.
        canvas : MplCanvas
            The MplCanvas instance where the data will be plotted.
        x : list of array_like
            The x data to plot.
        y : array_like
            The y data to plot.
        xkeys : list
            List of x axis keys.
        label : str
            Label for the plot.
        dimension : int, optional
            Number of dimensions to plot, by default 1.
        """
        super().__init__(parent=parent)
        # print(f"\nCreating PlotDataModel for {label}")
        self._x = x
        self._y = y
        self._xplot = None
        self._yplot = None
        self._xkeys = xkeys
        self._label = label
        self._indices = indices
        self.x_dim = dimension
        self.artist = None

    @property
    def shape(self):
        return self._y.shape

    @property
    def y_dim(self):
        return len(self._y.shape)

    def plot_data(self, indices=None):
        """
        Plots the given x, y data on the associated MplCanvas instance.

        Parameters
        ----------
        indices : tuple, optional
            Indices for slicing multidimensional data, by default None.

        Returns
        -------
        Line2D or None
            The matplotlib artist representing the plotted data.
        """
        if indices is not None:
            self._indices = indices
        else:
            indices = self._indices

        xlistmod = []
        if indices is None:
            indices = tuple([0 for n in range(len(self._x) - self.x_dim)])
        for x in self._x:
            if len(x.shape) > 1:
                xlistmod.append(x[indices])
            else:
                xlistmod.append(x)
        y = self._y[indices]
        x = xlistmod[-self.x_dim :]
        self._xplot = x
        self._yplot = y

        if self.artist is not None:
            # print(f"  Updating existing artist")
            # Update existing artist with new data
            self.artist.set_data(x[0], y)
            was_visible = self.artist.get_visible()
            self.artist.set_visible(True)
            if not was_visible:
                self.visibility_changed.emit(self, True)
            self.autoscale_requested.emit()
        else:
            # print(f"  Requesting new artist")
            self.artist_needed.emit(self)

    def set_visible(self, visible):
        """
        Set the visibility of the artist.

        Parameters
        ----------
        visible : bool
            Whether to show or hide the artist
        """
        if self.artist is not None:
            was_visible = self.artist.get_visible()
            self.artist.set_visible(visible)
            if was_visible != visible:
                self.visibility_changed.emit(self, visible)
            if visible:
                self.autoscale_requested.emit()
            self.draw_requested.emit()

    def set_artist(self, artist):
        self.artist = artist

    def update_data(self, x, y):
        """
        Updates the data and redraws the plot.

        Parameters
        ----------
        x : list of array_like
            New x data.
        y : array_like
            New y data.
        """
        self._x = x
        self._y = y
        self.plot_data()

    @Slot(tuple)
    def update_indices(self, indices):
        """
        Updates the plotted data based on the provided indices.

        Parameters
        ----------
        indices : tuple
            Indices into the first N-1 dimensions of the data arrays.
        """
        self.plot_data(indices)

    def clear(self):
        """Remove artist from plot and clean up."""
        if self.artist is not None:
            # print(f"\nClearing {self._label}")
            # print(f"  Artist visible: {self.artist.get_visible()}")
            # print(f"  Artist axes: {self.artist.axes}")
            try:
                if self.artist.axes is not None:
                    self.artist.remove()
                    # print("  Artist removed from axes")
                self.artist.set_data([], [])
                # print("  Artist data cleared")
            except Exception as e:
                print(f"  Error cleaning up artist: {e}")
            finally:
                self.artist = None
                # print("  Artist reference cleared")
                self.draw_requested.emit()
