"""Tests for headless ROI preview and commit APIs (Step 4)."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from nbs_viewer.models.plot.cube_view import CubeViewSpec, DimRole
from nbs_viewer.models.plot.frozen_spectrum import is_synthetic_key
from nbs_viewer.models.plot.plot_view_frame import frame_from_bundle
from nbs_viewer.models.plot.plotModel import PlotModel
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.roi_set import RoiOperation
from nbs_viewer.models.plot.runListModel import RunListModel
from nbs_viewer.models.plot.runModel import RunModel
from tests.fixtures.catalog_recipes import image_scan_run


def _setup_plot_with_roi(*, profile_storage_axis=0, stale=False):
    run_list = RunListModel()
    plot_model = PlotModel(run_list)
    run_model = RunModel(image_scan_run(1))
    run_list.add_run(run_model)

    parent_spec = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    plot_model.set_view_state(dimension=2, cube_view_spec=parent_spec)
    plot_model.set_selected_keys(["en_energy"], ["detector_image"])

    plot_data = plot_model.ensure_plot_data(
        run_model, "en_energy", "detector_image"
    )
    bundle = plot_data.get_plot_bundle(cube_view_spec=parent_spec)
    plot_data._visible = True

    frame = frame_from_bundle(bundle)
    from nbs_viewer.models.plot.region_mesh import (
        _cell_x_bounds_mesh,
        _cell_y_bounds_mesh,
    )

    x0, _ = _cell_x_bounds_mesh(frame, 5, 0)
    _, x1 = _cell_x_bounds_mesh(frame, 35, 0)
    y0, _ = _cell_y_bounds_mesh(frame, 2, 0)
    _, y1 = _cell_y_bounds_mesh(frame, 28, 0)
    region = RectRegion(x0=x0, x1=x1, y0=y0, y1=y1)
    entry_id = plot_model.roi_set.add(
        region,
        operation=RoiOperation(
            profile_storage_axis=profile_storage_axis,
            spatial_reduce="sum",
            span_full_profile_axis=True,
            label="test roi",
        ),
    )
    if stale:
        plot_model.roi_set.set_stale(entry_id, True)

    return plot_model, plot_data, parent_spec, entry_id, frame, region


def test_preview_roi_profile_returns_1d_bundle(qapp):
    plot_model, plot_data, parent_spec, entry_id, frame, _region = (
        _setup_plot_with_roi()
    )

    bundle = plot_model.preview_roi_profile(
        entry_id,
        parent_plot_data=plot_data,
        parent_spec=parent_spec,
        parent_frame=frame,
        parent_bundle=plot_data.last_bundle,
    )

    assert bundle.ndim == 1
    assert bundle.render_mode == "line"
    assert np.isfinite(bundle.y).any()


def test_commit_roi_profile_registers_synthetic_keys(qapp):
    plot_model, plot_data, parent_spec, entry_id, frame, region = (
        _setup_plot_with_roi()
    )
    run_model = plot_data._run

    first = plot_model.commit_roi_profile(
        entry_id,
        parent_plot_data=plot_data,
        parent_spec=parent_spec,
        parent_frame=frame,
        parent_bundle=plot_data.last_bundle,
        axis_names=("en_energy", "pixel"),
    )
    second_id = plot_model.roi_set.add(
        RectRegion(
            x0=region.x0 + 1.0,
            x1=region.x1 + 1.0,
            y0=region.y0 + 1.0,
            y1=region.y1 + 1.0,
        ),
        operation=RoiOperation(
            profile_storage_axis=0,
            spatial_reduce="sum",
            span_full_profile_axis=False,
            label="second roi",
        ),
    )
    second = plot_model.commit_roi_profile(
        second_id,
        parent_plot_data=plot_data,
        parent_spec=parent_spec,
        parent_frame=frame,
        parent_bundle=plot_data.last_bundle,
        axis_names=("en_energy", "pixel"),
    )

    assert is_synthetic_key(first.key)
    assert is_synthetic_key(second.key)
    assert first.key != second.key
    assert first.key in run_model.available_keys
    assert second.key in run_model.available_keys
    assert first.label == "test roi"
    assert second.label == "second roi"


def test_preview_rejects_stale_roi(qapp):
    plot_model, plot_data, parent_spec, entry_id, frame, _region = (
        _setup_plot_with_roi(stale=True)
    )

    with pytest.raises(ValueError, match="stale"):
        plot_model.preview_roi_profile(
            entry_id,
            parent_plot_data=plot_data,
            parent_spec=parent_spec,
            parent_frame=frame,
            parent_bundle=plot_data.last_bundle,
        )


def test_commit_rejects_local_profile(qapp):
    plot_model, plot_data, parent_spec, entry_id, frame, _region = (
        _setup_plot_with_roi(profile_storage_axis=1)
    )

    with pytest.raises(ValueError, match="Select a profile along"):
        plot_model.commit_roi_profile(
            entry_id,
            parent_plot_data=plot_data,
            parent_spec=parent_spec,
            parent_frame=frame,
            parent_bundle=plot_data.last_bundle,
            axis_names=("en_energy", "pixel"),
        )


def test_no_frozen_spectrum_construction_in_views():
    root = Path(__file__).resolve().parents[1] / "nbs_viewer" / "views"
    hits = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id == "FrozenSpectrum":
                hits.append(str(path.relative_to(root.parent)))
            elif isinstance(func, ast.Attribute) and func.attr == "FrozenSpectrum":
                hits.append(str(path.relative_to(root.parent)))
    assert hits == []
