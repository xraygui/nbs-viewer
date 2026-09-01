"""Tests for RoiSetModel ownership and stale marking."""

from nbs_viewer.models.plot.region import EllipseRegion, PolygonRegion, RectRegion
from nbs_viewer.models.plot.roi_set import RoiOperation, RoiSetModel


def test_add_select_and_update_region():
    model = RoiSetModel()
    region = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    entry_id = model.add(region, view_fingerprint=("a",))
    assert model.selected_id == entry_id
    assert model.selected_region() == region

    updated = RectRegion(x0=1.0, x1=2.0, y0=1.0, y1=2.0)
    model.update_region(entry_id, updated, view_fingerprint=("b",))
    entry = model.get(entry_id)
    assert entry.region == updated
    assert entry.view_fingerprint == ("b",)
    assert entry.stale is False


def test_set_or_replace_single_updates_existing():
    model = RoiSetModel()
    first = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    second = RectRegion(x0=2.0, x1=3.0, y0=2.0, y1=3.0)
    entry_id = model.set_or_replace_single(first, view_fingerprint=("a",))
    same_id = model.set_or_replace_single(second, view_fingerprint=("b",))
    assert same_id == entry_id
    assert len(model) == 1
    assert model.selected_region() == second


def test_mark_stale_for_fingerprint():
    model = RoiSetModel()
    model.add(RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0), view_fingerprint=("a",))
    newly = model.mark_stale_for_fingerprint(("b",))
    assert len(newly) == 1
    assert model.selected_entry().stale is True
    assert model.mark_stale_for_fingerprint(("b",)) == []


def test_remove_stale():
    model = RoiSetModel()
    fresh_id = model.add(
        RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0),
        view_fingerprint=("a",),
        select=False,
    )
    stale_id = model.add(
        RectRegion(x0=2.0, x1=3.0, y0=2.0, y1=3.0),
        view_fingerprint=("old",),
    )
    model.set_stale(stale_id, True)
    removed = model.remove_stale()
    assert removed == 1
    assert model.get(stale_id) is None
    assert model.get(fresh_id) is not None


def test_update_operation():
    model = RoiSetModel()
    entry_id = model.add(RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0))
    op = RoiOperation(mask_mode="outside", spatial_reduce="mean", label="band")
    model.update_operation(entry_id, op)
    assert model.get(entry_id).operation == op


def test_add_placeholder_rect_has_no_area():
    model = RoiSetModel()
    entry_id = model.add_placeholder_rect()
    entry = model.get(entry_id)
    assert entry is not None
    assert not model.entry_is_drawable(entry)
    assert model.selected_id == entry_id


def test_add_placeholder_ellipse_and_polygon():
    model = RoiSetModel()
    ellipse_id = model.add_placeholder("ellipse")
    polygon_id = model.add_placeholder("polygon")
    assert isinstance(model.get(ellipse_id).region, EllipseRegion)
    assert isinstance(model.get(polygon_id).region, PolygonRegion)
    assert not model.entry_is_drawable(model.get(ellipse_id))
    assert not model.entry_is_drawable(model.get(polygon_id))
