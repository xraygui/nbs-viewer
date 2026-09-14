"""
How to slice, reduce and orient an array for display -- the vocabulary only.

:mod:`spec` holds :class:`Projection`, the rank-bound description a request
carries, with the roles and aliases it is written in and the queries that
read one. :mod:`axes` is :class:`PlotAxes`, the same projection spoken in
dimension *names* rather than storage indices, which is what every stage
after the load uses.

**This package imports nothing else in ``models/plot``.** That is the point
of it: everything else here describes data, fetches it or draws it, and all
of them need these words, so the words cannot need anything back. Whenever
something in this package starts wanting a frame or a region, the thing that
wants it is not vocabulary and belongs elsewhere -- which is how
``storage_axis_to_plot_axis`` was found taking a frame it should never have
had, and how ``default_profile_label`` was found to be ROI text.

Unlike :mod:`~nbs_viewer.models.plot.geometry`, this surface hides almost
nothing; there is no arithmetic here to hide. It exists so that the 60-odd
callers who want three names -- ``Projection``, ``DimRole``, ``ViewCrop`` --
say one short thing, and so that how these two files divide the vocabulary
can change without touching any of them.

Not exported: ``profile_storage_axis``, which reads the plot-X axis back off
a 1-D profile projection and has no caller anywhere. The name is taken three
times over by a ``RoiOperation`` field and a widget method, which is why it
looked used. Left in place rather than deleted, and not put on the door.
"""

from .axes import PlotAxes
from .spec import (
    ROLE_LABELS,
    SLICE_ROLES,
    DimRole,
    PlotAxisName,
    Projection,
    SliceItem,
    SpatialReduce,
    ViewCrop,
    classify_profile_kind,
    eligible_profile_axes,
    is_plot_plane_storage_axis,
    plot_axis_to_storage_axis,
    profile_view_spec,
    projected_axis_names,
    resolve_axis_order,
    scan_profile_storage_axis,
    spec_from_slice_info,
    storage_axis_to_plot_axis,
)

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
    "classify_profile_kind",
    "eligible_profile_axes",
    "is_plot_plane_storage_axis",
    "plot_axis_to_storage_axis",
    "profile_view_spec",
    "projected_axis_names",
    "resolve_axis_order",
    "scan_profile_storage_axis",
    "spec_from_slice_info",
    "storage_axis_to_plot_axis",
]
