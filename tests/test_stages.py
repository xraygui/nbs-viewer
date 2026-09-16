"""Tests for the pipeline stages, from a request to a packed bundle."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.plane.roles import DimRole, ViewCrop
from nbs_viewer.models.plot.spec.projection import Projection
from nbs_viewer.models.plot.spec.stages import (
    apply_normalization,
    apply_transform,
    slice_info_for_key,
)
from nbs_viewer.models.plot.spec.request import PlotRequest
from nbs_viewer.models.plot.spec.region import RectRegion
from nbs_viewer.models.plot.run.source import RunSource
from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.sources.fixtures import (
    VPPEM_SHAPE,
    make_vppem_data,
    make_vppem_metadata,
    make_vppem_run,
    voltage_axis,
    vppem_factors,
)
import xarray as xr

from nbs_viewer.models.plot.spec.axes import PlotAxes
from tests.fixtures.catalog_recipes import image_scan_run
from tests.fixtures.display_plane import labelled_block
from tests.test_run_source import _frozen_entry


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
    # The names are the plot layer's answer; a bare run describes its keys
    # but knows nothing of the X selection.
    source = run if isinstance(run, RunSource) else RunSource(run)
    return PlotRequest(
        uid=run.uid,
        xkeys=tuple(xkeys),
        ykey=ykey,
        norm_keys=tuple(norm_keys),
        view=view,
        dims=source.plot_axis_names(ykey, xkeys),
        transform=transform
)


def _model():
    return RunSource(make_vppem_run())


def test_slice_info_for_key_by_name():
    slice_info = (4, slice(None), slice(1, 8))
    y_names = ["voltage", "dim_1", "dim_2"]
    got = slice_info_for_key(slice_info, y_names, ["voltage"])
    assert got == (4,
)


def _line_axes(names):
    """Name a 1-D view over the given dimension names."""
    return PlotAxes.of(
        ViewIntent(plot_ndim=1).project(len(names)), list(names),
    )


def test_apply_normalization_rank1_onto_rank2():
    """A norm broadcasts onto the axis it names, and only that one."""
    y = np.arange(12.0).reshape(3, 4)
    norm = np.array([2.0, 3.0, 4.0])
    out = apply_normalization(
        labelled_block(y, [np.arange(3.0), np.arange(4.0)], ["voltage", "dim_2"]),
        [xr.DataArray(norm, dims=["voltage"])]
)
    np.testing.assert_allclose(out.values, y / norm[:, None])
    assert out.dims == ("voltage", "dim_2")


def test_apply_normalization_refuses_an_axis_the_data_does_not_have():
    """
    Without this, xarray broadcasts into a *new* dimension.

    Measured: a (3, 4) array divided by a 3-long array named something the
    data does not have returns (3, 4, 3), silently. The hand-written aligner
    this replaced raised instead, and so does this.
    """
    data = labelled_block(
        np.ones((3, 4)), [np.arange(3.0), np.arange(4.0)], ["voltage", "dim_2"]
    )
    with pytest.raises(ValueError, match="cannot broadcast norm axes"):
        apply_normalization(data, [xr.DataArray(np.ones(3), dims=["roi"])])


def test_apply_transform_expression():
    """An expression rebinds y, and the coordinates come back unchanged."""
    data = labelled_block(
        np.array([10.0, 20.0, 30.0]), [np.array([1.0, 2.0, 3.0])], ["x"]
    )
    out = apply_transform(data, _line_axes(["x"]), "y = y / 10")
    np.testing.assert_allclose(out.values, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(out.coords["x"].values, [1.0, 2.0, 3.0])


def test_apply_transform_can_rewrite_the_coordinates_too():
    """
    ``x`` is writable, and the rewritten axis lands on the array.

    It used to be returned as a second value the caller threaded onward. Now
    it is read back out of the symbol table and assigned, so a transform that
    rescales an axis keeps the values and the axis together.
    """
    data = labelled_block(
        np.array([1.0, 2.0]), [np.array([0.0, 1.0])], ["x"]
    )
    out = apply_transform(data, _line_axes(["x"]), "x[0] = x[0] * 2 + 1")
    np.testing.assert_allclose(out.coords["x"].values, [1.0, 3.0])
    np.testing.assert_allclose(out.values, [1.0, 2.0])


def test_apply_transform_rejects_a_change_of_shape():
    """
    A shorter answer would leave every coordinate describing something else.
    """
    data = labelled_block(
        np.array([1.0, 2.0, 3.0]), [np.arange(3.0)], ["x"]
    )
    with pytest.raises(ValueError, match="changed the shape"):
        apply_transform(data, _line_axes(["x"]), "y = y[:2]")


def test_apply_transform_empty_is_noop():
    data = labelled_block(np.array([1.0, 2.0]), [np.array([0.0, 1.0])], ["x"])
    out = apply_transform(data, _line_axes(["x"]), "")
    np.testing.assert_allclose(out.values, [1.0, 2.0])


def test_1d_stats_line(qapp):
    model = _model()
    run = model.run
    a, b, c = vppem_factors()
    view = ViewIntent(plot_ndim=1).project(1)
    bundle = model.fetch.get_plot_bundle(
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
        reduce_indices=(4, 0)
)
    view = intent.project(1)
    assert view.ndim == 1
    assert view.roles == (DimRole.PLOT_X,
)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_stats",
            ["sampleVoltage_VSource"],
            view
)
    )
    assert bundle.y.ndim == 1


def test_2d_image_index_slice(qapp):
    model = _model()
    a, b, c = vppem_factors()
    view = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.INDEX,
),
        reduce_indices=(4,
)
).project(3, (11, 24, 32), VPPEM_NAMES)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view
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
        dim_order=("dim_1", "dim_2", "sampleVoltage_VSource")
).project(3, dim_names=VPPEM_NAMES)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view
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
        plot_x_axis=2
)
    view = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.INDEX,
),
        reduce_indices=(4,
)
).project(3, (11, 24, 32), VPPEM_NAMES, crop=crop)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view
)
    )
    expected = a[4] * b[2:8, None] * c[None, 3:10]
    np.testing.assert_allclose(bundle.y, expected[::-1, :])

    # The detector axes have no coordinate key, so they are labelled by their
    # storage index -- sliced with the data, so the crop keeps the positions
    # it was cut from rather than restarting at zero.
    left, right, bottom, top = bundle.extent
    assert sorted((left, right)) == pytest.approx([2.5, 9.5])
    assert sorted((bottom, top)) == pytest.approx([1.5, 7.5])


def test_mesh_when_plot_y_is_nonuniform_voltage(qapp):
    model = _model()
    view = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.MEAN,
),
        reduce_indices=(0,
),
        dim_order=("dim_1", "sampleVoltage_VSource", "dim_2")
).project(3, dim_names=VPPEM_NAMES)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view
)
    )
    assert bundle.render_mode == "mesh"
    assert bundle.y.ndim == 2


def test_normalize_stats_by_i0(qapp):
    model = _model()
    a, b, c = vppem_factors()
    i0 = np.linspace(2.0, 3.0, len(a))
    view = ViewIntent(plot_ndim=1).project(1)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_stats",
            ["sampleVoltage_VSource"],
            view,
            norm_keys=("i0",
)
)
    )
    np.testing.assert_allclose(bundle.y, a * b.mean() * c.mean() / i0)


def test_normalize_cube_by_i0_index_slice(qapp):
    model = _model()
    a, b, c = vppem_factors()
    i0 = np.linspace(2.0, 3.0, len(a))
    view = ViewIntent(
        plot_ndim=2,
        reduce_roles=(DimRole.INDEX,
),
        reduce_indices=(4,
)
).project(3, (11, 24, 32), VPPEM_NAMES)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
            norm_keys=("i0",
)
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
        dim_order=("dim_1", "dim_2", "sampleVoltage_VSource")
).project(3, dim_names=VPPEM_NAMES)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view,
            norm_keys=("i0",
)
)
    )
    np.testing.assert_allclose(bundle.y, a * b.mean() * c.mean() / i0)


def test_transform_from_request(qapp):
    model = _model()
    a, b, c = vppem_factors()
    view = ViewIntent(plot_ndim=1).project(1)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_stats",
            ["sampleVoltage_VSource"],
            view,
            transform="y = y * 2"
)
    )
    np.testing.assert_allclose(bundle.y, 2.0 * a * b.mean() * c.mean())


def test_empty_request_transform_leaves_data_unscaled(qapp):
    model = _model()
    a, b, c = vppem_factors()
    view = ViewIntent(plot_ndim=1).project(1)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_stats",
            ["sampleVoltage_VSource"],
            view
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
        dim_order=("dim_1", "dim_2", "sampleVoltage_VSource")
).project(3, dim_names=VPPEM_NAMES)
    bundle = model.fetch.get_plot_bundle(
        _request(
            model.run,
            "PCOEdge_image",
            ["sampleVoltage_VSource"],
            view
)
    )
    np.testing.assert_allclose(bundle.y, a * b.sum() * c.sum())


def _count_reads(run):
    """
    Record every key the run loads, returning the list they land in.

    ``RunSource.load`` is where every read goes -- ``read`` is a load without
    coordinates -- so this sees the block, its norms, and the X key a load is
    plotted against. Counting ``read`` alone would now see only the last.
    """
    calls = []
    original = run.load

    def counted(key, slice_info=None, **kwargs):
        calls.append((key, slice_info))
        return original(key, slice_info, **kwargs)

    run.load = counted
    return calls


def _coordinate_at(run, key, position):
    """
    An evenly spaced coordinate's value at a fractional index position.

    The image-scan planes are labelled by real coordinates: the requests here
    plot against ``en_energy``, which the fixture declares on the ``pixel``
    axis, and ``dim_2`` is its own axis's key. An ROI is geometry in data
    coordinates, so a region meant as "cells 1 to 2" is written through the
    key of the axis it lies along.
    """
    values = np.asarray(run.run.getData(key), dtype=float)
    return float(values[0] + position * (values[1] - values[0]))


def _image_request(run, ykey="detector_image", **kwargs):
    view = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
        **kwargs
)
    return PlotRequest(
        uid=run.uid,
        xkeys=("en_energy",
),
        ykey=ykey,
        norm_keys=(),
        view=view,
        dims=run.plot_axis_names(ykey, ("en_energy",
))
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
    plain = run.fetch.get_plot_bundle(request).y.copy()

    calls = _count_reads(run)
    doubled = run.fetch.get_plot_bundle(replace(request, transform="y * 2"))

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
    run.fetch.get_plot_bundle(_image_request(run))

    cropped = _image_request(
        run,
        crop=ViewCrop(storage_bbox=(2, 8, 3, 11), plot_y_axis=0, plot_x_axis=1)
)
    calls = _count_reads(run)
    from_cache = run.fetch.get_plot_bundle(cropped)
    assert calls == []
    assert from_cache.y.shape == (6, 8)

    fresh = RunSource(image_scan_run(1, n_y=12, n_x=16))
    np.testing.assert_allclose(
        from_cache.y, fresh.fetch.get_plot_bundle(cropped).y
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
        indices=(0, 0, 0)
)
    parent = PlotRequest(
        uid=run.uid,
        xkeys=("en_energy",
),
        ykey="detector_cube",
        norm_keys=(),
        view=view,
        dims=run.plot_axis_names("detector_cube", ("en_energy",
))
)
    # The plane is (en_energy, dim_2): rows along the energies, columns
    # along dim_2.
    def at(key, position):
        return _coordinate_at(run, key, position)

    wide = replace(
        parent,
        region=RectRegion(
            x0=at("dim_2", 0.4),
            x1=at("dim_2", 2.6),
            y0=at("en_energy", 1.5),
            y1=at("en_energy", 9.5)
),
        profile_axis=2
)
    inner = replace(
        wide,
        region=RectRegion(
            x0=at("dim_2", 0.9),
            x1=at("dim_2", 2.1),
            y0=at("en_energy", 3.5),
            y1=at("en_energy", 7.5)
)
)

    run.fetch.get_plot_bundle(wide)
    calls = _count_reads(run)
    from_cache = run.fetch.get_plot_bundle(inner)
    assert calls == []

    fresh = RunSource(image_scan_run(1, n_y=12, n_x=16, n_z=3))
    np.testing.assert_allclose(from_cache.y, fresh.fetch.get_plot_bundle(inner).y)


def test_toggling_a_norm_reads_the_norm_and_never_the_block():
    """
    Step 5: the block is held as read, and the norms beside it.

    The cache used to hold the *normalized* block, so the norm keys were part
    of its identity and turning a normalization on or off re-read the whole
    detector array -- a routine interaction, not an edge case. Now a norm
    costs one read of its own key the first time it is wanted, and turning it
    off, or back on, costs nothing: the divide re-runs, the read does not.
    """
    run = _model()
    view = Projection(
        ndim=3,
        plot_ndim=1,
        roles=(DimRole.SUM, DimRole.INDEX, DimRole.PLOT_X),
        indices=(0, 2, 0)
)
    plain = _request(run, "PCOEdge_image", ["sampleVoltage_VSource"], view)
    normed = replace(plain, norm_keys=("i0",
))
    run.fetch.get_plot_bundle(plain)

    calls = _count_reads(run)
    on = run.fetch.get_plot_bundle(normed)
    # The norm, and the X key its event axis is plotted against -- read for
    # it exactly as for the block. Never the block.
    assert [key for key, _slice in calls] == ["i0", "sampleVoltage_VSource"]

    del calls[:]
    off = run.fetch.get_plot_bundle(plain)
    again = run.fetch.get_plot_bundle(normed)
    assert calls == []

    np.testing.assert_allclose(on.y, _model().fetch.get_plot_bundle(normed).y)
    np.testing.assert_allclose(off.y, _model().fetch.get_plot_bundle(plain).y)
    np.testing.assert_allclose(again.y, on.y)
    assert not np.allclose(on.y, off.y)


def test_a_crop_inside_a_loaded_box_narrows_the_norms_with_the_block():
    """
    The norms in the entry were read against the held block, so a sub-block
    served from memory has to take the same window out of each of them. With
    coordinates on both, a norm left at full size does not broadcast quietly
    -- the exact join refuses it.
    """
    data = make_vppem_data()
    n_rows, n_cols = VPPEM_SHAPE[1:]
    flat = 1.0 + np.arange(n_rows, dtype=float)[:, None] * np.ones(n_cols)
    data["PCOEdge_flat"] = np.broadcast_to(flat[None, :, :], VPPEM_SHAPE).copy()

    def flat_model():
        return RunSource(MemoryRun(make_vppem_metadata(), data))

    run = flat_model()
    cube = ViewIntent(plot_ndim=2).project(3).with_index(0, 4)
    full = _request(
        run,
        "PCOEdge_image",
        ["sampleVoltage_VSource"],
        cube,
        norm_keys=("PCOEdge_flat",
)
)
    run.fetch.get_plot_bundle(full)

    crop = ViewCrop(storage_bbox=(2, 10, 4, 20), plot_y_axis=1, plot_x_axis=2)
    cropped = replace(full, view=replace(cube, crop=crop))
    calls = _count_reads(run)
    from_cache = run.fetch.get_plot_bundle(cropped)

    assert calls == []
    np.testing.assert_allclose(
        from_cache.y, flat_model().fetch.get_plot_bundle(cropped).y
    )


def test_swapping_the_plot_axes_reads_nothing():
    """
    The block is in storage order, so which two axes are drawn is not part
    of what was read. The cache compared the plot plane because the load used
    to flip it; once the flip moved to the pack, that was a re-read for
    nothing.
    """
    run = RunSource(image_scan_run(1, n_y=12, n_x=16))
    request = _image_request(run)
    plain = run.fetch.get_plot_bundle(request)

    swapped = replace(request, view=request.view.swap_rows(1))
    calls = _count_reads(run)
    from_cache = run.fetch.get_plot_bundle(swapped)

    assert calls == []
    assert from_cache.y.shape == plain.y.shape[::-1]
    fresh = RunSource(image_scan_run(1, n_y=12, n_x=16))
    np.testing.assert_allclose(from_cache.y, fresh.fetch.get_plot_bundle(swapped).y)


def test_a_transform_that_assigns_in_place_leaves_the_held_block_alone():
    """
    A clip written ``y[y > t] = t`` assigns into the array it is handed.

    A plane that needs no reduce reaches the transform as the held block
    itself, so handing the interpreter that array wrote the clip into every
    later fetch: turning the transform off did not bring the data back. An
    element assignment to ``x`` rewrote the held coordinates the same way.
    """
    run = _model()
    line = _request(
        run,
        "PCOEdge_stats",
        ["sampleVoltage_VSource"],
        ViewIntent(plot_ndim=1).project(1)
)
    plain = run.fetch.get_plot_bundle(line)
    y_before, x_before = plain.y.copy(), plain.x_line.copy()

    clipped = run.fetch.get_plot_bundle(replace(line, transform="y[0] = -99"))
    moved = run.fetch.get_plot_bundle(replace(line, transform="x[0][0] = -99"))
    assert clipped.y[0] == -99
    assert moved.x_line[0] == -99

    after = run.fetch.get_plot_bundle(line)
    np.testing.assert_array_equal(after.y, y_before)
    np.testing.assert_array_equal(after.x_line, x_before)


def test_a_data_change_clears_the_block_before_traces_refetch(qapp):
    """
    Traces refetch on ``RunSource.data_changed``, so the held block has to be
    gone by the time that signal reaches them. That is why the run clears its
    fetch directly, rather than the fetch listening to the same signal and
    depending on being connected first.
    """
    data = make_vppem_data()
    run = RunSource(MemoryRun(make_vppem_metadata(), data))
    line = _request(
        run,
        "PCOEdge_stats",
        ["sampleVoltage_VSource"],
        ViewIntent(plot_ndim=1).project(1)
)
    before = run.fetch.get_plot_bundle(line).y.copy()

    data["PCOEdge_stats"] = 2.0 * np.asarray(data["PCOEdge_stats"])
    seen = []
    run.data_changed.connect(
        lambda: seen.append(run.fetch.get_plot_bundle(line).y.copy())
    )
    run.run.data_changed.emit()

    assert len(seen) == 1
    np.testing.assert_allclose(seen[0], 2.0 * before)


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
        indices=(0, 2, 0)
)
    request = _request(
        run,
        "PCOEdge_image",
        ["sampleVoltage_VSource"],
        view,
        norm_keys=("i0",
)
)

    bundle = run.fetch.get_plot_bundle(request)

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
    plane = run.fetch.get_plot_bundle(parent)

    roi = replace(
        parent,
        region=RectRegion(
            x0=_coordinate_at(run, "en_energy", 0.4),
            x1=_coordinate_at(run, "en_energy", 2.6),
            y0=1.5,
            y1=9.5
),
        profile_axis=1
)
    from_cache = run.fetch.get_plot_bundle(roi, cached_plane=plane)

    fresh = RunSource(image_scan_run(1, n_y=12, n_x=16))
    from_load = fresh.fetch.get_plot_bundle(roi)

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
        indices=(0, 0, 0)
)
    parent = PlotRequest(
        uid=run.uid,
        xkeys=("en_energy",
),
        ykey="detector_cube",
        norm_keys=(),
        view=view,
        dims=run.plot_axis_names("detector_cube", ("en_energy",
)),
        transform="y * len(x)"
)
    assert run.fetch.get_plot_bundle(parent).ndim == 2

    roi = replace(
        parent,
        # The plane is (en_energy, dim_2), as above.
        region=RectRegion(
            x0=_coordinate_at(run, "dim_2", 0.4),
            x1=_coordinate_at(run, "dim_2", 2.6),
            y0=_coordinate_at(run, "en_energy", 1.5),
            y1=_coordinate_at(run, "en_energy", 9.5)
),
        profile_axis=2
)
    scaled = run.fetch.get_plot_bundle(roi)
    plain = run.fetch.get_plot_bundle(replace(roi, transform=""))

    np.testing.assert_allclose(scaled.y, 2.0 * plain.y)


# ---------------------------------------------------------------------------
# Normalization arrays arrive with their coordinates
# ---------------------------------------------------------------------------


def _image_scan_model():
    return RunSource(image_scan_run(0, n_y=6, n_x=5, n_z=3))


def _norms_for(model, ykey, xkeys, norm_keys, plot_ndim=2):
    """Run the load boundary and return ``(request, block, norm arrays)``."""
    from nbs_viewer.models.plot.spec.request import PlotRequest
    from nbs_viewer.models.plot.view_intent import ViewIntent

    shape = model.get_shape(ykey)
    view = ViewIntent(plot_ndim=min(plot_ndim, len(shape))).project(
        len(shape), shape
    )
    request = PlotRequest(
        uid=model.uid,
        xkeys=tuple(xkeys),
        ykey=ykey,
        norm_keys=tuple(norm_keys or ()),
        view=view,
        dims=tuple(model.plot_axis_names(ykey, xkeys))
)
    block, norms, _plan = model.fetch._load_block(request)
    return request, block, norms


def test_a_norm_arrives_with_the_same_coordinates_as_the_block():
    """
    A norm is aligned on coordinate *values*, not on a name and a length.

    Matching by name and shape divides one array into another wherever the
    two happen to be the same size, which is a plausible wrong answer rather
    than an error. Under ``arithmetic_join="exact"`` the coordinates have to
    agree, so the divide either lines up or raises.

    This only became possible once nothing in the pipeline was flipped: a
    reversed coordinate does not compare equal to the one the source holds,
    so the guard used to fire on correct data.
    """
    model = _image_scan_model()
    _request, block, norms = _norms_for(
        model, "detector_image", ["en_energy"], ["row"]
    )

    assert len(norms) == 1
    norm = norms[0]
    assert norm.dims == ("time",
)
    assert "time" in norm.coords
    np.testing.assert_array_equal(
        norm.coords["time"].values, block.coords["time"].values
    )


def test_a_norm_read_from_the_wrong_window_raises_instead_of_dividing():
    """
    The failure the coordinates exist to catch.

    A norm taken from a different stretch of the same axis has the right name
    and the right length, so nothing short of comparing coordinate values can
    tell. Shifting them by half a step is enough; the arrays still broadcast,
    which is exactly why the old rule could not see it.
    """
    # Same name, same length as the block's axis: it would broadcast without
    # complaint, which is exactly why the old rule could not see the shift.
    _request, block, norms = _norms_for(
        _image_scan_model(), "detector_image", ["en_energy"], ["row"]
    )
    assert norms[0].dims == ("time",
)
    assert norms[0].sizes["time"] == block.sizes["time"]

    model = _image_scan_model()
    original = model._run.load_coords

    def shifted(key, slice_info=None):
        coords = original(key, slice_info)
        if key == "row":
            coords = {
                dim: np.asarray(values, dtype=float) + 0.5
                for dim, values in coords.items()
            }
        return coords

    model._run.load_coords = shifted

    # Loading holds the block and the norm apart; the divide is where they
    # meet, so that is where the guard fires -- through the whole pipeline.
    request, _block, _norms = _norms_for(
        model, "detector_image", ["en_energy"], ["row"]
    )
    with pytest.raises(xr.AlignmentError):
        model.fetch.get_plot_bundle(request)


def test_a_frozen_norm_has_no_coordinates_and_aligns_by_position(qapp):
    """
    The one norm still aligned by position, and why.

    A frozen spectrum's axes are whatever the ROI reduction produced and
    stored -- they are not the block's, so attaching them would compare two
    unrelated coordinate systems. Its single axis is renamed onto the block's
    leading one instead, which is the same rule the old shape-matching
    fallback implemented by accident, stated on purpose.
    """
    model = _model()
    # Same length as the block's leading axis: a frozen stack spectrum is a
    # per-event quantity, and nothing but the length can say so.
    entry = _frozen_entry(
        model, key_suffix="norm", y=list(np.full(VPPEM_SHAPE[0], 2.0))
    )
    model.register_frozen_spectrum(entry)

    _request, block, norms = _norms_for(
        model, "PCOEdge_stats", ["sampleVoltage_VSource"], [entry.key], plot_ndim=1
    )

    assert norms[0].dims == block.dims[: norms[0].ndim]
    assert list(norms[0].coords) == []
