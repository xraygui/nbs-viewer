"""
How to slice, reduce and orient an array for display -- the vocabulary only.

:mod:`spec` holds :class:`Projection`, the rank-bound description a request
carries, with the roles and aliases it is written in. :mod:`axes` is
:class:`PlotAxes`, the same projection spoken in dimension *names* rather
than storage indices, which is what every stage after the load uses.

**This package imports nothing else in ``models/plot``.** That is the point
of it: everything else here describes data, fetches it or draws it, and all
of them need these words, so the words cannot need anything back. Whenever
something in this package starts wanting a frame or a region, the thing that
wants it is not vocabulary and belongs elsewhere -- which is how
``storage_axis_to_plot_axis`` was found taking a frame it should never have
had, and how ``default_profile_label`` was found to be ROI text.

Nine free functions that took a ``Projection`` as their first argument are
now methods on it, and a tenth that built one is
:meth:`Projection.from_slice_info`. They were the same shape as the methods
the class already carried, and the difference it makes is not tidiness: a
method travels with the object a caller already holds, so asking a
projection a question costs no import at all. That took this surface from
nineteen names to ten, of which nine are types.

The one function left is :func:`resolve_axis_order`, and it is left because
it decides an axis order *before* any projection exists -- policy rather than
a question about a value.
"""

from ..plane import (
    ROLE_LABELS,
    SLICE_ROLES,
    DimRole,
    PlotAxisName,
    SliceItem,
    SpatialReduce,
    ViewCrop,
)
from .axes import PlotAxes
from .spec import Projection, resolve_axis_order

__all__ = [
    "DimRole",
    "PlotAxes",
    "PlotAxisName",
    "Projection",
    "ROLE_LABELS",
    "SLICE_ROLES",
    "SliceItem",
    "SpatialReduce",
    "ViewCrop",
    "resolve_axis_order",
]
