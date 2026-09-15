"""Integration tests for run-list factories on catalog-wired runs."""

from __future__ import annotations

import numpy as np

from nbs_viewer.models.data.combined import (
    CombinationMethod,
    CombinedRun,
)
from nbs_viewer.models.plot.view.spec import DimRole, Projection
from nbs_viewer.models.data.frozen import FrozenRun
from nbs_viewer.models.plot.run.frozen_spectrum import (
    FrozenSpectrum,
    SYNTHETIC_KEY_PREFIX,
)
from nbs_viewer.models.plot.geometry.bundle import prepare_1d_bundle
from nbs_viewer.models.plot.fetch.request import PlotRequest
from nbs_viewer.models.plot.geometry.region import RectRegion

from tests.fixtures.session import HeadlessSession


def _select_catalog_runs(session: HeadlessSession, indices: tuple[int, ...]):
    """
    Select catalog runs through the AppModel signal path.

    Parameters
    ----------
    session : HeadlessSession
        Active headless session with a loaded catalog.
    indices : tuple of int
        Catalog run indices to select.

    Returns
    -------
    list of RunSource
        Run models present on the presenter run list.
    """
    models = []
    for index in indices:
        models.append(session.select_run(index))
    return models


def _frozen_stack_entry(run_model, *, key_suffix: str = "wired") -> FrozenSpectrum:
    bundle = prepare_1d_bundle(
        np.array([1.0, 2.0, 3.0], dtype=float),
        [np.array([0.0, 1.0, 2.0], dtype=float)],
        ["profile"]
)
    return FrozenSpectrum(
        key=f"{SYNTHETIC_KEY_PREFIX}{key_suffix}",
        label="mean(in ROI) · en_energy",
        bundle=bundle,
        kind="stack_spectrum",
        source_ykey="detector_image",
        committed_xkey="en_energy",
        request=PlotRequest(
            uid=run_model.uid,
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
        source_key=("en_energy", "detector_image", run_model.uid)
)


def test_combine_runs_on_catalog_selected_runs(qapp, app_model):
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="line_scan", runs=3)
    first, second = _select_catalog_runs(session, (0, 1))
    before = len(session.session.collection.available_models)

    combined = session.session.collection.combine(
        [first, second],
        method=CombinationMethod.SUM
)

    assert isinstance(combined.run, CombinedRun)
    assert combined in session.session.collection.available_models
    assert len(session.session.collection.available_models) == before + 1
    assert combined.run.combination_method == CombinationMethod.SUM
    assert combined.run.source_runs == [first.run, second.run]

    bundle = session.fetch_bundle(["time"], ["y"], run=combined)
    assert bundle.y.shape == (100,
)
    assert np.isfinite(bundle.y).all()


def test_freeze_runs_on_catalog_selected_runs(qapp, app_model):
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="line_scan", runs=3)
    first, second = _select_catalog_runs(session, (0, 1))
    session.session.selection.set_selection_for(first.uid, ["time"], ["y"])
    session.session.selection.set_selection_for(second.uid, ["time"], ["y"])
    before = len(session.session.collection.available_models)

    frozen = session.session.freeze_runs([first, second])

    assert len(frozen) == 2
    assert all(isinstance(item.run, FrozenRun) for item in frozen)
    assert len(session.session.collection.available_models) == before + 2
    assert {item.display_name for item in frozen} == {"y of 0", "y of 1"}

    for item in frozen:
        bundle = session.fetch_bundle(["time"], ["y"], run=item)
        assert bundle.y.shape == (100,
)


def test_frozen_spectra_changed_refreshes_run_list(qapp, app_model):
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="image_scan", runs=1)
    run_model = session.select_run(0)

    run_list_signals = []
    session.session.frozen_spectra_changed.connect(
        lambda: run_list_signals.append(True)
    )

    entry = _frozen_stack_entry(run_model)
    run_model.register_frozen_spectrum(entry)

    assert run_list_signals == [True]
    display_entries = session.session.collection.synthetic_display_entries()
    assert any(model is run_model and key == entry.key for model, key, _ in display_entries)
