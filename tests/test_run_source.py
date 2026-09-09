"""Tests for the RunSource surface on RunSource."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from nbs_viewer.models.plot.view_spec import ViewIntent
from nbs_viewer.models.plot.view_spec import (
    DimRole,
    Projection,
)
from nbs_viewer.models.plot.frozen_spectrum import (
    SYNTHETIC_KEY_PREFIX,
    FrozenSpectrum,
)
from nbs_viewer.models.plot.key_info import KeyInfo
from nbs_viewer.models.plot.plot_geometry import prepare_1d_bundle
from nbs_viewer.models.plot.plot_request import PlotRequest, build_plot_request
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.view_spec import Projection
from nbs_viewer.models.plot.runSource import RunSource, RunSource
from nbs_viewer.models.sources.fixtures import (
    VPPEM_UID,
    make_vppem_run,
    vppem_factors,
    vppem_image,
)


def _line_bundle(values, x=None, name="profile"):
    x = np.asarray(values if x is None else x, dtype=float)
    y = np.asarray(values, dtype=float)
    return prepare_1d_bundle(y, [x], [name])


def _frozen_entry(model, key_suffix="abc", y=None, label=None):
    bundle = _line_bundle(y if y is not None else [1.0, 2.0, 3.0])
    return FrozenSpectrum(
        key=f"{SYNTHETIC_KEY_PREFIX}{key_suffix}",
        label=label or "mean(in ROI) · sampleVoltage_VSource",
        bundle=bundle,
        kind="stack_spectrum",
        source_ykey="PCOEdge_image",
        committed_xkey="sampleVoltage_VSource",
        request=PlotRequest(
            uid=model.uid,
            xkeys=("sampleVoltage_VSource",),
            ykey="PCOEdge_image",
            norm_keys=(),
            view=Projection(
                ndim=2,
                plot_ndim=2,
                roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
                indices=(0, 0),
            ),
            region=RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0),
            profile_axis=1,
            spatial_reduce="mean",
        ),
        source_key=("sampleVoltage_VSource", "PCOEdge_image", model.uid),
    )


def _plot_request(model, xkeys, ykey, plot_ndim=1, projection=None, **kwargs):
    shape = model.get_shape(ykey)
    if projection is None:
        projection = ViewIntent(plot_ndim=plot_ndim).project(len(shape), shape)
    return build_plot_request(
        uid=model.uid,
        xkeys=xkeys,
        ykey=ykey,
        projection=projection,
        **kwargs,
    )


def test_run_source_alias():
    assert RunSource is RunSource


def test_key_table_catalog_and_frozen(qapp):
    """
    Catalog keys are hinted=True until get_hinted_keys is confirmed.

    Synthetic rows carry synthetic=True and the friendly frozen label.
    render_hint is filled from get_render_mode_hint when present, else None.
    """
    model = RunSource(make_vppem_run())
    entry = _frozen_entry(model)
    model.register_frozen_spectrum(entry)

    table = model.key_table()
    assert "PCOEdge_image" in table
    assert "PCOEdge_stats" in table
    assert "i0" in table
    assert entry.key in table

    image_info = table["PCOEdge_image"]
    assert isinstance(image_info, KeyInfo)
    assert image_info.synthetic is False
    assert image_info.hinted is True
    assert image_info.label == "PCOEdge_image"
    assert image_info.shape == (11, 24, 32)
    assert image_info.render_hint is None

    frozen_info = table[entry.key]
    assert frozen_info.synthetic is True
    assert frozen_info.hinted is False
    assert frozen_info.label == entry.label
    assert frozen_info.shape == (3,)
    assert frozen_info.render_hint is None


def test_identity_matches_fixture(qapp):
    model = RunSource(make_vppem_run())
    ident = model.identity()
    assert ident.uid == VPPEM_UID
    assert ident.scan_id == "102"
    assert ident.plan_name == "nd_scan"
    assert ident.display_name == model.display_name
    assert ident.metadata["uid"] == VPPEM_UID


def test_read_frozen_skips_catalog_get_data(qapp):
    model = RunSource(make_vppem_run())
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    get_data = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    model._run.getData = get_data

    np.testing.assert_allclose(model.read(entry.key), [10.0, 20.0, 30.0])
    get_data.assert_not_called()


def test_describe_axes_matches_catalog_ui_info(qapp):
    model = RunSource(make_vppem_run())
    xkeys = ["sampleVoltage_VSource"]
    layout = model.describe_axes("PCOEdge_image", xkeys)
    run_shape, run_names, run_placeholders, run_associated = (
        model.run.get_dimension_ui_info("PCOEdge_image", xkeys)
    )

    assert layout.shape == run_shape == (11, 24, 32)
    assert list(layout.names) == run_names
    assert run_names == ["sampleVoltage_VSource", "dim_1", "dim_2"]
    assert dict(layout.associated) == run_associated == {}
    for left, right in zip(layout.placeholders, run_placeholders):
        np.testing.assert_allclose(left, right)


def test_load_axes_matches_catalog_dimension_axes(qapp):
    model = RunSource(make_vppem_run())
    xkeys = ["sampleVoltage_VSource"]
    loaded = model.load_axes("PCOEdge_image", xkeys)
    catalog = model.run.get_dimension_axes("PCOEdge_image", xkeys)

    assert loaded[1] == catalog[1]
    assert loaded[1] == ["sampleVoltage_VSource", "dim_1", "dim_2"]
    for left, right in zip(loaded[0], catalog[0]):
        np.testing.assert_allclose(left, right)


def test_get_plot_bundle_1d_closed_form(qapp):
    model = RunSource(make_vppem_run())
    a, b, c = vppem_factors()
    expected = a * b.mean() * c.mean()
    bundle = model.get_plot_bundle(
        _plot_request(model, ["sampleVoltage_VSource"], "PCOEdge_stats")
    )
    assert bundle.render_mode == "line"
    np.testing.assert_allclose(bundle.y, expected)
    np.testing.assert_allclose(
        bundle.x_line, model.read("sampleVoltage_VSource")
    )


def test_get_plot_bundle_index_slice_closed_form(qapp):
    model = RunSource(make_vppem_run())
    spec = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(4, 0, 0),
    )
    bundle = model.get_plot_bundle(
        _plot_request(
            model,
            ["sampleVoltage_VSource"],
            "PCOEdge_image",
            plot_ndim=2,
            projection=spec,
        )
    )
    expected = vppem_image()[4]
    np.testing.assert_allclose(bundle.y, expected[::-1, :])


def test_get_plot_bundle_mean_mean_matches_stats(qapp):
    model = RunSource(make_vppem_run())
    spec = Projection(
        ndim=3,
        plot_ndim=1,
        roles=(DimRole.MEAN, DimRole.MEAN, DimRole.MEAN),
        indices=(0, 0, 0),
        axis_order=(1, 2, 0),
    )
    cube_bundle = model.get_plot_bundle(
        _plot_request(
            model,
            ["sampleVoltage_VSource"],
            "PCOEdge_image",
            plot_ndim=1,
            projection=spec,
        )
    )
    stats_bundle = model.get_plot_bundle(
        _plot_request(model, ["sampleVoltage_VSource"], "PCOEdge_stats")
    )
    np.testing.assert_allclose(cube_bundle.y, stats_bundle.y)


def test_get_plot_bundle_frozen_uses_read(qapp):
    model = RunSource(make_vppem_run())
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    get_data = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    model._run.getData = get_data

    bundle = model.get_plot_bundle(
        _plot_request(model, ["sampleVoltage_VSource"], entry.key)
    )
    np.testing.assert_allclose(bundle.y, [10.0, 20.0, 30.0])
    get_data.assert_called_once_with("sampleVoltage_VSource")
