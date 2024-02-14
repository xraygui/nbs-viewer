from bluesky_widgets.models.plot_specs import Axes, Line, Image, ArtistSpec
from bluesky_widgets._matplotlib_axes import MatplotlibAxes as _MPLAxes
import numpy as np

class ContourArtistWrapper:
    def __init__(self, axes):
        self.axes = axes
        self.contour = None
        self._gid = None

    def set_gid(self, gid):
        self._gid = gid

    def get_gid(self):
        return self._gid

    def set(self, alpha=None, **kwargs):
        pass

    def set_data(self, x, y, z, label=None):
        self.remove()
        if 1 in z.shape:
            self.contour = None
        else:
            self.contour = self.axes.contourf(x, y, z)

    def remove(self):
        if self.contour is not None:
            for coll in self.contour.collections:
                coll.remove()
        self.contour = None
        
class Contour(ArtistSpec):
    "Describes a contourf image"


class MatplotlibAxes(_MPLAxes):
    """
    Respond to changes in Axes by manipulating matplotlib.axes.Axes.
    Note that while most view classes accept model as their only __init__
    parameter, this view class expects matplotlib.axes.Axes as well. If we
    follow the pattern used elsewhere in bluesky-widgets, we would want to
    receive only the model and to create matplotlib.axes.Axes internally in
    this class.
    The reason we break the pattern is pragmatic: matplotlib's
    plt.subplots(...) function is the easiest way to create a Figure and Axes
    with a nice layout, and it creates both Figure and Axes. So, this class
    receives pre-made Axes from the outside, ultimately via plt.subplots(...).
    """

    def __init__(self, model: Axes, axes, *args, **kwargs):
        self.model = model
        self.axes = axes

        self.type_map = {
            Line: self._construct_line,
            Image: self._construct_image,
            Contour: self._construct_contour
        }

        # If we specify data limits and axes aspect and position, we have
        # overdetermined the system. When these are incompatible, we want
        # matplotlib to expand the data limts along one dimension rather than
        # disorting the boundaries of the axes (for example, creating a tall,
        # shinny axes box).
        self.axes.set_adjustable("datalim")

        axes.set_title(model.title)
        axes.set_xlabel(model.x_label)
        axes.set_ylabel(model.y_label)
        aspect = model.aspect or "auto"
        axes.set_aspect(aspect)
        if model.x_limits is not None:
            axes.set_xlim(model.x_limits)
        if model.y_limits is not None:
            axes.set_ylim(model.y_limits)

        # Use matplotlib's user-configurable ID so that we can look up the
        # Axes from the axes if we need to.
        axes.set_gid(model.uuid)

        # Keep a reference to all types of artist here.
        self._artists = {}

        for artist in model.artists:
            self._add_artist(artist)
        self.connect(model.artists.events.added, self._on_artist_spec_added)
        self.connect(model.artists.events.removed, self._on_artist_spec_removed)
        self.connect(model.events.title, self._on_title_changed)
        self.connect(model.events.x_label, self._on_x_label_changed)
        self.connect(model.events.y_label, self._on_y_label_changed)
        self.connect(model.events.aspect, self._on_aspect_changed)
        self.connect(model.events.x_limits, self._on_x_limits_changed)
        self.connect(model.events.y_limits, self._on_y_limits_changed)


    def _construct_contour(self, *, x, y, z, label, style):
        artist = ContourArtistWrapper(self.axes)
        if not 0 in z.shape:
            artist.set_data(x, y, z)
            
            if style.get("show_colorbar", False):
                cb = self.axes.figure.colorbar(artist)
                # Keep the reference to the colorbar so that it could be removed with the artist
                setattr(artist, "_bsw_colorbar", cb)  # bsw - bluesky-widgets

            self.axes.relim()  # Recompute data limits.
            self.axes.autoscale_view()  # Rescale the view using those new limits.
            self.draw_idle()
        else:
            artist.set_data(np.array([0, 1]), np.array([0, 1]), np.array([[0, 0], [0, 0]]))
            self.axes.relim()  # Recompute data limits.
            self.axes.autoscale_view()  # Rescale the view using those new limits.
            self.draw_idle()
            
        def update(*, x, y, z):
            if 0 not in z.shape:
                artist.set_data(x, y, z)
                l = self.axes.get_legend()
                if l is not None:
                    l.remove()
                self.draw_idle()

        return artist, update


