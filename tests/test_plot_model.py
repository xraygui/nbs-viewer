"""Tests for PlotSession ownership of RoiSetModel."""

from nbs_viewer.models.plot.plot_session import PlotSession
from nbs_viewer.models.plot.geometry.region import RectRegion
from nbs_viewer.models.plot.view_spec import ViewCrop
from tests.fixtures.plot_session import make_plot_session


def test_plot_model_exposes_roi_set():
    plot_model, run_list = make_plot_session()
    assert plot_model.region.roi_set is not None


def test_two_plot_models_get_distinct_roi_sets():
    first, _ = make_plot_session()
    second, _ = make_plot_session()
    assert first.region.roi_set is not second.region.roi_set


def test_roi_set_add_via_plot_model():
    plot_model = PlotSession()
    region = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    entry_id = plot_model.region.roi_set.add(region, view_fingerprint=("a",))
    assert plot_model.region.roi_set.selected_id == entry_id
    assert plot_model.region.roi_set.selected_region() == region


def test_sync_region_state_with_view_marks_mismatched_roi_stale(qapp):
    plot_model = PlotSession()
    region = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    entry_id = plot_model.region.roi_set.add(region, view_fingerprint=("a",))
    statuses = []
    plot_model.region.region_status_changed.connect(statuses.append)

    plot_model.region.sync_region_state_with_view()

    assert plot_model.region.roi_set.get(entry_id).stale
    assert statuses == ["ROI marked stale: view coordinates changed"]


def test_invalidate_all_region_state_clears_crop_and_marks_rois_stale(qapp):
    plot_model = PlotSession()
    region = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    entry_id = plot_model.region.roi_set.add(region, view_fingerprint=("a",))
    crop = ViewCrop(storage_bbox=(0, 2, 0, 3), plot_y_axis=0, plot_x_axis=1)
    plot_model.region.set_view_crop(crop, ("x", "y", "uid"))

    invalidated = []
    statuses = []
    plot_model.region.region_invalidation_requested.connect(invalidated.append)
    plot_model.region.region_status_changed.connect(statuses.append)

    plot_model.region.invalidate_all_region_state("field selection changed")

    assert plot_model.region.view_crop is None
    assert plot_model.region.roi_set.get(entry_id).stale
    assert invalidated == ["field selection changed"]
    assert statuses == [
        "Crop cleared: field selection changed",
        "ROI marked stale: field selection changed",
    ]
