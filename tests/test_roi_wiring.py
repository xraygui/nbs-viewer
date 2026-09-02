"""Integration tests for ROI APIs on catalog-wired 2D sessions."""

from __future__ import annotations

import numpy as np
import pytest

from nbs_viewer.models.plot.cube_view import CubeViewSpec, DimRole
from nbs_viewer.models.plot.frozen_spectrum import is_synthetic_key
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.region_mesh import (
    _cell_x_bounds_mesh,
    _cell_y_bounds_mesh,
)
from nbs_viewer.models.plot.roi_set import RoiOperation

from tests.fixtures.session import HeadlessSession


def _wired_image_scan_with_roi(
    app_model,
    *,
    profile_storage_axis: int = 0,
    stale: bool = False,
):
    """
    Build a catalog-wired 2D image session with one ROI entry.

    Parameters
    ----------
    app_model : AppModel
        Application root model.
    profile_storage_axis : int, optional
        Storage axis used for the ROI profile operation.
    stale : bool, optional
        When True, mark the ROI entry stale before returning.

    Returns
    -------
    tuple
        ``(session, run_model, plot_data, parent_spec, entry_id, frame, region)``
    """
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="image_scan", runs=1)
    run_model = session.select_run(0)

    parent_spec = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    session.plot.set_view_state(dimension=2, cube_view_spec=parent_spec)
    session.plot.set_selected_keys(["en_energy"], ["detector_image"])

    plot_data = session.plot.ensure_plot_data(
        run_model, "en_energy", "detector_image"
    )
    bundle = plot_data.get_plot_bundle(cube_view_spec=parent_spec)
    plot_data._visible = True

    frame = frame_from_bundle(bundle)
    x0, _ = _cell_x_bounds_mesh(frame, 5, 0)
    _, x1 = _cell_x_bounds_mesh(frame, 35, 0)
    y0, _ = _cell_y_bounds_mesh(frame, 2, 0)
    _, y1 = _cell_y_bounds_mesh(frame, 28, 0)
    region = RectRegion(x0=x0, x1=x1, y0=y0, y1=y1)
    entry_id = session.plot.roi_set.add(
        region,
        operation=RoiOperation(
            profile_storage_axis=profile_storage_axis,
            spatial_reduce="sum",
            span_full_profile_axis=True,
            label="test roi",
        ),
    )
    if stale:
        session.plot.roi_set.set_stale(entry_id, True)

    return session, run_model, plot_data, parent_spec, entry_id, frame, region


def test_preview_roi_profile_on_catalog_selected_run(qapp, app_model):
    session, _run_model, plot_data, parent_spec, entry_id, frame, _region = (
        _wired_image_scan_with_roi(app_model)
    )

    bundle = session.plot.preview_roi_profile(
        entry_id,
        parent_plot_data=plot_data,
        parent_spec=parent_spec,
        parent_frame=frame,
        parent_bundle=plot_data.last_bundle,
    )

    assert bundle.ndim == 1
    assert bundle.render_mode == "line"
    assert np.isfinite(bundle.y).any()


def test_commit_roi_profile_registers_frozen_spectrum(qapp, app_model):
    session, run_model, plot_data, parent_spec, entry_id, frame, _region = (
        _wired_image_scan_with_roi(app_model)
    )

    frozen = session.plot.commit_roi_profile(
        entry_id,
        parent_plot_data=plot_data,
        parent_spec=parent_spec,
        parent_frame=frame,
        parent_bundle=plot_data.last_bundle,
        axis_names=("en_energy", "pixel"),
    )

    assert is_synthetic_key(frozen.key)
    assert frozen.key in run_model.available_keys
    assert frozen.label == "test roi"


def test_committed_synthetic_key_fetchable_via_fetch_bundle(qapp, app_model):
    session, run_model, plot_data, parent_spec, entry_id, frame, _region = (
        _wired_image_scan_with_roi(app_model)
    )

    frozen = session.plot.commit_roi_profile(
        entry_id,
        parent_plot_data=plot_data,
        parent_spec=parent_spec,
        parent_frame=frame,
        parent_bundle=plot_data.last_bundle,
        axis_names=("en_energy", "pixel"),
    )

    bundle = session.fetch_bundle(["row"], [frozen.key], run=run_model)

    assert bundle.ndim == 1
    assert bundle.render_mode == "line"
    assert np.isfinite(bundle.y).any()


def test_preview_rejects_stale_roi_on_wired_session(qapp, app_model):
    session, _run_model, plot_data, parent_spec, entry_id, frame, _region = (
        _wired_image_scan_with_roi(app_model, stale=True)
    )

    with pytest.raises(ValueError, match="stale"):
        session.plot.preview_roi_profile(
            entry_id,
            parent_plot_data=plot_data,
            parent_spec=parent_spec,
            parent_frame=frame,
            parent_bundle=plot_data.last_bundle,
        )


def test_commit_rejects_local_profile_on_wired_session(qapp, app_model):
    session, _run_model, plot_data, parent_spec, entry_id, frame, _region = (
        _wired_image_scan_with_roi(app_model, profile_storage_axis=1)
    )

    with pytest.raises(ValueError, match="Select a profile along"):
        session.plot.commit_roi_profile(
            entry_id,
            parent_plot_data=plot_data,
            parent_spec=parent_spec,
            parent_frame=frame,
            parent_bundle=plot_data.last_bundle,
            axis_names=("en_energy", "pixel"),
        )
