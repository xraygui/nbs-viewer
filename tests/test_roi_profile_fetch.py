"""Tests for ROI profile requests and the cached-plane reduction."""

import numpy as np
import pytest

from nbs_viewer.models.plot.plane.roles import DimRole
from nbs_viewer.models.plot.spec.projection import Projection
from nbs_viewer.models.plot.spec.bundle import prepare_2d_bundle
from nbs_viewer.models.plot.spec.request import PlotRequest
from nbs_viewer.models.plot.spec.plan import plan_fetch
from nbs_viewer.models.plot.spec.region import (
    PolygonRegion,
    RectRegion,
    compile_with_mask_mode,
)

from tests.fixtures.display_plane import (
    display_bundle,
    display_frame,
    roi_profile_from_block,
)


def _plane_request(parent: Projection) -> PlotRequest:
    """
    Build the request that draws the parent 2-D plane.
    """
    return PlotRequest(
        uid="uid",
        xkeys=("x",
),
        ykey="y",
        norm_keys=(),
        view=parent,
        dims=tuple(f"dim_{axis}" for axis in range(parent.ndim))
)


def _profile_request(parent, region, *, profile_axis, reduce="sum"):
    """
    Build the ROI profile request the fetch path would carry.
    """
    return _plane_request(parent).with_roi_profile(
        region,
        profile_axis=profile_axis,
        spatial_reduce=reduce
)


_PLANE_2D = Projection(
    ndim=2,
    plot_ndim=2,
    roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
    indices=(0, 0),
)


def test_cached_plane_profile_mesh():
    y = np.arange(30 * 400, dtype=float).reshape(30, 400)
    col_axis = np.cumsum(np.linspace(0.1, 0.3, 400))
    row_axis = np.linspace(200.0, 1000.0, 30)
    plane = prepare_2d_bundle(
        y, [row_axis, col_axis], ["en_energy", "tes_mca_energies"]
    )
    frame = plane.view_frame()
    x0, _ = frame.cell_x_bounds(10, 0)
    _, x1 = frame.cell_x_bounds(20, 0)
    y0, _ = frame.cell_y_bounds(5, 0)
    _, y1 = frame.cell_y_bounds(8, 0)

    request = _profile_request(
        _PLANE_2D,
        RectRegion(x0=x0, x1=x1, y0=y0, y1=y1),
        profile_axis=frame.plot_y_dim
)
    bundle = request.reduce_cached_plane(plane, label="test roi")

    assert bundle.render_mode == "line"
    assert bundle.ndim == 1
    assert bundle.y.shape == (plane.y.shape[0],)
    assert np.isfinite(bundle.y).any()


def test_span_full_expands_an_in_plane_profile_only():
    plane = prepare_2d_bundle(
        np.ones((10, 20)),
        [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 19.0, 20)],
        ["a", "b"]
)
    frame = plane.view_frame()
    narrow = RectRegion(x0=5.0, x1=8.0, y0=3.0, y1=4.0)

    expanded = _plane_request(_PLANE_2D).with_roi_profile(
        narrow,
        profile_axis=1,
        plane_frame=frame,
        span_full=True
).region
    assert expanded.y0 == pytest.approx(3.0)
    assert expanded.y1 == pytest.approx(4.0)
    assert expanded.x0 == pytest.approx(-0.5)
    assert expanded.x1 == pytest.approx(19.5)

    stack_parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0, 0)
)
    unchanged = _plane_request(stack_parent).with_roi_profile(
        narrow,
        profile_axis=0,
        plane_frame=frame,
        span_full=True
).region
    assert unchanged.x0 == narrow.x0
    assert unchanged.y0 == narrow.y0


def test_cached_plane_profile_with_4d_parent_spec():
    y = np.arange(100, dtype=float).reshape(10, 10)
    plane = prepare_2d_bundle(
        y,
        [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 9.0, 10)],
        ["dim_1", "dim_2"],
        render_mode_hint="image"
)
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0, 0)
)
    request = _profile_request(
        parent,
        RectRegion(x0=2.5, x1=6.5, y0=2.5, y1=6.5),
        profile_axis=parent.storage_axis_for("plot_x")
)

    bundle = request.reduce_cached_plane(plane)

    assert bundle.render_mode == "line"
    assert bundle.y.shape == (10,
)
    assert np.isfinite(bundle.y).any()


# A right triangle: a rectangle fills its own bounding box, so its mask is
# invariant under reversal and cannot tell the two orders apart.
_TRIANGLE = PolygonRegion(vertices=((1.0, 0.4), (5.4, 0.4), (1.0, 4.6)))


def _display_profile(bundle, region, along):
    """
    Mask the displayed plane directly, one value and coordinate per bin.

    Shares nothing with the code under test but the mask compiler: the plane
    is what the user sees and the mask is compiled on the frame they drew
    on, so no orientation is involved at all.
    """
    frame = bundle.view_frame()
    mask = compile_with_mask_mode(frame, region, "inside").mask
    shown = np.where(mask, np.asarray(bundle.y), np.nan)
    left, right, bottom, top = frame.extent
    ny, nx = frame.shape
    if along == "plot_x":
        values = np.nansum(shown, axis=0)
        values[~mask.any(axis=0)] = np.nan
        coords = left + (np.arange(nx) + 0.5) * (right - left) / nx
    else:
        values = np.nansum(shown, axis=1)
        values[~mask.any(axis=1)] = np.nan
        coords = top - (np.arange(ny) + 0.5) * (top - bottom) / ny
    return coords, values


@pytest.mark.parametrize("along", ["plot_x", "plot_y"])
@pytest.mark.parametrize(
    "row_descending,col_descending",
    [(False, False), (True, False), (False, True), (True, True)],
    ids=["both ascending", "row descending", "col descending", "both descending"],
)
def test_an_in_plane_profile_masks_the_cells_the_user_drew_on(
    along, row_descending, col_descending
):
    """
    Ground truth for the in-plane route, in every orientation.

    The cached plane is display-ordered, while the masking stage works in
    storage order and turns the mask round to meet it. Handing it the plane
    as displayed turned the mask twice: an ROI drawn low on a row-reversed
    image summed the mirror-image rows at the top. The off-plane route had a
    four-orientation ground-truth test; this one was only ever compared with
    itself.
    """
    ny, nx = 7, 8
    storage = (np.arange(ny)[:, None] * 10 + np.arange(nx)[None, :]).astype(
        float
    )
    rows = np.arange(ny, dtype=float)
    cols = np.arange(nx, dtype=float)
    if row_descending:
        rows = rows[::-1].copy()
    if col_descending:
        cols = cols[::-1].copy()
    plane = display_bundle(storage, rows, cols, ("y", "x"))
    request = _profile_request(
        _PLANE_2D, _TRIANGLE, profile_axis=1 if along == "plot_x" else 0
    )

    got = request.reduce_cached_plane(plane)
    coords, values = _display_profile(plane, _TRIANGLE, along)

    # Pair by coordinate: the order a 1-D profile comes out in is not the
    # point, which value sits at which coordinate is.
    want, have = np.argsort(coords), np.argsort(got.x_line)
    np.testing.assert_allclose(got.x_line[have], coords[want])
    np.testing.assert_allclose(got.y[have], values[want])


def test_cached_plane_refuses_an_off_plane_profile():
    plane = prepare_2d_bundle(
        np.ones((6, 7)),
        [np.arange(6, dtype=float), np.arange(7, dtype=float)],
        ["dim_1", "dim_2"],
        render_mode_hint="image"
)
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0)
)
    request = _profile_request(
        parent, RectRegion(x0=1.5, x1=4.5, y0=0.5, y1=3.5), profile_axis=0
    )

    with pytest.raises(ValueError, match="off-plane"):
        request.reduce_cached_plane(plane)


# The selection-driven default from step 2: X key ``x`` is storage axis 0 and
# is plotted horizontally, so the plot-axis order is (1, 0) and neither plot
# axis sits at its own storage index.
_SELECTION_DRIVEN = Projection(
    ndim=2,
    plot_ndim=2,
    roles=(DimRole.PLOT_X, DimRole.PLOT_Y),
    indices=(0, 0),
    axis_order=(1, 0),
)


def test_storage_axis_to_plot_axis_follows_the_spec_not_the_frame():
    """
    The view spec decides which storage axis is horizontal, at rank 2 too.

    Since orientation moved to just after the load, every frame built by
    ``PlotBundle.view_frame()`` has ``plot_y_dim == 0`` and ``plot_x_dim == 1``:
    display positions, not storage axes. Reading the mapping off the frame
    inverted the answer for any view whose plot-axis order is not the
    identity -- which is the normal case as soon as the user picks an X key
    that is not the trailing axis.
    """
    plane = prepare_2d_bundle(
        np.zeros((32, 100)),
        [np.arange(32, dtype=float), np.linspace(0.0, np.pi, 100)],
        ["dim_1", "x"],
        render_mode_hint="image"
)
    frame = plane.view_frame()
    assert (frame.plot_y_dim, frame.plot_x_dim) == (0, 1)

    # The opposite of what those display positions say, which is why the
    # function no longer accepts a frame at all.
    assert _SELECTION_DRIVEN.plot_axis_for(0) == "plot_x"
    assert _SELECTION_DRIVEN.plot_axis_for(1) == "plot_y"


def test_span_full_expands_the_profile_axis_not_the_reduction_axis():
    """
    "Span full profile axis" must widen the axis the profile runs along.

    With the plot-axis order reversed by the X-key selection, it used to
    widen the orthogonal axis instead: the profile came back covering only
    the drawn band of its own axis, while the band being summed over was
    silently expanded to the whole plane.
    """
    plane = prepare_2d_bundle(
        np.zeros((32, 100)),
        [np.arange(32, dtype=float), np.linspace(0.0, np.pi, 100)],
        ["dim_1", "x"],
        render_mode_hint="image"
)
    frame = plane.view_frame()
    drawn = RectRegion(x0=0.6641, x1=2.618, y0=22.55, y1=27.42)

    expanded = _plane_request(_SELECTION_DRIVEN).with_roi_profile(
        drawn,
        profile_axis=0,
        plane_frame=frame,
        span_full=True
).region

    left, right, bottom, top = frame.extent
    assert (expanded.x0, expanded.x1) == pytest.approx((left, right))
    assert (expanded.y0, expanded.y1) == pytest.approx((drawn.y0, drawn.y1))


def test_a_1d_view_has_no_plot_plane_to_map_onto():
    """
    A projection with one plot axis cannot answer plot_x versus plot_y.

    It used to: ``plot_axis_order()`` returns a single axis for a 1-D view, so
    the old ``len(plot_order) >= 2`` test fell through to the frame and
    compared the storage axis against a display position. Raising is what
    lets the ROI window's plane guard be a question about the projection
    rather than about whether a frame happens to be cached.
    """
    spectrum = Projection(
        ndim=2,
        plot_ndim=1,
        roles=(DimRole.INDEX, DimRole.PLOT_X),
        indices=(0, 0)
)
    assert spectrum.plot_axis_order() == (1,
)
    assert not spectrum.is_plot_plane_axis(1)
    with pytest.raises(ValueError, match="2D projection"):
        spectrum.plot_axis_for(1)


def test_an_off_plane_storage_axis_has_no_plot_axis():
    """
    A slider axis is not on the plane, so it maps to neither plot axis.
    """
    cube = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0)
)
    assert not cube.is_plot_plane_axis(0)
    with pytest.raises(ValueError, match="not on the plot plane"):
        cube.plot_axis_for(0)


def test_storage_axis_to_plot_axis_maps_nd_storage_indices():
    parent_spec = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0, 0)
)
    assert parent_spec.plot_axis_for(3) == "plot_x"
    assert parent_spec.plot_axis_for(2) == "plot_y"


def test_stack_profile_fetch_slice_widens_the_profile_axis():
    """
    A profile along an axis the projection indexes has to be read in full,
    while every other indexed axis keeps its index.
    """
    y_count, x_count = 8, 10
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 1, 0, 0)
)
    frame = display_frame(
        np.zeros((y_count, x_count)),
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
        ["dim_1", "dim_2"]
)
    request = _profile_request(
        parent,
        RectRegion(x0=1.5, x1=4.5, y0=0.5, y1=3.5),
        profile_axis=0,
        reduce="mean"
)

    slice_info = plan_fetch(request, plane_frame=frame).slice_info

    assert slice_info[0] == slice(None)
    assert slice_info[1] == 1
    assert isinstance(slice_info[2], slice)
    assert isinstance(slice_info[3], slice)


def test_roi_profile_along_dim1_matches_plane_means():
    e_count, d0_count, y_count, x_count = 3, 5, 8, 10
    rng = np.random.default_rng(0)
    base = rng.random((y_count, x_count)) * 100 + 1000
    y_full = np.stack([base + float(d) for d in range(d0_count)], axis=0)
    y_full = np.broadcast_to(
        y_full[None, ...], (e_count, d0_count, y_count, x_count)
    ).copy()
    en_idx = 0
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(en_idx, 0, 0, 0)
)
    frame = display_frame(
        y_full[en_idx, 0],
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
        ["dim_1", "dim_2"]
)
    request = _profile_request(
        parent,
        RectRegion(x0=1.5, x1=6.5, y0=1.5, y1=5.5),
        profile_axis=1,
        reduce="mean"
)

    plan = plan_fetch(request, plane_frame=frame)
    fetch_slice = plan.slice_info
    # Sliced with the block, as ``load_axes`` returns them: a coordinate that
    # still spans the full axis does not describe a narrowed load.
    axis_arrays = [
        np.arange(count, dtype=float)[item]
        for count, item in zip(
            (e_count, d0_count, y_count, x_count), fetch_slice
        )
    ]
    y_roi = y_full[fetch_slice]
    profile, _, names = roi_profile_from_block(
        y_roi,
        axis_arrays,
        ["en_energy", "dim_0", "dim_1", "dim_2"],
        request,
        plan
)
    manual = np.array(
        [
            float(np.mean(y_full[en_idx, d, fetch_slice[2], fetch_slice[3]]))
            for d in range(d0_count)
        ]
    )
    np.testing.assert_allclose(profile, manual, rtol=1e-5)
    assert names == ["dim_0"]
