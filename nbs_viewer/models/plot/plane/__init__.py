"""
The plot plane: what maps onto it, where its cells are, and what covers them.

Four files, in dependency order. :mod:`roles` holds the words -- the
per-axis roles, the slice and reduce aliases, the mask mode, and
:class:`ViewCrop`. :mod:`orientation` decides how a plane should be drawn,
``image`` or ``mesh``, and which axes reverse. :mod:`frame` is the plane's
coordinate frame and answers where any one cell of it lies. :mod:`mask`
rasterizes a shape against a frame into a boolean mask.

**This package imports nothing else in ``models/plot``**, and
``tests/test_module_boundaries.py`` asserts it. Everything above describes
data, fetches it or draws it, and all of them need these words.
"""

from .frame import PlotViewFrame
from .orientation import RenderMode, classify_render_mode, display_flips
from .roles import (
    ROLE_LABELS,
    SLICE_ROLES,
    DimRole,
    MaskMode,
    PlotAxisName,
    SliceItem,
    SpatialReduce,
    ViewCrop,
)

__all__ = [
    "DimRole",
    "MaskMode",
    "PlotAxisName",
    "PlotViewFrame",
    "ROLE_LABELS",
    "RenderMode",
    "SLICE_ROLES",
    "SliceItem",
    "SpatialReduce",
    "ViewCrop",
    "classify_render_mode",
    "display_flips",
]
