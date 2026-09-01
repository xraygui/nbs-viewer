"""Tests for plot geometry classification and extent computation."""

import numpy as np
import pytest

from nbs_viewer.models.plot.plot_geometry import (
    PlotBundle,
    classify_render_mode,
    get_render_mode_hint,
    is_uniform_1d,
    prepare_2d_bundle,
    prepare_1d_bundle,
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
    assert bundle.y.shape == (400, 30)
    assert bundle.mesh_x.shape == bundle.mesh_y.shape
    assert bundle.y.shape[0] == bundle.mesh_x.shape[0] - 1
    assert bundle.y.shape[1] == bundle.mesh_x.shape[1] - 1


def test_prepare_2d_mesh_mca_like_shape():
    y = np.zeros((202, 800))
    row_axis = np.linspace(0, 10, 202)
    col_axis = np.cumsum(np.linspace(0.1, 0.3, 800))
    bundle = prepare_2d_bundle(y, [row_axis, col_axis], ["energy", "channel"])
    assert bundle.render_mode == "mesh"
    assert bundle.y.shape == (800, 202)
    assert bundle.mesh_x.shape[0] - 1 == bundle.y.shape[0]
    assert bundle.mesh_x.shape[1] - 1 == bundle.y.shape[1]


def test_render_mode_hint_override():
    hints = {
        "primary": [
            {
                "signal": "detector_image",
                "render_mode": "mesh",
            }
        ]
    }
    assert get_render_mode_hint(hints, "detector_image") == "mesh"
    assert get_render_mode_hint(hints, "other") is None


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
