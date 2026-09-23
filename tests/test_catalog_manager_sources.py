"""Tests for CatalogManagerModel source factories (Step 5b)."""

import pytest

from nbs_viewer.models.app_model import CatalogManagerModel, ConfigModel
from nbs_viewer.models.sources import testSource as test_source_mod
from nbs_viewer.models.sources.uriSource import URISourceModel
from nbs_viewer.models.sources.profileSource import ProfileSourceModel
from nbs_viewer.models.sources.kafkaSource import KafkaSourceModel
from nbs_viewer.models.sources.zmqSource import ZMQSourceModel
from nbs_viewer.models.sources.configSource import ConfigSourceModel
from nbs_viewer.models.catalog.memory import MemoryCatalog


def _manager():
    return CatalogManagerModel(ConfigModel())


def test_create_uri_source_type(qapp):
    model = _manager().create_uri_source()
    assert isinstance(model, URISourceModel)


def test_create_profile_source_type(qapp):
    model = _manager().create_profile_source()
    assert isinstance(model, ProfileSourceModel)


def test_create_kafka_source_type(qapp):
    model = _manager().create_kafka_source()
    assert isinstance(model, KafkaSourceModel)


def test_create_zmq_source_type(qapp):
    model = _manager().create_zmq_source()
    assert isinstance(model, ZMQSourceModel)


def test_create_test_source_and_load(qapp):
    manager = _manager()
    source = manager.create_test_source(runs=4)
    assert isinstance(source, test_source_mod.TestSourceModel)
    catalog, label = manager.load_catalog(source)
    assert isinstance(catalog, MemoryCatalog)
    assert len(catalog) == 4
    assert label == "Test Catalog"


def test_load_and_register_test_source(qapp):
    manager = _manager()
    source = manager.create_test_source(runs=3)
    label = manager.load_and_register(source)
    assert label in manager.get_catalog_labels()
    assert manager.get_current_catalog() is not None
    assert len(manager.get_current_catalog()) == 3


def test_create_from_config_uri_dispatch(qapp):
    manager = _manager()
    config = {
        "source_type": "uri",
        "label": "My URI",
        "url": "http://example.invalid:8000",
        "catalog_model": "BlueskyCatalog",
        "catalog_keys": ["a", "b"],
    }
    wrapped = manager.create_from_config(config)
    assert isinstance(wrapped, ConfigSourceModel)
    assert wrapped.get_display_label() == "My URI"
    assert isinstance(wrapped.source_model, URISourceModel)
    assert wrapped.source_model.uri == "http://example.invalid:8000"
    assert wrapped.source_model.selected_keys == ["a", "b"]


def test_create_from_config_unknown_type(qapp):
    manager = _manager()
    with pytest.raises(ValueError, match="Unknown source type"):
        manager.create_from_config({"source_type": "nope"})


def test_register_is_sole_registry(qapp):
    manager = _manager()
    source = manager.create_test_source(runs=2)
    manager.load_and_register(source, label="Solo")
    assert manager.get_catalog_labels() == ["Solo"]
    manager.unregister_catalog("Solo")
    assert manager.get_catalog_labels() == []
