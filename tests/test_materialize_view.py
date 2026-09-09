"""Tests for materialize_view."""

import numpy as np
import pytest

from nbs_viewer.models.plot.plot_bundle import materialize_view
from nbs_viewer.models.plot.view_spec import (
    ViewIntent,
    DimRole,
    Projection,
    eligible_profile_axes,
    profile_storage_axis,
    profile_view_spec,
)
from nbs_viewer.models.plot.plot_geometry import prepare_2d_bundle
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.region_mesh import _cell_x_bounds_mesh, _cell_y_bounds_mesh




def test_materialize_view_sum_over_axis():
    y = np.ones((2, 5))
    spec = Projection(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.SUM, DimRole.PLOT_X),
        indices=(0, 0),
    )
    y_out, axes, names = materialize_view(
        y,
        [np.arange(2), np.arange(5)],
        ["row", "col"],
        spec,
    )
    assert y_out.shape == (5,)
    assert np.allclose(y_out, 2.0)
    assert names == ["col"]
    np.testing.assert_array_equal(axes[0], np.arange(5))


def test_materialize_view_mean_and_2d_plot():
    y = np.arange(12).reshape(3, 4)
    spec = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    y_out, axes, names = materialize_view(
        y,
        [np.arange(3), np.arange(4)],
        ["y", "x"],
        spec,
    )
    assert y_out.shape == (3, 4)
    assert names == ["y", "x"]
    np.testing.assert_array_equal(y_out, y)


def test_materialize_view_rejects_region_without_frame():
    spec = ViewIntent(plot_ndim=1).project(2)
    region = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    with pytest.raises(ValueError, match="region_frame is required"):
        materialize_view(
            np.ones((5, 5)),
            [np.arange(5), np.arange(5)],
            ["y", "x"],
            spec,
            region=region,
        )


def test_profile_view_spec_in_plane_roles():
    parent = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    output = profile_view_spec(parent, profile_storage_axis=1, spatial_reduce="sum")
    assert output.plot_ndim == 1
    assert output.roles == (DimRole.SUM, DimRole.PLOT_X)
    along_y = profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="mean")
    assert along_y.roles[0] == DimRole.PLOT_X
    assert along_y.roles[1] == DimRole.MEAN


def test_materialize_in_plane_profile_image():
    y = np.arange(100, dtype=float).reshape(10, 10)
    bundle = prepare_2d_bundle(
        y,
        [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 9.0, 10)],
        ["y", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=2.5, x1=6.5, y0=2.5, y1=6.5)
    compiled = region.compile(frame)
    expected = np.array(
        [
            np.nansum(bundle.y[compiled.mask[:, j], j])
            if compiled.mask[:, j].any()
            else np.nan
            for j in range(bundle.y.shape[1])
        ]
    )

    parent = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    profile, axes, names = materialize_view(
        bundle.y,
        [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 9.0, 10)],
        ["y", "x"],
        profile_view_spec(parent, profile_storage_axis=1, spatial_reduce="sum"),
        region=region,
        region_frame=frame,
    )
    np.testing.assert_allclose(profile, expected, rtol=1e-5, equal_nan=True)
    assert names == ["x"]


def test_materialize_in_plane_profile_mesh():
    y = np.arange(30 * 400, dtype=float).reshape(30, 400)
    col_axis = np.cumsum(np.linspace(0.1, 0.3, 400))
    row_axis = np.linspace(200.0, 1000.0, 30)
    bundle = prepare_2d_bundle(
        y, [row_axis, col_axis], ["en_energy", "tes_mca_energies"]
    )
    frame = frame_from_bundle(bundle)
    x0, _ = _cell_x_bounds_mesh(frame, 10, 0)
    _, x1 = _cell_x_bounds_mesh(frame, 20, 0)
    y0, _ = _cell_y_bounds_mesh(frame, 5, 0)
    _, y1 = _cell_y_bounds_mesh(frame, 8, 0)
    region = RectRegion(x0=x0, x1=x1, y0=y0, y1=y1)
    compiled = region.compile(frame)
    expected = np.array(
        [
            np.nansum(bundle.y[i, compiled.mask[i, :]])
            if compiled.mask[i, :].any()
            else np.nan
            for i in range(bundle.y.shape[0])
        ]
    )

    parent = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    profile, axes, names = materialize_view(
        bundle.y,
        [row_axis, col_axis],
        ["en_energy", "tes_mca_energies"],
        profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="sum"),
        region=region,
        region_frame=frame,
        plot_plane_storage_axes=(frame.plot_y_dim, frame.plot_x_dim),
    )
    np.testing.assert_allclose(profile, expected, rtol=1e-5, equal_nan=True)
    assert names == ["en_energy"]


def test_profile_view_spec_stack_roles():
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    output = profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="mean")
    assert output.plot_ndim == 1
    assert output.roles[0] == DimRole.PLOT_X
    assert output.roles[1] == DimRole.SUM
    assert output.roles[2] == DimRole.MEAN
    assert output.roles[3] == DimRole.MEAN
    assert output.base_slice()[0] == slice(None)
    assert output.base_slice()[1] == slice(None)


def test_eligible_profile_axes_excludes_sum_mean():
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0, 0),
    )
    axes = eligible_profile_axes(parent)
    assert 0 in axes
    assert 2 in axes
    assert 3 in axes
    assert 1 not in axes


def test_materialize_stack_profile_4d():
    e_count, s_count, y_count, x_count = 4, 3, 5, 6
    y = (
        np.arange(e_count)[:, None, None, None] * 1000
        + np.arange(y_count)[None, None, :, None] * 10
        + np.arange(x_count)[None, None, None, :]
    ).astype(float)

    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    y_parent = y.sum(axis=1)[1]
    bundle = prepare_2d_bundle(
        y_parent,
        [np.arange(y_count), np.arange(x_count)],
        ["y", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)

    e_axis = np.linspace(200.0, 500.0, e_count)
    profile, axes, names = materialize_view(
        y,
        [e_axis, np.arange(s_count), np.arange(y_count), np.arange(x_count)],
        ["en_energy", "scan", "y", "x"],
        profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="sum"),
        region=region,
        region_frame=frame,
        plot_plane_storage_axes=(2, 3),
    )

    compiled = region.compile(frame)
    expected = np.full(e_count, np.nan, dtype=float)
    for e in range(e_count):
        plane = y[e].sum(axis=0)
        values = plane[compiled.mask]
        expected[e] = np.nansum(values) if values.size else np.nan

    np.testing.assert_allclose(profile, expected, rtol=1e-5, equal_nan=True)
    np.testing.assert_allclose(axes[0], e_axis, rtol=1e-5)
    assert names == ["en_energy"]


def test_materialize_in_plane_profile_outside_roi():
    y = np.ones((6, 8))
    bundle = prepare_2d_bundle(
        y,
        [np.arange(6), np.arange(8)],
        ["y", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=2.5, x1=4.5, y0=1.5, y1=3.5)
    parent = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    profile, _, _ = materialize_view(
        bundle.y,
        [np.arange(6), np.arange(8)],
        ["y", "x"],
        profile_view_spec(parent, profile_storage_axis=1, spatial_reduce="sum"),
        region=region,
        mask_mode="outside",
        region_frame=frame,
    )
    assert profile.shape == (8,)
    assert np.isfinite(profile).any()
