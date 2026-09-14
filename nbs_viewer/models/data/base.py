from typing import Dict, List, Tuple, Any, Optional
from qtpy.QtCore import QObject, Signal, Slot
import logging
import numpy as np
import xarray as xr

from .array_contract import labelled_array, surviving_dims
from .key_info import KeyInfo
from asteval import Interpreter
import time
from nbs_viewer.utils import print_debug


def render_mode_hint_for(plot_hints: dict, ykey: str) -> Optional[str]:
    """
    Read an explicit render_mode override from Bluesky plot hints.

    Lives in the data layer because it reads run metadata and nothing
    else; it sat in the plot layer's geometry module only because its one
    caller was there, which made the key table's render hint a plot-layer
    fact about a run-level record.

    Parameters
    ----------
    plot_hints : dict
        Plot hints dictionary from run metadata.
    ykey : str
        Y data key to match.

    Returns
    -------
    str or None
        ``image``, ``mesh``, or None if no override.
    """
    for field_list in plot_hints.values():
        if not isinstance(field_list, list):
            continue
        for field in field_list:
            if not isinstance(field, dict):
                continue
            signal = field.get("signal")
            if isinstance(signal, list):
                signal = signal[-1] if signal else None
            if signal == ykey:
                mode = field.get("render_mode")
                if mode in ("image", "mesh"):
                    return mode
    return None


class CatalogRun(QObject):
    """
    Base class for catalog run implementations.

    Provides data access, caching, and transformation services for a run.
    Can be shared between multiple models that need access to the same
    transformed data.

    Parameters
    ----------
    run : object
        The underlying run object
    key : str
        The key/identifier for this run
    catalog : object, optional
        The catalog containing this run
    dynamic : bool, optional
        Whether to enable dynamic updates, by default False
    """

    data_changed = Signal()
    keys_loading = Signal()
    keys_ready = Signal(object)
    keys_error = Signal(object)

    def __init__(self, run, key, catalog=None, dynamic=False, parent=None):
        super().__init__(parent)
        self._run = run
        self._key = key
        self._catalog = catalog
        self.metadata = {}

        # Dynamic updates
        self._dynamic = False

        # Initialize empty key list - subclasses can update later
        self._available_keys = []
        # Async key init state
        self._keys_init_started = False
        self._keys_initialized = False

        # Connect data_changed to cache clearing
        self.data_changed.connect(self._on_data_changed)

        # Connect async key init signals to state updates (queued across threads)
        self.keys_ready.connect(self._on_keys_ready)
        self.keys_error.connect(self._on_keys_error)

        # Set dynamic state last since it may trigger signals
        self.set_dynamic(dynamic)

    def __repr__(self):
        """
        Returns a string representation of the CatalogRun object.

        Returns
        -------
        str
            String representation including class name and run info
        """
        return f"{self.__class__.__name__}({self._run!r})"

    def setup(self):
        """
        Set up the run object.

        This method should initialize all attributes defined in METADATA_KEYS
        and any other required state.
        """
        pass

    def refresh(self):
        """
        Refresh the run data from its source.

        Default implementation reloads from catalog. Subclasses may override
        for different refresh behavior.
        """
        self._run = self._catalog[self._key]
        self.setup()

    def getData(
        self, key: str, indices: Optional[Tuple[int, ...]] = None
    ) -> np.ndarray:
        """
        Get data for a given key.

        Parameters
        ----------
        key : str
            The key to get data for

        Returns
        -------
        np.ndarray
            The data for the given key
        """
        pass

    def getShape(self, key: str) -> Tuple[int, ...]:
        """
        Get the shape of data for a given key.

        Parameters
        ----------
        key : str
            The key to get shape for

        Returns
        -------
        tuple
            The shape of the data
        """
        pass

    def getPlotHints(self) -> Dict[str, Any]:
        """
        Get plot hints for this run.

        Returns
        -------
        dict
            Plot hints dictionary. Default implementation returns empty dict.
        """
        return {}

    # ------------------------------------------------------------------
    # The data contract: one static description, one labelled array.
    # ------------------------------------------------------------------

    def describe(self, key: str) -> KeyInfo:
        """
        Return static facts about one key, reading no data.

        This is the single way to ask what a key is. ``getShape``,
        ``getPlotHints`` and the key table each used to answer part of it, and
        a fourth call answered a *selection-dependent* version -- which is why
        the answers could disagree. The description here depends on the key
        alone, so it can be cached for the life of the run.

        Parameters
        ----------
        key : str
            Data key name.

        Returns
        -------
        KeyInfo
            Name, label, ``{axis name: length}``, the render-mode hint, and
            which key supplies each axis's coordinate.

        Raises
        ------
        ValueError
            If this source disagrees with its own arrays about their rank or
            names its axes ambiguously. Enforced here rather than patched
            downstream: a consumer that pads a short name list cannot tell a
            missing name from a wrong one.
        """
        dims, _ = self.get_dims(key, [])
        shape = tuple(self.getShape(key))
        return KeyInfo.from_dims(
            key,
            dims,
            shape,
            hinted=True,
            render_hint=self.render_mode_hint(key),
            coords=self._coordinate_sources(key, tuple(dims), shape),
        )

    def _coordinate_sources(
        self, key: str, dims: Tuple[str, ...], shape: Tuple[int, ...]
    ) -> Dict[str, Tuple[str, ...]]:
        """
        Decide which key path supplies each dimension's coordinate.

        Two sources, both metadata. A plot hint's ``axes`` name the key's
        axes in order, skipping the event axis -- which is how a detector
        publishes its bin energies beside its spectrum. Failing that, a 1-D
        key of the dimension's own name and length is its coordinate, which is
        how a labelled Bluesky run spells ``time``. The hint wins where both
        exist, because it is a statement about this key and not about the run.

        A one-element path names a data key and is checked here: one that is
        missing, not 1-D, or of another length would only fail at load. A
        longer path is walked by :meth:`getAxis` -- config data, typically --
        and can only be checked when read.

        Parameters
        ----------
        key : str
            Data key being described.
        dims : tuple of str
            Its dimension names.
        shape : tuple of int
            Its shape.

        Returns
        -------
        dict of str to tuple of str
            Coordinate key path by dimension, for those that have one.
        """
        available = set(self.available_keys or [])

        def names_a_coordinate(name: str, length: int, dim: Optional[str]) -> bool:
            if name not in available:
                return False
            try:
                coord_dims, _ = self.get_dims(name, [])
                coord_shape = tuple(self.getShape(name))
            except Exception:
                return False
            if coord_shape != (length,):
                return False
            return dim is None or tuple(coord_dims) == (dim,)

        detector_dims = [dim for dim in dims if dim != "time"]
        hints = list(self.getAxisHints().get(key, []))
        sources: Dict[str, Tuple[str, ...]] = {}
        for dim, length in zip(dims, shape):
            if dim in detector_dims:
                position = detector_dims.index(dim)
                path = (
                    tuple(hints[position]) if position < len(hints) else ()
                )
                if len(path) > 1 or (
                    len(path) == 1 and names_a_coordinate(path[0], length, None)
                ):
                    sources[dim] = path
                    continue
            if names_a_coordinate(dim, length, dim):
                sources[dim] = (dim,)
        return sources

    def load(
        self,
        key: str,
        slice_info: Optional[tuple] = None,
        *,
        coords: bool = True,
    ) -> xr.DataArray:
        """
        Return the key's array with its dimensions named and coordinates on it.

        Names alone were nearly enough -- the pipeline matches a normalization
        array to its detector by axis name -- but not quite. With fly-scanned
        data every detector is its own timestream, so two keys whose axis is
        named ``time`` no longer share that axis, and two equal-length streams
        sampled out of phase would divide silently at mismatched times. A
        coordinate makes that an ``AlignmentError`` under
        ``arithmetic_join="exact"``.

        A dimension gets the coordinate :meth:`describe` says supplies it: a
        1-D key of its own name and length -- which is how a labelled Bluesky
        run spells ``time`` and a detector-internal axis like
        ``tes_mca_energies`` -- or the key a plot hint points at. An axis with
        neither keeps its bare name, where the join degrades to the shape
        check it was before.

        What is plotted *against* is not decided here. The X selection is a
        coordinate choice the plot layer makes on this array, so the load is
        the same whatever is selected.

        Parameters
        ----------
        key : str
            Data key name.
        slice_info : tuple, optional
            Per-axis slice tuple. Integer items index an axis away; the
            coordinates are sliced with the data.
        coords : bool, optional
            Attach coordinates. Each one costs a read of its own key, so a
            caller that drops the labels immediately -- everything upstream of
            step 4 -- asks for none and still gets the dimension names and the
            checks that come with them.

        Returns
        -------
        xarray.DataArray
            Labelled array for the (possibly sliced) key.
        """
        info = self.describe(key)
        values = np.asarray(self.getData(key, slice_info))
        dims = surviving_dims(info.dims, slice_info)
        if len(dims) != values.ndim:
            raise ValueError(
                f"key {key!r} sliced with {slice_info!r} returned rank "
                f"{values.ndim} against {len(dims)} surviving names {dims}"
            )
        return labelled_array(
            values,
            dims,
            coords=self._coords_for(info, slice_info) if coords else {},
            name=key,
        )

    def load_coords(
        self, key: str, slice_info: Optional[tuple] = None
    ) -> Dict[str, np.ndarray]:
        """
        Return the coordinates :meth:`load` would attach, without the values.

        What a consumer needs to label an axis -- a slider readout, the frame
        an ROI is compiled against -- is a 1-D read of the key that supplies
        its coordinate, and reading a camera stack to get one would be
        absurd. It is a call of its own rather than a ``load`` of the
        coordinate key because a plot hint can point outside the data keys:
        ``getAxis`` walks config paths.

        Parameters
        ----------
        key : str
            Data key name.
        slice_info : tuple, optional
            Per-axis slice tuple, as for :meth:`load`. An axis it indexes away
            has no coordinate to return.

        Returns
        -------
        dict of str to ndarray
            Coordinate values by dimension name, for the surviving dimensions
            that have one.
        """
        return self._coords_for(self.describe(key), slice_info)

    def _coords_for(
        self, info: KeyInfo, slice_info: Optional[tuple]
    ) -> Dict[str, np.ndarray]:
        """
        Read the coordinates a description names, sliced like the data.

        Parameters
        ----------
        info : KeyInfo
            Description of the key, naming each coordinate's source.
        slice_info : tuple, optional
            The slice applied to the data, so coordinates are sliced to match.

        Returns
        -------
        dict
            Coordinate arrays by dimension name, for those that resolve.
        """
        items = list(slice_info or ())
        coords: Dict[str, np.ndarray] = {}
        for axis, (dim, length) in enumerate(info.axes.items()):
            item = items[axis] if axis < len(items) else slice(None)
            path = info.coords.get(dim)
            if path is None or isinstance(item, (int, np.integer)):
                continue
            try:
                if len(path) == 1:
                    values = np.asarray(self.getData(path[0], (item,)))
                else:
                    # Read whole and sliced here: an axis-hint read is
                    # cached by path alone, whatever slice came with it.
                    values = np.asarray(self.getAxis(list(path)))[item]
            except Exception as ex:
                print_debug(
                    "CatalogRun._coords_for",
                    f"No coordinate for dimension {dim!r} from {path}: {ex}",
                    category="catalog",
                )
                continue
            # A source may clip an axis relative to its coordinate key --
            # CombinedRun does, to the shortest of its sources -- and a hint
            # path can only be checked once read. Attaching a mismatched
            # coordinate would raise, so the axis keeps its bare name and the
            # join falls back to a shape check.
            if values.ndim == 1 and values.shape[0] == len(range(length)[item]):
                coords[dim] = values
        return coords

    def render_mode_hint(self, key: str) -> Optional[str]:
        """
        Return a declared ``image`` / ``mesh`` override for one key.

        Parameters
        ----------
        key : str
            Data key name.

        Returns
        -------
        str or None
            The declared render mode, or None when the run declares none.
        """
        return render_mode_hint_for(self.getPlotHints(), key)

    def to_header(self) -> Dict[str, Any]:
        """
        Get a dictionary of metadata suitable for display in a header.

        Returns
        -------
        dict
            Dictionary of metadata key-value pairs
        """
        pass

    def to_row(self) -> List[Any]:
        """
        Returns a tuple of values corresponding to the METADATA_KEYS.

        Returns
        -------
        tuple
            Values for each metadata key
        """
        return tuple(getattr(self, attr, None) for attr in self.METADATA_KEYS)

    def getRunKeys(self) -> Tuple[Dict[int, List[str]], Dict[int, List[str]]]:
        """
        Get organized x and y keys for plotting.

        Returns
        -------
        Tuple[Dict[int, List[str]], Dict[int, List[str]]]
            A tuple of (xkeys, ykeys) where each is a dictionary mapping
            dimension (int) to list of keys (str)
        """
        pass

    def getAxis(self, keys: List[str]) -> np.ndarray:
        """
        Get axis data for a sequence of keys.

        Parameters
        ----------
        keys : List[str]
            Sequence of keys to traverse

        Returns
        -------
        np.ndarray
            The axis data
        """
        pass

    def get_default_selection(self) -> Tuple[List[str], List[str], List[str]]:
        """
        Get default key selection for this run type.

        Each run type may have different conventions for what should be
        plotted by default. This method encapsulates that run-specific logic.

        Returns
        -------
        Tuple[List[str], List[str], List[str]]
            Default (x_keys, y_keys, norm_keys) for this run
        """
        # print("Getting Default Selection")
        return ([], [], [])

    def scanFinished(self) -> bool:
        """
        Return whether this run has stopped acquiring.

        Default True: a run with no notion of progress -- a stored catalog
        run, an in-memory run, a synthetic one -- is finished by definition.
        Sources that stream (``BlueskyRun``, ``KafkaRun``) override this.

        Freezing reads this: a snapshot of a run that is still growing would
        not be a stable reference, which is the whole point of a frozen run.

        Returns
        -------
        bool
            True when no more data is expected.
        """
        return True

    def getAvailableKeys(self):
        """
        Get available data keys sorted by dimension and type.

        Returns
        -------
        List[str]
            List of available data keys, sorted as:
            1. x keys dimension 0 (e.g. time)
            2. x keys dimension 1 (e.g. motor positions)
            3. y keys dimension 1 (e.g. detector signals)
            4. y keys dimension 2+ if any
        """
        # Get organized keys from getRunKeys
        xkeys, ykeys = self.getRunKeys()
        # Initialize sorted key list
        sorted_keys = []

        # Add x keys in order of dimension
        for dim in sorted(xkeys.keys()):
            for key in sorted(xkeys[dim]):
                if key not in sorted_keys:
                    sorted_keys.append(key)

        # Add y keys in order of dimension
        for dim in sorted(ykeys.keys()):
            for key in sorted(ykeys[dim]):
                if key not in sorted_keys:
                    sorted_keys.append(key)
        print_debug(
            "CatalogRun.getAvailableKeys",
            f"Sorted keys: {sorted_keys} for run {self.uid}: {id(self)}",
            "run",
        )
        return sorted_keys

    def getAxisHints(self) -> Dict[str, List[List[str]]]:
        """
        Get axis hints from plot hints.

        Returns
        -------
        Dict[str, List[List[str]]]
            Dictionary mapping signal names to lists of axis key sequences
        """
        hints = {}
        for dlist in self.getPlotHints().values():
            for d in dlist:
                if isinstance(d, dict) and "axes" in d:
                    signal = d["signal"]
                    if isinstance(signal, list):
                        signal = signal[-1]
                    hints[signal] = d["axes"]
        return hints

    def _get_flattened_fields(self, fields: list) -> List[str]:
        """
        Get flattened list of fields from hints.

        Parameters
        ----------
        fields : list
            List of fields from hints

        Returns
        -------
        List[str]
            Flattened list of field names
        """
        flattened = []
        for field in fields:
            if isinstance(field, dict):
                if "signal" in field:
                    signal = field["signal"]
                    if isinstance(signal, list):
                        flattened.extend(signal)
                    else:
                        flattened.append(signal)
            else:
                flattened.append(field)
        return flattened

    def get_hinted_keys(self) -> Dict[int, List[str]]:
        """
        Get filtered keys based on NBS run's hints.

        Uses plot hints to filter keys, focusing on primary signals
        and their dimensions.

        Returns
        -------
        Dict[int, List[str]]
            Keys filtered by hints, organized by dimension
        """
        hints = self.getPlotHints()
        _, all_keys = self.getRunKeys()

        # Collect hinted fields
        hinted = []
        for fields in hints.values():
            for field in fields:
                if isinstance(field, dict):
                    if "signal" in field:
                        signal = field["signal"]
                        if isinstance(signal, list):
                            hinted.extend(signal)
                        else:
                            hinted.append(signal)
                else:
                    hinted.append(field)

        # Filter keys by dimension
        filtered = {}
        for dim, key_list in all_keys.items():
            filtered[dim] = [key for key in key_list if key in hinted]

        return filtered

    def set_dynamic(self, enabled):
        """Enable/disable dynamic updates."""
        if enabled != self._dynamic:
            self._dynamic = enabled
            if enabled:
                # Connect to data update signals
                pass  # Implementation depends on data source
            else:
                # Disconnect signals
                pass
            self.clear_caches()

    def _on_data_changed(self):
        """Clear caches when data changes without re-emitting signal."""
        pass

    def clear_caches(self):
        """Clear all data caches and notify of change."""
        self.data_changed.emit()

    def _compute_available_keys(self) -> list:
        """Compute available keys (no signals, safe for background thread)."""
        return self.getAvailableKeys() or []

    def _initialize_keys(self):
        """Initialize available keys synchronously on the calling thread."""
        # Mark as started and notify listeners
        self._keys_init_started = True
        self.keys_loading.emit()
        try:
            self._available_keys = self._compute_available_keys()
            self.keys_ready.emit(self._available_keys)
        except Exception as e:
            logging.getLogger("nbs_viewer.catalog").exception("Error initializing keys")
            self._available_keys = []
            self.keys_error.emit(str(e))
        finally:
            self.data_changed.emit()

    @Slot(object)
    def _on_keys_ready(self, keys) -> None:
        """Apply computed keys on the main thread and notify listeners."""
        print_debug(
            "CatalogRun._on_keys_ready",
            f"Keys ready for {self.uid}: {keys}",
            "run",
        )
        self._available_keys = keys or []
        self._keys_initialized = True
        self.data_changed.emit()

    @Slot(object)
    def _on_keys_error(self, message) -> None:
        logging.getLogger("nbs_viewer.catalog").warning(
            "Key initialization error for %s: %s", self._key, message
        )

    @property
    def available_keys(self) -> List[str]:
        """Get the list of available keys."""
        return self._available_keys

    @property
    def display_name(self) -> str:
        """Get the display name of the run."""
        return str(self)
