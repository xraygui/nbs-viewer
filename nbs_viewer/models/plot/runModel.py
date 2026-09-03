from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Any

from qtpy.QtCore import QObject, Signal
from asteval import Interpreter
import numpy as np
import time as ttime

from ..data.base import CatalogRun
from .cube_view import CubeViewSpec, MaterializeRequest
from .view_crop import ViewCrop, fetch_context_with_view_crop
from .derived_fetch import plot_plane_storage_axes
from .frozen_spectrum import FrozenSpectrum
from .key_info import AxisLayout, KeyInfo, RunIdentity
from .plot_bundle import (
    apply_normalization,
    apply_transform,
    build_plot_bundle,
    reduce_loaded_array,
    reduce_to_plot_plane,
    slice_info_for_key,
)
from .plot_geometry import PlotBundle, get_render_mode_hint
from .plot_request import PlotRequest, build_plot_request
from nbs_viewer.utils import print_debug


class RunModel(QObject):
    """
    Uniform key access over a catalog run plus frozen synthetic keys.

    The RunSource surface is ``key_table``, ``identity``, ``read``,
    ``describe_axes``, ``load_axes``, and ``get_plot_bundle``. Selection,
    visibility, and transform text remain on this object until PlotSession
    owns them.

    Parameters
    ----------
    run : CatalogRun
        The run to wrap.
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
        self._is_visible = True
        self._catalog_keys: List[str] = []
        self._frozen_spectra: Dict[str, FrozenSpectrum] = {}

        self._transform_text = ""
        self._transform = Interpreter()
        self._dynamic = False
        self._key_table: Optional[Dict[str, KeyInfo]] = None
        self._update_available_keys()
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

    def _invalidate_key_table(self) -> None:
        """Drop the cached key table so the next access rebuilds it."""
        self._key_table = None

    def _build_key_table(self) -> Dict[str, KeyInfo]:
        """
        Merge catalog keys with frozen entries into a KeyInfo table.

        Catalog keys are marked hinted until ``get_hinted_keys`` is confirmed
        as the "Show All Keys" backing. ``render_hint`` comes from
        ``get_render_mode_hint`` and is None when that returns nothing.

        Returns
        -------
        dict of str to KeyInfo
            Fresh table keyed by data key name.
        """
        table: Dict[str, KeyInfo] = {}
        plot_hints = self._run.getPlotHints()
        for name in self._catalog_keys:
            shape = tuple(self._run.getShape(name))
            table[name] = KeyInfo(
                name=name,
                label=name,
                shape=shape,
                synthetic=False,
                hinted=True,
                render_hint=get_render_mode_hint(plot_hints, name),
            )
        for key, entry in self._frozen_spectra.items():
            table[key] = KeyInfo(
                name=key,
                label=entry.label,
                shape=tuple(entry.get_shape()),
                synthetic=True,
                hinted=False,
                render_hint=None,
            )
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

    def _frozen_axis_names(self, entry: FrozenSpectrum) -> List[str]:
        """
        Resolve display dimension names for a frozen spectrum.

        Parameters
        ----------
        entry : FrozenSpectrum
            Registered frozen entry.

        Returns
        -------
        list of str
            Names truncated or padded to the storage rank.
        """
        shape = entry.get_shape()
        ndim = len(shape)
        names = list(entry.bundle.axis_names) if entry.bundle.axis_names else []
        if entry.label and ndim == 1:
            names = [entry.label]
        while len(names) < ndim:
            names.append(f"dim_{len(names)}")
        return names[:ndim]

    @staticmethod
    def _truncate_dim_names(
        ordered_dims: Sequence[str], ndim: int
    ) -> List[str]:
        """
        Pad or truncate dimension names to match storage rank.

        Parameters
        ----------
        ordered_dims : sequence of str
            Names from ``analyze_dimensions``.
        ndim : int
            Storage rank.

        Returns
        -------
        list of str
            Names of length ``ndim``.
        """
        names = list(ordered_dims)
        if len(names) < ndim:
            names = names + [f"dim_{i}" for i in range(len(names), ndim)]
        elif len(names) > ndim:
            names = names[:ndim]
        return names

    def read(self, key: str, slice_info=None) -> np.ndarray:
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

        Raises
        ------
        ValueError
            If the underlying source returns None.
        """
        entry = self._frozen_entry(key)
        if entry is not None:
            data = entry.get_data(slice_info)
        elif slice_info is None:
            data = self._run.getData(key)
        else:
            data = self._run.getData(key, slice_info)
        if data is None:
            raise ValueError(f"No data returned for key {key!r}")
        return np.asarray(data)

    def get_data(self, key: str, slice_info=None) -> np.ndarray:
        """
        Load array data for a catalog or frozen key.

        Compatibility shim over :meth:`read`.

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
        return self.read(key, slice_info)

    def describe_axes(self, ykey: str, xkeys: Sequence[str]) -> AxisLayout:
        """
        Return shape and placeholder axis coordinates for dimension UI.

        Applies the frozen-key overlay. Catalog keys use
        ``CatalogRun.analyze_dimensions`` with the same name truncation as
        ``get_dimension_ui_info``.

        Parameters
        ----------
        ykey : str
            Y data key.
        xkeys : sequence of str
            Selected X-axis keys.

        Returns
        -------
        AxisLayout
            Shape, truncated names, index placeholders, and analysis.
        """
        xkey_list = list(xkeys)
        entry = self._frozen_entry(ykey)
        if entry is not None:
            shape = tuple(entry.get_shape())
            names = self._frozen_axis_names(entry)
            placeholders = tuple(
                np.arange(size, dtype=float) for size in shape
            )
            return AxisLayout(
                shape=shape,
                names=tuple(names),
                placeholders=placeholders,
                associated=MappingProxyType({}),
                analysis=MappingProxyType({}),
            )
        dim_info = self._run.analyze_dimensions(ykey, xkey_list)
        shape = tuple(dim_info["effective_shape"])
        names = self._truncate_dim_names(dim_info["ordered_dims"], len(shape))
        placeholders = tuple(np.arange(size, dtype=float) for size in shape)
        return AxisLayout(
            shape=shape,
            names=tuple(names),
            placeholders=placeholders,
            associated=MappingProxyType({}),
            analysis=MappingProxyType(dict(dim_info)),
        )

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
        entry = self._frozen_entry(ykey)
        if entry is not None:
            if entry.kind == "stack_spectrum" and xkey_list:
                return self._stack_spectrum_dimension_axes(
                    entry, xkey_list, slice_info
                )
            return entry.get_dimension_axes(xkey_list, slice_info)
        return self._run.get_dimension_axes(ykey, xkey_list, slice_info)

    def get_dimension_ui_info(
        self, ykey: str, xkeys: List[str]
    ) -> Tuple[Tuple[int, ...], List[str], List[np.ndarray], Dict[str, Any]]:
        """
        Return shape and placeholder axis coordinates for dimension UI.

        Compatibility shim over :meth:`describe_axes`.

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
        layout = self.describe_axes(ykey, xkeys)
        return (
            layout.shape,
            list(layout.names),
            list(layout.placeholders),
            dict(layout.associated),
        )

    def get_dimension_axes(
        self, ykey: str, xkeys: List[str], slice_info=None
    ):
        """
        Return axis coordinates for a catalog or frozen Y key.

        Compatibility shim over :meth:`load_axes`.

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
        """
        return self.load_axes(ykey, xkeys, slice_info)

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

        Parameters
        ----------
        key : str
            Data key.

        Returns
        -------
        tuple of int
            Storage shape.
        """
        info = self.key_table().get(key)
        if info is not None:
            return info.shape
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
        keys_changed = set(new_keys) != set(self._catalog_keys)
        self._catalog_keys = new_keys
        self._invalidate_key_table()
        if keys_changed:
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

    def _load_slice_for_request(
        self,
        request: PlotRequest,
        *,
        region_frame=None,
        parent_spec: Optional[CubeViewSpec] = None,
        view_crop: Optional[ViewCrop] = None,
    ) -> Tuple[tuple, object]:
        """
        Resolve the storage load slice and ROI materialize frame.

        Crop on a 2-D view is already folded into ``request.view.load_slice``.
        A 1-D ROI profile cannot carry that crop on the view, so ``view_crop``
        remains an extra argument for N-D ROI loads.

        Parameters
        ----------
        request : PlotRequest
            Frozen plot description.
        region_frame : PlotViewFrame, optional
            Parent 2D view frame required when ``request.region`` is set.
        parent_spec : CubeViewSpec, optional
            Parent cube view for plot-plane storage axis lookup.
        view_crop : ViewCrop, optional
            Parent-plane crop applied only on the ROI load path.

        Returns
        -------
        tuple
            ``(slice_info, materialize_frame)``. ``materialize_frame`` is
            None when there is no region.
        """
        if request.region is None:
            return request.view.load_slice(), None
        if region_frame is None:
            raise ValueError(
                "region_frame is required when request.region is set"
            )
        materialize_request = MaterializeRequest(
            spec=request.view.to_cube_view_spec(),
            region=request.region,
            mask_mode=request.mask_mode,
        )
        if view_crop is not None:
            return fetch_context_with_view_crop(
                materialize_request,
                view_crop,
                parent_spec,
            )
        return materialize_request.fetch_context(
            region_frame=region_frame,
            parent_spec=parent_spec,
        )

    def _normalized_y(
        self,
        y: np.ndarray,
        y_plot_names: Sequence[str],
        request: PlotRequest,
        slice_info: tuple,
        y_storage_names: Sequence[str],
    ) -> np.ndarray:
        """
        Load and reduce each norm key, then divide into ``y``.

        Parameters
        ----------
        y : np.ndarray
            Plot-plane y array.
        y_plot_names : sequence of str
            Names of the plot-plane axes of ``y``.
        request : PlotRequest
            Supplies norm keys, x keys, and the y view roles.
        slice_info : tuple
            Load slice used for the y key.
        y_storage_names : sequence of str
            Full storage names of the y key.

        Returns
        -------
        np.ndarray
            Normalized y array.
        """
        if not request.norm_keys:
            return y
        xkeys = list(request.xkeys)
        roles = request.view.roles
        reduced = []
        for norm_key in request.norm_keys:
            layout = self.describe_axes(norm_key, xkeys)
            norm_names = list(layout.names)
            if self._frozen_entry(norm_key) is not None:
                arr = self.read(norm_key, slice_info)
                reduced.append((arr, list(norm_names)))
                continue
            key_slice = slice_info_for_key(
                slice_info, y_storage_names, norm_names
            )
            arr = self.read(norm_key, key_slice)
            reduced.append(
                reduce_loaded_array(
                    arr, list(norm_names), y_storage_names, roles
                )
            )
        return apply_normalization(y, y_plot_names, reduced)

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
            Whether to apply the run model's transform expression.

        Returns
        -------
        tuple
            (xlist, y)
        """
        shape = self.get_shape(ykey)
        plot_ndim = 2 if len(shape) >= 2 else 1
        request = build_plot_request(
            uid=self.uid,
            xkeys=xkeys,
            ykey=ykey,
            shape=shape,
            norm_keys=norm_keys,
            plot_ndim=plot_ndim,
            slice_info=slice_info,
            transform=self._transform_text if transform else "",
        )
        bundle = self.get_plot_bundle(request)
        if bundle.ndim == 1:
            xlist = [] if bundle.x_line is None else [bundle.x_line]
        else:
            xlist = []
        return xlist, bundle.y

    def get_plot_bundle(
        self,
        request: PlotRequest,
        *,
        region_frame=None,
        parent_spec: Optional[CubeViewSpec] = None,
        label: str = "",
        view_crop: Optional[ViewCrop] = None,
    ) -> PlotBundle:
        """
        Load, reduce, normalize, transform, and pack one plot request.

        Parameters
        ----------
        request : PlotRequest
            Frozen plot description.
        region_frame : PlotViewFrame, optional
            Parent 2D view frame required when ``request.region`` is set.
        parent_spec : CubeViewSpec, optional
            Parent cube view for ROI plot-plane axis lookup.
        label : str
            Optional display label for 1D ROI output.
        view_crop : ViewCrop, optional
            Parent-plane crop for N-D ROI loads. Ordinary 2-D crops belong on
            ``request.view``.

        Returns
        -------
        PlotBundle
            Prepared plot payload for the view layer.
        """
        xkeys = list(request.xkeys)
        ykey = request.ykey
        slice_info, materialize_frame = self._load_slice_for_request(
            request,
            region_frame=region_frame,
            parent_spec=parent_spec,
            view_crop=view_crop,
        )

        t0 = ttime.time()
        storage_axes, storage_names, _extra = self.load_axes(
            ykey, xkeys, slice_info
        )
        y = self.read(ykey, slice_info)
        t_load = ttime.time() - t0

        t0 = ttime.time()
        y, coords, names = reduce_to_plot_plane(
            y,
            storage_axes,
            storage_names,
            request,
            region_frame=materialize_frame,
            plot_plane_storage_axes=plot_plane_storage_axes(parent_spec),
        )
        t_materialize = ttime.time() - t0

        t0 = ttime.time()
        y = self._normalized_y(
            y, names, request, slice_info, storage_names
        )
        t_norm = ttime.time() - t0

        t0 = ttime.time()
        coords, y = apply_transform(coords, y, request.transform)
        t_transform = ttime.time() - t0

        print_debug(
            "RunModel.get_plot_bundle",
            f"{ykey} shape={getattr(y, 'shape', None)} "
            f"load={t_load:.4f}s materialize={t_materialize:.4f}s "
            f"norm={t_norm:.4f}s transform={t_transform:.4f}s",
            category="plots",
        )

        frozen = self._frozen_entry(ykey)
        if frozen is not None and y.ndim == 1:
            names = [label or frozen.label]
        info = self.key_table().get(ykey)
        hint = info.render_hint if info is not None else None
        if hint is None and frozen is None:
            hint = get_render_mode_hint(self.get_plot_hints(ykey), ykey)
        return build_plot_bundle(
            y,
            coords,
            names,
            request,
            render_mode_hint=hint,
            label=label,
        )

    def transform_data(
        self, xlist: List[np.ndarray], y: np.ndarray
    ) -> Tuple[List[np.ndarray], np.ndarray]:
        """
        Transform data using this run's current expression text.

        Parameters
        ----------
        xlist : list of np.ndarray
            Plot-plane coordinate arrays.
        y : np.ndarray
            Plot-plane data.

        Returns
        -------
        tuple
            Transformed ``(xlist, y)``.
        """
        return apply_transform(xlist, y, self._transform_text)

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


RunSource = RunModel
