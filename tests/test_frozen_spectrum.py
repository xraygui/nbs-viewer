"""Tests for frozen synthetic spectra on RunSource."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.view_spec import (
    DimRole,
    Projection,
    classify_profile_kind,
    scan_profile_storage_axis,
)
from nbs_viewer.models.plot.frozen_spectrum import (
    SYNTHETIC_KEY_PREFIX,
    FrozenSpectrum,
    copy_plot_bundle,
    is_synthetic_key,
)
from nbs_viewer.models.plot.plot_geometry import prepare_1d_bundle
from nbs_viewer.models.plot.plot_request import PlotRequest, build_plot_request
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.run_source import RunSource
from tests.fixtures.catalog_recipes import image_scan_run, line_scan_run


def _run_model(catalog_keys=None):
    run = image_scan_run(1)
    model = RunSource(run)
    if catalog_keys is not None:
        model._catalog_keys = list(catalog_keys)
    return model


def _line_bundle(values, x=None, name="profile"):
    x = np.asarray(values if x is None else x, dtype=float)
    y = np.asarray(values, dtype=float)
    return prepare_1d_bundle(y, [x], [name])


def _frozen_entry(model, key_suffix="abc", y=None):
    bundle = _line_bundle(y if y is not None else [1.0, 2.0, 3.0])
    return FrozenSpectrum(
        key=f"{SYNTHETIC_KEY_PREFIX}{key_suffix}",
        label="mean(in ROI) · en_energy",
        bundle=bundle,
        kind="stack_spectrum",
        source_ykey="detector_image",
        committed_xkey="en_energy",
        request=PlotRequest(
            uid=model.uid,
            xkeys=("en_energy",),
            ykey="detector_image",
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
        source_key=("en_energy", "detector_image", model.uid),
    )


def _plot_request(model, xkeys, ykey, plot_ndim=1, projection=None, **kwargs):
    shape = model.get_shape(ykey)
    if projection is None:
        # As the session does: a key that cannot fill the plot projects on
        # its own rank rather than dropping out.
        plot_ndim = min(plot_ndim, len(shape))
        projection = ViewIntent(plot_ndim=plot_ndim).project(len(shape), shape)
    return build_plot_request(
        uid=model.uid,
        xkeys=xkeys,
        ykey=ykey,
        projection=projection,
        **kwargs,
    )


def test_is_synthetic_key():
    assert is_synthetic_key(f"{SYNTHETIC_KEY_PREFIX}abc")
    assert not is_synthetic_key("en_energy")


def test_scan_profile_storage_axis_4d():
    spec = Projection(
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
    assert scan_profile_storage_axis(spec) == 0
    assert classify_profile_kind(spec, 0) == "stack_spectrum"
    assert classify_profile_kind(spec, 1) == "local_profile"
    assert classify_profile_kind(spec, 3) == "local_profile"


def test_scan_profile_storage_axis_2d_mesh():
    spec = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    assert scan_profile_storage_axis(spec) == 0
    assert classify_profile_kind(spec, 0) == "stack_spectrum"
    assert classify_profile_kind(spec, 1) == "local_profile"


def test_scan_profile_storage_axis_unchanged_after_swap():
    spec = Projection(
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
    swapped = spec.swap_rows(1)
    assert scan_profile_storage_axis(swapped) == 0


def test_copy_plot_bundle_is_independent():
    bundle = _line_bundle([1.0, 2.0])
    copied = copy_plot_bundle(bundle)
    copied.y[0] = 99.0
    assert bundle.y[0] == 1.0


def test_register_and_available_keys(qapp):
    model = _run_model()
    entry = _frozen_entry(model)
    model.register_frozen_spectrum(entry)
    assert entry.key in model.available_keys
    assert entry.key not in model.catalog_keys
    assert model.is_synthetic_key(entry.key)


def test_frozen_get_data_respects_slice_info():
    entry = _frozen_entry(RunSource(line_scan_run(0)), y=[10.0, 20.0, 30.0])
    np.testing.assert_allclose(entry.get_data((1,)), [20.0])
    np.testing.assert_allclose(
        entry.get_data((slice(None),)), [10.0, 20.0, 30.0]
    )


def test_run_model_get_data_delegates_to_frozen(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    np.testing.assert_allclose(model.read(entry.key, (0,)), [10.0])
    np.testing.assert_allclose(model.get_shape(entry.key), (3,))


def test_run_source_describe_axes_for_frozen(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    layout = model.describe_axes(entry.key, ["en_energy"])
    assert layout.shape == (3,)
    assert list(layout.names) == [entry.label]
    np.testing.assert_allclose(layout.placeholders[0], [0.0, 1.0, 2.0])
    assert dict(layout.associated) == {}


def test_synthetic_y_fetch_ignores_catalog_get_data(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    get_data = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    model._run.getData = get_data
    bundle = model.get_plot_bundle(
        _plot_request(model, ["en_energy"], entry.key)
    )
    assert bundle.render_mode == "line"
    np.testing.assert_allclose(bundle.y, [10.0, 20.0, 30.0])
    np.testing.assert_allclose(bundle.x_line, [0.0, 1.0, 2.0])
    get_data.assert_called_once_with("en_energy")


def test_stack_spectrum_uses_selected_catalog_x(qapp):
    model = _run_model(["en_energy", "time", "motor_position"])

    def _get_data(key, slice_info=None):
        data = {
            "en_energy": np.array([100.0, 200.0, 300.0]),
            "time": np.array([1.0, 2.0, 3.0]),
            "motor_position": np.array([0.1, 0.2, 0.3]),
        }[key]
        return data

    model._run.getData = MagicMock(side_effect=_get_data)
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)

    bundle_time = model.get_plot_bundle(
        _plot_request(model, ["time"], entry.key)
    )
    np.testing.assert_allclose(bundle_time.y, [10.0, 20.0, 30.0])
    np.testing.assert_allclose(bundle_time.x_line, [1.0, 2.0, 3.0])

    bundle_motor = model.get_plot_bundle(
        _plot_request(model, ["motor_position"], entry.key)
    )
    np.testing.assert_allclose(bundle_motor.x_line, [0.1, 0.2, 0.3])


def test_stack_spectrum_x_length_mismatch_raises(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData = MagicMock(return_value=np.array([0.0, 1.0]))
    with pytest.raises(ValueError, match="does not match"):
        model.get_plot_bundle(_plot_request(model, ["en_energy"], entry.key))


def test_local_profile_keeps_frozen_x(qapp):
    model = _run_model()
    bundle = _line_bundle([1.0, 2.0, 3.0], x=[10.0, 20.0, 30.0])
    entry = FrozenSpectrum(
        key=f"{SYNTHETIC_KEY_PREFIX}local",
        label="profile · dim_2",
        bundle=bundle,
        kind="local_profile",
        source_ykey="detector_image",
        committed_xkey="dim_2",
        request=PlotRequest(
            uid=model.uid,
            xkeys=("en_energy",),
            ykey="detector_image",
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
        source_key=("en_energy", "detector_image", model.uid),
    )
    model.register_frozen_spectrum(entry)
    get_data = MagicMock()
    model._run.getData = get_data
    result = model.get_plot_bundle(
        _plot_request(model, ["en_energy"], entry.key)
    )
    np.testing.assert_allclose(result.x_line, [10.0, 20.0, 30.0])
    get_data.assert_not_called()


def test_synthetic_norm_without_get_data_for_norm_key(qapp):
    model = _run_model()
    norm_entry = _frozen_entry(model, key_suffix="norm", y=[2.0, 2.0, 2.0])
    model.register_frozen_spectrum(norm_entry)

    model._run.getData = MagicMock(return_value=np.array([4.0, 8.0, 12.0]))
    model._run.get_dimension_axes = MagicMock(
        return_value=(
            [np.array([0.0, 1.0, 2.0])],
            ["en_energy"],
            {},
        )
    )

    bundle = model.get_plot_bundle(
        _plot_request(
            model, ["en_energy"], "time", norm_keys=[norm_entry.key]
        )
    )
    np.testing.assert_allclose(bundle.y, [2.0, 4.0, 6.0])
    model._run.getData.assert_called_once()


def test_frozen_plot_projects_on_its_own_rank(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    # The session downgrades plot_ndim for a key that cannot fill the plot,
    # so a 1-D frozen spectrum never receives the 2-D image's projection.
    bundle = model.get_plot_bundle(
        _plot_request(model, ["en_energy"], entry.key, plot_ndim=2)
    )
    assert bundle.render_mode == "line"
    np.testing.assert_allclose(bundle.y, [10.0, 20.0, 30.0])


def test_transform_assignment_updates_y(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    bundle = model.get_plot_bundle(
        _plot_request(
            model, ["en_energy"], entry.key, transform="y = y * 2"
        )
    )
    np.testing.assert_allclose(bundle.y, [20.0, 40.0, 60.0])


def test_remove_frozen_spectrum_drops_key(qapp):
    model = _run_model()
    entry = _frozen_entry(model)
    model.register_frozen_spectrum(entry)
    assert entry.key in model.available_keys
    assert model.remove_frozen_spectrum(entry.key)
    assert entry.key not in model.available_keys
