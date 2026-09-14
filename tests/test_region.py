"""Tests for region definitions and reduction."""

import numpy as np
import pytest

from nbs_viewer.models.plot.geometry.bundle import prepare_2d_bundle
from nbs_viewer.models.plot.geometry.frame import frame_from_bundle
from nbs_viewer.models.plot.geometry.region import (
    EllipseRegion,
    PolygonRegion,
    RectRegion,
    expand_region_for_profile,
    reduce_masked_plane,
    region_from_dict,
)


def test_reduce_masked_plane_sum():
    y = np.array([[1.0, 2.0], [3.0, 4.0]])
    bundle = prepare_2d_bundle(y, [np.arange(2.0), np.arange(2.0)], ["a", "b"])
    frame = frame_from_bundle(bundle)
    region = RectRegion(x0=-0.5, x1=1.5, y0=-0.5, y1=1.5)
    compiled = region.compile(frame)
    value = reduce_masked_plane(bundle.y, compiled, "sum")
    assert value == pytest.approx(10.0)


def test_rect_region_normalizes_corners():
    region = RectRegion(x0=5.0, x1=1.0, y0=4.0, y1=2.0).normalized()
    assert region.x0 == 1.0
    assert region.x1 == 5.0
    assert region.y0 == 2.0
    assert region.y1 == 4.0


def test_expand_region_for_profile_spans_profile_axis():
    y = np.ones((4, 6))
    bundle = prepare_2d_bundle(
        y, [np.linspace(0.0, 3.0, 4), np.linspace(0.0, 5.0, 6)], ["a", "b"]
    )
    frame = frame_from_bundle(bundle)
    narrow = RectRegion(x0=1.0, x1=2.0, y0=1.0, y1=2.0)
    along_x = expand_region_for_profile(frame, narrow, "plot_x")
    assert along_x.y0 == pytest.approx(1.0)
    assert along_x.y1 == pytest.approx(2.0)
    assert along_x.x0 == pytest.approx(-0.5)
    assert along_x.x1 == pytest.approx(5.5)
    along_y = expand_region_for_profile(frame, narrow, "plot_y")
    assert along_y.x0 == pytest.approx(1.0)
    assert along_y.x1 == pytest.approx(2.0)
    assert along_y.y0 == pytest.approx(-0.5)
    assert along_y.y1 == pytest.approx(3.5)


def test_rect_region_dict_round_trip():
    region = RectRegion(x0=1.0, x1=2.0, y0=3.0, y1=4.0)
    restored = region_from_dict(region.to_dict())
    assert isinstance(restored, RectRegion)
    assert restored == region


def test_subcell_rect_selects_centroid_cell():
    y = np.zeros((4, 4))
    bundle = prepare_2d_bundle(
        y,
        [np.arange(4.0), np.arange(4.0)],
        ["a", "b"],
        render_mode_hint="image",
    )
    frame = frame_from_bundle(bundle)
    tiny = RectRegion(x0=1.4, x1=1.45, y0=2.4, y1=2.45)
    compiled = tiny.compile(frame)
    assert compiled.pixel_count == 1


def _image_frame(ny=8, nx=8):
    y = np.zeros((ny, nx))
    bundle = prepare_2d_bundle(
        y,
        [np.arange(float(ny)), np.arange(float(nx))],
        ["a", "b"],
        render_mode_hint="image",
    )
    return frame_from_bundle(bundle)


def test_ellipse_region_compile_image():
    frame = _image_frame()
    region = EllipseRegion(cx=3.5, cy=3.5, rx=2.0, ry=1.5, angle=0.0)
    compiled = region.compile(frame)
    assert compiled.pixel_count > 0
    assert compiled.pixel_count < compiled.mask.size
    assert not region.separable_for_profile
    assert expand_region_for_profile(frame, region, "plot_x") is region


def test_ellipse_circle_and_dict_round_trip():
    region = EllipseRegion(cx=1.0, cy=2.0, rx=3.0, ry=3.0, angle=15.0)
    restored = region_from_dict(region.to_dict())
    assert isinstance(restored, EllipseRegion)
    assert restored == region
    assert "Circle" in region.describe()


def test_ellipse_rotated_bounds():
    region = EllipseRegion(cx=0.0, cy=0.0, rx=2.0, ry=1.0, angle=90.0)
    x0, x1, y0, y1 = region.data_bounds()
    assert x0 == pytest.approx(-1.0)
    assert x1 == pytest.approx(1.0)
    assert y0 == pytest.approx(-2.0)
    assert y1 == pytest.approx(2.0)


def test_polygon_region_compile_image():
    frame = _image_frame()
    region = PolygonRegion(
        vertices=((1.0, 1.0), (6.0, 1.0), (6.0, 5.0), (2.0, 5.0))
    )
    compiled = region.compile(frame)
    assert compiled.pixel_count > 0
    assert compiled.pixel_count < compiled.mask.size
    restored = region_from_dict(region.to_dict())
    assert isinstance(restored, PolygonRegion)
    assert restored.vertices == region.vertices


def test_polygon_empty_has_no_area():
    region = PolygonRegion(vertices=())
    assert not region.has_area()
    frame = _image_frame()
    assert region.compile(frame).pixel_count == 0


def test_subcell_ellipse_selects_centroid_cell():
    frame = _image_frame(4, 4)
    tiny = EllipseRegion(cx=1.5, cy=2.5, rx=0.01, ry=0.01)
    compiled = tiny.compile(frame)
    assert compiled.pixel_count == 1
