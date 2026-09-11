from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Any, Union

from qtpy.QtCore import QObject, Signal
import numpy as np
import xarray as xr

from ..data.base import CatalogRun
from ..data.key_info import KeyInfo
from ..data.key_source import CatalogKey
from .frozen_spectrum import FrozenSpectrum
from .run_fetch import RunFetch
from .run_identity import RunIdentity
from nbs_viewer.utils import print_debug


class RunSource(QObject):
    """
    The union of a catalog run and its frozen synthetic keys, under one key
    space, plus the key table, identity and signals the plot layer needs.

    A :class:`CatalogRun` is one source of labelled arrays for a run's keys.
    This is a higher-level object rather than a near-duplicate of it, and
    :meth:`_source` is where the difference lives: one place decides which
    source holds a key, and everything else either delegates to what it
    returns or reads a fact off the key's description. Only one thing needs
    both sources at once -- a frozen stack spectrum plotted against the
    catalog's X keys -- and that is this class's own business.

    The RunSource surface is ``key_table``, ``identity``, ``describe``,
    ``load``, ``read``, ``plot_axis_names`` and ``load_axes``, plus
    ``fetch``, which turns a plot request into a bundle. Selection,
    visibility, and transform live on :class:`PlotSession`.

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
        # Before the keys load, because loading them clears its cache.
        self._fetch = RunFetch(self)
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
    def fetch(self) -> RunFetch:
        """
        The fetch for this run's keys: plot request in, plot bundle out.

        Handed out rather than forwarded, so callers ask it directly.
        """
        return self._fetch

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
        self._fetch.clear()

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

    def identity(self) -> RunIdentity:
        """
        Return a snapshot of run identity fields for views.

        Returns
        -------
        RunIdentity
            uid, scan_id, plan_name, display_name, and metadata.
        """
        return RunIdentity(
            uid=str(self.uid),
            scan_id=str(self.scan_id),
            plan_name=str(self.plan_name),
            display_name=str(self.display_name),
            metadata=MappingProxyType(dict(self.metadata)),
        )

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

    def load(self, key: str, slice_info=None, *, coords: bool = True) -> xr.DataArray:
        """
        Return a labelled array for a catalog or frozen key.

        The one place the two sources are joined. Both answer ``load``
        themselves, so this dispatches once rather than unpacking two
        differently-shaped answers.

        Parameters
        ----------
        key : str
            Data key.
        slice_info : tuple, optional
            Per-axis slice tuple.
        coords : bool, optional
            Attach coordinate values as well as dimension names.

        Returns
        -------
        xarray.DataArray
            Storage array with named dimensions, and its coordinates when
            asked for.
        """
        return self._source(key).load(slice_info, coords=coords)

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

    def plot_axis_names(
        self, ykey: str, xkeys: Sequence[str]
    ) -> Tuple[str, ...]:
        """
        Return the axis names to plot a key under a given X selection.

        Deliberately *not* part of ``describe``, which is static. This answers
        a different question, and the difference is the one bug 15 was made
        of: a key's dimensions are fixed, while the selected X key renames the
        event axis after whatever is being plotted against it. A UCAL run says
        the scanned motor is a key *on* the event axis rather than a name of
        it, so the rename is a display choice rather than a fact about the
        array.

        It is kept because the projection rule locates the X key's storage
        axis *by name* -- default axis order would stop working without it.
        Step 4 replaces it: with coordinates on the array, choosing what to
        plot against is ``swap_dims`` on a non-dimension coordinate, and the
        dimension keeps its own name throughout. Each source answers it: a
        frozen payload's axes are whatever the reduction produced, so the
        selection does not reach them.

        Parameters
        ----------
        ykey : str
            Y data key.
        xkeys : sequence of str
            Selected X-axis keys.

        Returns
        -------
        tuple of str
            One name per storage axis.
        """
        return self._source(ykey).plot_axis_names(list(xkeys))

    def load_axes(
        self, ykey: str, xkeys: Sequence[str], slice_info=None
    ) -> Tuple[List[np.ndarray], List[str], Dict[str, Any]]:
        """
        Return real axis coordinates for a catalog or frozen Y key.

        Stack spectra resolve X from the selected catalog keys so the
        same frozen Y can be plotted against any scan-length independent
        (``time``, motor position, etc.). Local profiles keep the frozen
        profile-axis coordinates from the reduction.

        Parameters
        ----------
        ykey : str
            Y data key.
        xkeys : sequence of str
            Selected X-axis keys.
        slice_info : tuple, optional
            Per-axis slice tuple.

        Returns
        -------
        tuple
            ``(axis_arrays, axis_names, associated_data)``.

        Raises
        ------
        ValueError
            If a catalog X key length does not match the frozen spectrum.
        """
        xkey_list = list(xkeys)
        source = self._source(ykey)
        # The one thing that is genuinely this class's own business rather
        # than either source's: a frozen Y plotted against the *catalog's* X
        # keys is the only case that needs both at once. The branch is on the
        # kind a source declares itself to be, not on which class it is.
        if source.kind == "stack_spectrum" and xkey_list:
            return self._stack_spectrum_dimension_axes(
                source, xkey_list, slice_info
            )
        return source.get_dimension_axes(xkey_list, slice_info)

    def _stack_spectrum_dimension_axes(
        self,
        entry: FrozenSpectrum,
        xkeys: List[str],
        slice_info=None,
    ) -> Tuple[List[np.ndarray], List[str], Dict[str, Any]]:
        """
        Resolve catalog X coordinates for a frozen stack spectrum.

        Parameters
        ----------
        entry : FrozenSpectrum
            Registered stack-spectrum entry.
        xkeys : list of str
            Selected catalog X keys.
        slice_info : tuple, optional
            Per-axis slice applied to Y and each X array.

        Returns
        -------
        tuple
            ``(axis_arrays, axis_names, associated_data)``.

        Raises
        ------
        ValueError
            If any X key is not length-compatible with the frozen Y.
        """
        y_full = np.asarray(entry.get_data(None))
        if y_full.ndim != 1:
            raise ValueError(
                f"stack spectrum {entry.key!r} must be 1-D, got shape {y_full.shape}"
            )
        n_full = int(y_full.shape[0])
        x_slice = slice(None)
        if slice_info is not None and len(slice_info) > 0:
            x_slice = slice_info[0]
        axis_arrays: List[np.ndarray] = []
        axis_names: List[str] = []
        for xkey in xkeys:
            raw_full = np.asarray(self.read(xkey), dtype=float).ravel()
            if raw_full.size != n_full:
                raise ValueError(
                    f"X key {xkey!r} length {raw_full.size} does not match "
                    f"frozen spectrum {entry.label!r} length {n_full}"
                )
            raw = np.atleast_1d(np.asarray(raw_full[x_slice], dtype=float))
            axis_arrays.append(raw)
            axis_names.append(xkey)
        return axis_arrays, axis_names, {}

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
            "run",
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
        self._fetch.clear()
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
