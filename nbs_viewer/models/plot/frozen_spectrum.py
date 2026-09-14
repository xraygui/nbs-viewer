"""
Frozen ROI-derived spectra registered as synthetic keys on RunSource.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Tuple

import numpy as np

import xarray as xr

from ..data.array_contract import labelled_array, surviving_dims
from ..data.key_info import KeyInfo
from ..data.synthetic_keys import SYNTHETIC_KEY_PREFIX, is_synthetic_key
from .plot_geometry import PlotBundle
from .plot_request import PlotRequest

__all__ = [
    "SYNTHETIC_KEY_PREFIX",
    "is_synthetic_key",
    "FrozenSpectrum",
    "copy_plot_bundle",
]


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
            storage_names = (
                [names[1], names[0]] if len(names) >= 2 else names[:2]
            )
            return [
                np.asarray(col_axis, dtype=float),
                np.asarray(row_axis, dtype=float),
            ], storage_names

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
    request : PlotRequest
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
    request: PlotRequest
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

    def describe(self) -> KeyInfo:
        """
        Return static facts about this synthetic key.

        The same contract a catalog run answers, so the two sources can be
        asked the same question rather than dispatched between. A 1-D frozen
        spectrum names its single axis after its label, which is what the
        dimension controls have always shown for it.

        Returns
        -------
        KeyInfo
            Name, label, ``{axis name: length}``, no render hint.
        """
        shape = self.get_shape()
        ndim = len(shape)
        names = list(self.bundle.axis_names) if self.bundle.axis_names else []
        if self.label and ndim == 1:
            names = [self.label]
        while len(names) < ndim:
            names.append(f"dim_{len(names)}")
        return KeyInfo.from_dims(
            self.key,
            names[:ndim],
            shape,
            label=self.label,
            synthetic=True,
            hinted=False,
        )

    def load(
        self, slice_info: Optional[tuple] = None, *, coords: bool = True
    ) -> xr.DataArray:
        """
        Return the frozen payload with its dimensions named and coordinates on.

        The coordinates are the ones the reduction produced and stored, so a
        frozen profile carries the axis it was measured against rather than an
        index range. They are matched to dimensions by storage position:
        :func:`_storage_axes_from_bundle` returns one array per storage axis,
        and for a mesh it reports those axes under swapped names, which is a
        separate question from which axis each array belongs to.

        Parameters
        ----------
        slice_info : tuple, optional
            Per-axis slice tuple, same convention as catalog ``getData``.
        coords : bool, optional
            Attach coordinates, as on a catalog run.

        Returns
        -------
        xarray.DataArray
            Labelled frozen array.
        """
        values = self.get_data(slice_info)
        dims = surviving_dims(self.describe().dims, slice_info)
        return labelled_array(
            values,
            dims,
            coords=self.load_coords(slice_info) if coords else {},
            name=self.key,
        )

    def load_coords(
        self, slice_info: Optional[tuple] = None
    ) -> Dict[str, np.ndarray]:
        """
        Return the coordinates ``load`` attaches, without the values.

        The same question a catalog key answers, so the plot layer can label
        an axis from either source. A stack spectrum plotted against a
        catalog X key is the one case where these are not the answer, and
        that is ``RunSource``'s business: it needs both sources at once.

        Parameters
        ----------
        slice_info : tuple, optional
            Per-axis slice tuple, same convention as catalog ``getData``.

        Returns
        -------
        dict of str to ndarray
            Stored coordinate values by dimension name.
        """
        info = self.describe()
        axis_arrays, _names = _storage_axes_from_bundle(self.bundle)
        items = _normalize_slice_info(slice_info, info.ndim)
        coords: Dict[str, np.ndarray] = {}
        for axis, ((name, length), item) in enumerate(
            zip(info.axes.items(), items)
        ):
            if isinstance(item, (int, np.integer)) or axis >= len(axis_arrays):
                continue
            coord = _slice_axis_array(axis_arrays[axis], item)
            if coord.shape[0] == len(range(length)[item]):
                coords[name] = coord
        return coords
