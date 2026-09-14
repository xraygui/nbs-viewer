"""Tests that a narrowed load orients to the same plane as the full load."""

import numpy as np

from nbs_viewer.models.plot.bundle import prepare_2d_bundle
from nbs_viewer.models.plot.orientation import display_flips
from tests.fixtures.display_plane import orient_block
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle


def _oriented_plane(y, row_axis, col_axis):
    """
    Orient a storage plane and pack it, the way the fetch path does.
    """
    row_reversed, col_reversed = display_flips(row_axis, col_axis, "image")
    reversed_axes = [
        axis for axis, flip in enumerate((row_reversed, col_reversed)) if flip
    ]
    y, (row_axis, col_axis) = orient_block(
        y, [row_axis, col_axis], reversed_axes
    )
    return prepare_2d_bundle(
        y,
        [row_axis, col_axis],
        ["dim_0", "dim_1"],
        render_mode_hint="image",
        row_reversed=row_reversed,
        col_reversed=col_reversed,
    )


def test_narrowed_load_orients_to_the_same_rows_as_the_full_load():
    """
    A crop narrows the load in storage space; the block must land in the
    display plane exactly where the same rows of the full plane land.
    """
    y_count, x_count = 20, 30
    row_axis = np.arange(y_count, dtype=float)
    col_axis = np.arange(x_count, dtype=float)
    y_full = np.arange(y_count * x_count, dtype=float).reshape(y_count, x_count)

    full = _oriented_plane(y_full, row_axis, col_axis)
    frame = frame_from_bundle(full)
    assert frame.row_reversed and not frame.col_reversed

    display_bbox = (4, 13, 5, 15)
    r0, r1, c0, c1 = frame.storage_bbox(display_bbox)
    cropped = _oriented_plane(
        y_full[r0:r1, c0:c1], row_axis[r0:r1], col_axis[c0:c1]
    )

    assert np.array_equal(cropped.y, full.y[4:13, 5:15])
    # Display rows 4:13 of a 20-row reversed plane are storage rows 7:16, so
    # the block covers data y 7..15 and data x 5..14.
    assert cropped.extent == (4.5, 14.5, 6.5, 15.5)


def test_storage_bbox_is_its_own_inverse():
    """
    One method converts both ways, so a crop committed in display space can
    be read back from the storage bounds that were actually loaded.
    """
    bundle = _oriented_plane(
        np.zeros((10, 12)),
        np.arange(10, dtype=float),
        np.arange(12, dtype=float)[::-1],
    )
    frame = frame_from_bundle(bundle)
    assert frame.row_reversed and frame.col_reversed

    display_bbox = (2, 6, 1, 5)
    storage_bbox = frame.storage_bbox(display_bbox)
    assert storage_bbox == (4, 8, 7, 11)
    assert frame.storage_bbox(storage_bbox) == display_bbox
