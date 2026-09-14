"""
The set of ROIs a user has drawn, and the words shown for one.

:mod:`set` owns the entries, the selection, and the per-entry stale flags;
the canvas renders from that model rather than holding geometry itself.
:mod:`labels` turns a mask mode, a reduce op and an axis into legend and
dropdown text.

This package is deliberately small, and smaller than the plan predicted. The
profile-axis queries -- ``eligible_profile_axes``, ``profile_view_spec``,
``profile_storage_axis``, ``scan_profile_storage_axis``,
``classify_profile_kind``, ``is_plot_plane_storage_axis`` -- were slated to
move here because the ROI feature is what asks them. They stayed in
:mod:`view_spec`: every one reads a :class:`Projection` and answers a
question about a view, and ``PlotAxes.to_profile`` needs
``profile_view_spec``, so moving it here would make ``view`` import ``roi``
while ``roi`` already imports ``view`` for ``SpatialReduce``. What is left
here is what does *not* take a projection.

The surface is what the ``views/`` layer needs, which is the whole reason
this package has one.
"""

from .labels import default_profile_label, profile_axis_name
from .set import RoiEntry, RoiOperation, RoiSetModel

__all__ = [
    "RoiEntry",
    "RoiOperation",
    "RoiSetModel",
    "default_profile_label",
    "profile_axis_name",
]
