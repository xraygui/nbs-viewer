"""Tests for mesh and image region mask compilation."""

import numpy as np
import pytest

from nbs_viewer.models.plot.plot_geometry import prepare_2d_bundle
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.region import (
    AxisSliceRegion,
    EllipseRegion,
    PolygonRegion,
    RectRegion,
)
from nbs_viewer.models.plot.region_mesh import mask_from_data_rect
from nbs_viewer.models.plot.plot_bundle import materialize_view
from nbs_viewer.models.plot.view_spec import (
    DimRole,
    Projection,
)
from tests.fixtures.display_plane import labelled_block, profile_axes


def _tes_like_mesh_bundle():
    y = np.ones((30, 400), dtype=float)
    row_axis = np.linspace(200.0, 1000.0, 30)
    col_axis = np.cumsum(np.linspace(0.1, 0.3, 400))
    return prepare_2d_bundle(y, [row_axis, col_axis], ["en_energy", "tes_mca_energies"])


def test_frame_from_mesh_bundle_axes():
    bundle = _tes_like_mesh_bundle()
    assert bundle.render_mode == "mesh"
    frame = frame_from_bundle(bundle)
    assert frame.shape == bundle.y.shape
    # Mesh frames use the same display convention as images: display rows are
    # plot Y, display columns are plot X, in storage order. Which dimension a
    # user wants on the horizontal axis is a view-spec choice, not something
    # the renderer decides.
    assert frame.plot_x_dim == 1
    assert frame.plot_y_dim == 0
    assert frame.plot_y_name == "en_energy"
    assert frame.plot_x_name == "tes_mca_energies"
    assert frame.mesh_x is not None
    assert frame.shape[0] == 30
    assert frame.shape[1] == 400


def test_rect_on_non_uniform_col_selects_cells():
    from nbs_viewer.models.plot.plot_view_frame import (
        cell_x_bounds_mesh,
        cell_y_bounds_mesh,
    )

    bundle = _tes_like_mesh_bundle()
    frame = frame_from_bundle(bundle)
    x0, _ = cell_x_bounds_mesh(frame, 50, 0)
    _, x1 = cell_x_bounds_mesh(frame, 60, 0)
    y0, _ = cell_y_bounds_mesh(frame, 5, 0)
    _, y1 = cell_y_bounds_mesh(frame, 15, 0)
    mask = mask_from_data_rect(frame, x0, x1, y0, y1)
    assert mask.shape == bundle.y.shape
    assert mask.sum() > 0
    assert mask.sum() < mask.size


def test_axis_slice_plot_y_band():
    bundle = _tes_like_mesh_bundle()
    frame = frame_from_bundle(bundle)
    y_lo = float(np.min(frame.mesh_y))
    y_hi = float(np.max(frame.mesh_y))
    mid = (y_lo + y_hi) / 2.0
    region = AxisSliceRegion(axis="plot_y", v0=y_lo, v1=mid)
    compiled = region.compile(frame)
    assert compiled.pixel_count > 0
    assert compiled.pixel_count < compiled.mask.size


def test_profile_along_en_energy_sums_over_tes_band():
    bundle = _tes_like_mesh_bundle()
    y = np.arange(bundle.y.size, dtype=float).reshape(bundle.y.shape)
    frame = frame_from_bundle(bundle)
    from nbs_viewer.models.plot.plot_view_frame import cell_x_bounds_mesh, data_limits

    _, _, y_lo, y_hi = data_limits(frame)
    x0, _ = cell_x_bounds_mesh(frame, 100, 0)
    _, x1 = cell_x_bounds_mesh(frame, 150, 0)
    region = RectRegion(x0=x0, x1=x1, y0=y_lo, y1=y_hi)
    compiled = region.compile(frame)
    parent = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    # Cell centres, not the edge grids. ``mesh_y`` and ``mesh_x`` carry
    # ``n + 1`` edges per axis; passing those as coordinates used to go
    # unnoticed because nothing compared them against the array, and the
    # profile's own coordinates come from the frame rather than from here.
    row_edges = np.nanmean(bundle.mesh_y, axis=1)
    col_edges = np.nanmean(bundle.mesh_x, axis=0)
    row_axis = 0.5 * (row_edges[:-1] + row_edges[1:])
    col_axis = 0.5 * (col_edges[:-1] + col_edges[1:])
    names = ["en_energy", "tes_mca_energies"]
    out = materialize_view(
        labelled_block(y, [row_axis, col_axis], names),
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
    profile = out.values
    assert out.dims == ("en_energy",)
    assert profile.shape == (bundle.y.shape[0],)
    assert np.isfinite(profile).any()
    expected = np.array(
        [
            np.nansum(y[i, compiled.mask[i, :]])
            if compiled.mask[i, :].any()
            else np.nan
            for i in range(y.shape[0])
        ]
    )
    np.testing.assert_allclose(profile, expected, rtol=1e-5, equal_nan=True)


def test_image_rect_mask_shape():
    y = np.zeros((50, 100))
    bundle = prepare_2d_bundle(
        y,
        [np.linspace(0, 10, 50), np.linspace(0, 99, 100)],
        ["y", "x"],
    )
    assert bundle.render_mode == "image"
    frame = frame_from_bundle(bundle)
    assert frame.shape == (50, 100)
    assert frame.plot_x_dim == 1
    region = RectRegion(x0=10.0, x1=20.0, y0=2.0, y1=4.0)
    compiled = region.compile(frame)
    assert compiled.mask.shape == (50, 100)


def test_cell_centers_image_shape_and_order():
    from nbs_viewer.models.plot.region_mesh import cell_centers
    from nbs_viewer.models.plot.plot_view_frame import data_limits

    ny, nx = 4, 5
    bundle = prepare_2d_bundle(
        np.zeros((ny, nx)),
        [np.arange(ny, dtype=float), np.arange(nx, dtype=float)],
        ["y", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    centers_x, centers_y = cell_centers(frame)
    assert centers_x.shape == (ny, nx)
    assert centers_y.shape == (ny, nx)
    left, right, bottom, top = data_limits(frame)
    assert centers_x[0, 0] == pytest.approx(left + 0.5 * (right - left) / nx)
    assert centers_y[0, 0] == pytest.approx(top - 0.5 * (top - bottom) / ny)
    assert centers_y[-1, 0] < centers_y[0, 0]


def test_image_mask_at_plot_top_selects_storage_row_zero():
    """
    Regression: row 0 must map to the top of the axes under origin='upper'.
    """
    from nbs_viewer.models.plot.region_mesh import mask_from_data_rect
    from nbs_viewer.models.plot.plot_view_frame import data_limits

    ny, nx = 10, 12
    bundle = prepare_2d_bundle(
        np.zeros((ny, nx)),
        [np.linspace(0.0, 9.0, ny), np.linspace(0.0, 11.0, nx)],
        ["dim_1", "dim_2"],
    )
    frame = frame_from_bundle(bundle)
    left, right, bottom, top = data_limits(frame)
    mask = mask_from_data_rect(frame, left, right, top - 0.6, top)
    assert mask[0, :].any()
    assert not mask[ny - 1, :].any()


def test_image_rect_mask_matches_imshow_origin_upper():
    """
    ROI rows must follow imshow origin='upper' (row 0 at top of axes).
    """
    from nbs_viewer.models.plot.plot_view_frame import image_cell_bounds

    ny, nx = 20, 30
    y = np.arange(ny * nx, dtype=float).reshape(ny, nx)
    row_axis = np.linspace(100.0, 200.0, ny)
    col_axis = np.linspace(0.0, 29.0, nx)
    bundle = prepare_2d_bundle(y, [row_axis, col_axis], ["dim_1", "dim_2"])
    frame = frame_from_bundle(bundle)
    row, col0, col_last = 3, 5, 7
    x0, _, y0, y1 = image_cell_bounds(frame, row, col0)
    _, x1, _, _ = image_cell_bounds(frame, row, col_last)
    region = RectRegion(x0=x0, x1=x1, y0=y0, y1=y1)
    compiled = region.compile(frame)
    assert compiled.mask[row, col0 : col_last + 1].all()
    assert not compiled.mask[row, :col0].any()
    assert not compiled.mask[row, col_last + 1 :].any()
    assert not compiled.mask[0, :].any()
    assert not compiled.mask[ny - 1, :].any()


def test_ellipse_on_non_uniform_mesh_selects_cells():
    bundle = _tes_like_mesh_bundle()
    frame = frame_from_bundle(bundle)
    x_lo = float(np.nanmin(frame.mesh_x))
    x_hi = float(np.nanmax(frame.mesh_x))
    y_lo = float(np.nanmin(frame.mesh_y))
    y_hi = float(np.nanmax(frame.mesh_y))
    region = EllipseRegion(
        cx=0.5 * (x_lo + x_hi),
        cy=0.5 * (y_lo + y_hi),
        rx=0.2 * (x_hi - x_lo),
        ry=0.15 * (y_hi - y_lo),
        angle=25.0,
    )
    compiled = region.compile(frame)
    assert compiled.mask.shape == bundle.y.shape
    assert compiled.pixel_count > 0
    assert compiled.pixel_count < compiled.mask.size


def test_polygon_on_non_uniform_mesh_selects_cells():
    bundle = _tes_like_mesh_bundle()
    frame = frame_from_bundle(bundle)
    x_lo = float(np.nanmin(frame.mesh_x))
    x_hi = float(np.nanmax(frame.mesh_x))
    y_lo = float(np.nanmin(frame.mesh_y))
    y_hi = float(np.nanmax(frame.mesh_y))
    x_mid = 0.5 * (x_lo + x_hi)
    y_mid = 0.5 * (y_lo + y_hi)
    region = PolygonRegion(
        vertices=(
            (x_lo + 0.1 * (x_hi - x_lo), y_mid),
            (x_mid, y_lo + 0.1 * (y_hi - y_lo)),
            (x_hi - 0.1 * (x_hi - x_lo), y_mid),
            (x_mid, y_hi - 0.1 * (y_hi - y_lo)),
        )
    )
    compiled = region.compile(frame)
    assert compiled.mask.shape == bundle.y.shape
    assert compiled.pixel_count > 0
    assert compiled.pixel_count < compiled.mask.size


def test_nd_roi_profile_on_mesh_plane_matches_masked_sum():
    """
    An ROI drawn on a mesh plane must reduce the cells it actually covers.

    While ``prepare_2d_bundle`` transposed mesh data, the compiled mask was
    shaped for the displayed plane and the array was in storage order, so this
    path raised a shape mismatch rather than producing a profile.
    """
    n_stack, n_row, n_col = 3, 5, 6
    row_axis = np.cumsum(np.linspace(1.0, 2.0, n_row))
    col_axis = np.cumsum(np.linspace(1.0, 3.0, n_col))
    plane = np.arange(n_row)[:, None] * 100.0 + np.arange(n_col)[None, :]
    cube = np.stack([plane, plane * 2.0, plane * 3.0])

    bundle = prepare_2d_bundle(plane, [row_axis, col_axis], ["row", "col"])
    assert bundle.render_mode == "mesh"
    frame = frame_from_bundle(bundle)

    region = RectRegion(
        x0=float(col_axis[2]) - 0.1,
        x1=float(col_axis[3]) + 0.1,
        y0=float(row_axis[1]) - 0.1,
        y1=float(row_axis[2]) + 0.1,
    )
    compiled = region.compile(frame)
    assert compiled.pixel_count == 4

    parent = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0),
    )
    names = ["stack", "row", "col"]
    profile = materialize_view(
        labelled_block(
            cube, [np.arange(n_stack, dtype=float), row_axis, col_axis], names
        ),
        profile_axes(parent, names, 0, "sum", plane_axes=(1, 2)),
        region=region,
        region_frame=frame,
    ).values

    expected = np.array(
        [np.nansum(np.where(compiled.mask, cube[i], np.nan)) for i in range(n_stack)]
    )
    np.testing.assert_allclose(profile, expected, rtol=1e-5)


def test_cell_bounds_vary_with_index_on_an_image_frame():
    """
    Cell bounds must depend on the cell index in both render modes.

    The per-mode index juggling this replaced overwrote the requested row
    with the reference index on image frames, so every plot-Y index returned
    the bounds of the same cell.
    """
    from nbs_viewer.models.plot.plot_view_frame import (
        cell_x_bounds_mesh,
        cell_y_bounds_mesh,
    )

    bundle = prepare_2d_bundle(
        np.zeros((10, 12)),
        [np.arange(10.0), np.arange(12.0)],
        ["y", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)

    assert cell_y_bounds_mesh(frame, 2, 0) != cell_y_bounds_mesh(frame, 7, 0)
    assert cell_x_bounds_mesh(frame, 3, 0) != cell_x_bounds_mesh(frame, 9, 0)
    # display row 0 is the top of an origin="upper" image, so plot Y descends
    assert cell_y_bounds_mesh(frame, 2, 0) > cell_y_bounds_mesh(frame, 7, 0)
    assert cell_x_bounds_mesh(frame, 3, 0) == (2.5, 3.5)
