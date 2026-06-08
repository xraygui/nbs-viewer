"""
Frozen ROI-derived spectra registered as synthetic keys on RunModel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np

from .cube_view import MaterializeRequest
from .plot_geometry import PlotBundle

SYNTHETIC_KEY_PREFIX = "__roi__/"


def is_synthetic_key(key: str) -> bool:
    """
    Return whether a run display key identifies a frozen synthetic spectrum.

    Parameters
    ----------
    key : str
        Run display key name.

    Returns
    -------
    bool
        True for keys with the synthetic prefix.
    """
    return isinstance(key, str) and key.startswith(SYNTHETIC_KEY_PREFIX)


def _normalize_slice_info(
    slice_info: Optional[tuple], ndim: int
) -> Tuple[Any, ...]:
    """
    Pad or truncate a slice tuple to match storage dimensionality.
    """
    if slice_info is None:
        return (slice(None),) * ndim
    items = list(slice_info[:ndim])
    while len(items) < ndim:
        items.append(slice(None))
    return tuple(items)


def _apply_slice_info(array: np.ndarray, slice_info: Optional[tuple]) -> np.ndarray:
    """
    Slice a storage array the same way catalog :meth:`getData` would.
    """
    array = np.asarray(array)
    if slice_info is None:
        return array
    return array[_normalize_slice_info(slice_info, array.ndim)]


def _slice_axis_array(axis: np.ndarray, item) -> np.ndarray:
    """
    Apply one slice item to a 1D coordinate array.
    """
    axis = np.asarray(axis, dtype=float)
    sliced = axis[item]
    return np.atleast_1d(np.asarray(sliced, dtype=float))


def _storage_axes_from_bundle(bundle: PlotBundle) -> Tuple[List[np.ndarray], List[str]]:
    """
    Build per-storage-dimension coordinate arrays from a frozen bundle.
    """
    y = np.asarray(bundle.y)
    ndim = y.ndim
    names = list(bundle.axis_names) if bundle.axis_names else []
    while len(names) < ndim:
        names.append(f"dim_{len(names)}")

    if ndim == 1:
        if bundle.x_line is not None:
            axis = np.asarray(bundle.x_line, dtype=float)
        else:
            axis = np.arange(y.shape[0], dtype=float)
        return [axis], names[:1]

    if ndim == 2:
        if (
            bundle.render_mode == "mesh"
            and bundle.mesh_x is not None
            and bundle.mesh_y is not None
        ):
            mesh_x = np.asarray(bundle.mesh_x, dtype=float)
            mesh_y = np.asarray(bundle.mesh_y, dtype=float)
            if mesh_x.shape[1] > 1:
                col_axis = 0.5 * (mesh_x[0, :-1] + mesh_x[0, 1:])
            else:
                col_axis = mesh_x[0]
            if mesh_y.shape[0] > 1:
                row_axis = 0.5 * (mesh_y[:-1, 0] + mesh_y[1:, 0])
            else:
                row_axis = mesh_y[:, 0]
            return [
                np.asarray(row_axis, dtype=float),
                np.asarray(col_axis, dtype=float),
            ], names[:2]

        row_axis = np.arange(y.shape[0], dtype=float)
        col_axis = np.arange(y.shape[1], dtype=float)
        return [row_axis, col_axis], names[:2]

    raise ValueError(f"unsupported frozen bundle ndim {ndim}")


def copy_plot_bundle(bundle: PlotBundle) -> PlotBundle:
    """
    Return a deep copy of array fields in a plot bundle.

    Parameters
    ----------
    bundle : PlotBundle
        Source bundle.

    Returns
    -------
    PlotBundle
        Bundle with copied numpy arrays.
    """
    return PlotBundle(
        ndim=bundle.ndim,
        y=np.array(bundle.y, copy=True),
        render_mode=bundle.render_mode,
        axis_names=list(bundle.axis_names),
        x_line=(
            None
            if bundle.x_line is None
            else np.array(bundle.x_line, copy=True)
        ),
        extent=bundle.extent,
        mesh_x=(
            None if bundle.mesh_x is None else np.array(bundle.mesh_x, copy=True)
        ),
        mesh_y=(
            None if bundle.mesh_y is None else np.array(bundle.mesh_y, copy=True)
        ),
    )


@dataclass(frozen=True)
class FrozenSpectrum:
    """
    A committed frozen spectrum or plane from an ROI reduction.

    Parameters
    ----------
    key : str
        Internal synthetic key (``__roi__/<uuid>``).
    label : str
        Display label in Run Display.
    bundle : PlotBundle
        Frozen storage payload with correct dimensionality and shape.
    kind : str
        ``stack_spectrum`` or ``local_profile``.
    source_ykey : str
        Parent detector catalog key.
    committed_xkey : str
        X key selected at save time.
    request : MaterializeRequest
        Provenance for export; not used for re-fetch.
    source_key : tuple
        ``(xkey, ykey, run_uid)`` of the parent 2D trace.
    cube_fingerprint : tuple or None
        Slice and cube-view snapshot at commit time.
    """

    key: str
    label: str
    bundle: PlotBundle
    kind: Literal["stack_spectrum", "local_profile"]
    source_ykey: str
    committed_xkey: str
    request: MaterializeRequest
    source_key: Tuple[Any, ...]
    cube_fingerprint: Optional[Tuple[Any, ...]] = None

    def get_shape(self) -> Tuple[int, ...]:
        """
        Return the storage shape of the frozen payload.

        Returns
        -------
        tuple of int
            Shape of the stored ``y`` array.
        """
        return np.asarray(self.bundle.y).shape

    def get_data(self, slice_info: Optional[tuple] = None) -> np.ndarray:
        """
        Return stored data with optional slicing.

        Parameters
        ----------
        slice_info : tuple, optional
            Per-axis slice tuple, same convention as catalog :meth:`getData`.

        Returns
        -------
        np.ndarray
            Sliced or full storage array.
        """
        return _apply_slice_info(self.bundle.y, slice_info)

    def get_dimension_axes(
        self,
        xkeys: List[str],
        slice_info: Optional[tuple] = None,
    ) -> Tuple[List[np.ndarray], List[str], Dict[str, Dict[str, Any]]]:
        """
        Return axis coordinates for each storage dimension.

        Parameters
        ----------
        xkeys : list of str
            Selected X-axis catalog keys.
        slice_info : tuple, optional
            Per-axis slice tuple applied to storage and axis arrays.

        Returns
        -------
        tuple
            ``(axis_arrays, axis_names, associated_data)`` like catalog runs.
        """
        del xkeys
        axis_arrays, axis_names = _storage_axes_from_bundle(self.bundle)
        ndim = len(axis_arrays)
        if slice_info is not None:
            items = _normalize_slice_info(slice_info, ndim)
            axis_arrays = [
                _slice_axis_array(axis, item)
                for axis, item in zip(axis_arrays, items)
            ]
        return axis_arrays, axis_names, {}
