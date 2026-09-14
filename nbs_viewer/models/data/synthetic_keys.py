"""
The naming convention that marks a key as synthetic rather than measured.

A frozen ROI spectrum is registered on a run under a key of its own so the
rest of the application can treat it like any other key. The data layer has to
recognise those keys in order to refuse them -- a synthetic key has no array
in the catalog and reaching for one is a programming error, not a missing
measurement.

The convention lives here, below both layers that use it, because it used to
live in ``models/plot`` and ``models/data/bluesky.py`` imported upward to
reach it. What the data layer needs is the convention, not the class that
follows it: :class:`~nbs_viewer.models.plot.run.frozen_spectrum.FrozenSpectrum`
carries a ``PlotBundle`` and stays in the plot layer.
"""

from __future__ import annotations

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
