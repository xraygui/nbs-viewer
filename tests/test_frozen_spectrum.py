"""Tests for frozen synthetic spectra on RunSource."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.plane.roles import DimRole
from nbs_viewer.models.plot.spec.projection import Projection
from nbs_viewer.models.plot.run.frozen_spectrum import (
    FrozenSpectrum,
    SYNTHETIC_KEY_PREFIX,
)
from nbs_viewer.models.plot.spec.bundle import PlotBundle
from nbs_viewer.models.plot.spec.request import PlotRequest
from nbs_viewer.models.plot.spec.region import RectRegion
from nbs_viewer.models.plot.run.source import RunSource
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
    return PlotBundle.from_1d(y, [x], [name])


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
            xkeys=("en_energy",
),
            ykey="detector_image",
            norm_keys=(),
            view=Projection(
                ndim=2,
                plot_ndim=2,
                roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
                indices=(0, 0)
),
            dims=("time", "pixel"),
            region=RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0),
            profile_axis=1,
            spatial_reduce="mean"
),
        source_key=("en_energy", "detector_image", model.uid)
)


def _plot_request(model, xkeys, ykey, plot_ndim=1, projection=None, **kwargs):
    shape = model.get_shape(ykey)
    if projection is None:
        # As the session does: a key that cannot fill the plot projects on
        # its own rank rather than dropping out.
        plot_ndim = min(plot_ndim, len(shape))
        projection = ViewIntent(plot_ndim=plot_ndim).project(len(shape), shape)
    return PlotRequest(
        uid=model.uid,
        xkeys=tuple(xkeys),
        ykey=ykey,
        norm_keys=tuple(kwargs.pop("norm_keys", ()) or ()),
        view=projection,
        dims=tuple(model.plot_axis_names(ykey, xkeys)),
        transform=kwargs.pop("transform", "") or "",
        **kwargs
)


def test_scan_profile_storage_axis_4d():
    spec = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(
            DimRole.INDEX,
            DimRole.INDEX,
            DimRole.PLOT_Y,
            DimRole.PLOT_X
),
        indices=(0, 0, 0, 0)
)
    assert spec.scan_axis == 0
    assert spec.profile_kind(0) == "stack_spectrum"
    assert spec.profile_kind(1) == "local_profile"
    assert spec.profile_kind(3) == "local_profile"


def test_scan_profile_storage_axis_2d_mesh():
    spec = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0)
)
    assert spec.scan_axis == 0
    assert spec.profile_kind(0) == "stack_spectrum"
    assert spec.profile_kind(1) == "local_profile"


def test_scan_profile_storage_axis_unchanged_after_swap():
    spec = Projection(
        ndim=4,
        plot_ndim=2,
        roles=(
            DimRole.INDEX,
            DimRole.INDEX,
            DimRole.PLOT_Y,
            DimRole.PLOT_X
),
        indices=(0, 0, 0, 0)
)
    swapped = spec.swap_rows(1)
    assert swapped.scan_axis == 0


def test_the_bundle_copy_is_independent():
    bundle = _line_bundle([1.0, 2.0])
    copied = bundle.copy()
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
    np.testing.assert_allclose(entry.get_data((1,
)), [20.0])
    np.testing.assert_allclose(
        entry.get_data((slice(None),
)), [10.0, 20.0, 30.0]
    )


def test_run_model_get_data_delegates_to_frozen(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    np.testing.assert_allclose(model.read(entry.key, (0,
)), [10.0])
    np.testing.assert_allclose(model.get_shape(entry.key), (3,
))


def test_run_source_describes_a_frozen_key(qapp):
    """
    A frozen key answers ``describe`` the way a catalog key does.

    Its one axis is named after its label, which is what the dimension
    controls have always shown for a frozen spectrum. The X selection does not
    reach it: a frozen payload's axes are whatever the reduction produced.
    """
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)

    info = model.describe(entry.key)
    assert info.shape == (3,
)
    assert info.dims == (entry.label,
)
    assert info.axes == {entry.label: 3}
    assert info.synthetic is True
    assert model.plot_axis_names(entry.key, ["en_energy"]) == (entry.label,
)


def test_synthetic_y_fetch_ignores_catalog_get_data(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    get_data = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    model._run.getData = get_data
    bundle = _plot_request(model, ["en_energy"], entry.key).plot_bundle(model)
    assert bundle.render_mode == "line"
    np.testing.assert_allclose(bundle.y, [10.0, 20.0, 30.0])
    np.testing.assert_allclose(bundle.x_line, [0.0, 1.0, 2.0])
    get_data.assert_called_once_with("en_energy", None)


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

    bundle_time = _plot_request(model, ["time"], entry.key).plot_bundle(model)
    np.testing.assert_allclose(bundle_time.y, [10.0, 20.0, 30.0])
    np.testing.assert_allclose(bundle_time.x_line, [1.0, 2.0, 3.0])

    bundle_motor = _plot_request(model, ["motor_position"], entry.key).plot_bundle(model)
    np.testing.assert_allclose(bundle_motor.x_line, [0.1, 0.2, 0.3])


def test_stack_spectrum_x_length_mismatch_raises(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData = MagicMock(return_value=np.array([0.0, 1.0]))
    with pytest.raises(ValueError, match="does not match"):
        _plot_request(model, ["en_energy"], entry.key).plot_bundle(model)


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
            xkeys=("en_energy",
),
            ykey="detector_image",
            norm_keys=(),
            view=Projection(
                ndim=2,
                plot_ndim=2,
                roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
                indices=(0, 0)
),
            dims=("time", "pixel"),
            region=RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0),
            profile_axis=1,
            spatial_reduce="mean"
),
        source_key=("en_energy", "detector_image", model.uid)
)
    model.register_frozen_spectrum(entry)
    get_data = MagicMock()
    model._run.getData = get_data
    result = _plot_request(model, ["en_energy"], entry.key).plot_bundle(model)
    np.testing.assert_allclose(result.x_line, [10.0, 20.0, 30.0])
    get_data.assert_not_called()


def test_synthetic_norm_without_get_data_for_norm_key(qapp):
    model = _run_model()
    norm_entry = _frozen_entry(model, key_suffix="norm", y=[2.0, 2.0, 2.0])
    model.register_frozen_spectrum(norm_entry)

    model._run.getData = MagicMock(return_value=np.array([4.0, 8.0, 12.0]))
    model._run.load_coords = MagicMock(
        return_value={"time": np.array([0.0, 1.0, 2.0])}
    )

    bundle = _plot_request(
            model, ["en_energy"], "time", norm_keys=[norm_entry.key]
        ).plot_bundle(model)
    np.testing.assert_allclose(bundle.y, [2.0, 4.0, 6.0])
    model._run.getData.assert_called_once()


def test_frozen_plot_projects_on_its_own_rank(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    # The session downgrades plot_ndim for a key that cannot fill the plot,
    # so a 1-D frozen spectrum never receives the 2-D image's projection.
    bundle = _plot_request(model, ["en_energy"], entry.key, plot_ndim=2).plot_bundle(model)
    assert bundle.render_mode == "line"
    np.testing.assert_allclose(bundle.y, [10.0, 20.0, 30.0])


def test_transform_assignment_updates_y(qapp):
    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    bundle = _plot_request(
            model, ["en_energy"], entry.key, transform="y = y * 2"
        ).plot_bundle(model)
    np.testing.assert_allclose(bundle.y, [20.0, 40.0, 60.0])


def test_remove_frozen_spectrum_drops_key(qapp):
    model = _run_model()
    entry = _frozen_entry(model)
    model.register_frozen_spectrum(entry)
    assert entry.key in model.available_keys
    assert model.remove_frozen_spectrum(entry.key)
    assert entry.key not in model.available_keys
