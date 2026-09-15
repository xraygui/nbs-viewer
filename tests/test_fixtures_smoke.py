"""Smoke tests for shared headless fixtures."""

from __future__ import annotations

import numpy as np

from tests.fixtures.view import apply_projection
from nbs_viewer.models.plot.view.spec import DimRole, Projection

from nbs_viewer.models.plot.session import PlotSession
from nbs_viewer.models.plot.run.source import RunSource

from tests.fixtures.catalog_recipes import (
    RECIPE_NAMES,
    build_runs,
    image_scan_run,
)
from tests.fixtures.session import HeadlessSession


def test_catalog_recipes_line_scan_shapes():
    run = build_runs("line_scan", runs=1)[0]
    assert "time" in run.available_keys
    assert "y" in run.available_keys
    assert run.getShape("y") == (100,)


def test_headless_session_catalog_signal_path(headless_session):
    run_model = headless_session.select_run(0)
    assert run_model.uid == headless_session.catalog.get_runs()[0].uid
    assert len(headless_session.session.collection.available_models) == 1


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
    apply_projection(session.session.view_intent, spec)

    bundle = session.fetch_bundle(["en_energy"], ["detector_image"], run=run_model)
    assert bundle.y.ndim == 2
    assert bundle.y.shape == (30, 40)
    assert np.isfinite(bundle.y).all()


def test_every_recipe_carries_a_time_axis():
    """
    Every run has a time axis, even a one-point one.

    It is the event axis, and ``MemoryRun._resolve_dims`` derives dimension
    names from whether it is present: without a ``time`` array every 1-D key
    falls back to ``dim_0`` and an N-D detector to ``(dim_0, dim_1, ...)``,
    so unrelated axes collide by name. Normalization aligns a norm array to
    ``y`` by axis *name*, so a collision makes it divide by the wrong axis or
    raise. ``image_scan_run`` was the one recipe without it.
    """
    for recipe in RECIPE_NAMES:
        run = build_runs(recipe, runs=1)[0]
        assert "time" in run.available_keys, f"{recipe} offers no time key"
        assert run.getShape("time")[0] >= 1, f"{recipe} has an empty time axis"
        assert run.get_dims("time", [])[0] == ("time",)


def test_normalization_follows_the_axis_a_key_actually_names(qapp):
    """
    A per-event key divides down the rows; a per-channel key divides across.

    Alignment is by axis *name*, so this only works when a key's declared
    dimensions say which axis it lies along. Before ``image_scan_run`` had a
    time axis, ``row`` (length 6) and ``en_energy`` (length 8) both inferred
    ``dim_0`` -- which also named the detector's first axis -- so normalizing
    by ``en_energy`` tried to broadcast 8 values onto a 6-long axis and
    raised. Both directions are asserted because getting one right by
    accident is easy; getting both right requires the names to be real.
    """
    run = RunSource(image_scan_run(1, n_y=6, n_x=8, n_z=3))

    def plane(norm_keys):
        session = PlotSession(is_main_display=True)
        session.collection.add_runs([run])
        session.selection.set_selected_keys(
            ["en_energy"], ["detector_image"], norm_keys
        )
        session.view_intent.set_plot_ndim(2)
        trace = session.ensure_trace(
            run, "en_energy", "detector_image", norm_keys=norm_keys
        )
        return trace.get_plot_bundle().y

    def constants_along(divisor, axis):
        """Return the per-slice divisor, asserting it is constant on ``axis``."""
        moved = divisor if axis == 1 else divisor.T
        values = []
        for line in moved:
            finite = line[np.isfinite(line)]
            if finite.size:
                assert np.allclose(finite, finite[0]), "divisor is not constant"
                values.append(finite[0])
        return values

    # The recipe's row axis starts at 0.0, so one row divides by zero. That is
    # arithmetic, not misalignment, and the finite entries carry the check.
    with np.errstate(divide="ignore", invalid="ignore"):
        plain = plane([])
        by_row = plain / plane(["row"])
        by_channel = plain / plane(["en_energy"])

    assert plain.shape == (6, 8)

    # `row` is per event: constant across each row, varying down them.
    row_values = constants_along(by_row, axis=1)
    assert len(row_values) >= 2
    assert len(set(np.round(row_values, 9))) == len(row_values)

    # `en_energy` is per channel: constant down each column, varying across.
    channel_values = constants_along(by_channel, axis=0)
    assert len(channel_values) == 8
    assert len(set(np.round(channel_values, 9))) == 8
