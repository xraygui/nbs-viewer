from typing import Tuple
from qtpy.QtCore import Signal, Slot, QObject
from qtpy.QtWidgets import QWidget
import numpy as np
import time as ttime
from nbs_viewer.utils import print_debug
from matplotlib.image import AxesImage


class PlotDataModel(QObject):
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
        self._visible = self._run._is_visible
        self._run.visibility_changed.connect(self.set_visible)
        self._run.selected_keys_changed.connect(self._on_keys_changed)
        self._run.transform_changed.connect(self._on_data_changed)
        self._run.data_changed.connect(self._on_data_changed)

    @property
    def label(self):
        return self._label or f"{self._ykey}.{self._run.scan_id}"

    def get_plot_data(self, indices=None, dimension=None):
        """
        Gets plot data and dimension information.

        Parameters
        ----------
        indices : tuple, optional
            Indices for slicing multidimensional data, by default None
        dimension : int, optional
            Number of dimensions to plot, by default None

        Returns
        -------
        Tuple[List[np.ndarray], np.ndarray]
            The x and y data arrays for plotting
        """
        norm_keys = self._norm_keys
        xkeys = [self._xkey]
        ykeys = self._ykey
        print_debug(
            "PlotDataModel.get_plot_data",
            f"getting plot data for {self.label} with keys: {xkeys} and {ykeys}",
        )

        xlist, ylist = self._run.get_plot_data(xkeys, ykeys, norm_keys, indices)
        return xlist, ylist

    def update_data_info(self, norm_keys=None, indices=None, dimension=None):
        # print(f"Updating data info for {self.label}")
        changed = False
        if self.artist is None:
            changed = True
        if norm_keys is not None and set(norm_keys) != set(self._norm_keys):
            self._norm_keys = norm_keys
            changed = True
        if indices is not None and indices != self._indices:
            self._indices = indices
            changed = True
        if dimension is not None and dimension != self._dimension:
            self._dimension = dimension
            changed = True
        if not self._run._is_visible:
            changed = False
        if changed:
            print_debug(
                "PlotDataModel.update_data_info",
                f"Data info changed for {self.label}",
                category="DEBUG_PLOTS",
            )
            self.data_changed.emit(self)
        else:
            print_debug(
                "PlotDataModel.update_data_info",
                f"Data info not changed for {self.label}, visible: {self._visible}",
                category="DEBUG_PLOTS",
            )

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
        visible = visible and self._run._is_visible
        if self.artist is not None:
            print_debug(
                "PlotDataModel.set_visible",
                f"Setting {self.label} visible to {visible}",
                category="DEBUG_PLOTS",
            )
            # print(f"Setting {self.label} visible to {visible}")
            was_visible = self.artist.get_visible()
            if was_visible != visible:
                self._visible = visible
                self.artist.set_visible(visible)
                self.visibility_changed.emit(self, visible)
                self.autoscale_requested.emit()
                self.draw_requested.emit()
        else:
            print_debug(
                "PlotDataModel.set_visible",
                f"{self.label} has no artist",
                category="DEBUG_PLOTS",
            )
            # print(f"{self.label} has no artist")
            pass

    def _on_keys_changed(self, xkeys, ykeys, normkeys):
        """
        Handle changes in selected keys.
        """

        if self._xkey not in xkeys or self._ykey not in ykeys:
            print_debug(
                "PlotDataModel._on_keys_changed",
                f"Keys changed for {self.label}: {self._xkey}, {self._ykey} not visible",
                category="DEBUG_PLOTS",
            )
            self.set_visible(False)
        else:
            print_debug(
                "PlotDataModel._on_keys_changed",
                f"Keys changed for {self.label}: {self._xkey}, {self._ykey} visible",
                category="DEBUG_PLOTS",
            )
            self.set_visible(True)

    def _on_data_changed(self, *args):
        """
        Handle data changes from the RunModel.
        """
        if self._visible:
            print_debug(
                "PlotDataModel._on_data_changed",
                f"Emitting data changed for {self.label}",
                category="DEBUG_PLOTS",
            )
            self.data_changed.emit(self)
        else:
            print_debug(
                "PlotDataModel._on_data_changed",
                f"Not emitting data changed for {self.label} because it is not visible",
                category="DEBUG_PLOTS",
            )

    def set_artist(self, artist):
        """
        Set the artist for this model.

        Parameters
        ----------
        artist : Artist
            The matplotlib artist
        """
        self.artist = artist
        # print(f"Setting {self.label} artist to {artist}")

    def clear(self):
        """
        Remove artist from plot and clean up.

        Handles both Line2D and QuadMesh artists appropriately.
        """
        print_debug(
            "PlotDataModel.clear",
            f"Clearing artist for {self.label}",
            category="DEBUG_PLOTS",
        )
        if self.artist is not None:
            try:
                if self.artist.axes is not None:
                    # Remove from axes
                    self.artist.remove()

                # Clear data based on artist type
                if isinstance(self.artist, AxesImage):
                    self.artist.set_data([[]])
                elif hasattr(self.artist, "set_data"):
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

    def remove_artist_from_axes(self):
        if self.artist is not None:
            if self.artist.axes is not None:
                self.artist.remove()
                self.draw_requested.emit()

    def add_artist_to_axes(self, axes):
        if self.artist is not None:
            axes.add_artist(self.artist)
            self.draw_requested.emit()

    def move_artist_to_axes(self, axes):
        if self.artist is not None:
            if self.artist.axes != axes:
                print_debug(
                    "PlotDataModel.move_artist_to_axes",
                    f"Moving artist {self.label} from {self.artist.axes} to {axes}",
                )
                if self.artist.axes is not None:
                    self.artist.remove()
                axes.add_artist(self.artist)
                self.draw_requested.emit()
