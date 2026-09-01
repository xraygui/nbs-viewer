"""Tests for frozen synthetic spectra on RunModel."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from nbs_viewer.models.plot.cube_view import (
    CubeViewSpec,
    DimRole,
    MaterializeRequest,
    classify_profile_kind,
    default_spec,
    scan_profile_storage_axis,
)
from nbs_viewer.models.plot.frozen_spectrum import (
    SYNTHETIC_KEY_PREFIX,
    FrozenSpectrum,
    copy_plot_bundle,
    is_synthetic_key,
)
from nbs_viewer.models.plot.plot_geometry import PlotBundle, prepare_1d_bundle
from nbs_viewer.models.plot.runModel import RunModel


def _mock_run(catalog_keys=None):
    run = MagicMock()
    run.uid = "uid-1"
    run.scan_id = "7063"
    run.available_keys = catalog_keys or ["en_energy", "time"]
    run.get_default_selection.return_value = (["en_energy"], [], [])
    run.data_changed = MagicMock()
    run.data_changed.connect = MagicMock()
    run.keys_ready = MagicMock()
    run.keys_ready.connect = MagicMock()
    run.keys_error = MagicMock()
    run.keys_error.connect = MagicMock()
    return run


def _line_bundle(values, x=None, name="profile"):
    x = np.asarray(values if x is None else x, dtype=float)
    y = np.asarray(values, dtype=float)
    return prepare_1d_bundle(y, [x], [name])


def _frozen_entry(key_suffix="abc", y=None):
    bundle = _line_bundle(y if y is not None else [1.0, 2.0, 3.0])
    return FrozenSpectrum(
        key=f"{SYNTHETIC_KEY_PREFIX}{key_suffix}",
        label="mean(in ROI) · en_energy",
        bundle=bundle,
        kind="stack_spectrum",
        source_ykey="detector_image",
        committed_xkey="en_energy",
        request=MaterializeRequest(
            CubeViewSpec(
                ndim=2,
                plot_ndim=1,
                roles=(DimRole.PLOT_X, DimRole.MEAN),
                indices=(0, 0),
            )
        ),
        source_key=("en_energy", "detector_image", "uid-1"),
    )


def test_is_synthetic_key():
    assert is_synthetic_key(f"{SYNTHETIC_KEY_PREFIX}abc")
    assert not is_synthetic_key("en_energy")


def test_scan_profile_storage_axis_4d():
    spec = CubeViewSpec(
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
    spec = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    assert scan_profile_storage_axis(spec) == 0
    assert classify_profile_kind(spec, 0) == "stack_spectrum"
    assert classify_profile_kind(spec, 1) == "local_profile"


def test_scan_profile_storage_axis_unchanged_after_swap():
    spec = CubeViewSpec(
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


def test_register_and_available_keys():
    model = RunModel(_mock_run())
    entry = _frozen_entry()
    model.register_frozen_spectrum(entry)
    assert entry.key in model.available_keys
    assert entry.key not in model.catalog_keys
    assert model.is_synthetic_key(entry.key)


def test_frozen_get_data_respects_slice_info():
    entry = _frozen_entry(y=[10.0, 20.0, 30.0])
    np.testing.assert_allclose(entry.get_data((1,)), [20.0])
    np.testing.assert_allclose(
        entry.get_data((slice(None),)), [10.0, 20.0, 30.0]
    )


def test_run_model_get_data_delegates_to_frozen():
    model = RunModel(_mock_run())
    entry = _frozen_entry(y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    np.testing.assert_allclose(model.get_data(entry.key, (0,)), [10.0])
    np.testing.assert_allclose(model.get_shape(entry.key), (3,))


def test_run_model_get_dimension_ui_info_for_frozen():
    model = RunModel(_mock_run())
    entry = _frozen_entry(y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    shape, names, axis_arrays, associated = model.get_dimension_ui_info(
        entry.key, ["en_energy"]
    )
    assert shape == (3,)
    assert names == [entry.label]
    np.testing.assert_allclose(axis_arrays[0], [0.0, 1.0, 2.0])
    assert associated == {}
    model._run.get_dimension_ui_info.assert_not_called()


def test_synthetic_y_fetch_ignores_catalog_get_data():
    model = RunModel(_mock_run())
    entry = _frozen_entry(y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData.return_value = np.array([0.0, 1.0, 2.0])
    bundle = model.get_plot_bundle(["en_energy"], entry.key)
    assert bundle.render_mode == "line"
    np.testing.assert_allclose(bundle.y, [10.0, 20.0, 30.0])
    np.testing.assert_allclose(bundle.x_line, [0.0, 1.0, 2.0])
    model._run.getData.assert_called_once_with("en_energy")


def test_stack_spectrum_uses_selected_catalog_x():
    model = RunModel(_mock_run(["en_energy", "time", "motor_position"]))
    entry = _frozen_entry(y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)

    def _get_data(key, slice_info=None):
        data = {
            "en_energy": np.array([100.0, 200.0, 300.0]),
            "time": np.array([1.0, 2.0, 3.0]),
            "motor_position": np.array([0.1, 0.2, 0.3]),
        }[key]
        return data

    model._run.getData.side_effect = _get_data

    bundle_time = model.get_plot_bundle(["time"], entry.key)
    np.testing.assert_allclose(bundle_time.y, [10.0, 20.0, 30.0])
    np.testing.assert_allclose(bundle_time.x_line, [1.0, 2.0, 3.0])

    bundle_motor = model.get_plot_bundle(["motor_position"], entry.key)
    np.testing.assert_allclose(bundle_motor.x_line, [0.1, 0.2, 0.3])


def test_stack_spectrum_x_length_mismatch_raises():
    model = RunModel(_mock_run())
    entry = _frozen_entry(y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData.return_value = np.array([0.0, 1.0])
    with pytest.raises(ValueError, match="does not match"):
        model.get_plot_bundle(["en_energy"], entry.key)


def test_local_profile_keeps_frozen_x():
    model = RunModel(_mock_run())
    bundle = _line_bundle([1.0, 2.0, 3.0], x=[10.0, 20.0, 30.0])
    entry = FrozenSpectrum(
        key=f"{SYNTHETIC_KEY_PREFIX}local",
        label="profile · dim_2",
        bundle=bundle,
        kind="local_profile",
        source_ykey="detector_image",
        committed_xkey="dim_2",
        request=MaterializeRequest(
            CubeViewSpec(
                ndim=2,
                plot_ndim=1,
                roles=(DimRole.PLOT_X, DimRole.MEAN),
                indices=(0, 0),
            )
        ),
        source_key=("en_energy", "detector_image", "uid-1"),
    )
    model.register_frozen_spectrum(entry)
    result = model.get_plot_bundle(["en_energy"], entry.key)
    np.testing.assert_allclose(result.x_line, [10.0, 20.0, 30.0])
    model._run.getData.assert_not_called()


def test_synthetic_norm_without_get_data_for_norm_key():
    model = RunModel(_mock_run())
    norm_entry = _frozen_entry(key_suffix="norm", y=[2.0, 2.0, 2.0])
    model.register_frozen_spectrum(norm_entry)

    model._run.getData.return_value = np.array([4.0, 8.0, 12.0])
    model._run.get_dimension_axes.return_value = (
        [np.array([0.0, 1.0, 2.0])],
        ["en_energy"],
        {},
    )

    xlist, axis_names, y = model._fetch_plot_arrays(
        ["en_energy"],
        "time",
        norm_keys=[norm_entry.key],
        slice_info=None,
    )
    np.testing.assert_allclose(y, [2.0, 4.0, 6.0])
    model._run.getData.assert_called_once()


def test_frozen_plot_ignores_parent_cube_view_spec():
    model = RunModel(_mock_run())
    entry = _frozen_entry(y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData.return_value = np.array([0.0, 1.0, 2.0])
    spec = default_spec(2, plot_ndim=2)
    bundle = model.get_plot_bundle(["en_energy"], entry.key, cube_view_spec=spec)
    assert bundle.render_mode == "line"
    np.testing.assert_allclose(bundle.y, [10.0, 20.0, 30.0])


def test_transform_assignment_updates_y():
    model = RunModel(_mock_run())
    entry = _frozen_entry(y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData.return_value = np.array([0.0, 1.0, 2.0])
    model.set_transform({"enabled": True, "text": "y = y * 2"})
    bundle = model.get_plot_bundle(["en_energy"], entry.key)
    np.testing.assert_allclose(bundle.y, [20.0, 40.0, 60.0])


def test_remove_frozen_spectrum_clears_selection():
    model = RunModel(_mock_run())
    entry = _frozen_entry()
    model.register_frozen_spectrum(entry)
    model.set_selected_keys([], [entry.key], [], force_update=False)
    assert model.remove_frozen_spectrum(entry.key)
    assert entry.key not in model.available_keys
    y_keys = model.get_selected_keys()[1]
    assert entry.key not in y_keys
