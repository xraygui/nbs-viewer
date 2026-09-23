"""
The set of ROIs a user has drawn.

:mod:`set` owns the entries, the selection, and the per-entry stale flags;
the canvas renders from that model rather than holding geometry itself.

This package is deliberately small, and smaller than the plan predicted. Six
profile-axis queries were slated to move here because the ROI feature is what
asks them. They did not, and they no longer exist as functions: each one read
a :class:`~nbs_viewer.models.plot.view.Projection` and is now a method on it,
so the ROI code asks the projection directly and imports nothing to do it.
What belongs here is what never took a projection in the first place.

The surface is what the ``views/`` layer needs, which is the whole reason
this package has one.
"""

from .set import RoiEntry, RoiOperation, RoiSetModel

__all__ = [
    "RoiEntry",
    "RoiOperation",
    "RoiSetModel",
]
