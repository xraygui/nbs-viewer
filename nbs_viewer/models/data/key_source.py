"""
One key, from whichever source holds it.

``RunSource`` offers a catalog run's keys and a run's frozen synthetic keys
under one key space, and it used to perform that union separately in every
method that touched a key -- five methods, each spelling out "frozen?
``entry.this(...)`` : ``run.that(...)``". A union performed once is an
abstraction; performed five times it is a copy, and the copies could drift.

What makes one dispatch possible is that the two sources have different
*shapes* rather than different capabilities. A
:class:`~nbs_viewer.models.plot.frozen_spectrum.FrozenSpectrum` **is** one
key, so its methods take no key name. A :class:`CatalogRun` holds many, so
its methods take one. :class:`CatalogKey` binds a run and a key name together
so that both answer the same key-free protocol, and ``RunSource`` picks a
source once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import xarray as xr

from .key_info import KeyInfo


@dataclass(frozen=True)
class CatalogKey:
    """
    One key of a catalog run, answering the key-free source protocol.

    Parameters
    ----------
    run : CatalogRun
        The run holding the key.
    key : str
        Data key name.
    """

    run: Any
    key: str

    #: What kind of source this is. ``RunSource`` reads it for the one case
    #: that is genuinely the union's own business rather than either source's:
    #: a frozen stack spectrum plotted against the catalog's X keys.
    kind: str = "catalog"

    def describe(self) -> KeyInfo:
        """
        Return static facts about the key.

        Returns
        -------
        KeyInfo
            Name, label, ``{axis name: length}``, and the render hint.
        """
        return self.run.describe(self.key)

    def load(
        self, slice_info: Optional[tuple] = None, *, coords: bool = True
    ) -> xr.DataArray:
        """
        Return the key's array with its dimensions named.

        Parameters
        ----------
        slice_info : tuple, optional
            Per-axis slice tuple.
        coords : bool, optional
            Attach coordinate values as well as names.

        Returns
        -------
        xarray.DataArray
            Labelled array.
        """
        return self.run.load(self.key, slice_info, coords=coords)

    def plot_axis_names(self, xkeys: Sequence[str]) -> Tuple[str, ...]:
        """
        Return the axis names to plot this key under an X selection.

        Parameters
        ----------
        xkeys : sequence of str
            Selected X-axis keys.

        Returns
        -------
        tuple of str
            One name per storage axis.
        """
        return self.run.plot_axis_names(self.key, xkeys)

    def get_dimension_axes(
        self, xkeys: Sequence[str], slice_info: Optional[tuple] = None
    ) -> Tuple[List[np.ndarray], List[str], Dict[str, Any]]:
        """
        Return real axis coordinates for each dimension of the key.

        Parameters
        ----------
        xkeys : sequence of str
            Selected X-axis keys.
        slice_info : tuple, optional
            Per-axis slice tuple.

        Returns
        -------
        tuple
            ``(axis_arrays, axis_names, associated_data)``.
        """
        return self.run.get_dimension_axes(self.key, list(xkeys), slice_info)
