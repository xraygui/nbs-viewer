"""
The labelled-array contract the data sources return, and its library settings.

Every source answers two questions about a key: :meth:`describe`, which is
static and reads nothing, and :meth:`load`, which returns an
``xarray.DataArray`` whose dimensions are named and whose coordinates are
attached. This module holds the construction that enforces that contract and
the two xarray defaults that would otherwise quietly break it.

xarray is not a new dependency: it already arrives through
``bluesky-widgets -> bluesky-live``, non-extra at every hop. What changed is
that it is now declared.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Tuple

import numpy as np
import xarray as xr


# ``inner`` is xarray's default and it is a silent-wrong-answer generator for
# this pipeline: ``y / norm`` on coordinates that do not match drops the rows
# they do not share and returns a shorter array, with nothing raised. Measured:
# a 5-row y divided by a 4-row norm returns 4 rows. ``exact`` raises instead.
#
# This matters most for data this codebase does not handle yet. With fly-scanned
# data each detector is its own timestream, so two keys whose axis is named
# ``time`` no longer share that axis; equal-length streams sampled out of phase
# are exactly the case a shape check cannot catch and a coordinate check can.
#
# Set at import of the data layer rather than around each call, because the
# hazard is an arithmetic expression written *without* thinking about joins.
ARITHMETIC_JOIN = "exact"

xr.set_options(arithmetic_join=ARITHMETIC_JOIN)


# xarray has no global equivalent for ``skipna``; it is a per-call argument, and
# its default (True for float data) erases a distinction this pipeline makes on
# purpose -- ``np.sum`` for the projection reduce against ``np.nansum`` for the
# masked ROI reduce. The reductions are still numpy today, so there is nothing
# to pin here yet; the setting belongs with the stages when they convert.
REDUCE_SKIPNA = False


def surviving_dims(
    dims: Sequence[str], slice_info: Optional[tuple]
) -> Tuple[str, ...]:
    """
    Return the dimension names left after applying a slice tuple.

    An integer item indexes an axis away; a slice keeps it. This is the same
    convention ``CatalogRun.getData`` applies, so the two agree by
    construction rather than by coincidence.

    Parameters
    ----------
    dims : sequence of str
        Storage dimension names, one per storage axis.
    slice_info : tuple or None
        Per-axis slice tuple, or None for the whole array.

    Returns
    -------
    tuple of str
        Names of the axes that survive.
    """
    if slice_info is None:
        return tuple(dims)
    items = list(slice_info[: len(dims)])
    while len(items) < len(dims):
        items.append(slice(None))
    return tuple(
        name
        for name, item in zip(dims, items)
        if not isinstance(item, (int, np.integer))
    )


def labelled_array(
    values: np.ndarray,
    dims: Sequence[str],
    *,
    coords: Optional[Mapping[str, Any]] = None,
    name: Optional[str] = None,
    attrs: Optional[Mapping[str, Any]] = None,
) -> xr.DataArray:
    """
    Build the contract's return value, or fail loudly.

    ``xr.DataArray`` already raises on the two disagreements this codebase has
    produced -- more dimension names than the array has axes (bug 6), and a
    coordinate whose length disagrees with the data -- so this adds only the
    check xarray declines to make: duplicate dimension names, which it accepts
    with a warning that *"most xarray functionality is likely to fail silently
    if you do not [rename]"*. Bug 15 produced exactly that.

    Parameters
    ----------
    values : ndarray
        Storage array.
    dims : sequence of str
        One name per axis of ``values``.
    coords : mapping, optional
        Coordinates to attach, keyed by dimension name.
    name : str, optional
        Name for the array, normally the data key.
    attrs : mapping, optional
        Metadata. Note that xarray drops ``attrs`` silently through reductions
        and arithmetic, so nothing load-bearing may travel here.

    Returns
    -------
    xarray.DataArray
        Labelled array.

    Raises
    ------
    ValueError
        If two axes are given the same name.
    """
    dims = tuple(dims)
    if len(set(dims)) != len(dims):
        raise ValueError(
            f"duplicate dimension names for {name!r}: {dims}. Two axes with "
            "one name cannot be told apart, and normalization aligns by name."
        )
    return xr.DataArray(
        np.asarray(values),
        dims=dims,
        coords=dict(coords or {}),
        name=name,
        attrs=dict(attrs or {}),
    )


def index_placeholders(shape: Sequence[int]) -> Tuple[np.ndarray, ...]:
    """
    Return index coordinates, one array per axis.

    What a description without a load can offer for an axis: its position
    numbers. Real coordinates come from :meth:`CatalogRun.load`, and a caller
    that has both prefers those. This used to be a stored field on the
    description, which meant every describe built and carried ``arange``
    arrays whether or not anything looked at them.

    Parameters
    ----------
    shape : sequence of int
        Axis lengths.

    Returns
    -------
    tuple of ndarray
        ``arange`` per axis.
    """
    return tuple(np.arange(size, dtype=float) for size in shape)
