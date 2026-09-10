"""Tests for the request-to-bundle pipeline."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.view_spec import DimRole, Projection, ViewCrop
from nbs_viewer.models.plot.plot_bundle import (
    apply_normalization,
    apply_transform,
    slice_info_for_key,
)
from nbs_viewer.models.plot.plot_request import PlotRequest
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.run_source import RunSource
from nbs_viewer.models.sources.fixtures import (
    make_vppem_run,
    voltage_axis,
    vppem_factors,
)
from tests.fixtures.catalog_recipes import image_scan_run


VPPEM_NAMES = ("sampleVoltage_VSource", "dim_1", "dim_2")


def _request(
    run,
    ykey,
    xkeys,
    view: Projection,
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
    ).project(3, (11, 24, 32), VPPEM_NAMES)
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
        dim_order=("dim_1", "dim_2", "sampleVoltage_VSource"),
    ).project(3, dim_names=VPPEM_NAMES)
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
    ).project(3, (11, 24, 32), VPPEM_NAMES, crop=crop)
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
        dim_order=("dim_1", "sampleVoltage_VSource", "dim_2"),
    ).project(3, dim_names=VPPEM_NAMES)
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
    ).project(3, (11, 24, 32), VPPEM_NAMES)
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
        dim_order=("dim_1", "dim_2", "sampleVoltage_VSource"),
    ).project(3, dim_names=VPPEM_NAMES)
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
        dim_order=("dim_1", "dim_2", "sampleVoltage_VSource"),
    ).project(3, dim_names=VPPEM_NAMES)
    bundle = model.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
        )
    )
    np.testing.assert_allclose(bundle.y, a * b.sum() * c.sum())


def _count_reads(run):
    """
    Record every ``RunSource.read`` call, returning the list they land in.
    """
    calls = []
    original = run.read

    def counted(key, slice_info=None):
        calls.append((key, slice_info))
        return original(key, slice_info)

    run.read = counted
    return calls


def _image_request(run, ykey="detector_image", **kwargs):
    view = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
        **kwargs,
    )
    return PlotRequest(
        uid=run.uid,
        xkeys=("en_energy",),
        ykey=ykey,
        norm_keys=(),
        view=view,
    )


def test_a_transform_change_reads_nothing_and_still_changes_the_values():
    """
    Bug 8: editing a transform used to go all the way back to the database.

    Load, orient and normalize depend only on the fetch plan, and a transform
    change leaves the plan identical, so the block already in memory serves
    the new request and only the tail re-runs.
    """
    run = RunSource(image_scan_run(1, n_y=12, n_x=16))
    request = _image_request(run)
    plain = run.get_plot_bundle(request).y.copy()

    calls = _count_reads(run)
    doubled = run.get_plot_bundle(replace(request, transform="y * 2"))

    assert calls == []
    np.testing.assert_allclose(doubled.y, 2.0 * plain)


def test_a_crop_inside_an_already_loaded_box_reads_nothing():
    """
    The containment half of the comparison: a crop shrink is a sub-block.

    Checked against a run with an empty cache rather than against a
    hand-derived slice, because the interesting part is the mirroring -- the
    held block is display-ordered, so a storage window has to be reflected
    before it can be taken out of it.
    """
    run = RunSource(image_scan_run(1, n_y=12, n_x=16))
    run.get_plot_bundle(_image_request(run))

    cropped = _image_request(
        run,
        crop=ViewCrop(storage_bbox=(2, 8, 3, 11), plot_y_axis=0, plot_x_axis=1),
    )
    calls = _count_reads(run)
    from_cache = run.get_plot_bundle(cropped)
    assert calls == []
    assert from_cache.y.shape == (6, 8)

    fresh = RunSource(image_scan_run(1, n_y=12, n_x=16))
    np.testing.assert_allclose(
        from_cache.y, fresh.get_plot_bundle(cropped).y
    )


def test_an_roi_moved_inside_a_loaded_box_reads_nothing():
    """
    Same comparison, reached the other way.

    An off-plane profile narrows the load to the ROI's bounding box, so
    dragging the ROI inwards asks for a sub-block of what was just read.
    """
    run = RunSource(image_scan_run(1, n_y=12, n_x=16, n_z=3))
    view = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X, DimRole.INDEX),
        indices=(0, 0, 0),
    )
    parent = PlotRequest(
        uid=run.uid,
        xkeys=("en_energy",),
        ykey="detector_cube",
        norm_keys=(),
        view=view,
    )
    wide = replace(
        parent,
        region=RectRegion(x0=0.4, x1=2.6, y0=1.5, y1=9.5),
        profile_axis=2,
    )
    inner = replace(wide, region=RectRegion(x0=0.9, x1=2.1, y0=3.5, y1=7.5))

    run.get_plot_bundle(wide)
    calls = _count_reads(run)
    from_cache = run.get_plot_bundle(inner)
    assert calls == []

    fresh = RunSource(image_scan_run(1, n_y=12, n_x=16, n_z=3))
    np.testing.assert_allclose(from_cache.y, fresh.get_plot_bundle(inner).y)


def test_a_norm_key_varying_along_a_reduced_axis_divides_before_the_reduce():
    """
    The test that pins the normalization order, and nothing else did.

    ``i0`` varies along the voltage axis and the view sums that axis away, so
    the two orders give different answers: dividing per element and then
    summing is not summing and then dividing by a summed norm. Per element is
    the physically right one -- a flat field divides each pixel, and only
    then is the result reduced.
    """
    run = _model()
    a, b, c = vppem_factors()
    i0 = np.linspace(2.0, 3.0, a.size)
    view = Projection(
        ndim=3,
        plot_ndim=1,
        roles=(DimRole.SUM, DimRole.INDEX, DimRole.PLOT_X),
        indices=(0, 2, 0),
    )
    request = _request(
        run,
        "PCOEdge_image",
        ["sampleVoltage_VSource"],
        view,
        norm_keys=("i0",),
    )

    bundle = run.get_plot_bundle(request)

    per_element = float(np.sum(a / i0)) * b[2] * c
    after_reduce = float(np.sum(a)) / float(np.sum(i0)) * b[2] * c
    np.testing.assert_allclose(bundle.y, per_element)
    assert not np.allclose(per_element, after_reduce)


def test_an_in_plane_roi_is_the_same_whether_or_not_the_plane_is_cached():
    """
    There is one implementation of masking a 2-D plane, so it is one answer.

    The load path used to mask an N-D block for an in-plane profile while the
    cached path masked the finished plane. Now the load path builds the plane
    and hands it to the same reduction, so the transform is on it either way.
    """
    run = RunSource(image_scan_run(1, n_y=12, n_x=16))
    parent = replace(_image_request(run), transform="y * 2")
    plane = run.get_plot_bundle(parent)

    roi = replace(
        parent,
        region=RectRegion(x0=0.4, x1=2.6, y0=1.5, y1=9.5),
        profile_axis=1,
    )
    from_cache = run.get_plot_bundle(roi, cached_plane=plane)

    fresh = RunSource(image_scan_run(1, n_y=12, n_x=16))
    from_load = fresh.get_plot_bundle(roi)

    np.testing.assert_allclose(from_load.y, from_cache.y)
    np.testing.assert_allclose(from_load.x_line, from_cache.x_line)


def test_the_off_plane_transform_sees_the_planes_own_coordinates():
    """
    ``x`` means the plane's two coordinate arrays, whichever way it is cut.

    An off-plane profile reduces a stack of planes, so the block the
    transform runs on carries a third axis. Handing its coordinates to the
    transform as well would make ``x`` mean something different depending on
    which way the profile runs, and the whole point of running the transform
    before the mask is that the ROI reduces what the plane already shows.
    """
    run = RunSource(image_scan_run(1, n_y=12, n_x=16, n_z=3))
    view = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X, DimRole.INDEX),
        indices=(0, 0, 0),
    )
    parent = PlotRequest(
        uid=run.uid,
        xkeys=("en_energy",),
        ykey="detector_cube",
        norm_keys=(),
        view=view,
        transform="y * len(x)",
    )
    assert run.get_plot_bundle(parent).ndim == 2

    roi = replace(
        parent,
        region=RectRegion(x0=0.4, x1=2.6, y0=1.5, y1=9.5),
        profile_axis=2,
    )
    scaled = run.get_plot_bundle(roi)
    plain = run.get_plot_bundle(replace(roi, transform=""))

    np.testing.assert_allclose(scaled.y, 2.0 * plain.y)
