from typing import Dict, List, Tuple, Any, Optional
from qtpy.QtCore import QObject, Signal, Slot
import logging
import numpy as np
from asteval import Interpreter
from nbs_viewer.utils import time_function
import time
from nbs_viewer.utils import print_debug


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
        # Caching
        self._plot_data_cache = {}
        self._dimensions_cache = {}

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

    def getDimensions(self, key: str) -> int:
        """
        Get number of dimensions for a key.

        Parameters
        ----------
        key : str
            The key to get dimensions for

        Returns
        -------
        int
            Number of dimensions
        """
        return len(self.getShape(key))

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
        self._plot_data_cache.clear()
        self._dimensions_cache.clear()

    def clear_caches(self):
        """Clear all data caches and notify of change."""
        self._plot_data_cache.clear()
        self._dimensions_cache.clear()
        self.data_changed.emit()

    def _compute_available_keys(self) -> list:
        """Compute available keys (no signals, safe for background thread)."""
        return self.getAvailableKeys() or []

    @time_function(
        function_name="CatalogRun._initialize_keys", category="DEBUG_CATALOG"
    )
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

    def analyze_slice_request(
        self, keys: List[str], slice_info: Optional[tuple] = None
    ) -> Dict[str, Any]:
        """
        Analyze shapes and determine appropriate slicing for each key.

        Parameters
        ----------
        keys : List[str]
            List of keys to analyze
        slice_info : tuple
            The requested slice information, e.g. (slice(None), 0, slice(None))

        Returns
        -------
        Dict[str, Any]
            {
                'plot_dims': int,  # Number of non-integer slice dimensions
                'keys': {
                    key_name: {
                        'shape': tuple,  # Original shape of the data
                        'getData_slice': tuple,  # Slice to pass to getData
                        'effective_shape': tuple,  # Shape with broadcasting
                        'output_shape': tuple  # Final shape after slicing
                    }
                    for key_name in keys
                }
            }
        """
        # Calculate plot dimensions from slice_info
        if slice_info is not None:
            plot_dims = sum(1 for s in slice_info if isinstance(s, slice))
        else:
            plot_dims = max(len(self.getShape(key)) for key in keys)

        result = {"plot_dims": plot_dims, "keys": {}}

        # Process each key
        for key in keys:
            shape = self.getShape(key)
            key_info = {"shape": shape}

            if slice_info is not None:
                # Generate getData slice - only include indices up to the data's dimensionality
                getData_slice = tuple(
                    s for i, s in enumerate(slice_info) if i < len(shape)
                )
                key_info["effective_slice"] = getData_slice

                # Calculate effective shape (with broadcasting)
                """
                if len(shape) == 1:
                    effective_shape = shape + (1,) * (max(0, plot_dims - 1))
                else:
                    effective_shape = shape
                key_info["effective_shape"] = effective_shape
                """

                # Calculate output shape
                # First get shape after getData slice
                sliced_shape = tuple(
                    1 if isinstance(s, int) else dim
                    for s, dim in zip(getData_slice, shape)
                )
                # Then add broadcasting dimensions if needed
                if len(shape) == 1 and plot_dims > 1:
                    output_shape = sliced_shape + (1,) * (plot_dims - 1)
                else:
                    output_shape = sliced_shape
                key_info["output_shape"] = output_shape

            else:
                # No slicing
                key_info.update(
                    {
                        "effective_slice": None,
                        "output_shape": shape,
                    }
                )

            result["keys"][key] = key_info

        return result

    @time_function(function_name="CatalogRun.analyze_dimensions")
    def analyze_dimensions(self, ykey: str, xkeys: List[str] = []) -> Dict[str, Any]:
        """
        Analyze dimensions for a given y-key and set of x-keys, synthesizing information
        from both data shapes and metadata.

        This function handles complex cases where dimensions in the data may be:
        1. Direct dimensions in the data array (e.g. dim_0, dim_1)
        2. Associated motor positions for each time point
        3. Described in metadata (e.g. hints about gridding and dimensions)
        4. Defined by axis hints (e.g. tes_mca_energies)

        Parameters
        ----------
        ykey : str
            The key for the y-data to analyze
        xkeys : List[str]
            List of keys for x-axes

        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - ordered_dims: List[str] - Properly ordered dimension names
            - effective_shape: Tuple[int] - Shape after considering metadata
            - dim_metadata: Dict - Additional metadata about each dimension
            - original_dims: Dict - Original dimension info from the data
            - grid_mapping: Dict - How original dims map to effective dims
            - axis_hints: Dict - Mapping of dimensions to axis hint paths
            - associated_axes: Dict - Motors or other axes associated with dimensions
        """
        result = {
            "ordered_dims": [],
            "effective_shape": None,
            "dim_metadata": {},
            "original_dims": {},
            "grid_mapping": {},
            "axis_hints": {},
            "associated_axes": {},
        }

        # Get shapes and dimension info for all keys
        yshape = list(self.getShape(ykey))  # Convert to list for mutability

        y_dims, x_dims = self.get_dims(ykey, xkeys)
        result["original_dims"][ykey] = y_dims
        result["original_dims"].update(x_dims)

        axis_hints = self.getAxisHints()
        y_axis_hints = axis_hints.get(ykey, [])
        # Check metadata for dimension hints
        try:
            start_doc = self.start
            hints = start_doc.get("hints", {})
            dimensions = hints.get("dimensions", [])
        except Exception as e:
            print(f"Error accessing metadata: {e}")
            start_doc = {}
            dimensions = []

        if not xkeys:
            xkeys = start_doc.get("motors", [])

        # Initialize dimension tracking
        ordered_dims = []
        dim_metadata = {}

        # Process time dimension
        if "time" in y_dims:
            ordered_dims.append("time")
            dim_metadata["time"] = {
                "type": "independent",
                "original_dim": "time",
            }

            # Collect any motors associated with time
            time_motors = []

            # First check dimensions metadata
            if dimensions:
                for dim_info in dimensions:
                    if len(dim_info) >= 2:
                        motor_list = dim_info[0]
                        if isinstance(motor_list, list):
                            for motor in motor_list:
                                if motor in xkeys:
                                    time_motors.append(motor)

            # Then check x_dims for any keys that share the time dimension
            for key in xkeys:
                if key in x_dims and x_dims[key] == ("time",):
                    if key not in time_motors:
                        time_motors.append(key)

            # Add motors as associated axes if we have any
            if time_motors:
                result["associated_axes"]["time"] = time_motors

        # Add remaining x dimensions
        for key in xkeys:
            if (
                key not in ordered_dims
                and key != "time"
                and not any(key in axes for axes in result["associated_axes"].values())
            ):
                ordered_dims.append(key)
                dim_metadata[key] = {
                    "type": "independent",
                    "original_dim": result["original_dims"].get(key, (key,))[0],
                }

        # Add remaining y dimensions, checking axis hints
        y_dims_list = list(y_dims)
        if "time" in y_dims_list:
            y_dims_list.remove("time")

        # Process remaining dimensions with axis hints
        for i, dim in enumerate(y_dims_list):
            if dim not in ordered_dims:
                ordered_dims.append(dim)
                # Check if we have an axis hint for this dimension
                if i < len(y_axis_hints):
                    hint_path = y_axis_hints[i]
                    result["axis_hints"][dim] = hint_path
                    dim_metadata[dim] = {
                        "type": "dependent_with_axis",
                        "original_dim": dim,
                        "axis_hint": hint_path,
                    }
                else:
                    dim_metadata[dim] = {"type": "dependent", "original_dim": dim}

        # Update result and handle dimension replacement
        result["ordered_dims"] = ordered_dims
        result["effective_shape"] = tuple(yshape)
        result["dim_metadata"] = dim_metadata

        # Final step: Replace dimensions with their single associated axis when appropriate
        dims_to_replace = []
        for dim, associated in result["associated_axes"].items():
            if len(associated) == 1:
                motor = associated[0]
                dims_to_replace.append((dim, motor))

        for old_dim, new_dim in dims_to_replace:
            if old_dim == new_dim:
                del result["associated_axes"][new_dim]
                continue
            idx = result["ordered_dims"].index(old_dim)
            result["ordered_dims"][idx] = new_dim

            # Transfer metadata
            result["dim_metadata"][new_dim] = result["dim_metadata"][old_dim].copy()
            result["dim_metadata"][new_dim]["original_dim"] = old_dim
            del result["dim_metadata"][old_dim]
        return result

    def get_dimension_axes(
        self, ykey: str, xkeys: List[str], slice_info: Optional[tuple] = None
    ) -> Tuple[List[np.ndarray], List[str], Dict[str, Dict[str, Any]]]:
        """
        Get axis data for each dimension of the data.

        This function uses analyze_dimensions to determine the dimensions and their
        types, then generates appropriate axis data for each:
        - For motor dimensions: uses the motor position data
        - For dimensions with axis hints: uses the specified axis data
        - For other dimensions: generates index arrays using np.arange
        - For dummy dimensions (length 1): returns empty array

        Parameters
        ----------
        ykey : str
            The key for the y-data to analyze
        xkeys : List[str]
            List of keys for x-axes

        Returns
        -------
        Tuple[List[np.ndarray], List[str], Dict[str, Dict[str, Any]]]
            Tuple of:
            - axis_arrays: list of numpy arrays for each dimension
            - axis_names: list of strings naming each dimension
            - associated_data: dict mapping dimension names to dict containing:
                - arrays: List[np.ndarray] - associated data arrays
                - names: List[str] - names of the associated axes
        """
        # First get dimension analysis
        dim_info = self.analyze_dimensions(ykey, xkeys)

        # Initialize output lists
        axis_arrays = []
        axis_names = []
        associated_data = {}

        # Get the shape for reference
        effective_shape = dim_info["effective_shape"]
        if slice_info is None:
            slice_info = tuple([slice(None)] * len(dim_info["ordered_dims"]))

        # Process each dimension in order
        for i, dim_name in enumerate(dim_info["ordered_dims"]):
            dim_meta = dim_info["dim_metadata"][dim_name]
            dim_type = dim_meta["type"]

            # Get dimension size - default to 1 if beyond effective_shape
            dim_size = effective_shape[i] if i < len(effective_shape) else 1
            effective_slice = slice_info[: i + 1]

            if dim_type == "motor":
                # For motor dimensions in a grid, use the motor position data
                axis_data = self.getData(dim_name, effective_slice)
                if dim_meta["original_dim"] == "time":
                    # Reshape motor data according to grid mapping
                    if "time" in dim_info["grid_mapping"]:
                        grid_info = dim_info["grid_mapping"]["time"][dim_name]
                        axis_data = axis_data[: grid_info["shape"]]

            elif dim_type == "independent":
                # For independent dimensions (like time), use the data directly
                axis_data = self.getData(dim_name, effective_slice)

                # Check for associated axes
                if dim_name in dim_info["associated_axes"]:
                    associated = []
                    motor_names = dim_info["associated_axes"][dim_name]
                    for motor in motor_names:
                        motor_data = self.getData(motor, effective_slice)
                        associated.append(motor_data)
                    associated_data[dim_name] = {
                        "arrays": associated,
                        "names": motor_names,
                    }

            elif dim_type == "dependent_with_axis":
                # Use the axis hint path to get the axis data
                try:
                    hint_path = dim_info["axis_hints"][dim_name]
                    axis_data = self.getAxis(hint_path, effective_slice)
                except Exception as e:
                    print(f"Error getting axis data from hint: {e}")
                    # Fall back to index array
                    axis_data = np.arange(dim_size)[effective_slice[-1]]

            else:
                # For dimensions without hints, use index arrays
                if dim_size == 1:
                    # Dummy dimension
                    axis_data = np.array([])
                else:
                    # Regular index array
                    axis_data = np.arange(dim_size)[effective_slice[-1]]

            axis_arrays.append(axis_data)
            axis_names.append(dim_name)

        return axis_arrays, axis_names, associated_data
