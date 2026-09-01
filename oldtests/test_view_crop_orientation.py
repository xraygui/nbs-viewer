"""Tests that cropped display matches uncropped imshow orientation."""

import numpy as np

from nbs_viewer.models.plot.plot_geometry import prepare_2d_bundle


def test_prepare_view_crop_bundle_matches_prepare_2d_bundle_orientation():
    y_count, x_count = 20, 30
    row_axis = np.arange(y_count, dtype=float)
    col_axis = np.arange(x_count, dtype=float)
    y_full = np.arange(y_count * x_count, dtype=float).reshape(y_count, x_count)
    full = prepare_2d_bundle(
        y_full,
        [row_axis, col_axis],
        ["dim_0", "dim_1"],
        render_mode_hint="image",
    )
    r0, r1, c0, c1 = 4, 13, 5, 15
    y_slice = y_full[r0:r1, c0:c1]
    cropped = prepare_2d_bundle(
        y_slice,
        [row_axis[r0:r1], col_axis[c0:c1]],
        ["dim_0", "dim_1"],
        render_mode_hint="image",
    )

    assert np.array_equal(cropped.y, full.y[-r1:-r0, c0:c1])
    left, right, bottom, top = cropped.extent
    assert left <= 5.0 and right >= 14.0
    assert bottom <= 4.0 and top >= 12.0
