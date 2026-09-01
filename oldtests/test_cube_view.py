"""Tests for N-D cube view specification and application."""

import numpy as np
import pytest

from nbs_viewer.models.plot.cube_view import (
    DimRole,
    apply_cube_view,
    default_spec,
    resolve_roles,
    spec_for_plot_ndim,
    spec_from_slice_info,
    CubeViewSpec,
)


def test_default_spec_1d_trailing_axis():
    spec = default_spec(4, plot_ndim=1)
    assert spec.roles == (
        DimRole.INDEX,
        DimRole.INDEX,
        DimRole.INDEX,
        DimRole.PLOT_X,
    )
    assert spec.to_load_slice_info() == (0, 0, 0, slice(None))


def test_default_spec_2d_trailing_axes():
    spec = default_spec(4, plot_ndim=2)
    assert spec.roles[-2:] == (DimRole.PLOT_Y, DimRole.PLOT_X)
    assert spec.to_load_slice_info()[-2:] == (slice(None), slice(None))


def test_spec_from_slice_info_roundtrip():
    legacy = (0, 0, slice(None))
    spec = spec_from_slice_info(legacy, plot_ndim=1)
    assert spec.roles[0] == DimRole.INDEX
    assert spec.roles[-1] == DimRole.PLOT_X


def test_apply_cube_view_index_and_plot_x():
    y = np.arange(24).reshape(2, 3, 4)
    spec = CubeViewSpec(
        ndim=3,
        plot_ndim=1,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_X),
        indices=(1, 2, 0),
    )
    y_out, axes, names = apply_cube_view(
        y[1, 2, :],
        [np.arange(2), np.arange(3), np.arange(4)],
        ["a", "b", "c"],
        spec,
    )
    assert y_out.shape == (4,)
    np.testing.assert_array_equal(y_out, y[1, 2, :])
    assert names == ["c"]
    np.testing.assert_array_equal(axes[0], np.arange(4))


def test_apply_cube_view_sum_over_axis():
    y = np.ones((2, 5))
    spec = CubeViewSpec(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.SUM, DimRole.PLOT_X),
        indices=(0, 0),
    )
    y_out, axes, names = apply_cube_view(
        y,
        [np.arange(2), np.arange(5)],
        ["row", "col"],
        spec,
    )
    assert y_out.shape == (5,)
    assert np.allclose(y_out, 2.0)


def test_apply_cube_view_mean_and_2d_plot():
    y = np.arange(12).reshape(3, 4)
    spec = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    y_out, axes, names = apply_cube_view(
        y,
        [np.arange(3), np.arange(4)],
        ["y", "x"],
        spec,
    )
    assert y_out.shape == (3, 4)
    assert names == ["y", "x"]


def test_swap_rows_exchanges_roles():
    spec = default_spec(3, plot_ndim=1)
    swapped = spec.swap_rows(1)
    d0, d1 = spec.axis_order[0], spec.axis_order[1]
    assert swapped.roles[d0] == spec.roles[d1]
    assert swapped.roles[d1] == spec.roles[d0]


def test_resolve_roles_from_axis_order():
    spec = CubeViewSpec(
        ndim=3,
        plot_ndim=1,
        roles=(DimRole.SUM, DimRole.INDEX, DimRole.INDEX),
        indices=(0, 0, 0),
        axis_order=(2, 0, 1),
    )
    resolved = resolve_roles(spec)
    assert resolved.roles[1] == DimRole.PLOT_X
    assert resolved.roles[0] == DimRole.SUM


def test_swap_rows_moves_plot_axis():
    spec = default_spec(3, plot_ndim=1)
    swapped = spec.swap_rows(2)
    assert swapped.roles[swapped.axis_order[-1]] == DimRole.PLOT_X


def test_with_slice_role():
    spec = default_spec(3, plot_ndim=1)
    updated = spec.with_slice_role(0, DimRole.SUM)
    assert updated.roles[0] == DimRole.SUM


def test_spec_for_plot_ndim_switches_to_2d():
    spec = default_spec(4, plot_ndim=1)
    spec2 = spec_for_plot_ndim(spec, 2)
    assert spec2.plot_ndim == 2
    assert spec2.roles[-2:] == (DimRole.PLOT_Y, DimRole.PLOT_X)


def test_resolve_roles_fixes_duplicate_plot_x():
    spec = CubeViewSpec(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.PLOT_X, DimRole.PLOT_X),
        indices=(0, 0),
    )
    assert sum(1 for r in spec.roles if r == DimRole.PLOT_X) == 1
