"""Tests for materialize_view."""

import numpy as np
import pytest

from nbs_viewer.models.plot.stages import materialize_view
from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.view.spec import DimRole, Projection
from nbs_viewer.models.plot.geometry.bundle import prepare_2d_bundle
from nbs_viewer.models.plot.geometry.frame import (
    cell_x_bounds_mesh,
    cell_y_bounds_mesh,
    frame_from_bundle,
)
from nbs_viewer.models.plot.geometry.region import RectRegion
from nbs_viewer.models.plot.view.axes import PlotAxes
from tests.fixtures.display_plane import labelled_block, profile_axes


def test_materialize_view_sum_over_axis():
    y = np.ones((2, 5))
    spec = Projection(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.SUM, DimRole.PLOT_X),
        indices=(0, 0),
    )
    out = materialize_view(
        labelled_block(y, [np.arange(2), np.arange(5)], ["row", "col"]),
        PlotAxes.of(spec, ["row", "col"]),
    )
    assert out.shape == (5,)
    assert np.allclose(out.values, 2.0)
    assert out.dims == ("col",)
    np.testing.assert_array_equal(out.coords["col"].values, np.arange(5))


def test_materialize_view_mean_and_2d_plot():
    y = np.arange(12).reshape(3, 4)
    spec = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    out = materialize_view(
        labelled_block(y, [np.arange(3), np.arange(4)], ["y", "x"]),
        PlotAxes.of(spec, ["y", "x"]),
    )
    assert out.shape == (3, 4)
    assert out.dims == ("y", "x")
    np.testing.assert_array_equal(out.values, y)


def test_materialize_view_rejects_region_without_frame():
    spec = ViewIntent(plot_ndim=1).project(2)
    region = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    with pytest.raises(ValueError, match="region_frame is required"):
        materialize_view(
            labelled_block(np.ones((5, 5)), [np.arange(5), np.arange(5)], ["y", "x"]),
            PlotAxes.of(spec, ["y", "x"]),
            region=region,
        )


def test_profile_view_spec_in_plane_roles():
    parent = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    output = parent.to_profile(profile_storage_axis=1, spatial_reduce="sum")
    assert output.plot_ndim == 1
    assert output.roles == (DimRole.SUM, DimRole.PLOT_X)
    along_y = parent.to_profile(profile_storage_axis=0, spatial_reduce="mean")
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
    out = materialize_view(
        labelled_block(
            bundle.y,
            [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 9.0, 10)],
            ["y", "x"],
        ),
        profile_axes(parent, ["y", "x"], 1, "sum"),
        region=region,
        region_frame=frame,
    )
    np.testing.assert_allclose(out.values, expected, rtol=1e-5, equal_nan=True)
    assert out.dims == ("x",)


def test_materialize_in_plane_profile_mesh():
    y = np.arange(30 * 400, dtype=float).reshape(30, 400)
    col_axis = np.cumsum(np.linspace(0.1, 0.3, 400))
    row_axis = np.linspace(200.0, 1000.0, 30)
    bundle = prepare_2d_bundle(
        y, [row_axis, col_axis], ["en_energy", "tes_mca_energies"]
    )
    frame = frame_from_bundle(bundle)
    x0, _ = cell_x_bounds_mesh(frame, 10, 0)
    _, x1 = cell_x_bounds_mesh(frame, 20, 0)
    y0, _ = cell_y_bounds_mesh(frame, 5, 0)
    _, y1 = cell_y_bounds_mesh(frame, 8, 0)
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
    names = ["en_energy", "tes_mca_energies"]
    out = materialize_view(
        labelled_block(bundle.y, [row_axis, col_axis], names),
        profile_axes(
            parent,
            names,
            0,
            "sum",
            plane_axes=(frame.plot_y_dim, frame.plot_x_dim),
        ),
        region=region,
        region_frame=frame,
    )
    np.testing.assert_allclose(out.values, expected, rtol=1e-5, equal_nan=True)
    assert out.dims == ("en_energy",)


def test_profile_view_spec_stack_roles():
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    output = parent.to_profile(profile_storage_axis=0, spatial_reduce="mean")
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
    axes = parent.eligible_profile_axes()
    assert 0 in axes
    assert 2 in axes
    assert 3 in axes
    assert 1 not in axes


def test_materialize_stack_profile_4d():
    e_count, s_count, y_count, x_count = 4, 3, 5, 6
    # The scan axis is real. It used to broadcast to length 1 while a
    # length-3 coordinate was passed alongside it, so "sum over the stack"
    # summed one slab and nothing noticed -- the old code zipped coordinates
    # against axes and trimmed. Building the array as a DataArray rejects the
    # mismatch, which is the contract doing its job on a test fixture.
    y = np.broadcast_to(
        (
            np.arange(e_count)[:, None, None, None] * 1000
            + np.arange(y_count)[None, None, :, None] * 10
            + np.arange(x_count)[None, None, None, :]
        ).astype(float),
        (e_count, s_count, y_count, x_count),
    ).copy()

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
    names = ["en_energy", "scan", "y", "x"]
    out = materialize_view(
        labelled_block(
            y,
            [e_axis, np.arange(s_count), np.arange(y_count), np.arange(x_count)],
            names,
        ),
        profile_axes(parent, names, 0, "sum", plane_axes=(2, 3)),
        region=region,
        region_frame=frame,
    )

    compiled = region.compile(frame)
    expected = np.full(e_count, np.nan, dtype=float)
    for e in range(e_count):
        plane = y[e].sum(axis=0)
        values = plane[compiled.mask]
        expected[e] = np.nansum(values) if values.size else np.nan

    np.testing.assert_allclose(out.values, expected, rtol=1e-5, equal_nan=True)
    np.testing.assert_allclose(out.coords["en_energy"].values, e_axis, rtol=1e-5)
    assert out.dims == ("en_energy",)


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
    out = materialize_view(
        labelled_block(bundle.y, [np.arange(6), np.arange(8)], ["y", "x"]),
        profile_axes(parent, ["y", "x"], 1, "sum"),
        region=region,
        mask_mode="outside",
        region_frame=frame,
    )
    assert out.shape == (8,)
    assert np.isfinite(out.values).any()


# ---------------------------------------------------------------------------
# What the named stages have to keep true
# ---------------------------------------------------------------------------


def test_a_swapped_axis_order_transposes_the_plane():
    """
    Plot order is the view's, not the array's storage order.

    ``axis_order`` records a manual arrangement of the dimension rows, and the
    reduce has to end with the array laid out that way -- the renderer never
    reorders anything. The transpose used to be a permutation built by
    position from parallel role and name lists; it is now the view's own
    dimension order, intersected with what survives.
    """
    names = ["row", "col"]
    spec = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
        axis_order=(1, 0),
    )
    y = np.arange(12.0).reshape(3, 4)

    out = materialize_view(
        labelled_block(y, [np.arange(3.0), np.arange(4.0)], names),
        PlotAxes.of(spec, names),
    )

    assert out.dims == ("col", "row")
    np.testing.assert_array_equal(out.values, y.T)
    np.testing.assert_array_equal(out.coords["col"].values, np.arange(4.0))


def test_the_projection_reduce_is_not_nan_aware():
    """
    ``sum`` here means ``np.sum``, and a NaN in the data propagates.

    The NaN-aware reducer belongs to the masked ROI reduce and nowhere else:
    there, NaN means "outside the region", and treating it as a zero is the
    point. Here NaN means a missing measurement, and hiding it would make a
    detector dropout indistinguishable from a real value. xarray's default is
    the other way round, so the flag is explicit and this is what holds it.
    """
    names = ["row", "col"]
    spec = Projection(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.SUM, DimRole.PLOT_X),
        indices=(0, 0),
    )
    y = np.ones((2, 5))
    y[0, 2] = np.nan

    out = materialize_view(
        labelled_block(y, [np.arange(2.0), np.arange(5.0)], names),
        PlotAxes.of(spec, names),
    )

    np.testing.assert_array_equal(np.isnan(out.values), [0, 0, 1, 0, 0])
    np.testing.assert_allclose(out.values[[0, 1, 3, 4]], 2.0)


def test_the_roi_mask_aligns_by_name_not_by_position():
    """
    The plane is not always the array's trailing pair.

    Profiling along a cube's slider axis leaves the plane at the *leading*
    axes, because the surviving dimensions are in storage order and the slider
    can outrank both plane axes. That used to need a hand transpose of the
    compiled mask plus a reshape into the right broadcast shape. A mask
    labelled with the plane's dimension names lands on those axes wherever
    they are, so building it the other way round gives the same answer.
    """
    n_stack, n_row, n_col = 3, 5, 6
    cube = np.arange(n_stack * n_row * n_col, dtype=float).reshape(
        n_stack, n_row, n_col
    )
    bundle = prepare_2d_bundle(
        cube[0],
        [np.arange(n_row, dtype=float), np.arange(n_col, dtype=float)],
        ["row", "col"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    compiled = region.compile(frame)

    names = ["stack", "row", "col"]
    parent = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0),
    )
    out = materialize_view(
        labelled_block(
            cube,
            [
                np.arange(n_stack, dtype=float),
                np.arange(n_row, dtype=float),
                np.arange(n_col, dtype=float),
            ],
            names,
        ),
        profile_axes(parent, names, 0, "sum", plane_axes=(1, 2)),
        region=region,
        region_frame=frame,
    )

    expected = np.array(
        [np.nansum(np.where(compiled.mask, cube[i], np.nan)) for i in range(n_stack)]
    )
    assert out.dims == ("stack",)
    np.testing.assert_allclose(out.values, expected)
