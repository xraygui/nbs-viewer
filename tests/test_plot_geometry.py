"""Tests for plot geometry classification and extent computation."""

import numpy as np
import pytest

from tests.fixtures.display_plane import orient_block
from nbs_viewer.models.plot.plot_geometry import (
    classify_render_mode,
    display_flips,
    is_uniform_1d,
    prepare_2d_bundle,
    prepare_1d_bundle,
)


def _packed_for_display(y, row_axis, col_axis, axis_names, render_mode):
    """
    Orient a storage plane and pack it, the way the fetch path does.

    ``prepare_2d_bundle`` no longer reorders anything; orientation is a
    separate step that runs immediately after the load.
    """
    row_reversed, col_reversed = display_flips(row_axis, col_axis, render_mode)
    reversed_axes = [
        axis
        for axis, flip in enumerate((row_reversed, col_reversed))
        if flip
    ]
    y, (row_axis, col_axis) = orient_block(
        y, [row_axis, col_axis], reversed_axes
    )
    return prepare_2d_bundle(
        y,
        [row_axis, col_axis],
        axis_names,
        render_mode_hint=render_mode,
        row_reversed=row_reversed,
        col_reversed=col_reversed,
    )


def test_is_uniform_1d_uniform():
    assert is_uniform_1d(np.arange(10.0))


def test_is_uniform_1d_non_uniform():
    assert not is_uniform_1d(np.cumsum(np.linspace(1, 2, 20)))


def test_classify_no_axes_detector_image():
    y_shape = (2160, 2560)
    assert classify_render_mode(y_shape, []) == "image"


def test_classify_uniform_axes():
    y_shape = (100, 200)
    x_axes = [np.arange(100.0), np.arange(200.0)]
    assert classify_render_mode(y_shape, x_axes) == "image"


def test_classify_non_uniform_energy():
    y_shape = (50, 400)
    energy = np.cumsum(np.linspace(0.1, 0.3, 400))
    motor = np.linspace(0, 10, 50)
    assert classify_render_mode(y_shape, [motor, energy]) == "mesh"


def test_classify_2d_coordinate_grid():
    y_shape = (10, 20)
    x_axes = [np.zeros((10, 20)), np.zeros((10, 20))]
    assert classify_render_mode(y_shape, x_axes) == "mesh"


def test_classify_length_mismatch():
    y_shape = (10, 20)
    x_axes = [np.arange(5.0), np.arange(20.0)]
    assert classify_render_mode(y_shape, x_axes) == "mesh"


def test_prepare_2d_image_extent():
    y = np.zeros((2160, 2560))
    bundle = prepare_2d_bundle(y, [], [])
    assert bundle.render_mode == "image"
    assert bundle.extent is not None
    left, right, bottom, top = bundle.extent
    assert right - left == pytest.approx(2560.0)
    assert top - bottom == pytest.approx(2160.0)


def test_prepare_2d_image_uniform_extent():
    y = np.zeros((100, 200))
    x_axes = [np.arange(100.0), np.linspace(0, 199, 200)]
    bundle = prepare_2d_bundle(y, x_axes, ["row", "col"])
    assert bundle.render_mode == "image"
    left, right, bottom, top = bundle.extent
    assert left == pytest.approx(-0.5)
    assert right == pytest.approx(199.5)
    assert bottom == pytest.approx(-0.5)
    assert top == pytest.approx(99.5)


def test_prepare_2d_mesh_has_grids():
    y = np.random.rand(30, 400)
    energy = np.cumsum(np.linspace(0.1, 0.3, 400))
    motor = np.linspace(0, 10, 30)
    bundle = prepare_2d_bundle(y, [motor, energy], ["motor", "energy"])
    assert bundle.render_mode == "mesh"
    assert bundle.mesh_x is not None
    assert bundle.mesh_y is not None
    # Storage order is preserved: rows stay rows, as in image mode.
    assert bundle.y.shape == (30, 400)
    assert bundle.axis_names == ["motor", "energy"]
    assert bundle.mesh_x.shape == bundle.mesh_y.shape
    assert bundle.y.shape[0] == bundle.mesh_x.shape[0] - 1
    assert bundle.y.shape[1] == bundle.mesh_x.shape[1] - 1


def test_prepare_2d_mesh_mca_like_shape():
    y = np.zeros((202, 800))
    row_axis = np.linspace(0, 10, 202)
    col_axis = np.cumsum(np.linspace(0.1, 0.3, 800))
    bundle = prepare_2d_bundle(y, [row_axis, col_axis], ["energy", "channel"])
    assert bundle.render_mode == "mesh"
    assert bundle.y.shape == (202, 800)
    assert bundle.axis_names == ["energy", "channel"]
    assert bundle.mesh_x.shape[0] - 1 == bundle.y.shape[0]
    assert bundle.mesh_x.shape[1] - 1 == bundle.y.shape[1]


def test_prepare_1d_bundle():
    y = np.sin(np.linspace(0, 1, 50))
    x = np.linspace(0, 10, 50)
    bundle = prepare_1d_bundle(y, [x], ["time"])
    assert bundle.render_mode == "line"
    assert bundle.ndim == 1
    np.testing.assert_array_equal(bundle.x_line, x)


def test_hint_forces_image_on_non_uniform():
    y = np.zeros((10, 20))
    energy = np.cumsum(np.linspace(0.1, 0.3, 20))
    motor = np.linspace(0, 10, 10)
    bundle = prepare_2d_bundle(
        y, [motor, energy], ["m", "e"], render_mode_hint="image"
    )
    assert bundle.render_mode == "image"


def test_image_extent_decreasing_row_axis_is_not_inverted():
    """
    Cropped ROI rows often run from high dim_1 to low; extent must stay ascending.
    """
    row_axis = np.linspace(645.0, 361.0, 8)
    col_axis = np.linspace(353.0, 605.0, 10)
    y = np.arange(80, dtype=float).reshape(8, 10)
    bundle = prepare_2d_bundle(y, [row_axis, col_axis], ["dim_1", "dim_2"])
    left, right, bottom, top = bundle.extent
    assert bottom < top
    dy = (top - bottom) / 8
    assert top - 0.5 * dy == pytest.approx(645.0, rel=0.01)
    assert bottom + 0.5 * dy == pytest.approx(361.0, rel=0.01)


def _screen_position(bundle, value):
    """
    Return the (horizontal, vertical) data coordinate of a marked cell.

    Works for either render mode so the two can be compared directly.
    """
    arr = np.asarray(bundle.y)
    (row,), (col,) = np.where(arr == value)
    if bundle.render_mode == "image":
        left, right, bottom, top = bundle.extent
        return (
            left + (col + 0.5) * (right - left) / arr.shape[1],
            top - (row + 0.5) * (top - bottom) / arr.shape[0],
        )
    return (
        float(np.mean(bundle.mesh_x[row : row + 2, col : col + 2])),
        float(np.mean(bundle.mesh_y[row : row + 2, col : col + 2])),
    )


def test_image_and_mesh_agree_on_axis_placement():
    """
    The renderer must not decide which dimension goes on which screen axis.

    ``classify_render_mode`` switches to mesh whenever an axis is non-uniform,
    so if the two modes disagreed here a dataset would silently rotate when
    its coordinates drifted off a uniform grid.
    """
    row_axis = np.array([10.0, 20.0, 30.0, 40.0])
    col_axis = np.array([100.0, 200.0, 300.0, 400.0, 500.0, 600.0])
    y = np.zeros((4, 6))
    y[2, 4] = 1.0

    image = _packed_for_display(
        y, row_axis, col_axis, ["axis0", "axis1"], "image"
    )
    mesh = _packed_for_display(
        y, row_axis, col_axis, ["axis0", "axis1"], "mesh"
    )

    assert image.y.shape == mesh.y.shape == y.shape
    assert image.axis_names == mesh.axis_names == ["axis0", "axis1"]
    assert _screen_position(image, 1.0) == _screen_position(mesh, 1.0)
    # storage axis 1 is horizontal, storage axis 0 is vertical, in both modes
    assert _screen_position(image, 1.0) == (500.0, 30.0)


# ---------------------------------------------------------------------------
# The pack is where display order begins
# ---------------------------------------------------------------------------


def _plain_2d_request():
    """A 2-D request with no region, for the packing step."""
    from nbs_viewer.models.plot.plot_request import build_plot_request
    from nbs_viewer.models.plot.view_intent import ViewIntent

    return build_plot_request(
        uid="uid",
        xkeys=["x"],
        ykey="det",
        projection=ViewIntent(plot_ndim=2).project(2, (4, 5)),
    )


@pytest.mark.parametrize("row_descending", [False, True], ids=["row asc", "row desc"])
@pytest.mark.parametrize("col_descending", [False, True], ids=["col asc", "col desc"])
def test_the_pack_turns_the_plane_the_right_way_up(row_descending, col_descending):
    """
    ``build_plot_bundle`` is the only place data is ever reordered.

    It used to happen immediately after the load, on the whole N-D block,
    which made a matplotlib convention -- ``origin="upper"`` puts storage row
    0 at the top -- reach five stages back: a normalization array sharing a
    plot-plane axis had to be reversed to match, the block cache had to mirror
    its windows, and the render mode had to be classified before the reduce so
    the flip could be decided.

    All four orientations are checked because three of them are flips, and a
    reversal applied to the wrong axis is a silently plausible image.
    """
    from nbs_viewer.models.plot.plot_geometry import build_plot_bundle
    from tests.fixtures.display_plane import labelled_block

    y = np.arange(20.0).reshape(4, 5)
    rows = np.arange(4.0)[::-1] if row_descending else np.arange(4.0)
    cols = np.arange(5.0)[::-1] if col_descending else np.arange(5.0)

    bundle = build_plot_bundle(
        labelled_block(y, [rows, cols], ["row", "col"]), _plain_2d_request()
    )

    # Display order is the order in which the coordinates ascend upward and
    # rightward, which is what ``imshow(origin="upper")`` needs.
    expected = y
    if not row_descending:
        expected = np.flip(expected, axis=0)
    if col_descending:
        expected = np.flip(expected, axis=1)
    np.testing.assert_array_equal(bundle.y, expected)

    assert bundle.row_reversed is (not row_descending)
    assert bundle.col_reversed is col_descending
    assert bundle.render_mode == "image"


def test_the_pack_leaves_a_mesh_alone():
    """
    A mesh carries its own coordinate grids, so nothing is ever reordered.
    """
    from nbs_viewer.models.plot.plot_geometry import build_plot_bundle
    from tests.fixtures.display_plane import labelled_block

    y = np.arange(20.0).reshape(4, 5)
    rows = np.arange(4.0)
    cols = np.cumsum(np.linspace(0.1, 0.9, 5))

    bundle = build_plot_bundle(
        labelled_block(y, [rows, cols], ["row", "col"]), _plain_2d_request()
    )

    assert bundle.render_mode == "mesh"
    assert bundle.row_reversed is False
    assert bundle.col_reversed is False
    np.testing.assert_array_equal(bundle.y, y)
