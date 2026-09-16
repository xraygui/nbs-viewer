"""Tests for headless ROI preview and commit APIs (Step 4)."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from tests.fixtures.view import apply_projection
from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.plane.roles import DimRole
from nbs_viewer.models.plot.spec.projection import Projection
from nbs_viewer.models.plot.spec.region import RectRegion
from nbs_viewer.models.plot.roi import RoiOperation
from nbs_viewer.models.plot.run.source import RunSource
from tests.fixtures.catalog_recipes import image_scan_run
from tests.fixtures.plot_session import make_plot_session


def _setup_plot_with_roi(*, profile_storage_axis=0, stale=False):
    plot_model, _ = make_plot_session()
    run_model = RunSource(image_scan_run(1))
    plot_model.collection.add_runs([run_model])

    parent_spec = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0)
)
    apply_projection(plot_model.view_intent, parent_spec)
    plot_model.selection.set_selected_keys(["en_energy"], ["detector_image"])

    plot_data = plot_model.ensure_trace(
        run_model, "en_energy", "detector_image",
    )
    bundle = plot_data.get_plot_bundle()

    frame = bundle.view_frame()
    x0, _ = frame.cell_x_bounds(5, 0)
    _, x1 = frame.cell_x_bounds(35, 0)
    y0, _ = frame.cell_y_bounds(2, 0)
    _, y1 = frame.cell_y_bounds(28, 0)
    region = RectRegion(x0=x0, x1=x1, y0=y0, y1=y1)
    entry_id = plot_model.region.roi_set.add(
        region,
        operation=RoiOperation(
            profile_storage_axis=profile_storage_axis,
            spatial_reduce="sum",
            span_full_profile_axis=True,
            label="test roi"
)
)
    if stale:
        plot_model.region.roi_set.set_stale(entry_id, True)

    return plot_model, plot_data, entry_id, frame, region


def test_preview_roi_profile_returns_1d_bundle(qapp):
    plot_model, plot_data, entry_id, frame, _region = _setup_plot_with_roi()

    bundle = plot_model.region.preview_roi_profile(
        entry_id,
        parent_trace=plot_data,
        parent_frame=frame,
        cached_plane=plot_data.last_bundle
)

    assert bundle.ndim == 1
    assert bundle.render_mode == "line"
    assert np.isfinite(bundle.y).any()


def test_commit_roi_profile_registers_synthetic_keys(qapp):
    plot_model, plot_data, entry_id, frame, region = _setup_plot_with_roi()
    run_model = plot_data.run

    first = plot_model.region.commit_roi_profile(
        entry_id,
        parent_trace=plot_data,
        parent_frame=frame,
        cached_plane=plot_data.last_bundle,
        axis_names=("en_energy", "pixel")
)
    second_id = plot_model.region.roi_set.add(
        RectRegion(
            x0=region.x0 + 1.0,
            x1=region.x1 + 1.0,
            y0=region.y0 + 1.0,
            y1=region.y1 + 1.0
),
        operation=RoiOperation(
            profile_storage_axis=0,
            spatial_reduce="sum",
            span_full_profile_axis=False,
            label="second roi"
)
)
    second = plot_model.region.commit_roi_profile(
        second_id,
        parent_trace=plot_data,
        parent_frame=frame,
        cached_plane=plot_data.last_bundle,
        axis_names=("en_energy", "pixel")
)

    assert run_model.is_synthetic_key(first.key)
    assert run_model.is_synthetic_key(second.key)
    assert first.key != second.key
    assert first.key in run_model.available_keys
    assert second.key in run_model.available_keys
    assert first.label == "test roi"
    assert second.label == "second roi"


def test_preview_rejects_stale_roi(qapp):
    plot_model, plot_data, entry_id, frame, _region = _setup_plot_with_roi(
        stale=True
    )

    with pytest.raises(ValueError, match="stale"):
        plot_model.region.preview_roi_profile(
            entry_id,
            parent_trace=plot_data,
            parent_frame=frame,
            cached_plane=plot_data.last_bundle
)


def test_commit_rejects_local_profile(qapp):
    plot_model, plot_data, entry_id, frame, _region = _setup_plot_with_roi(
        profile_storage_axis=1
    )

    with pytest.raises(ValueError, match="Select a profile along"):
        plot_model.region.commit_roi_profile(
            entry_id,
            parent_trace=plot_data,
            parent_frame=frame,
            cached_plane=plot_data.last_bundle,
            axis_names=("en_energy", "pixel")
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


def test_nd_roi_preview_masks_the_display_plane(qapp):
    """
    An ROI profile along an off-plane axis loads beyond the drawn plane, so it
    reduces raw storage rather than the cached bundle. That path applied the
    display-order mask to a storage-order array; three of the four axis
    orientations came back wrong.

    The ROI is a triangle on purpose: a rectangle fills its own bounding box,
    so its mask is unchanged by the row reversal and cannot detect this.
    """
    from nbs_viewer.models.plot.spec.region import PolygonRegion, compile_with_mask_mode
    from nbs_viewer.models.sources.fixtures import make_vppem_run, vppem_factors

    plot_model, _ = make_plot_session()
    run_model = RunSource(make_vppem_run())
    plot_model.collection.add_runs([run_model])

    parent_spec = ViewIntent(plot_ndim=2).project(3).with_index(0, 4)
    apply_projection(plot_model.view_intent, parent_spec)
    plot_model.selection.set_selected_keys(["sampleVoltage_VSource"], ["PCOEdge_image"])
    plot_data = plot_model.ensure_trace(
        run_model, "sampleVoltage_VSource", "PCOEdge_image"
    )
    bundle = plot_data.get_plot_bundle()
    frame = bundle.view_frame()
    assert frame.row_reversed

    roi = PolygonRegion(vertices=((1.0, 1.0), (20.0, 1.0), (1.0, 16.0)))
    entry_id = plot_model.region.roi_set.add(
        roi,
        operation=RoiOperation(
            profile_storage_axis=0,
            spatial_reduce="sum",
            label="triangle"
)
)

    profile = plot_model.region.preview_roi_profile(entry_id)

    a, b, c = vppem_factors()
    mask = compile_with_mask_mode(frame, roi, "inside").mask
    expected = a * float(np.outer(b, c)[::-1, :][mask].sum())

    assert profile.ndim == 1
    np.testing.assert_allclose(profile.y, expected, rtol=1e-9)
