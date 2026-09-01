"""Tests for PlotPresenter and DisplayManager (Step 6a/6b)."""

from nbs_viewer.models.plot.displayManager import DisplayManager, PlotPresenter
from nbs_viewer.models.plot.runListModel import RunListModel
from nbs_viewer.models.plot.plotModel import PlotModel
from nbs_viewer.models.app_model import AppModel
from nbs_viewer.models.sources.testSource import create_runs


def test_plot_presenter_owns_private_run_list_and_plot():
    presenter = PlotPresenter("sess", single_selection_mode=False)
    assert isinstance(presenter.run_list, RunListModel)
    assert isinstance(presenter.plot, PlotModel)
    assert presenter.plot.run_list_model is presenter.run_list
    assert presenter.run_list._single_selection_mode is False


def test_plot_presenter_single_selection_mode():
    presenter = PlotPresenter("grid", single_selection_mode=True)
    assert presenter.run_list._single_selection_mode is True


def test_display_manager_owns_presenters_without_registry():
    manager = DisplayManager()
    assert "main" in manager.get_display_ids()
    presenter = manager.get_presenter("main")
    assert manager.get_run_list_model("main") is presenter.run_list
    assert manager.get_plot_model("main") is presenter.plot


def test_register_presenter_with_explicit_single_selection():
    manager = DisplayManager()
    display_id = manager.register_display(
        "image_grid", single_selection_mode=True
    )
    presenter = manager.get_presenter(display_id)
    assert presenter.run_list._single_selection_mode is True
    assert manager.get_display_type(display_id) == "image_grid"


def test_create_display_with_runs_does_not_infer_from_type_name():
    manager = DisplayManager()
    runs = create_runs(runs=2)
    display_id = manager.create_display_with_runs(
        runs, "image_grid", single_selection_mode=False
    )
    assert manager.get_presenter(display_id).run_list._single_selection_mode is False
    assert len(manager.get_run_list_model(display_id).available_models) == 2


def test_catalog_selection_path_adds_run_without_canvas():
    manager = DisplayManager()
    runs = create_runs(runs=1)
    manager.add_run_to_display(runs[0], "main")
    presenter = manager.get_presenter("main")
    assert len(presenter.run_list.available_models) == 1
    assert presenter.plot is not None
    assert presenter.plot.roi_set is not None


def test_app_model_has_no_display_registry():
    app = AppModel()
    assert not hasattr(app, "display_registry")
    assert "main" in app.display_manager.get_display_ids()
    runs = create_runs(runs=1)
    app.display_manager.add_run_to_display(runs[0], "main")
    assert len(app.display_manager.get_presenter("main").run_list.available_models) == 1
