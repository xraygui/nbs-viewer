from typing import Dict, List, Optional, Tuple, Any

from qtpy.QtCore import QObject, Signal
from asteval import Interpreter
import numpy as np

from ..data.base import CatalogRun
from .cube_view import CubeViewSpec, apply_cube_view
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
        self._available_keys = list()  # Track our own copy of available keys

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
        previous_empty = len(self._available_keys) == 0
        self._update_available_keys()
        if previous_empty and self._available_keys:
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
    def available_keys(self) -> List[str]:
        """Get the set of available keys."""
        return self._available_keys

    def _update_available_keys(self) -> None:
        """Update internal available keys from run."""
        new_keys = self._run.available_keys
        print_debug(
            "RunModel._update_available_keys",
            f"available_keys for {self.uid}: {new_keys} from run {id(self._run)}",
            "run",
        )
        if set(new_keys) != set(self._available_keys):
            self._available_keys = new_keys
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
        transform=True,
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
        transform : bool
            Whether to apply the user transform expression.

        Returns
        -------
        tuple
            (xlist, axis_names, y)
        """
        if cube_view_spec is not None:
            slice_info = cube_view_spec.to_load_slice_info()

        xlist, axis_names, _extra = self._run.get_dimension_axes(
            ykey, xkeys, slice_info
        )
        y = self._run.getData(ykey, slice_info)
        storage_axes = list(xlist)
        storage_names = list(axis_names)

        if cube_view_spec is not None:
            y, xlist, axis_names = apply_cube_view(
                y, storage_axes, storage_names, cube_view_spec
            )
        elif y.size > 1:
            filtered = [(x, n) for x, n in zip(xlist, axis_names) if x.size > 1]
            if filtered:
                xlist, axis_names = zip(*filtered)
                xlist = list(xlist)
                axis_names = list(axis_names)
            else:
                xlist = []
                axis_names = []

        if norm_keys is not None:
            normlist = [
                self._run.getData(norm_key, slice_info) for norm_key in norm_keys
            ]
            if cube_view_spec is not None:
                for i, norm in enumerate(normlist):
                    normlist[i], _, _ = apply_cube_view(
                        norm, storage_axes, storage_names, cube_view_spec
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

        if transform:
            xlist, y = self.transform_data(xlist, y)
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
        transform=True,
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
        transform : bool
            Whether to apply transforms.

        Returns
        -------
        PlotBundle
            Prepared plot payload for the view layer.
        """
        xlist, axis_names, y = self._fetch_plot_arrays(
            xkeys,
            ykey,
            norm_keys,
            slice_info=slice_info,
            cube_view_spec=cube_view_spec,
            transform=transform,
        )
        hint = get_render_mode_hint(self._run.getPlotHints(), ykey)

        if y.ndim == 1:
            return prepare_1d_bundle(y, xlist, axis_names)
        if y.ndim == 2:
            bundle = prepare_2d_bundle(y, xlist, axis_names, render_mode_hint=hint)
            print_debug(
                "RunModel.get_plot_bundle",
                f"{ykey} render_mode={bundle.render_mode} shape={y.shape}",
                category="DEBUG_PLOTS",
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
            y = self._transform(self._transform_text)

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
