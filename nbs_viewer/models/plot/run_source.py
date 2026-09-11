from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Any, Union

from qtpy.QtCore import QObject, Signal
import numpy as np
import xarray as xr
import time as ttime

from ..data.base import CatalogRun
from ..data.key_info import KeyInfo
from ..data.key_source import CatalogKey
from .frozen_spectrum import FrozenSpectrum
from .run_identity import RunIdentity
from .plot_axes import PlotAxes
from .plot_bundle import (
    apply_normalization,
    apply_transform,
    mask_to_profile,
    reduce_before_mask,
    reduce_cached_plane,
    reduce_to_plane,
    slice_info_for_key,
)
from .plot_geometry import (
    PlaneOrientation,
    PlotBundle,
    build_plot_bundle,
    classify_render_mode,
    display_flips,
)
from ..data.array_contract import labelled_array
from .plot_request import FetchPlan, PlotRequest, plan_fetch
from .plot_view_frame import PlotViewFrame, frame_for_plane
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
    ``load``, ``read``, ``plot_axis_names``, ``load_axes``, and
    ``get_plot_bundle``. Selection, visibility, and transform live on
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
        # One loaded block, kept so a transform edit -- or an ROI moved
        # inside a box already read -- re-runs only the tail of the
        # pipeline. One entry, not a map: it covers the transform-edit case
        # and the still-on-this-plane case, and it cannot grow.
        self._block: Optional[Tuple] = None
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
        self._block = None

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
        self._block = None
        self._update_available_keys()
        self.data_changed.emit()

    def _plane_frame(
        self, request: PlotRequest
    ) -> Optional[PlotViewFrame]:
        """
        Derive the display frame of the request's full plot plane.

        An ROI is geometry in data coordinates, so something has to say which
        cell each coordinate falls in. That is a pure function of the plane's
        shape, its two coordinate arrays and the render mode, all of which are
        1-D and cheap to read, so the frame is derived here rather than passed
        in from whichever bundle the canvas happened to have drawn.

        Parameters
        ----------
        request : PlotRequest
            Request whose ``view`` describes the plane.

        Returns
        -------
        PlotViewFrame or None
            Frame of the uncropped plane, or None when there is no region to
            compile against it.
        """
        if request.region is None:
            return None
        plane_axes = request.plane_axes
        if plane_axes is None:
            raise ValueError("cannot resolve the plot plane for an ROI fetch")
        row_axis, col_axis = plane_axes
        axes, names, _extra = self.load_axes(
            request.ykey, list(request.xkeys), request.view.base_slice()
        )
        rows = np.atleast_1d(np.asarray(axes[row_axis]))
        cols = np.atleast_1d(np.asarray(axes[col_axis]))
        plane_shape = (int(rows.size), int(cols.size))
        render_mode = classify_render_mode(
            plane_shape,
            [rows, cols],
            render_mode_hint=self._render_hint(request.ykey),
        )
        row_reversed, col_reversed = display_flips(rows, cols, render_mode)
        return frame_for_plane(
            plane_shape,
            rows[::-1] if row_reversed else rows,
            cols[::-1] if col_reversed else cols,
            [names[row_axis], names[col_axis]],
            render_mode_hint=render_mode,
            row_reversed=row_reversed,
            col_reversed=col_reversed,
        )

    def _render_hint(self, ykey: str) -> Optional[str]:
        """
        Return the declared render mode for a key, if any.

        It is on the description, which both sources fill in -- a frozen
        payload declares none. This used to read the key table and then fall
        back to the run's plot hints, which meant two sources of one answer
        that had to agree.

        Parameters
        ----------
        ykey : str
            Y data key.

        Returns
        -------
        str or None
            ``image`` or ``mesh`` from the key table or plot hints.
        """
        return self.describe(ykey).render_hint

    def _plane_render_mode(
        self,
        ykey: str,
        data: xr.DataArray,
        axes: PlotAxes,
    ) -> Optional[str]:
        """
        Classify the render mode of the loaded plot plane.

        Classified before any reduction, because the orientation decision
        depends on it and orientation happens immediately after the load. The
        answer is recorded on the :class:`PlaneOrientation` so the packing
        step does not classify a second time.

        Parameters
        ----------
        ykey : str
            Y data key, for the plot-hint lookup.
        data : xarray.DataArray
            Loaded block, before orientation.
        axes : PlotAxes
            Named view, for the plane's dimension names.

        Returns
        -------
        str or None
            ``image`` or ``mesh``, or the bare hint when the plane is not in
            the loaded array.
        """
        hint = self._render_hint(ykey)
        plane = axes.plane
        if plane is None or any(dim not in data.dims for dim in plane):
            return hint
        return classify_render_mode(
            tuple(data.sizes[dim] for dim in plane),
            [np.asarray(data.coords[dim].values) for dim in plane],
            render_mode_hint=hint,
        )

    def _view_by_name(self, request: PlotRequest) -> PlotAxes:
        """
        Name the request's projection, once, before anything is read.

        Every stage after the load takes this and never sees a storage axis
        index again. It is derived from the request alone: which dimension
        plays which role, and what order they end up in, are decided by the
        view and the X selection rather than by anything the data turns out
        to be.

        Parameters
        ----------
        request : PlotRequest
            Frozen plot description.

        Returns
        -------
        PlotAxes
            The projection, by dimension name.
        """
        return PlotAxes.of(
            request.view,
            self.plot_axis_names(request.ykey, request.xkeys),
        )

    def _norm_arrays(
        self,
        request: PlotRequest,
        plan: FetchPlan,
        axes: PlotAxes,
        data: xr.DataArray,
        orientation: PlaneOrientation,
    ) -> List[xr.DataArray]:
        """
        Read each normalization key, labelled and oriented to match the block.

        Normalization runs immediately after the orientation and before any
        SUM or MEAN, because that is the physically right order: a flat field
        divides per pixel and only then is summed.

        A catalog norm shares axis *names* with the block, so it takes the
        block's slice on the axes it has and is flipped the same way -- a norm
        divided into an image upside down is a silent wrong answer. A frozen
        synthetic norm shares no name with anything: it is a per-event
        quantity that took the block's own slice, so its axes correspond in
        order to the block's leading axes and are named after them. Without
        that renaming xarray would broadcast it into a *new* dimension instead
        of dividing element by element -- the hand-written aligner this
        replaced fell back to matching by shape, which is the same rule stated
        as a coincidence.

        Parameters
        ----------
        request : PlotRequest
            Supplies norm keys and X keys.
        plan : FetchPlan
            Load slices used for the Y key.
        axes : PlotAxes
            Named view of the Y key.
        data : xarray.DataArray
            The oriented block, for its dimension names.
        orientation : PlaneOrientation
            Which plane axes were flipped.

        Returns
        -------
        list of xarray.DataArray
            One labelled array per normalization key.
        """
        if not request.norm_keys:
            return []
        slice_info = plan.slice_info
        xkeys = list(request.xkeys)
        reversed_dims = set(orientation.reversed_dims(axes.plane))
        norms: List[xr.DataArray] = []
        for norm_key in request.norm_keys:
            if self.describe(norm_key).synthetic:
                values = self.read(norm_key, slice_info)
                norms.append(
                    xr.DataArray(values, dims=list(data.dims[: values.ndim]))
                )
                continue
            norm_names = list(self.plot_axis_names(norm_key, xkeys))
            key_slice = slice_info_for_key(
                slice_info, list(axes.names), norm_names
            )
            values = self.read(norm_key, key_slice)
            dims = [
                name
                for name, item in zip(norm_names, key_slice)
                if not isinstance(item, (int, np.integer))
            ]
            norm = xr.DataArray(values, dims=dims)
            for dim in dims:
                if dim in reversed_dims:
                    norm = norm.isel({dim: slice(None, None, -1)})
            norms.append(norm)
        return norms

    @staticmethod
    def _contained_window(
        cached: Sequence, wanted: Sequence
    ) -> Optional[List[Optional[Tuple[int, Optional[int]]]]]:
        """
        Locate a wanted load inside one already performed.

        The containment half of the fetch comparison: shrinking a crop, or
        moving an ROI inside a box already read, asks for a sub-block of what
        is in memory and needs no round trip.

        Parameters
        ----------
        cached : sequence
            Per-storage-axis load items of the block held.
        wanted : sequence
            Per-storage-axis load items now wanted.

        Returns
        -------
        list or None
            None when the wanted load is not contained. Otherwise one entry
            per storage axis: None for an axis needing no narrowing, else
            ``(start, stop)`` offsets into the cached block, ``stop`` None
            meaning "to the end".
        """
        if len(cached) != len(wanted):
            return None
        windows: List[Optional[Tuple[int, Optional[int]]]] = []
        for have, want in zip(cached, wanted):
            if isinstance(have, int) or isinstance(want, int):
                if have != want:
                    return None
                windows.append(None)
                continue
            have_start = 0 if have.start is None else int(have.start)
            have_stop = None if have.stop is None else int(have.stop)
            want_start = 0 if want.start is None else int(want.start)
            want_stop = None if want.stop is None else int(want.stop)
            if want_start < have_start:
                return None
            if have_stop is not None and (
                want_stop is None or want_stop > have_stop
            ):
                return None
            if want_start == have_start and want_stop == have_stop:
                windows.append(None)
                continue
            windows.append(
                (
                    want_start - have_start,
                    None if want_stop is None else want_stop - have_start,
                )
            )
        return windows

    @staticmethod
    def _block_cache_key(request: PlotRequest) -> Tuple:
        """
        What, besides the load slices, decides the contents of a block.

        Returns
        -------
        tuple
            Y key, x keys and norm keys. The uid is implied by the run.
        """
        return (request.ykey, request.xkeys, request.norm_keys)

    def _block_for_plan(
        self, cache_key: Tuple, plan: FetchPlan, axes: PlotAxes
    ) -> Optional[Tuple[xr.DataArray, PlaneOrientation]]:
        """
        Serve an oriented, normalized block from memory if one covers it.

        Parameters
        ----------
        cache_key : tuple
            Key from :meth:`_block_cache_key`.
        plan : FetchPlan
            Plan the caller is about to execute.
        axes : PlotAxes
            Named view, for mapping a storage axis to its dimension.

        Returns
        -------
        tuple or None
            ``(data, orientation)`` narrowed to ``plan``, or None when a read
            is needed.
        """
        if self._block is None:
            return None
        held_key, held_plan, data, orientation = self._block
        if held_key != cache_key or held_plan.plane_axes != plan.plane_axes:
            return None
        windows = self._contained_window(held_plan.slice_info, plan.slice_info)
        if windows is None:
            return None

        reversed_dims = set(orientation.reversed_dims(axes.plane))
        for storage_axis, window in enumerate(windows):
            if window is None:
                continue
            dim = axes.names[storage_axis]
            if dim not in data.dims:
                continue
            length = data.sizes[dim]
            start, stop = window
            stop = length if stop is None else stop
            if dim in reversed_dims:
                # The block was flipped along this axis at load, so the
                # storage window sits at the mirrored position in it.
                lo, hi = length - stop, length - start
            else:
                lo, hi = start, stop
            data = data.isel({dim: slice(lo, hi)})
        return data, orientation

    def _load_block(
        self, request: PlotRequest, plan: FetchPlan, axes: PlotAxes
    ) -> Tuple[xr.DataArray, PlaneOrientation]:
        """
        Read, label, orient and normalize the block a plan asks for.

        The stages that depend only on the fetch plan, so that the ones that
        do not -- reduce, transform, mask -- can be re-run without a read.

        This is also the boundary where storage axis indices stop. Everything
        it returns is addressed by dimension name.

        Parameters
        ----------
        request : PlotRequest
            Request being served.
        plan : FetchPlan
            Load slices for it.
        axes : PlotAxes
            Named view of the Y key.

        Returns
        -------
        tuple
            ``(data, orientation)``.
        """
        slice_info = plan.slice_info
        ykey = request.ykey

        t0 = ttime.time()
        storage_coords, _names, _extra = self.load_axes(
            ykey, list(request.xkeys), slice_info
        )
        values = self.read(ykey, slice_info)
        t_load = ttime.time() - t0

        surviving = [
            axis
            for axis, item in enumerate(slice_info)
            if not isinstance(item, (int, np.integer))
        ]
        data = labelled_array(
            values,
            [axes.names[axis] for axis in surviving],
            coords={
                axes.names[axis]: np.asarray(storage_coords[axis])
                for axis in surviving
            },
            name=ykey,
        )

        render_mode = self._plane_render_mode(ykey, data, axes)
        reversed_axes = plan.reversed_axes_for(storage_coords, render_mode)
        plane_axes = plan.plane_axes or ()
        orientation = PlaneOrientation(
            render_mode=render_mode,
            row_reversed=bool(plane_axes and plane_axes[0] in reversed_axes),
            col_reversed=bool(plane_axes and plane_axes[1] in reversed_axes),
        )
        # One reversal per flipped axis, and the coordinate follows the data
        # because they are the same object. This replaced a flip of the array
        # by tensor axis plus a separate flip of a coordinate list by storage
        # axis, with a map between the two.
        for dim in orientation.reversed_dims(axes.plane):
            if dim in data.dims:
                data = data.isel({dim: slice(None, None, -1)})

        t0 = ttime.time()
        data = apply_normalization(
            data, self._norm_arrays(request, plan, axes, data, orientation)
        )
        t_norm = ttime.time() - t0

        print_debug(
            "RunSource._load_block",
            f"{ykey} shape={data.shape} "
            f"load={t_load:.4f}s norm={t_norm:.4f}s",
            category="plots",
        )
        return data, orientation

    def get_plot_bundle(
        self,
        request: PlotRequest,
        *,
        cached_plane: Optional[PlotBundle] = None,
        label: str = "",
    ) -> PlotBundle:
        """
        Load, orient, normalize, reduce, transform, mask and pack a request.

        The request is the whole description: the projection, the crop, and
        for an ROI the region, the profile axis and the spatial reduce. What
        the plot plane's coordinate frame is, and which storage indices to
        read, are both derived from it here.

        The stage order is the content of the pipeline:

        - Storage-to-display reorientation happens immediately after the
          load, so every later step sees display-ordered data and the
          renderer never reorders anything again.
        - Normalization happens next, on the whole block, so a norm key is
          divided in per element before anything is summed.
        - The transform runs on the finished plot plane, *before* the ROI
          mask. The user already sees ``f(y)`` on the image and draws the ROI
          on what they see, so summing the ROI must sum what they see.

        Load, orient and normalize depend only on the fetch plan, so their
        result is held: editing a transform, or moving an ROI inside a box
        already read, re-runs only the tail.

        Parameters
        ----------
        request : PlotRequest
            Frozen plot description.
        cached_plane : PlotBundle, optional
            Plot plane already in memory for ``request.view``. Used to skip
            rebuilding the plane an in-plane ROI profile reduces; ignored
            otherwise.
        label : str
            Optional display label for 1D ROI output.

        Returns
        -------
        PlotBundle
            Prepared plot payload for the view layer.
        """
        plane_axes = request.plane_axes

        # An ROI whose profile runs along an axis the plane already shows is
        # a reduction of the finished plane, so it is served by masking that
        # plane -- from memory when the caller has one, otherwise by building
        # it here. One implementation of masking a 2-D plane, and what it
        # masks is f(y), which is what the ROI was drawn on.
        if request.region is not None and request.profile_axis in (
            plane_axes or ()
        ):
            plane = cached_plane
            if plane is None or plane.ndim != 2:
                plane = self.get_plot_bundle(request.plane_request)
            return reduce_cached_plane(plane, request, label=label)

        axes = self._view_by_name(request)
        plan = plan_fetch(request, plane_frame=self._plane_frame(request))
        cache_key = self._block_cache_key(request)
        block = self._block_for_plan(cache_key, plan, axes)
        if block is None:
            block = self._load_block(request, plan, axes)
            self._block = (cache_key, plan) + block
        data, orientation = block

        t0 = ttime.time()
        if request.region is None:
            data = reduce_to_plane(data, axes)
            data = apply_transform(data, axes, request.transform)
        else:
            # Off-plane profile: the plane the user sees is one slice of the
            # block, so reduce to that stack, transform it, and only then
            # mask. The profile axis is read in full by plan_fetch. The
            # transform sees the plane's own coordinates either way, so ``x``
            # means the same thing here as when the plane itself is drawn.
            profile = axes.to_profile(
                request.profile_axis, request.spatial_reduce
            )
            data = reduce_before_mask(data, profile)
            data = apply_transform(data, profile, request.transform)
            data = mask_to_profile(
                data,
                profile,
                request.region,
                request.mask_mode,
                plan.region_frame,
            )
        t_reduce = ttime.time() - t0

        print_debug(
            "RunSource.get_plot_bundle",
            f"{request.ykey} shape={data.shape} "
            f"cached={self._block is not None} reduce={t_reduce:.4f}s",
            category="plots",
        )

        info = self.describe(request.ykey)
        if info.synthetic and data.ndim == 1:
            data = data.rename({data.dims[0]: label or info.label})
        return build_plot_bundle(data, orientation, request, label=label)

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
