from typing import Dict, List, Optional, Tuple, Any

from qtpy.QtCore import QObject, Signal
from asteval import Interpreter
import numpy as np
import time as ttime

from ..data.base import CatalogRun
from .cube_view import CubeViewSpec, MaterializeRequest, materialize_view
from .view_crop import ViewCrop, apply_view_crop_to_slice_info, fetch_context_with_view_crop
from .derived_fetch import plot_plane_storage_axes
from .frozen_spectrum import FrozenSpectrum
from .plot_geometry import (
    PlotBundle,
    get_render_mode_hint,
    prepare_1d_bundle,
    prepare_2d_bundle,
)
from nbs_viewer.utils import print_debug


class RunModel(QObject):
    """
    Model for managing run data selection and filtering state.

    Manages available keys, key selection, and filtering options for a run.

    Parameters
    ----------
    run : CatalogRun
        The run to manage state for
    """

    available_keys_changed = Signal()
    frozen_spectra_changed = Signal()
    selected_keys_changed = Signal(list, list, list)
    transform_changed = Signal(dict)
    data_changed = Signal()
    visibility_changed = Signal(bool)  # (artist, is_visible)
    plot_update_needed = Signal()  # Signal to trigger plot refresh

    def __init__(self, run: CatalogRun):
        super().__init__()
        self._run = run
        print_debug("RunModel.__init__", f"RunModel for run {run.uid}", "run")
        # Selection state
        self._selected_x: List[str] = []
        self._selected_y: List[str] = []
        self._selected_norm: List[str] = []
        # self._artists = {}
        self._is_visible = True  # Track overall visibility state
        self._catalog_keys: List[str] = []
        self._frozen_spectra: Dict[str, FrozenSpectrum] = {}

        self._transform_text = ""
        self._transform = Interpreter()
        # Initialize state
        self._update_available_keys()  # Initial key setup
        self._set_default_selection()
        self._connect_run()

    def _connect_run(self):
        self._run.data_changed.connect(self._on_data_changed)
        # Also react to async key init signals to update available keys quickly
        if hasattr(self._run, "keys_ready"):
            self._run.keys_ready.connect(self._on_keys_event)
        if hasattr(self._run, "keys_error"):
            self._run.keys_error.connect(self._on_keys_event)

    def _on_keys_event(self, *_):
        # Single place to update keys and default selection on first load
        previous_empty = len(self._catalog_keys) == 0
        self._update_available_keys()
        if previous_empty and self._catalog_keys:
            # First time keys become available; set defaults if none selected
            if not (self._selected_x or self._selected_y or self._selected_norm):
                self._set_default_selection()

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

    def _frozen_entry(self, key: str) -> Optional[FrozenSpectrum]:
        """
        Return a frozen spectrum entry when registered.

        Parameters
        ----------
        key : str
            Run display key.

        Returns
        -------
        FrozenSpectrum or None
            Registered frozen entry, if any.
        """
        return self._frozen_spectra.get(key)

    def get_data(self, key: str, slice_info=None) -> np.ndarray:
        """
        Load array data for a catalog or frozen key.

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
        """
        entry = self._frozen_entry(key)
        if entry is not None:
            data = entry.get_data(slice_info)
        else:
            data = self._run.getData(key, slice_info)
        if data is None:
            raise ValueError(f"No data returned for key {key!r}")
        return np.asarray(data)

    def get_dimension_ui_info(
        self, ykey: str, xkeys: List[str]
    ) -> Tuple[Tuple[int, ...], List[str], List[np.ndarray], Dict[str, Any]]:
        """
        Return shape and placeholder axis coordinates for dimension UI.

        Parameters
        ----------
        ykey : str
            Y data key.
        xkeys : list of str
            Selected X-axis keys.

        Returns
        -------
        tuple
            ``(shape, dimension_names, axis_arrays, associated_data)``.
        """
        entry = self._frozen_entry(ykey)
        if entry is not None:
            shape = entry.get_shape()
            ndim = len(shape)
            names = list(entry.bundle.axis_names) if entry.bundle.axis_names else []
            if entry.label and ndim == 1:
                names = [entry.label]
            while len(names) < ndim:
                names.append(f"dim_{len(names)}")
            names = names[:ndim]
            axis_arrays = [np.arange(size, dtype=float) for size in shape]
            return shape, names, axis_arrays, {}
        return self._run.get_dimension_ui_info(ykey, xkeys)

    def get_dimension_axes(
        self, ykey: str, xkeys: List[str], slice_info=None
    ):
        """
        Return axis coordinates for a catalog or frozen Y key.

        Stack spectra resolve X from the selected catalog keys so the
        same frozen Y can be plotted against any scan-length independent
        (``time``, motor position, etc.). Local profiles keep the frozen
        profile-axis coordinates from the reduction.

        Parameters
        ----------
        ykey : str
            Y data key.
        xkeys : list of str
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
        entry = self._frozen_entry(ykey)
        if entry is not None:
            if entry.kind == "stack_spectrum" and xkeys:
                return self._stack_spectrum_dimension_axes(
                    entry, xkeys, slice_info
                )
            return entry.get_dimension_axes(xkeys, slice_info)
        return self._run.get_dimension_axes(ykey, xkeys, slice_info)

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
            raw_full = np.asarray(self._run.getData(xkey), dtype=float).ravel()
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

        Parameters
        ----------
        key : str
            Data key.

        Returns
        -------
        tuple of int
            Storage shape.
        """
        entry = self._frozen_entry(key)
        if entry is not None:
            return entry.get_shape()
        return self._run.getShape(key)

    def get_plot_hints(self, ykey: str) -> Dict[str, Any]:
        """
        Return plot hints for a catalog or frozen Y key.

        Parameters
        ----------
        ykey : str
            Y data key.

        Returns
        -------
        dict
            Plot hints dictionary.
        """
        if self._frozen_entry(ykey) is not None:
            return {}
        return self._run.getPlotHints()

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
        entry = self._frozen_entry(ykey)
        if entry is not None:
            return f"{entry.label}.{self.scan_id}"
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
        x_keys, y_keys, norm_keys = self.get_selected_keys()
        if key in x_keys or key in y_keys or key in norm_keys:
            self.set_selected_keys(
                [k for k in x_keys if k != key],
                [k for k in y_keys if k != key],
                [k for k in norm_keys if k != key],
                force_update=True,
            )
        self.available_keys_changed.emit()
        self.frozen_spectra_changed.emit()
        return True

    def _update_available_keys(self) -> None:
        """Update catalog keys from the run; preserve synthetic keys."""
        new_keys = self._run.available_keys
        print_debug(
            "RunModel._update_available_keys",
            f"available_keys for {self.uid}: {new_keys} from run {id(self._run)}",
            "run",
        )
        if set(new_keys) != set(self._catalog_keys):
            self._catalog_keys = new_keys
            self.available_keys_changed.emit()

    def _set_default_selection(self) -> None:
        """Set default key selection based on run hints."""
        x_keys, y_keys, norm_keys = self._run.get_default_selection()
        self.set_selected_keys(x_keys, y_keys, norm_keys)

    def _on_data_changed(self) -> None:
        """Handle data changes from RunData service."""
        print_debug("RunModel._on_data_changed", f"Data changed for {self.uid}", "run")
        self._update_available_keys()
        self.data_changed.emit()

    def _fetch_plot_arrays(
        self,
        xkeys,
        ykey,
        norm_keys=None,
        slice_info=None,
        cube_view_spec=None,
        materialize_request: Optional[MaterializeRequest] = None,
        view_crop: Optional[ViewCrop] = None,
        transform=True,
        preserve_storage_axes: bool = False,
        *,
        region_frame=None,
        parent_spec: Optional[CubeViewSpec] = None,
    ) -> Tuple[List[np.ndarray], List[str], np.ndarray]:
        """
        Load and normalize raw x/y arrays for plotting.

        Parameters
        ----------
        xkeys : list of str
            X axis keys.
        ykey : str
            Y data key.
        norm_keys : list of str, optional
            Normalization keys.
        slice_info : tuple, optional
            Legacy slice specification.
        cube_view_spec : CubeViewSpec, optional
            N-D cube view (slice, reduce, axis order). Takes precedence over
            ``slice_info`` when provided.
        materialize_request : MaterializeRequest, optional
            Unified view request. When set, takes precedence over
            ``cube_view_spec``.
        view_crop : ViewCrop, optional
            Persistent spatial crop applied to plot-plane load slices.
        transform : bool
            Whether to apply the user transform expression.
        preserve_storage_axes : bool
            When True, keep one coordinate array per storage axis even if an
            axis was collapsed to length 1 by ``slice_info``.
        region_frame : PlotViewFrame, optional
            Parent 2D view frame required when ``materialize_request.region``
            is set.
        parent_spec : CubeViewSpec, optional
            Parent cube view for plot-plane storage axis lookup during ROI
            materialization.

        Returns
        -------
        tuple
            (xlist, axis_names, y)
        """
        view_spec = None
        request = materialize_request
        materialize_frame = region_frame
        if self._frozen_entry(ykey) is not None:
            request = None
            materialize_request = None
            cube_view_spec = None
        if request is not None:
            view_spec = request.spec
            if request.region is not None:
                if region_frame is None:
                    raise ValueError(
                        "region_frame is required when materialize_request.region is set"
                    )
                if view_crop is not None:
                    slice_info, materialize_frame = fetch_context_with_view_crop(
                        request,
                        view_crop,
                        parent_spec,
                    )
                else:
                    slice_info, materialize_frame = request.fetch_context(
                        region_frame=region_frame,
                        parent_spec=parent_spec,
                    )
            else:
                slice_info = view_spec.to_load_slice_info()
                if view_crop is not None:
                    slice_info = apply_view_crop_to_slice_info(slice_info, view_crop)
            preserve_storage_axes = True
        elif cube_view_spec is not None:
            view_spec = cube_view_spec
            slice_info = cube_view_spec.to_load_slice_info()
            if view_crop is not None:
                slice_info = apply_view_crop_to_slice_info(slice_info, view_crop)

        t0 = ttime.time()
        xlist, axis_names, _extra = self.get_dimension_axes(
            ykey, xkeys, slice_info
        )
        y = self.get_data(ykey, slice_info)
        t_load = ttime.time() - t0
        storage_axes = list(xlist)
        storage_names = list(axis_names)

        t0 = ttime.time()
        if request is not None:
            y, xlist, axis_names = materialize_view(
                y,
                storage_axes,
                storage_names,
                request,
                region_frame=materialize_frame,
                plot_plane_storage_axes=plot_plane_storage_axes(parent_spec),
            )
        elif view_spec is not None:
            y, xlist, axis_names = materialize_view(
                y,
                storage_axes,
                storage_names,
                MaterializeRequest(view_spec),
            )
        elif y.size > 1 and not preserve_storage_axes:
            filtered = [(x, n) for x, n in zip(xlist, axis_names) if x.size > 1]
            if filtered:
                xlist, axis_names = zip(*filtered)
                xlist = list(xlist)
                axis_names = list(axis_names)
            else:
                xlist = []
                axis_names = []
        t_materialize = ttime.time() - t0

        t0 = ttime.time()
        if norm_keys is not None:
            normlist = [
                self.get_data(norm_key, slice_info) for norm_key in norm_keys
            ]
            if request is not None:
                for i, norm_key in enumerate(norm_keys):
                    if self._frozen_entry(norm_key) is not None:
                        continue
                    normlist[i], _, _ = materialize_view(
                        normlist[i],
                        storage_axes,
                        storage_names,
                        request,
                        region_frame=materialize_frame,
                        plot_plane_storage_axes=plot_plane_storage_axes(parent_spec),
                    )
            elif view_spec is not None:
                for i, norm_key in enumerate(norm_keys):
                    if self._frozen_entry(norm_key) is not None:
                        continue
                    normlist[i], _, _ = materialize_view(
                        normlist[i],
                        storage_axes,
                        storage_names,
                        MaterializeRequest(view_spec),
                    )
            norm = np.prod(normlist, axis=0)
        else:
            norm = None

        if norm is not None:
            if np.isscalar(norm):
                y = y / norm
            else:
                temp_norm = norm
                while temp_norm.ndim < y.ndim:
                    temp_norm = np.expand_dims(temp_norm, axis=-1)
                y = y / temp_norm
        t_norm = ttime.time() - t0

        t0 = ttime.time()
        if transform:
            xlist, y = self.transform_data(xlist, y)
        t_transform = ttime.time() - t0

        print_debug(
            "RunModel._fetch_plot_arrays",
            f"{ykey} shape={getattr(y, 'shape', None)} "
            f"load={t_load:.4f}s materialize={t_materialize:.4f}s "
            f"norm={t_norm:.4f}s transform={t_transform:.4f}s",
            category="plots",
        )
        return xlist, axis_names, y

    def get_plot_data(
        self, xkeys, ykey, norm_keys=None, slice_info=None, transform=True
    ) -> Tuple[List[np.ndarray], np.ndarray]:
        """
        Get plot x arrays and y data (backward-compatible API).

        Parameters
        ----------
        xkeys : list of str
            X axis keys.
        ykey : str
            Y data key.
        norm_keys : list of str, optional
            Normalization keys.
        slice_info : tuple, optional
            Slice specification.
        transform : bool
            Whether to apply transforms.

        Returns
        -------
        tuple
            (xlist, y)
        """
        xlist, _axis_names, y = self._fetch_plot_arrays(
            xkeys, ykey, norm_keys, slice_info, transform
        )
        return xlist, y

    def get_plot_bundle(
        self,
        xkeys,
        ykey,
        norm_keys=None,
        slice_info=None,
        cube_view_spec=None,
        materialize_request: Optional[MaterializeRequest] = None,
        view_crop: Optional[ViewCrop] = None,
        transform=True,
        *,
        region_frame=None,
        parent_spec: Optional[CubeViewSpec] = None,
        label: str = "",
    ) -> PlotBundle:
        """
        Get a prepared PlotBundle with render mode and coordinates.

        Parameters
        ----------
        xkeys : list of str
            X axis keys.
        ykey : str
            Y data key.
        norm_keys : list of str, optional
            Normalization keys.
        slice_info : tuple, optional
            Slice specification.
        cube_view_spec : CubeViewSpec, optional
            N-D cube view specification.
        materialize_request : MaterializeRequest, optional
            Unified view request including optional ROI parameters.
        view_crop : ViewCrop, optional
            Persistent spatial crop applied to plot-plane load slices.
        transform : bool
            Whether to apply transforms.
        region_frame : PlotViewFrame, optional
            Parent 2D view frame required when ``materialize_request.region``
            is set.
        parent_spec : CubeViewSpec, optional
            Parent cube view for ROI plot-plane axis lookup.
        label : str
            Optional display label for 1D ROI output.

        Returns
        -------
        PlotBundle
            Prepared plot payload for the view layer.
        """
        request = materialize_request
        if request is not None and request.region is not None:
            if region_frame is None:
                raise ValueError(
                    "region_frame is required when materialize_request.region is set"
                )
            xlist, axis_names, y = self._fetch_plot_arrays(
                xkeys,
                ykey,
                norm_keys,
                materialize_request=request,
                view_crop=view_crop,
                transform=transform,
                region_frame=region_frame,
                parent_spec=parent_spec,
            )
            if request.spec.plot_ndim != 1:
                raise ValueError(
                    f"ROI requests always reduce to a profile, got plot_ndim "
                    f"{request.spec.plot_ndim}"
                )
            if not np.isfinite(y).any():
                raise ValueError("ROI profile is empty after reduction")
            display_label = label or (axis_names[0] if axis_names else "profile")
            return prepare_1d_bundle(y, xlist, [display_label])

        xlist, axis_names, y = self._fetch_plot_arrays(
            xkeys,
            ykey,
            norm_keys,
            slice_info=slice_info,
            cube_view_spec=cube_view_spec,
            materialize_request=request,
            view_crop=view_crop,
            transform=transform,
        )
        if y is None:
            raise ValueError(f"Plot data for {ykey!r} is missing")
        hint = get_render_mode_hint(self.get_plot_hints(ykey), ykey)
        frozen = self._frozen_entry(ykey)
        if frozen is not None and y.ndim == 1:
            axis_names = [label or frozen.label]

        if y.ndim == 1:
            return prepare_1d_bundle(y, xlist, axis_names)
        if y.ndim == 2:
            t0 = ttime.time()
            bundle = prepare_2d_bundle(
                y, xlist, axis_names, render_mode_hint=hint
            )
            print_debug(
                "RunModel.get_plot_bundle",
                f"{ykey} prepare_2d mode={bundle.render_mode} "
                f"shape={y.shape} {ttime.time() - t0:.4f}s",
                category="plots",
            )
            return bundle

        raise ValueError(f"Unsupported plot dimensionality: {y.ndim}")

    def transform_data(
        self, xlist: List[np.ndarray], y: np.ndarray
    ) -> Tuple[List[np.ndarray], np.ndarray]:
        """
        Transform data using normalization and custom transformations.

        Parameters
        ----------
        xlist : List[np.ndarray]
            List of x-axis data arrays
        y : np.ndarray
            Y-axis data array
        norm : Optional[np.ndarray]
            Optional normalization data

        Returns
        -------
        Tuple[List[np.ndarray], np.ndarray]
            Transformed (x_data_list, y_data)
        """
        # Apply normalization if provided
        # Apply custom transformation
        if self._transform_text:
            self._transform.symtable["y"] = y
            self._transform.symtable["x"] = xlist
            result = self._transform(self._transform_text)
            if result is not None:
                y = result
            else:
                y = self._transform.symtable.get("y", y)

        return xlist, y

    def set_transform(self, transform_state: Dict[str, Any]) -> None:
        """
        Set the transformation expression.

        Parameters
        ----------
        transform_state : Dict[str, Any]
            Dictionary with transform settings:
            - enabled: bool, whether transform is enabled
            - text: str, Python expression for data transformation
        """
        if transform_state["enabled"]:
            transform_text = transform_state["text"]
        else:
            transform_text = ""

        if transform_text != self._transform_text:
            self._transform_text = transform_text
            self.transform_changed.emit(transform_state)

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
        # Disconnect RunData signals
        print_debug("RunModel.cleanup", f"Cleaning up run {self.uid}", "run")
        try:
            self._disconnect_run()
        except Exception as e:
            print(f"Warning: Error disconnecting run signals: {e}")

        # Clear selection state
        self._selected_x.clear()
        self._selected_y.clear()
        self._selected_norm.clear()

        # Emit a final signal to ensure any remaining references are cleaned up
        # self.data_changed.emit()
        self.visibility_changed.emit(False)

    def get_selected_keys(self):
        return self._selected_x, self._selected_y, self._selected_norm

    def set_selected_keys(
        self,
        x_keys: List[str],
        y_keys: List[str],
        norm_keys: Optional[List[str]] = None,
        force_update: bool = False,
    ) -> None:
        """
        Set the current key selection.

        Parameters
        ----------
        x_keys : List[str]
            Keys to select for x-axis
        y_keys : List[str]
            Keys to select for y-axis
        norm_keys : Optional[List[str]], optional
            Keys to select for normalization, by default None
        force_update : bool, optional
            Whether to force update the plot regardless of auto_add setting
        """
        # Check if any selections have changed
        x_keys = [key for key in x_keys if key in self.available_keys]
        y_keys = [key for key in y_keys if key in self.available_keys]
        if norm_keys is None:
            norm_keys = []
        norm_keys = [key for key in norm_keys if key in self.available_keys]
        if (
            x_keys != self._selected_x
            or y_keys != self._selected_y
            or norm_keys != self._selected_norm
        ):

            self._selected_x = x_keys
            self._selected_y = y_keys
            self._selected_norm = norm_keys
            self.selected_keys_changed.emit(
                self._selected_x, self._selected_y, self._selected_norm
            )
            if force_update:
                self.plot_update_needed.emit()

    def set_visible(self, is_visible):
        """
        Set visibility for all artists.

        Parameters
        ----------
        is_visible : bool
            New visibility state
        """
        if is_visible != self._is_visible:
            self._is_visible = is_visible  # Save visibility state
            self.visibility_changed.emit(is_visible)
