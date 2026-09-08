"""Tests for ROI profile requests and the cached-plane reduction."""

import numpy as np
import pytest

from nbs_viewer.models.plot.view_spec import (
    DimRole,
    Projection,
    plot_axis_to_storage_axis,
    storage_axis_to_plot_axis,
)
from nbs_viewer.models.plot.plot_bundle import (
    reduce_cached_plane,
    reduce_to_plot_plane,
)
from nbs_viewer.models.plot.plot_geometry import (
    orient_for_display,
    prepare_2d_bundle,
)
from nbs_viewer.models.plot.plot_request import (
    PlotRequest,
    plan_fetch,
    roi_profile_request,
)
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.view_spec import Projection

from tests.fixtures.display_plane import display_frame


def _plane_request(parent: Projection) -> PlotRequest:
    """
    Build the request that draws the parent 2-D plane.
    """
    return PlotRequest(
        uid="uid",
        xkeys=("x",),
        ykey="y",
        norm_keys=(),
        view=parent,
    )


def _profile_request(parent, region, *, profile_axis, reduce="sum"):
    """
    Build the ROI profile request the fetch path would carry.
    """
    return roi_profile_request(
        _plane_request(parent),
        region,
        profile_axis=profile_axis,
        spatial_reduce=reduce,
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
    from nbs_viewer.models.plot.region_mesh import (
        _cell_x_bounds_mesh,
        _cell_y_bounds_mesh,
    )

    frame = frame_from_bundle(plane)
    x0, _ = _cell_x_bounds_mesh(frame, 10, 0)
    _, x1 = _cell_x_bounds_mesh(frame, 20, 0)
    y0, _ = _cell_y_bounds_mesh(frame, 5, 0)
    _, y1 = _cell_y_bounds_mesh(frame, 8, 0)

    request = _profile_request(
        _PLANE_2D,
        RectRegion(x0=x0, x1=x1, y0=y0, y1=y1),
        profile_axis=frame.plot_y_dim,
    )
    bundle = reduce_cached_plane(plane, request, label="test roi")

    assert bundle.render_mode == "line"
    assert bundle.ndim == 1
    assert bundle.y.shape == (plane.y.shape[0],)
    assert np.isfinite(bundle.y).any()


def test_span_full_expands_an_in_plane_profile_only():
    plane = prepare_2d_bundle(
        np.ones((10, 20)),
        [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 19.0, 20)],
        ["a", "b"],
    )
    frame = frame_from_bundle(plane)
    narrow = RectRegion(x0=5.0, x1=8.0, y0=3.0, y1=4.0)

    expanded = roi_profile_request(
        _plane_request(_PLANE_2D),
        narrow,
        profile_axis=1,
        plane_frame=frame,
        span_full=True,
    ).region
    assert expanded.y0 == pytest.approx(3.0)
    assert expanded.y1 == pytest.approx(4.0)
    assert expanded.x0 == pytest.approx(-0.5)
    assert expanded.x1 == pytest.approx(19.5)

    stack_parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0, 0),
    )
    unchanged = roi_profile_request(
        _plane_request(stack_parent),
        narrow,
        profile_axis=0,
        plane_frame=frame,
        span_full=True,
    ).region
    assert unchanged.x0 == narrow.x0
    assert unchanged.y0 == narrow.y0


def test_cached_plane_profile_with_4d_parent_spec():
    y = np.arange(100, dtype=float).reshape(10, 10)
    plane = prepare_2d_bundle(
        y,
        [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 9.0, 10)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0, 0),
    )
    request = _profile_request(
        parent,
        RectRegion(x0=2.5, x1=6.5, y0=2.5, y1=6.5),
        profile_axis=plot_axis_to_storage_axis(parent, "plot_x"),
    )

    bundle = reduce_cached_plane(plane, request)

    assert bundle.render_mode == "line"
    assert bundle.y.shape == (10,)
    assert np.isfinite(bundle.y).any()


def test_cached_plane_refuses_an_off_plane_profile():
    plane = prepare_2d_bundle(
        np.ones((6, 7)),
        [np.arange(6, dtype=float), np.arange(7, dtype=float)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    parent = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    request = _profile_request(
        parent, RectRegion(x0=1.5, x1=4.5, y0=0.5, y1=3.5), profile_axis=0
    )

    with pytest.raises(ValueError, match="off-plane"):
        reduce_cached_plane(plane, request)


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
    ``frame_from_bundle`` has ``plot_y_dim == 0`` and ``plot_x_dim == 1``:
    display positions, not storage axes. Reading the mapping off the frame
    inverted the answer for any view whose plot-axis order is not the
    identity -- which is the normal case as soon as the user picks an X key
    that is not the trailing axis.
    """
    plane = prepare_2d_bundle(
        np.zeros((32, 100)),
        [np.arange(32, dtype=float), np.linspace(0.0, np.pi, 100)],
        ["dim_1", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(plane)
    assert (frame.plot_y_dim, frame.plot_x_dim) == (0, 1)

    assert storage_axis_to_plot_axis(
        frame, 0, parent_spec=_SELECTION_DRIVEN
    ) == "plot_x"
    assert storage_axis_to_plot_axis(
        frame, 1, parent_spec=_SELECTION_DRIVEN
    ) == "plot_y"


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
        render_mode_hint="image",
    )
    frame = frame_from_bundle(plane)
    drawn = RectRegion(x0=0.6641, x1=2.618, y0=22.55, y1=27.42)

    expanded = roi_profile_request(
        _plane_request(_SELECTION_DRIVEN),
        drawn,
        profile_axis=0,
        plane_frame=frame,
        span_full=True,
    ).region

    left, right, bottom, top = frame.extent
    assert (expanded.x0, expanded.x1) == pytest.approx((left, right))
    assert (expanded.y0, expanded.y1) == pytest.approx((drawn.y0, drawn.y1))


def test_storage_axis_to_plot_axis_maps_nd_storage_indices():
    plane = prepare_2d_bundle(
        np.arange(100, dtype=float).reshape(10, 10),
        [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 9.0, 10)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(plane)
    parent_spec = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0, 0),
    )
    assert storage_axis_to_plot_axis(
        frame, 3, parent_spec=parent_spec
    ) == "plot_x"
    assert storage_axis_to_plot_axis(
        frame, 2, parent_spec=parent_spec
    ) == "plot_y"


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
        indices=(0, 1, 0, 0),
    )
    frame = display_frame(
        np.zeros((y_count, x_count)),
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
        ["dim_1", "dim_2"],
    )
    request = _profile_request(
        parent,
        RectRegion(x0=1.5, x1=4.5, y0=0.5, y1=3.5),
        profile_axis=0,
        reduce="mean",
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
        indices=(en_idx, 0, 0, 0),
    )
    frame = display_frame(
        y_full[en_idx, 0],
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
        ["dim_1", "dim_2"],
    )
    request = _profile_request(
        parent,
        RectRegion(x0=1.5, x1=6.5, y0=1.5, y1=5.5),
        profile_axis=1,
        reduce="mean",
    )

    plan = plan_fetch(request, plane_frame=frame)
    fetch_slice = plan.slice_info
    axis_arrays = [
        np.arange(e_count, dtype=float),
        np.arange(d0_count, dtype=float),
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
    ]
    y_roi, axis_arrays = orient_for_display(
        y_full[fetch_slice],
        axis_arrays,
        plan.reversed_axes_for(axis_arrays, "image"),
        {1: 0, 2: 1, 3: 2},
    )
    profile, _, names = reduce_to_plot_plane(
        y_roi,
        axis_arrays,
        ["en_energy", "dim_0", "dim_1", "dim_2"],
        request,
        region_frame=plan.region_frame,
        plot_plane_storage_axes=plan.plane_axes,
    )
    manual = np.array(
        [
            float(np.mean(y_full[en_idx, d, fetch_slice[2], fetch_slice[3]]))
            for d in range(d0_count)
        ]
    )
    np.testing.assert_allclose(profile, manual, rtol=1e-5)
    assert names == ["dim_0"]
