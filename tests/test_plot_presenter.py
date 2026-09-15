"""Tests for PlotPresenter and DisplayManager (Step 6a/6b)."""

from nbs_viewer.models.displays.manager import DisplayManager, PlotPresenter
from nbs_viewer.views.dataSource.run_list_item_model import RunListItemModel
from nbs_viewer.models.plot.session import PlotSession
from nbs_viewer.models.sources.testSource import create_runs


def test_plot_presenter_owns_session_not_the_item_model(qapp):
    presenter = PlotPresenter("sess", single_selection_mode=False)
    assert isinstance(presenter.session, PlotSession)
    assert presenter.session.collection.single_selection_mode is False
    # The sidebar item model is a view adapter; RunListView builds it.
    assert not hasattr(presenter, "run_list")


def test_plot_presenter_single_selection_mode(qapp):
    presenter = PlotPresenter("grid", single_selection_mode=True)
    assert presenter.session.collection.single_selection_mode is True


def test_display_manager_owns_presenters_without_registry(qapp):
    manager = DisplayManager()
    assert "main" in manager.get_display_ids()
    presenter = manager.get_presenter("main")
    assert manager.get_session("main") is presenter.session
    assert not hasattr(manager, "get_run_list_model")


def test_register_presenter_with_explicit_single_selection(qapp):
    manager = DisplayManager()
    display_id = manager.register_display(
        "image_grid", single_selection_mode=True
    )
    presenter = manager.get_presenter(display_id)
    assert presenter.session.collection.single_selection_mode is True
    assert manager.get_display_type(display_id) == "image_grid"


def test_create_display_with_runs_does_not_infer_from_type_name(qapp):
    manager = DisplayManager()
    runs = create_runs(runs=2)
    display_id = manager.create_display_with_runs(
        runs, "image_grid", single_selection_mode=False
    )
    assert manager.get_presenter(display_id).session.collection.single_selection_mode is False
    item_model = RunListItemModel(manager.get_session(display_id).collection)
    assert item_model.rowCount() == 2
    presenter = manager.get_presenter(display_id)
    assert len(presenter.session.collection.available_models) == 2


def test_catalog_selection_path_adds_run_without_canvas(qapp):
    manager = DisplayManager()
    runs = create_runs(runs=1)
    manager.add_run_to_display(runs[0], "main")
    presenter = manager.get_presenter("main")
    assert len(presenter.session.collection.available_models) == 1
    assert presenter.session is not None
    assert presenter.session.region.roi_set is not None
    assert presenter.session is presenter.session


def test_app_model_has_no_display_registry(app_model):
    assert not hasattr(app_model, "display_registry")
    assert "main" in app_model.display_manager.get_display_ids()
    runs = create_runs(runs=1)
    app_model.display_manager.add_run_to_display(runs[0], "main")
    presenter = app_model.display_manager.get_presenter("main")
    assert len(presenter.session.collection.available_models) == 1
