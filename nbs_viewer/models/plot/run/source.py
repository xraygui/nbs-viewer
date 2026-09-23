from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from qtpy.QtCore import QObject, Signal
import numpy as np
import xarray as xr

from ...data.base import CatalogRun
from ...data.key_info import KeyInfo
from ...data.key_source import CatalogKey
from .cache import BlockCache
from .frozen_spectrum import FrozenSpectrum
from ..spec.plan import FetchPlan
from nbs_viewer.utils import print_debug


def x_dimension(y: KeyInfo, x: Optional[KeyInfo]) -> Optional[str]:
    """
    Return the dimension of ``y`` that ``x`` is a coordinate along, or None.

    **The X selection rule, and the only place it is decided.** Choosing X
    changes nothing about the data: a scanned motor is a 1-D key whose own
    dimension is the event axis -- a labelled run declares ``en_energy`` as
    ``('time',
)`` -- so it is one more coordinate that axis can be plotted
    against. X's dimension is ``x.dims[0]``. When ``y`` has that dimension,
    X becomes its coordinate and the dimension carries X's name, which is
    ``swap_dims`` in xarray's terms.

    It is refused, and ``y`` keeps its own names, when X's name is already a
    dimension of ``y`` -- which includes X being that dimension's own
    coordinate, as ``time`` is -- or when the lengths differ. Nothing is ever
    reordered: a dimension keeps its storage position whatever it is called.
    The analysis this replaced put a selected detector axis's name second,
    and so named the wrong axis after it (bug 16).

    Parameters
    ----------
    y : KeyInfo
        Description of the key being plotted.
    x : KeyInfo or None
        Description of the selected X key; None when nothing is selected or
        the run does not hold it.

    Returns
    -------
    str or None
        The storage dimension of ``y`` that X attaches to.
    """
    if x is None or x.ndim != 1:
        return None
    dim = x.dims[0]
    if dim not in y.axes or x.name in y.axes:
        return None
    if x.axes[dim] != y.axes[dim]:
        return None
    return dim


class RunSource(QObject):
    """
    The union of a catalog run and its frozen synthetic keys, under one key
    space, plus the key table and signals the plot layer needs.

    A :class:`CatalogRun` is one source of labelled arrays for a run's keys.
    This is a higher-level object rather than a near-duplicate of it, and
    :meth:`_source` is where the difference lives: one place decides which
    source holds a key, and everything else either delegates to what it
    returns or reads a fact off the key's description. Two things are this
    class's own business rather than either source's: applying the X
    selection, which needs a second key's description, and the one case that
    needs both sources at once -- a frozen stack spectrum plotted against the
    catalog's X keys.

    The RunSource surface is ``key_table`` and ``identity``, plus the six
    read methods that make it the *reader* for its own key space:
    ``describe``, ``load``, ``load_coords``, ``read``, ``plot_axis_names``
    and ``block``. Only ``block`` remembers anything, and it is the only one
    that delegates -- to the :class:`~.cache.BlockCache` this class owns.

    Turning a plot request into a bundle is no longer here and no longer
    beside it: that is ``PlotRequest.plot_bundle``, which takes this object
    as its reader. Selection, visibility, and transform live on
    :class:`PlotSession`.

    Parameters
    ----------
    run : CatalogRun
        The run to wrap.
    """

    available_keys_changed = Signal()
    frozen_spectra_changed = Signal()
    data_changed = Signal()
    plot_update_needed = Signal()

    def __init__(self, run: CatalogRun):
        super().__init__()
        self._run = run
        print_debug("RunSource.__init__", f"RunSource for run {run.uid}", "run")
        self._catalog_keys: List[str] = []
        self._frozen_spectra: Dict[str, FrozenSpectrum] = {}
        self._dynamic = False
        self._key_table: Optional[Dict[str, KeyInfo]] = None
        # Before the keys load, because loading them clears the cache.
        self._cache = BlockCache(self)
        self._update_available_keys()
        self._connect_run()

    def _connect_run(self):
        self._run.data_changed.connect(self._on_data_changed)
        if hasattr(self._run, "keys_ready"):
            self._run.keys_ready.connect(self._on_keys_event)
        if hasattr(self._run, "keys_error"):
            self._run.keys_error.connect(self._on_keys_event)

    def _on_keys_event(self, *_):
        self._update_available_keys()

    def _disconnect_run(self):
        """Disconnect RunData signals."""
        self._run.data_changed.disconnect(self._on_data_changed)

    @property
    def display_name(self) -> str:
        """Get descriptive name for the run."""
        return self.run.display_name

    @property
    def run(self) -> CatalogRun:
        """Get the underlying run object."""
        return self._run

    @property
    def metadata(self):
        return self.run.metadata

    @property
    def uid(self) -> str:
        """Get the unique identifier for the run."""
        return self.run.uid

    @property
    def scan_id(self) -> str:
        """Get the scan ID for the run."""
        return self.run.scan_id

    @property
    def plan_name(self) -> str:
        """Get the plan name for the run."""
        return self.run.plan_name

    @property
    def catalog_keys(self) -> List[str]:
        """Get catalog stream keys from the run."""
        return self._catalog_keys

    @property
    def available_keys(self) -> List[str]:
        """Get catalog keys plus frozen synthetic spectrum keys."""
        return self._catalog_keys + list(self._frozen_spectra.keys())

    def is_synthetic_key(self, key: str) -> bool:
        """
        Return whether a key identifies a frozen synthetic spectrum on this run.

        Parameters
        ----------
        key : str
            Run display key.

        Returns
        -------
        bool
            True when the key is a registered synthetic spectrum.
        """
        return key in self._frozen_spectra

    def _invalidate_key_table(self) -> None:
        """Drop the cached key table so the next access rebuilds it."""
        self._key_table = None
        self._cache.clear()

    def _build_key_table(self) -> Dict[str, KeyInfo]:
        """
        Merge catalog keys with frozen entries into a KeyInfo table.

        Both sources answer ``describe`` themselves, so this assembles rather
        than derives: it no longer reads shapes and plot hints and builds the
        records here, which was a third place that had to agree with the two
        sources about what a key is.

        Returns
        -------
        dict of str to KeyInfo
            Fresh table keyed by data key name.
        """
        table: Dict[str, KeyInfo] = {}
        for name in self._catalog_keys:
            table[name] = self._run.describe(name)
        for key, entry in self._frozen_spectra.items():
            table[key] = entry.describe()
        return table

    def key_table(self) -> Mapping[str, KeyInfo]:
        """
        Return the cached catalog-plus-frozen key table.

        Returns
        -------
        mapping of str to KeyInfo
            Read-only view of the current table. Invalidated on catalog key
            updates, data changes, and frozen register/remove.
        """
        if self._key_table is None:
            self._key_table = self._build_key_table()
        return MappingProxyType(self._key_table)

    def _source(self, key: str) -> Union[FrozenSpectrum, CatalogKey]:
        """
        Return whichever source holds this key, bound to it.

        **The union, performed once.** Everything else on this class delegates
        to what this returns, or reads a fact off the key's description. It
        used to be spelled out in five separate methods -- one dispatch,
        written five times, which is a copy rather than an abstraction.

        The two sources answer the same key-free protocol: a
        :class:`FrozenSpectrum` *is* one key already, and :class:`CatalogKey`
        binds a run to one of its many.

        Parameters
        ----------
        key : str
            Run display key.

        Returns
        -------
        FrozenSpectrum or CatalogKey
            The source that holds the key.
        """
        entry = self._frozen_spectra.get(key)
        if entry is not None:
            return entry
        return CatalogKey(self._run, key)

    def load(
        self,
        key: str,
        slice_info=None,
        *,
        coords: bool = True,
        xkeys: Sequence[str] = (),
        dims: Optional[Sequence[str]] = None
) -> xr.DataArray:
        """
        Return a labelled array for a catalog or frozen key, under an X choice.

        Both sources answer ``load`` themselves and say nothing about X, so
        this dispatches once and then applies the selection: the dimensions
        take their plot names, and the coordinates are :meth:`load_coords`'s.

        Parameters
        ----------
        key : str
            Data key.
        slice_info : tuple, optional
            Per-axis slice tuple, in storage order.
        coords : bool, optional
            Attach coordinate values as well as dimension names.
        xkeys : sequence of str, optional
            Selected X keys.
        dims : sequence of str, optional
            Plot name per storage axis, when the caller already has them. A
            request carries the names its projection was chosen against, so
            the fetch passes those rather than having them derived again.

        Returns
        -------
        xarray.DataArray
            Storage-ordered array named for plotting against ``xkeys``, with
            its coordinates when asked for.
        """
        data = self._source(key).load(slice_info, coords=False)
        names = self._plot_names(key, xkeys, dims)
        renamed = {dim: names[dim] for dim in data.dims if names[dim] != dim}
        if renamed:
            data = data.rename(renamed)
        if coords:
            data = data.assign_coords(
                self.load_coords(key, slice_info, xkeys, dims=dims)
            )
        return data

    def read(self, key: str, slice_info=None) -> np.ndarray:
        """
        Load raw array data for a catalog or frozen key.

        The pipeline still works in bare numpy, so this drops the labels
        ``load`` attaches, and asks for no coordinates -- each one would cost
        a read of its own key to be discarded. What it keeps is the *check*: a
        source that disagrees with its own arrays about their rank, or names
        two axes the same thing, now fails here rather than mislabelling an
        axis silently.

        Parameters
        ----------
        key : str
            Data key.
        slice_info : tuple, optional
            Per-axis slice tuple.

        Returns
        -------
        np.ndarray
            Storage array for the key.

        Raises
        ------
        ValueError
            If the underlying source returns None.
        """
        data = self.load(key, slice_info, coords=False)
        if data is None:
            raise ValueError(f"No data returned for key {key!r}")
        return np.asarray(data.values)

    def describe(self, key: str) -> KeyInfo:
        """
        Return static facts about a catalog or frozen key.

        The key table already holds a description of every key either source
        offers, so this is a cache read for anything selectable. The fallback
        covers a key asked about before the table is built.

        Parameters
        ----------
        key : str
            Data key.

        Returns
        -------
        KeyInfo
            Name, label, ``{axis name: length}``, and the render hint.
        """
        info = self.key_table().get(key)
        if info is not None:
            return info
        return self._source(key).describe()

    def _describe_x(self, xkey: str) -> Optional[KeyInfo]:
        """
        Describe an X key, or return None when this run does not hold it.

        The X selection is shared by every run on a plot, so a key one run
        lacks is the ordinary case rather than an error: that run plots
        against its own axes.

        Parameters
        ----------
        xkey : str
            Selected X key.

        Returns
        -------
        KeyInfo or None
            Its description, when there is one.
        """
        try:
            return self.describe(xkey)
        except Exception:
            return None

    def plot_axis_names(
        self, ykey: str, xkeys: Sequence[str]
    ) -> Tuple[str, ...]:
        """
        Return the axis names to plot a key under a given X selection.

        The key's own dimensions, in storage order, with the one the first X
        key lives on named after it -- :func:`x_dimension` decides which, from
        the two descriptions, reading nothing. The projection locates the X
        key's storage axis by this name, which is why it is carried on the
        request rather than asked for again.

        A frozen payload's axes are whatever the reduction produced, so no
        catalog key lives on them and its names come back unchanged. A stack
        spectrum is still plotted against the catalog's X; that is a
        coordinate, attached by :meth:`load_coords`, not a name.

        Parameters
        ----------
        ykey : str
            Y data key.
        xkeys : sequence of str
            Selected X-axis keys. Only the first can name an axis, which is
            the one the default axis order follows.

        Returns
        -------
        tuple of str
            One name per storage axis.
        """
        info = self.describe(ykey)
        xkeys = list(xkeys)
        dim = x_dimension(info, self._describe_x(xkeys[0])) if xkeys else None
        if dim is None:
            return info.dims
        return tuple(xkeys[0] if name == dim else name for name in info.dims)

    def _plot_names(
        self,
        key: str,
        xkeys: Sequence[str],
        dims: Optional[Sequence[str]]
) -> Dict[str, str]:
        """
        Map each storage dimension of a key to its plot name.

        From the caller's names when it has them, and otherwise from
        :meth:`plot_axis_names`. Names a caller carries are checked rather
        than re-derived: an axis may be called by its own name or by the
        first X key's, and by nothing else, since an axis named after a key
        is plotted against that key.

        Parameters
        ----------
        key : str
            Data key.
        xkeys : sequence of str
            Selected X keys.
        dims : sequence of str or None
            Plot name per storage axis, if the caller has them.

        Returns
        -------
        dict of str to str
            Plot name by storage dimension.

        Raises
        ------
        ValueError
            If the carried names do not fit the key, or name an axis after
            something other than the X key.
        """
        info = self.describe(key)
        if dims is None:
            dims = self.plot_axis_names(key, xkeys)
        dims = tuple(dims)
        if len(dims) != info.ndim:
            raise ValueError(
                f"{len(dims)} axis names {dims} for {key!r}, which has "
                f"dimensions {info.dims}"
            )
        xkey = xkeys[0] if len(xkeys) else None
        for dim, name in zip(info.dims, dims):
            if name != dim and name != xkey:
                raise ValueError(
                    f"{key!r} axis {dim!r} is named {name!r}, which is "
                    f"neither its own name nor the X key {xkey!r}"
                )
        return dict(zip(info.dims, dims))

    def load_coords(
        self,
        key: str,
        slice_info=None,
        xkeys: Sequence[str] = (),
        *,
        dims: Optional[Sequence[str]] = None
) -> xr.Coordinates:
        """
        Return the coordinates of a key's surviving axes, under an X choice.

        What anything that labels an axis needs -- the fetch, the frame an ROI
        is compiled against, the dimension sliders -- and it reads none of
        the key's values, only the 1-D keys its description names. Per
        surviving dimension, under its plot name:

        - an axis named after the X key carries that key's values;
        - any other carries the coordinate its source holds for it, or else
          its storage index, sliced like the data, so a cropped plane keeps
          the positions it was cropped from rather than restarting at zero;
        - a further X key living on an axis rides there as a *non-dimension*
          coordinate. Only one key can name an axis, and the others are what
          a slider shows beside its own value.

        Parameters
        ----------
        key : str
            Data key.
        slice_info : tuple, optional
            Per-axis slice tuple, in storage order.
        xkeys : sequence of str, optional
            Selected X keys.
        dims : sequence of str, optional
            Plot name per storage axis, when the caller already has them.

        Returns
        -------
        xarray.Coordinates
            Ready to assign to the key's array loaded under the same names.

        Raises
        ------
        ValueError
            If the carried names do not fit the key, or a stack spectrum is
            plotted against an X key of another length.
        """
        info = self.describe(key)
        source = self._source(key)
        names = self._plot_names(key, xkeys, dims)
        items = list(slice_info or ())[: info.ndim]
        items += [slice(None)] * (info.ndim - len(items))
        kept = {
            dim: item
            for dim, item in zip(info.dims, items)
            if not isinstance(item, (int, np.integer))
        }
        found = source.load_coords(slice_info)
        coords = {}
        for dim, item in kept.items():
            name = names[dim]
            if name != dim:
                values = self.read(name, (item,
))
            else:
                values = found.get(dim)
                if values is None:
                    values = np.arange(info.axes[dim], dtype=float)[item]
            coords[name] = (name, np.asarray(values))

        xkeys = list(xkeys)
        # Branched on the kind a source declares itself to be, not on its
        # class: a frozen per-event quantity is plotted against the catalog's
        # X, and only this class holds both.
        if xkeys and source.kind == "stack_spectrum":
            dim = info.dims[0]
            if dim in kept:
                values = self._stack_spectrum_x(info, xkeys[0], kept[dim])
                coords[dim] = (dim, values)
            return xr.Coordinates(coords)

        for xkey in xkeys[1:]:
            if xkey in coords:
                continue
            dim = x_dimension(info, self._describe_x(xkey))
            if dim is None or dim not in kept:
                continue
            values = np.asarray(self.read(xkey, (kept[dim],
)))
            coords[xkey] = (names[dim], values)
        return xr.Coordinates(coords)

    def _stack_spectrum_x(
        self, info: KeyInfo, xkey: str, item
    ) -> np.ndarray:
        """
        Read a catalog X key as the coordinate of a frozen stack spectrum.

        A stack spectrum is a per-event quantity, so the X it was committed
        against is not the only one it can be plotted against: any key as
        long as the scan will do. Its axis keeps the frozen label either way.

        Parameters
        ----------
        info : KeyInfo
            The stack spectrum's description.
        xkey : str
            Catalog X key.
        item : slice
            Slice of the spectrum's one axis.

        Returns
        -------
        ndarray
            The X key's values, sliced like the spectrum.

        Raises
        ------
        ValueError
            If the spectrum is not 1-D or the X key is another length.
        """
        if info.ndim != 1:
            raise ValueError(
                f"stack spectrum {info.name!r} must be 1-D, got shape "
                f"{info.shape}"
            )
        full = np.asarray(self.read(xkey), dtype=float).ravel()
        if full.size != info.shape[0]:
            raise ValueError(
                f"X key {xkey!r} length {full.size} does not match "
                f"frozen spectrum {info.label!r} length {info.shape[0]}"
            )
        return np.atleast_1d(full[item])

    def block(
        self, plan: FetchPlan
    ) -> Tuple[xr.DataArray, List[xr.DataArray]]:
        """
        Return the block a plan asks for and its norms, cached.

        The sixth read method, and the only one that remembers anything. The
        cache is a collaborator this run owns and hands its own reads to, not
        a layer wrapped around it: there is no non-caching reader to wrap,
        because the reader is this class.

        Parameters
        ----------
        plan : FetchPlan
            What to read and which indices of it.

        Returns
        -------
        tuple
            ``(data, norms)``, one norm array per ``plan.norm_keys`` in order.
        """
        return self._cache.block(plan)

    def get_shape(self, key: str) -> Tuple[int, ...]:
        """
        Return storage shape for a catalog or frozen key.

        A view onto ``describe``, which is where the two sources are joined.
        It used to dispatch between them a second time and reach past the key
        table to the run when a key was missing from it, which meant a shape
        could come from three places and was checked in none of them.

        Parameters
        ----------
        key : str
            Data key.

        Returns
        -------
        tuple of int
            Storage shape.
        """
        return self.describe(key).shape

    def frozen_spectra(self) -> List[FrozenSpectrum]:
        """
        Return registered frozen synthetic spectra.

        Returns
        -------
        list of FrozenSpectrum
            Copy of the frozen spectrum list.
        """
        return list(self._frozen_spectra.values())

    def legend_label_for_ykey(self, ykey: str) -> str:
        """
        Return the matplotlib legend label for a Y data key.

        Parameters
        ----------
        ykey : str
            Catalog or synthetic Y key.

        Returns
        -------
        str
            Human-readable legend text.
        """
        info = self.key_table().get(ykey)
        if info is not None and info.synthetic:
            return f"{info.label}.{self.scan_id}"
        return f"{ykey}.{self.scan_id}"

    def register_frozen_spectrum(self, entry: FrozenSpectrum) -> str:
        """
        Register a frozen synthetic spectrum.

        Parameters
        ----------
        entry : FrozenSpectrum
            Frozen spectrum to register.

        Returns
        -------
        str
            Synthetic key.
        """
        self._frozen_spectra[entry.key] = entry
        self._invalidate_key_table()
        self.available_keys_changed.emit()
        self.frozen_spectra_changed.emit()
        return entry.key

    def remove_frozen_spectrum(self, key: str) -> bool:
        """
        Remove a frozen synthetic spectrum by key.

        Parameters
        ----------
        key : str
            Synthetic key to remove.

        Returns
        -------
        bool
            True when a spectrum was removed.
        """
        if key not in self._frozen_spectra:
            return False
        del self._frozen_spectra[key]
        self._invalidate_key_table()
        self.available_keys_changed.emit()
        self.frozen_spectra_changed.emit()
        return True

    def _update_available_keys(self) -> None:
        """Update catalog keys from the run; preserve synthetic keys."""
        new_keys = self._run.available_keys
        print_debug(
            "RunSource._update_available_keys",
            f"available_keys for {self.uid}: {new_keys} from run {id(self._run)}",
            "run"
)
        keys_changed = set(new_keys) != set(self._catalog_keys)
        self._catalog_keys = new_keys
        self._invalidate_key_table()
        if keys_changed:
            self.available_keys_changed.emit()

    def _on_data_changed(self) -> None:
        """Handle data changes from RunData service."""
        print_debug("RunSource._on_data_changed", f"Data changed for {self.uid}", "run")
        # Directly, and before the signal: traces refetch on it.
        self._cache.clear()
        self._update_available_keys()
        self.data_changed.emit()

    @property
    def dynamic_update(self) -> bool:
        """
        Whether dynamic updates are enabled for this run.

        Returns
        -------
        bool
            True when live data updates are enabled.
        """
        return self._dynamic

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
        """Clean up resources and disconnect signals."""
        print_debug("RunSource.cleanup", f"Cleaning up run {self.uid}", "run")
        try:
            self._disconnect_run()
        except Exception as e:
            print(f"Warning: Error disconnecting run signals: {e}")
