"""
The words the ROI workbench puts on screen.

Neither of these takes a :class:`Projection`, which is what separates them
from the profile-axis queries next door in :mod:`view_spec`: those answer
questions about a view, while these two turn an answer into a string for a
legend or a dropdown. They sat in ``view_spec`` because that is where the
ROI work happened, not because they describe a projection.
"""

from __future__ import annotations

from typing import Sequence

from ..geometry import MaskMode
from ..view_spec import SpatialReduce


def default_profile_label(
    mask_mode: MaskMode,
    spatial_reduce: SpatialReduce,
    profile_axis: int,
    axis_names: Sequence[str],
) -> str:
    """
    Return a short default legend label for an ROI profile.

    Parameters
    ----------
    mask_mode : str
        ``inside`` or ``outside`` the ROI.
    spatial_reduce : str
        ``sum`` or ``mean`` within the ROI.
    profile_axis : int
        Storage axis the profile runs along.
    axis_names : sequence of str
        Names per parent storage axis.

    Returns
    -------
    str
        Label summarizing mask mode, reduce op, and profile axis.
    """
    region = "in" if mask_mode == "inside" else "out"
    return (
        f"{spatial_reduce} ({region} ROI) · "
        f"{profile_axis_name(profile_axis, axis_names)}"
    )


def profile_axis_name(storage_axis: int, axis_names: Sequence[str]) -> str:
    """
    Return a display name for a profile axis dropdown entry.

    Parameters
    ----------
    storage_axis : int
        Storage dimension index.
    axis_names : sequence of str
        Names per storage axis.

    Returns
    -------
    str
        Axis label for UI display.
    """
    if storage_axis < len(axis_names):
        return axis_names[storage_axis]
    return f"axis {storage_axis}"
