"""Build display-ordered 2D planes the way the fetch path does.

``prepare_2d_bundle`` packs a plane; it does not reorder one. Orientation is
a separate step that :meth:`RunSource.get_plot_bundle` runs immediately after
the load, so a test that wants a frame matching what the user sees has to run
it too.
"""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from nbs_viewer.models.plot.plot_geometry import (
    PlotBundle,
    display_flips,
    orient_for_display,
    prepare_2d_bundle,
)
from nbs_viewer.models.plot.plot_view_frame import PlotViewFrame, frame_from_bundle


def oriented_plane(
    y: np.ndarray,
    row_axis: np.ndarray,
    col_axis: np.ndarray,
    render_mode: str = "image",
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[bool, bool]]:
    """
    Reverse a storage plane into display order.

    Returns
    -------
    tuple
        ``(y, row_axis, col_axis, (row_reversed, col_reversed))``.
    """
    row_reversed, col_reversed = display_flips(row_axis, col_axis, render_mode)
    reversed_axes = [
        axis for axis, flip in enumerate((row_reversed, col_reversed)) if flip
    ]
    y, (row_axis, col_axis) = orient_for_display(
        y, [row_axis, col_axis], reversed_axes, {0: 0, 1: 1}
    )
    return y, row_axis, col_axis, (row_reversed, col_reversed)


def display_bundle(
    y: np.ndarray,
    row_axis: np.ndarray,
    col_axis: np.ndarray,
    axis_names: Sequence[str] = ("dim_0", "dim_1"),
    render_mode: str = "image",
) -> PlotBundle:
    """
    Orient a storage plane and pack it into a bundle.
    """
    y, row_axis, col_axis, (row_reversed, col_reversed) = oriented_plane(
        y, row_axis, col_axis, render_mode
    )
    return prepare_2d_bundle(
        y,
        [row_axis, col_axis],
        list(axis_names),
        render_mode_hint=render_mode,
        row_reversed=row_reversed,
        col_reversed=col_reversed,
    )


def display_frame(
    y: np.ndarray,
    row_axis: np.ndarray,
    col_axis: np.ndarray,
    axis_names: Sequence[str] = ("dim_0", "dim_1"),
    render_mode: str = "image",
) -> PlotViewFrame:
    """
    Orient a storage plane and return the frame the user would draw on.
    """
    return frame_from_bundle(
        display_bundle(y, row_axis, col_axis, axis_names, render_mode)
    )
