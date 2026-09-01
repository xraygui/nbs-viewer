"""Tests for PlotModel ownership of RoiSetModel."""

from unittest.mock import MagicMock

from nbs_viewer.models.plot.plotModel import PlotModel
from nbs_viewer.models.plot.region import RectRegion
from nbs_viewer.models.plot.runListModel import RunListModel
from nbs_viewer.models.plot.view_crop import ViewCrop


def test_plot_model_exposes_roi_set():
    run_list = RunListModel()
    plot_model = PlotModel(run_list)
    assert plot_model.roi_set is not None
    assert plot_model.run_list_model is run_list


def test_two_plot_models_get_distinct_roi_sets():
    run_list = RunListModel()
    first = PlotModel(run_list)
    second = PlotModel(run_list)
    assert first.roi_set is not second.roi_set


def test_roi_set_add_via_plot_model():
    plot_model = PlotModel(RunListModel())
    region = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    entry_id = plot_model.roi_set.add(region, view_fingerprint=("a",))
    assert plot_model.roi_set.selected_id == entry_id
    assert plot_model.roi_set.selected_region() == region


def test_sync_region_state_with_view_marks_mismatched_roi_stale(qapp):
    plot_model = PlotModel(RunListModel())
    region = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    entry_id = plot_model.roi_set.add(region, view_fingerprint=("a",))
    statuses = []
    plot_model.region_status_changed.connect(statuses.append)

    plot_model.sync_region_state_with_view()

    assert plot_model.roi_set.get(entry_id).stale
    assert statuses == ["ROI marked stale: view coordinates changed"]


def test_invalidate_all_region_state_clears_crop_and_marks_rois_stale(qapp):
    plot_model = PlotModel(RunListModel())
    region = RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0)
    entry_id = plot_model.roi_set.add(region, view_fingerprint=("a",))
    crop = MagicMock(spec=ViewCrop)
    plot_model.set_view_crop(crop)

    invalidated = []
    statuses = []
    plot_model.region_invalidation_requested.connect(invalidated.append)
    plot_model.region_status_changed.connect(statuses.append)

    plot_model.invalidate_all_region_state("field selection changed")

    assert plot_model.view_crop is None
    assert plot_model.roi_set.get(entry_id).stale
    assert invalidated == ["field selection changed"]
    assert statuses == [
        "Crop cleared: field selection changed",
        "ROI marked stale: field selection changed",
    ]
