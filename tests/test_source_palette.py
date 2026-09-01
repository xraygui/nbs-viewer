"""Tests for source palette and catalog_loaded wiring (Step 5d)."""

from nbs_viewer.models.app_model import CatalogManagerModel, ConfigModel
from nbs_viewer.models.sources.testSource import TestSourceModel
from nbs_viewer.models.catalog.memory import MemoryCatalog


def _manager():
    return CatalogManagerModel(ConfigModel())


def test_source_load_emits_catalog_loaded_and_manager_registers(qapp):
    manager = _manager()
    source = manager.create_test_source(runs=3)
    manager.add_source("test", source)

    emitted = []
    source.catalog_loaded.connect(lambda c, label: emitted.append((c, label)))

    catalog, label = source.load()
    assert isinstance(catalog, MemoryCatalog)
    assert label == "Test Catalog"
    assert len(emitted) == 1
    assert manager.get_catalog_labels() == ["Test Catalog"]
    assert manager.get_catalog("Test Catalog") is catalog


def test_two_loads_from_one_source_unique_labels(qapp):
    manager = _manager()
    source = manager.create_test_source(runs=2)
    manager.add_source("test", source)

    source.load()
    source.load()

    labels = manager.get_catalog_labels()
    assert labels == ["Test Catalog", "Test Catalog (2)"]
    assert manager.get_catalog(labels[0]) is not manager.get_catalog(labels[1])


def test_ensure_interactive_palette_contains_defaults(qapp):
    manager = _manager()
    manager.ensure_interactive_palette()
    keys = [k for k, _ in manager.iter_palette()]
    assert keys == ["uri", "profile", "kafka", "zmq", "test"]
    assert isinstance(manager.get_palette_source("test"), TestSourceModel)


def test_load_and_register_headless_helper_no_double_register(qapp):
    manager = _manager()
    source = manager.create_test_source(runs=2)
    manager.add_source("test", source)

    label = manager.load_and_register(source, label="Solo")
    assert label == "Solo"
    assert manager.get_catalog_labels() == ["Solo"]


def test_catalog_added_and_removed_signals(qapp):
    manager = _manager()
    added = []
    removed = []
    manager.catalog_added.connect(lambda label, cat: added.append(label))
    manager.catalog_removed.connect(lambda label: removed.append(label))

    source = manager.create_test_source(runs=1)
    manager.add_source("test", source)
    source.load()

    assert added == ["Test Catalog"]
    manager.unregister_catalog("Test Catalog")
    assert removed == ["Test Catalog"]
    assert manager.get_catalog_labels() == []
