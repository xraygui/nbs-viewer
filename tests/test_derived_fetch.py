"""Tests for derived profile bundle fetch."""

import numpy as np
import pytest

from nbs_viewer.models.plot.cube_view import (
    CubeViewSpec,
    DimRole,
    MaterializeRequest,
    materialize_view,
    plot_axis_to_storage_axis,
    profile_view_spec,
    storage_axis_to_plot_axis,
)
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.derived_fetch import (
    fetch_materialized_bundle,
    materialize_request_for_profile,
    plot_plane_storage_axes,
    resolve_profile_region,
)
from nbs_viewer.models.plot.plot_geometry import prepare_1d_bundle, prepare_2d_bundle
from nbs_viewer.models.plot.region import RectRegion


class _StubRunModel:
    def __init__(self, bundle, *, ndim_arrays=None, ndim_y=None):
        self.uid = "stub"
        self._bundle = bundle
        self._ndim_arrays = ndim_arrays
        self._ndim_y = ndim_y

    def get_plot_bundle(
        self,
        request,
        *,
        region_frame=None,
        parent_spec=None,
        label="",
        view_crop=None,
    ):
        if request.region is None:
            return self._bundle

        materialize_request = MaterializeRequest(
            spec=request.view.to_cube_view_spec(),
            region=request.region,
            mask_mode=request.mask_mode,
        )
        load_slice = materialize_request.spec.to_load_slice_info()
        xlist, names, y = self._fetch_plot_arrays(load_slice)
        y, xlist, names = materialize_view(
            y,
            xlist,
            names,
            materialize_request,
            region_frame=region_frame,
            plot_plane_storage_axes=plot_plane_storage_axes(parent_spec),
        )
        if materialize_request.spec.plot_ndim != 1:
            raise ValueError(
                f"ROI requests always reduce to a profile, got plot_ndim "
                f"{materialize_request.spec.plot_ndim}"
            )
        display_label = label or names[0]
        return prepare_1d_bundle(y, xlist, [display_label])

    def _fetch_plot_arrays(self, slice_info):
        if self._ndim_y is None or self._ndim_arrays is None:
            raise ValueError("ndim data not configured on stub")
        y = self._ndim_y[tuple(slice_info)]
        names = [f"dim_{i}" for i in range(len(self._ndim_arrays))]
        return self._ndim_arrays, names, y


def test_fetch_materialized_profile_mesh():
    y = np.arange(30 * 400, dtype=float).reshape(30, 400)
    col_axis = np.cumsum(np.linspace(0.1, 0.3, 400))
    row_axis = np.linspace(200.0, 1000.0, 30)
    storage_bundle = prepare_2d_bundle(
        y, [row_axis, col_axis], ["en_energy", "tes_mca_energies"]
    )
    from nbs_viewer.models.plot.region_mesh import _cell_x_bounds_mesh, _cell_y_bounds_mesh

    frame = frame_from_bundle(storage_bundle)
    x0, _ = _cell_x_bounds_mesh(frame, 10, 0)
    _, x1 = _cell_x_bounds_mesh(frame, 20, 0)
    y0, _ = _cell_y_bounds_mesh(frame, 5, 0)
    _, y1 = _cell_y_bounds_mesh(frame, 8, 0)
    parent_spec = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    request = materialize_request_for_profile(
        parent_spec,
        RectRegion(x0=x0, x1=x1, y0=y0, y1=y1),
        frame.plot_y_dim,
        "sum",
        parent_frame=frame,
    )
    bundle = fetch_materialized_bundle(
        request,
        parent_bundle=storage_bundle,
        parent_spec=parent_spec,
        label="test roi",
    )
    assert bundle.render_mode == "line"
    assert bundle.ndim == 1
    assert bundle.y.shape == (storage_bundle.y.shape[0],)
    assert np.isfinite(bundle.y).any()


def test_resolve_profile_region_expands_in_plane_only():
    y = np.ones((10, 20))
    storage_bundle = prepare_2d_bundle(
        y, [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 19.0, 20)], ["a", "b"]
    )
    frame = frame_from_bundle(storage_bundle)
    narrow = RectRegion(x0=5.0, x1=8.0, y0=3.0, y1=4.0)
    parent_spec = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    expanded = resolve_profile_region(
        frame,
        narrow,
        profile_storage_axis=1,
        parent_spec=parent_spec,
        span_full=True,
    )
    assert expanded.y0 == pytest.approx(3.0)
    assert expanded.y1 == pytest.approx(4.0)
    assert expanded.x0 == pytest.approx(-0.5)
    assert expanded.x1 == pytest.approx(19.5)

    stack_parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0, 0, 0),
    )
    unchanged = resolve_profile_region(
        frame,
        narrow,
        profile_storage_axis=0,
        parent_spec=stack_parent,
        span_full=True,
    )
    assert unchanged.x0 == narrow.x0
    assert unchanged.y0 == narrow.y0


def test_fetch_materialized_profile_image_with_4d_parent_spec():
    y = np.arange(100, dtype=float).reshape(10, 10)
    storage_bundle = prepare_2d_bundle(
        y,
        [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 9.0, 10)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    parent_spec = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(
            DimRole.INDEX,
            DimRole.INDEX,
            DimRole.PLOT_Y,
            DimRole.PLOT_X,
        ),
        indices=(0, 0, 0, 0),
    )
    region = RectRegion(x0=2.5, x1=6.5, y0=2.5, y1=6.5)
    request = materialize_request_for_profile(
        parent_spec,
        region,
        plot_axis_to_storage_axis(parent_spec, "plot_x"),
        "sum",
    )
    bundle = fetch_materialized_bundle(
        request,
        parent_bundle=storage_bundle,
        parent_spec=parent_spec,
    )
    assert bundle.render_mode == "line"
    assert bundle.y.shape == (10,)
    assert np.isfinite(bundle.y).any()


def test_storage_axis_to_plot_axis_prefers_frame_on_2d_mesh_parent():
    """
    Rendered mesh orientation can disagree with CubeViewSpec row roles.
    """
    from nbs_viewer.models.plot.plot_view_frame import PlotViewFrame

    parent_spec = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    frame = PlotViewFrame(
        shape=(400, 30),
        render_mode="mesh",
        axis_names=["en_energy", "tes_mca_energies"],
        plot_x_dim=0,
        plot_y_dim=1,
    )
    assert storage_axis_to_plot_axis(
        frame, 0, parent_spec=parent_spec
    ) == "plot_x"
    assert storage_axis_to_plot_axis(
        frame, 1, parent_spec=parent_spec
    ) == "plot_y"


def test_storage_axis_to_plot_axis_maps_nd_storage_indices():
    y = np.arange(100, dtype=float).reshape(10, 10)
    storage_bundle = prepare_2d_bundle(
        y,
        [np.linspace(0.0, 9.0, 10), np.linspace(0.0, 9.0, 10)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(storage_bundle)
    parent_spec = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(
            DimRole.INDEX,
            DimRole.INDEX,
            DimRole.PLOT_Y,
            DimRole.PLOT_X,
        ),
        indices=(0, 0, 0, 0),
    )
    assert storage_axis_to_plot_axis(
        frame, 3, parent_spec=parent_spec
    ) == "plot_x"
    assert storage_axis_to_plot_axis(
        frame, 2, parent_spec=parent_spec
    ) == "plot_y"


def test_stack_profile_fetch_slice_uses_dim0_index():
    """
    ROI stack profile along energy must honor dim_0 INDEX in parent spec.
    """
    from nbs_viewer.models.plot.cube_view import MaterializeRequest, profile_view_spec

    e_count, d0_count, y_count, x_count = 4, 5, 8, 10
    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(
            DimRole.INDEX,
            DimRole.INDEX,
            DimRole.PLOT_Y,
            DimRole.PLOT_X,
        ),
        indices=(0, 1, 0, 0),
    )
    bundle = prepare_2d_bundle(
        np.zeros((y_count, x_count)),
        [np.arange(y_count), np.arange(x_count)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=1.5, x1=4.5, y0=0.5, y1=3.5)
    request = MaterializeRequest(
        profile_view_spec(parent, profile_storage_axis=0, spatial_reduce="mean"),
        region=region,
    )
    slice_info = request.to_fetch_slice_info(
        region_frame=frame,
        parent_spec=parent,
    )
    assert slice_info[0] == slice(None)
    assert slice_info[1] == 1
    assert isinstance(slice_info[2], slice)
    assert isinstance(slice_info[3], slice)


def test_roi_profile_along_dim0_matches_plane_means():
    from nbs_viewer.models.plot.cube_view import MaterializeRequest, materialize_view

    e_count, d0_count, y_count, x_count = 3, 5, 8, 10
    rng = np.random.default_rng(0)
    base = rng.random((y_count, x_count)) * 100 + 1000
    y_full = np.stack(
        [base + float(d) for d in range(d0_count)],
        axis=0,
    )
    y_full = np.broadcast_to(
        y_full[None, ...], (e_count, d0_count, y_count, x_count)
    ).copy()
    en_idx = 0
    parent = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(
            DimRole.INDEX,
            DimRole.INDEX,
            DimRole.PLOT_Y,
            DimRole.PLOT_X,
        ),
        indices=(en_idx, 0, 0, 0),
    )
    bundle = prepare_2d_bundle(
        y_full[en_idx, 0],
        [np.arange(y_count), np.arange(x_count)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=1.5, x1=6.5, y0=1.5, y1=5.5)
    request = MaterializeRequest(
        profile_view_spec(parent, profile_storage_axis=1, spatial_reduce="mean"),
        region=region,
    )
    fetch_slice, cropped = request.fetch_context(
        region_frame=frame,
        parent_spec=parent,
    )
    y_roi = y_full[fetch_slice]
    axis_arrays = [
        np.arange(e_count, dtype=float),
        np.arange(d0_count, dtype=float),
        np.arange(y_count, dtype=float),
        np.arange(x_count, dtype=float),
    ]
    profile, _, names = materialize_view(
        y_roi,
        axis_arrays,
        ["en_energy", "dim_0", "dim_1", "dim_2"],
        request,
        region_frame=cropped,
        plot_plane_storage_axes=(2, 3),
    )
    manual = np.array(
        [
            float(np.mean(y_full[en_idx, d, fetch_slice[2], fetch_slice[3]]))
            for d in range(d0_count)
        ]
    )
    np.testing.assert_allclose(profile, manual, rtol=1e-5)
    assert names == ["dim_0"]


def test_fetch_materialized_stack_profile_along_middle_index_axis():
    e_count, d0_count, y_count, x_count = 3, 5, 6, 7
    y_full = (
        np.arange(d0_count)[None, :, None, None] * 100
        + np.arange(y_count)[None, None, :, None] * 10
        + np.arange(x_count)[None, None, None, :]
    ).astype(float)
    y_full = np.broadcast_to(y_full, (e_count, d0_count, y_count, x_count)).copy()
    y_parent = y_full[1, 0]
    storage_bundle = prepare_2d_bundle(
        y_parent,
        [np.arange(y_count), np.arange(x_count)],
        ["dim_1", "dim_2"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(storage_bundle)
    parent_spec = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(
            DimRole.INDEX,
            DimRole.INDEX,
            DimRole.PLOT_Y,
            DimRole.PLOT_X,
        ),
        indices=(1, 0, 0, 0),
    )
    region = RectRegion(x0=1.5, x1=4.5, y0=0.5, y1=3.5)
    request = materialize_request_for_profile(
        parent_spec,
        region,
        1,
        "sum",
    )
    run = _StubRunModel(
        storage_bundle,
        ndim_y=y_full,
        ndim_arrays=[
            np.linspace(200.0, 400.0, e_count),
            np.arange(d0_count),
            np.arange(y_count),
            np.arange(x_count),
        ],
    )
    bundle = fetch_materialized_bundle(
        request,
        run_model=run,
        xkeys=["dim_2"],
        ykey="data",
        parent_spec=parent_spec,
        region_frame=frame,
    )
    assert bundle.render_mode == "line"
    assert bundle.y.shape == (d0_count,)
    assert np.isfinite(bundle.y).all()


def test_fetch_materialized_stack_profile_end_to_end():
    e_count, s_count, y_count, x_count = 4, 3, 5, 6
    y_full = (
        np.arange(e_count)[:, None, None, None] * 1000
        + np.arange(y_count)[None, None, :, None] * 10
        + np.arange(x_count)[None, None, None, :]
    ).astype(float)
    y_parent = y_full.sum(axis=1)[1]
    storage_bundle = prepare_2d_bundle(
        y_parent,
        [np.arange(y_count), np.arange(x_count)],
        ["y", "x"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(storage_bundle)
    parent_spec = CubeViewSpec(
        ndim=4,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.SUM, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(1, 0, 0, 0),
    )
    region = RectRegion(x0=1.5, x1=3.5, y0=0.5, y1=2.5)
    request = materialize_request_for_profile(
        parent_spec,
        region,
        0,
        "sum",
    )
    run = _StubRunModel(
        storage_bundle,
        ndim_y=y_full,
        ndim_arrays=[
            np.linspace(200.0, 500.0, e_count),
            np.arange(s_count),
            np.arange(y_count),
            np.arange(x_count),
        ],
    )
    bundle = fetch_materialized_bundle(
        request,
        run_model=run,
        xkeys=["en_energy"],
        ykey="data",
        parent_spec=parent_spec,
        region_frame=frame,
        label="stack profile",
    )
    assert bundle.render_mode == "line"
    assert bundle.y.shape == (e_count,)
    assert np.isfinite(bundle.y).all()
    assert bundle.axis_names == ["stack profile"]
