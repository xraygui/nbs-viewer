"""Integration tests for catalog → AppModel → presenter signal wiring."""

from __future__ import annotations

from nbs_viewer.models.catalog.memory import MemoryCatalog

from tests.fixtures.session import HeadlessSession


def test_source_load_registers_catalog_on_app_model(qapp, app_model):
    source = app_model.catalogs.create_test_source(runs=3)
    app_model.catalogs.add_source("test", source)

    catalog, label = source.load()

    assert isinstance(catalog, MemoryCatalog)
    assert label == "Test Catalog"
    assert app_model.catalogs.get_catalog_labels() == ["Test Catalog"]
    assert app_model.catalogs.get_catalog("Test Catalog") is catalog
    assert len(catalog) == 3


def test_load_and_register_on_app_catalogs(qapp, app_model):
    source = app_model.catalogs.create_test_source(runs=2)

    label = app_model.catalogs.load_and_register(source, label="Solo")

    assert label == "Solo"
    assert app_model.catalogs.get_catalog_labels() == ["Solo"]
    assert len(app_model.catalogs.get_catalog("Solo")) == 2


def test_multi_run_selection_accumulates_on_run_list(qapp, app_model):
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="line_scan", runs=3)

    session.select_run(0)
    session.select_run(1)
    session.select_run(2)

    assert len(session.catalog.get_selected_runs()) == 3
    assert len(session.session.collection.available_models) == 3
    run_list_uids = {model.uid for model in session.session.collection.available_models}
    selected_uids = {run.uid for run in session.catalog.get_selected_runs()}
    assert run_list_uids == selected_uids


def test_deselect_run_emits_catalog_and_manager_signals(qapp, app_model):
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="line_scan", runs=2)
    first = session.select_run(0)
    session.select_run(1)

    item_deselected = []
    manager_deselected = []
    session.catalog.item_deselected.connect(
        lambda run: item_deselected.append(run.uid)
    )
    app_model.catalogs.run_deselected.connect(
        lambda run: manager_deselected.append(run.uid)
    )

    session.catalog.deselect_run(first.uid)

    assert item_deselected == [first.uid]
    assert manager_deselected == [first.uid]
    assert len(session.catalog.get_selected_runs()) == 1
    assert first.uid not in {run.uid for run in session.catalog.get_selected_runs()}


def test_deselect_run_removes_run_from_presenter_run_list(qapp, app_model):
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="line_scan", runs=3)
    first = session.select_run(0)
    second = session.select_run(1)
    assert len(session.session.collection.available_models) == 2

    session.catalog.deselect_run(first.uid)

    remaining = {model.uid for model in session.session.collection.available_models}
    assert remaining == {second.uid}
    assert first.uid not in remaining


def test_source_load_then_select_wires_to_presenter(qapp, app_model):
    source = app_model.catalogs.create_test_source(runs=2)
    app_model.catalogs.add_source("test", source)
    _catalog, label = source.load()
    catalog = app_model.catalogs.get_catalog(label)
    run = catalog.get_runs()[0]

    catalog.select_run(run.uid)

    plot = app_model.display_manager.get_presenter("main").session
    assert len(plot.collection.available_models) == 1
    assert plot.collection.available_models[0].uid == run.uid
