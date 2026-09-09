"""
A run pinned as an immutable reference for other runs to be computed against.

This is the *cross-run* half of "frozen" in this codebase. The other half,
:class:`~nbs_viewer.models.plot.frozen_spectrum.FrozenSpectrum`, is an
intra-run synthetic key produced by an ROI commit and registered on the
``RunSource`` it came from. A :class:`FrozenRun` is a different thing: a
whole run whose data is captured so that a *different* run can be divided
by it, averaged with it, or plotted beside it -- the motivating case being
one run used as the normalization input for a set of others, rather than
normalizing each run by one of its own keys.

It is a :class:`MemoryRun` because that is exactly what it is: arrays in a
dictionary with metadata, static by construction. Immutability is therefore
structural rather than promised -- the arrays are copies, and nothing links
back to the parent.
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional, Tuple

import numpy as np

from .base import CatalogRun
from .memory import MemoryRun


class FreezeError(Exception):
    """Raised when a run cannot be frozen."""


def _x_keys_of(run: CatalogRun) -> List[str]:
    """
    Return the run's x keys, flattened in dimension order.

    Parameters
    ----------
    run : CatalogRun
        Run to inspect.

    Returns
    -------
    list of str
        X keys, lowest dimension first, duplicates removed.
    """
    xkeys, _ykeys = run.getRunKeys()
    ordered: List[str] = []
    for dim in sorted(xkeys or {}):
        for key in xkeys[dim]:
            if key not in ordered:
                ordered.append(key)
    return ordered


class FrozenRun(MemoryRun):
    """
    An immutable capture of one Y key of a run, plus the axes to plot it.

    The captured key keeps its original name, so a frozen run still averages
    or sums with runs that measured the same thing. What it does *not* keep
    is the parent's other detectors: a frozen run offers the key it holds and
    nothing else, so it cannot be mistaken for a general stand-in for its
    parent.

    Parameters
    ----------
    parent : CatalogRun
        Run to capture from. Must be finished; see :meth:`CatalogRun.scanFinished`.
    ykey : str
        The Y key to pin.
    uid : str, optional
        Identifier for the frozen run. A fresh uuid4 by default, because the
        frozen run is a separate member of the collection from its parent.

    Raises
    ------
    FreezeError
        If ``ykey`` is not available on ``parent``, or ``parent`` has not
        finished acquiring.
    """

    def __init__(
        self,
        parent: CatalogRun,
        ykey: str,
        *,
        uid: Optional[str] = None,
    ):
        if ykey not in (parent.available_keys or []):
            raise FreezeError(
                f"Run {parent.scan_id} has no key {ykey!r} to freeze"
            )
        if not parent.scanFinished():
            raise FreezeError(
                f"Run {parent.scan_id} is still acquiring; a snapshot of it "
                "would not be a stable reference"
            )

        xkeys = [
            key for key in _x_keys_of(parent) if key in parent.available_keys
        ]
        captured: Dict[str, np.ndarray] = {}
        for key in xkeys + [ykey]:
            captured[key] = np.array(parent.getData(key), copy=True)

        y_dims, x_dims = parent.get_dims(ykey, xkeys)
        declared: Dict[str, Tuple[str, ...]] = {ykey: tuple(y_dims)}
        for key, dims in x_dims.items():
            declared[key] = tuple(dims)

        metadata = dict(parent.metadata or {})
        metadata.update(
            {
                "uid": uid or str(uuid.uuid4()),
                "plan_name": "Frozen",
                "dims": declared,
                "frozen_from_uid": parent.uid,
                "frozen_key": ykey,
            }
        )

        self._ykey = ykey
        self._parent_scan_id = parent.scan_id
        super().__init__(metadata, captured)

    @property
    def frozen_key(self) -> str:
        """
        Return the Y key this run holds.
        """
        return self._ykey

    @property
    def display_name(self) -> str:
        """
        Return the run-list label, e.g. ``"det of 5"``.
        """
        return f"{self._ykey} of {self._parent_scan_id}"

    def __str__(self) -> str:
        return self.display_name
