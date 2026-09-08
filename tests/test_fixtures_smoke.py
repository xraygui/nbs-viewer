"""Smoke tests for shared headless fixtures."""

from __future__ import annotations

import numpy as np

from nbs_viewer.models.plot.view_spec import (
    DimRole,
    Projection,
)

from tests.fixtures.catalog_recipes import build_runs
from tests.fixtures.session import HeadlessSession


def test_catalog_recipes_line_scan_shapes():
    run = build_runs("line_scan", runs=1)[0]
    assert "time" in run.available_keys
    assert "y" in run.available_keys
    assert run.getShape("y") == (100,)


def test_headless_session_catalog_signal_path(headless_session):
    run_model = headless_session.select_run(0)
    assert run_model.uid == headless_session.catalog.get_runs()[0].uid
    assert len(headless_session.session.available_models) == 1


def test_headless_session_line_scan_fetch(headless_session):
    headless_session.select_run(0)
    bundle = headless_session.fetch_bundle(["time"], ["y"])
    assert bundle.y.ndim == 1
    assert bundle.y.shape == (100,)


def test_image_scan_get_plot_bundle_without_injected_bundle(app_model):
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="image_scan", runs=1)
    run_model = session.select_run(0)

    spec = Projection(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    session.session.set_view_state(dimension=2, cube_view_spec=spec)

    bundle = session.fetch_bundle(["en_energy"], ["detector_image"], run=run_model)
    assert bundle.y.ndim == 2
    assert bundle.y.shape == (30, 40)
    assert np.isfinite(bundle.y).all()
