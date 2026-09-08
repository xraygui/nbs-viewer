"""Tests for the request-to-bundle pipeline."""

from __future__ import annotations

import numpy as np

from nbs_viewer.models.plot.cube_view import DimRole
from nbs_viewer.models.plot.plot_bundle import (
    apply_normalization,
    apply_transform,
    reduce_loaded_array,
    slice_info_for_key,
)
from nbs_viewer.models.plot.plot_request import PlotRequest
from nbs_viewer.models.plot.runSource import RunSource
from nbs_viewer.models.plot.view_spec import ViewCrop, ViewIntent, ViewSpec
from nbs_viewer.models.sources.fixtures import (
    make_vppem_run,
    voltage_axis,
    vppem_factors,
)


def _request(
    run,
    ykey,
    xkeys,
    view: ViewSpec,
    *,
    norm_keys=(),
    transform="",
) -> PlotRequest:
    return PlotRequest(
        uid=run.uid,
        xkeys=tuple(xkeys),
        ykey=ykey,
        norm_keys=tuple(norm_keys),
        view=view,
        transform=transform,
    )


def _model():
    return RunSource(make_vppem_run())


def test_slice_info_for_key_by_name():
    slice_info = (4, slice(None), slice(1, 8))
    y_names = ["voltage", "dim_1", "dim_2"]
    got = slice_info_for_key(slice_info, y_names, ["voltage"])
    assert got == (4,)


def test_reduce_loaded_array_mean_on_matching_dims():
    arr = np.arange(12.0).reshape(3, 4)
    reduced, names = reduce_loaded_array(
        arr,
        ["time", "dim_1"],
        ["time", "dim_1", "dim_2"],
        (DimRole.PLOT_X, DimRole.MEAN, DimRole.MEAN),
    )
    np.testing.assert_allclose(reduced, arr.mean(axis=1))
    assert names == ["time"]


def test_reduce_loaded_array_skips_index():
    arr = np.array([2.0, 4.0, 6.0])
    reduced, names = reduce_loaded_array(
        arr[1],
        ["time"],
        ["time", "dim_1", "dim_2"],
        (DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
    )
    np.testing.assert_allclose(reduced, 4.0)
    assert names == []


def test_apply_normalization_rank1_onto_rank2():
    y = np.arange(12.0).reshape(3, 4)
    norm = np.array([2.0, 3.0, 4.0])
    out = apply_normalization(
        y,
        ["voltage", "dim_2"],
        [(norm, ["voltage"])],
    )
    np.testing.assert_allclose(out, y / norm[:, None])


def test_apply_transform_expression():
    x = [np.array([1.0, 2.0, 3.0])]
    y = np.array([10.0, 20.0, 30.0])
    coords, out = apply_transform(x, y, "y = y / 10")
    np.testing.assert_allclose(out, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(coords[0], [1.0, 2.0, 3.0])


def test_apply_transform_empty_is_noop():
    y = np.array([1.0, 2.0])
    coords, out = apply_transform([np.array([0.0, 1.0])], y, "")
    np.testing.assert_allclose(out, y)


def test_1d_stats_line(qapp):
    model = _model()
    run = model.run
    a, b, c = vppem_factors()
    view = ViewIntent(plot_ndim=1).project(1)
    bundle = model.get_plot_bundle(
        _request(run, "PCOEdge_stats", ["sampleVoltage_VSource"], view)
    )
    assert bundle.render_mode == "line"
    np.testing.assert_allclose(bundle.y, a * b.mean() * c.mean())
    np.testing.assert_allclose(bundle.x_line, voltage_axis(len(a)))
    assert bundle.axis_names == ["sampleVoltage_VSource"]


def test_rank1_projection_needs_no_frozen_short_circuit(qapp):
    model = _model()
    intent = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.INDEX, DimRole.MEAN),
        reduce_indices=(4, 0),
        axis_order=(0, 1, 2),
    )
    view = intent.project(1)
    assert view.ndim == 1
    assert view.roles == (DimRole.PLOT_X,)
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_stats",
            ["sampleVoltage_VSource"],
            view,
        )
    )
    assert bundle.y.ndim == 1


def test_2d_image_index_slice(qapp):
    model = _model()
    a, b, c = vppem_factors()
    view = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.INDEX,),
        reduce_indices=(4,),
    ).project(3, (11, 24, 32))
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
        )
    )
    expected = a[4] * b[:, None] * c[None, :]
    assert bundle.render_mode == "image"
    np.testing.assert_allclose(bundle.y, expected[::-1, :])


def test_3d_mean_detectors_line_vs_voltage(qapp):
    model = _model()
    a, b, c = vppem_factors()
    view = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.MEAN, DimRole.MEAN),
        reduce_indices=(0, 0),
        axis_order=(1, 2, 0),
    ).project(3)
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
        )
    )
    np.testing.assert_allclose(bundle.y, a * b.mean() * c.mean())
    np.testing.assert_allclose(bundle.x_line, voltage_axis(len(a)))
    assert bundle.axis_names == ["sampleVoltage_VSource"]


def test_2d_crop_on_view_spec(qapp):
    model = _model()
    a, b, c = vppem_factors()
    crop = ViewCrop(
        storage_bbox=(2, 8, 3, 10),
        plot_y_axis=1,
        plot_x_axis=2,
    )
    view = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.INDEX,),
        reduce_indices=(4,),
        crop=crop,
    ).project(3, (11, 24, 32))
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
        )
    )
    expected = a[4] * b[2:8, None] * c[None, 3:10]
    np.testing.assert_allclose(bundle.y, expected[::-1, :])


def test_mesh_when_plot_y_is_nonuniform_voltage(qapp):
    model = _model()
    view = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.MEAN,),
        reduce_indices=(0,),
        axis_order=(1, 0, 2),
    ).project(3)
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
        )
    )
    assert bundle.render_mode == "mesh"
    assert bundle.y.ndim == 2


def test_normalize_stats_by_i0(qapp):
    model = _model()
    a, b, c = vppem_factors()
    i0 = np.linspace(2.0, 3.0, len(a))
    view = ViewIntent(plot_ndim=1).project(1)
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_stats",
            ["sampleVoltage_VSource"],
            view,
            norm_keys=("i0",),
        )
    )
    np.testing.assert_allclose(bundle.y, a * b.mean() * c.mean() / i0)


def test_normalize_cube_by_i0_index_slice(qapp):
    model = _model()
    a, b, c = vppem_factors()
    i0 = np.linspace(2.0, 3.0, len(a))
    view = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.INDEX,),
        reduce_indices=(4,),
    ).project(3, (11, 24, 32))
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
            norm_keys=("i0",),
        )
    )
    expected = (a[4] * b[:, None] * c[None, :]) / i0[4]
    np.testing.assert_allclose(bundle.y, expected[::-1, :])


def test_normalize_cube_by_i0_mean_detectors(qapp):
    model = _model()
    a, b, c = vppem_factors()
    i0 = np.linspace(2.0, 3.0, len(a))
    view = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.MEAN, DimRole.MEAN),
        reduce_indices=(0, 0),
        axis_order=(1, 2, 0),
    ).project(3)
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
            norm_keys=("i0",),
        )
    )
    np.testing.assert_allclose(bundle.y, a * b.mean() * c.mean() / i0)


def test_transform_from_request(qapp):
    model = _model()
    a, b, c = vppem_factors()
    view = ViewIntent(plot_ndim=1).project(1)
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_stats",
            ["sampleVoltage_VSource"],
            view,
            transform="y = y * 2",
        )
    )
    np.testing.assert_allclose(bundle.y, 2.0 * a * b.mean() * c.mean())


def test_empty_request_transform_leaves_data_unscaled(qapp):
    model = _model()
    a, b, c = vppem_factors()
    view = ViewIntent(plot_ndim=1).project(1)
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_stats",
            ["sampleVoltage_VSource"],
            view,
        )
    )
    np.testing.assert_allclose(bundle.y, a * b.mean() * c.mean())


def test_sum_role_matches_closed_form(qapp):
    model = _model()
    a, b, c = vppem_factors()
    view = ViewIntent(
        plot_ndim=1,
        reduce_roles=(DimRole.SUM, DimRole.SUM),
        reduce_indices=(0, 0),
        axis_order=(1, 2, 0),
    ).project(3)
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
        )
    )
    np.testing.assert_allclose(bundle.y, a * b.sum() * c.sum())
