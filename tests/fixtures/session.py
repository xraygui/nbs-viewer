"""Headless AppModel session helper for integration tests."""

from __future__ import annotations

from typing import List, Optional, Sequence

from nbs_viewer.models.app_model import AppModel
from nbs_viewer.models.catalog.memory import MemoryCatalog
from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.plot_geometry import PlotBundle
from nbs_viewer.models.plot.plotModel import PlotModel
from nbs_viewer.models.plot.presenter import PlotPresenter
from nbs_viewer.models.plot.runListModel import RunListModel
from nbs_viewer.models.plot.runModel import RunModel

from .catalog_recipes import build_catalog


class HeadlessSession:
    """
    Thin wrapper around :class:`AppModel` for headless test flows.

    Parameters
    ----------
    app : AppModel
        Application root model.
    display_id : str, optional
        Presenter / display id to bind. Defaults to ``"main"``.
    """

    def __init__(self, app: AppModel, *, display_id: str = "main"):
        self.app = app
        self.display_id = display_id
        self._catalog: Optional[MemoryCatalog] = None
        self._catalog_label: Optional[str] = None

    @property
    def presenter(self) -> PlotPresenter:
        """Plot presenter for :attr:`display_id`."""
        return self.app.display_manager.get_presenter(self.display_id)

    @property
    def plot(self) -> PlotModel:
        """Plot session model for the bound presenter."""
        return self.presenter.plot

    @property
    def run_list(self) -> RunListModel:
        """Run list for the bound presenter."""
        return self.presenter.run_list

    @property
    def catalog(self) -> MemoryCatalog:
        """
        Currently loaded catalog.

        Raises
        ------
        RuntimeError
            If no catalog has been loaded yet.
        """
        if self._catalog is None:
            raise RuntimeError("No catalog loaded; call load_catalog() first")
        return self._catalog

    @property
    def catalog_label(self) -> str:
        """
        Registry label for the loaded catalog.

        Raises
        ------
        RuntimeError
            If no catalog has been loaded yet.
        """
        if self._catalog_label is None:
            raise RuntimeError("No catalog loaded; call load_catalog() first")
        return self._catalog_label

    def load_catalog(
        self,
        recipe: str = "line_scan",
        *,
        runs: int = 3,
        label: str = "Test Catalog",
    ) -> str:
        """
        Register a synthetic in-memory catalog on the app model.

        Parameters
        ----------
        recipe : str, optional
            Catalog recipe name.
        runs : int, optional
            Number of runs in the catalog.
        label : str, optional
            Registry label.

        Returns
        -------
        str
            Label used in :class:`CatalogManagerModel`.
        """
        catalog = build_catalog(recipe, runs=runs)
        registered = self.app.catalogs.register_catalog(label, catalog)
        self._catalog = catalog
        self._catalog_label = registered
        return registered

    def select_run(self, index: int = 0) -> RunModel:
        """
        Select a catalog run and route it through the app signal path.

        Parameters
        ----------
        index : int, optional
            Index into the visible catalog run list.

        Returns
        -------
        RunModel
            Run model added to the presenter run list.
        """
        runs = self.catalog.get_runs()
        if not runs:
            raise IndexError("catalog has no runs")
        if index < 0 or index >= len(runs):
            raise IndexError(f"run index {index} out of range for {len(runs)} runs")
        catalog_run = runs[index]
        self.catalog.select_run(catalog_run.uid)
        return self._run_model_for_uid(catalog_run.uid)

    def add_run_direct(self, run: MemoryRun) -> RunModel:
        """
        Add a run to the presenter without going through catalog selection.

        Parameters
        ----------
        run : MemoryRun
            Run to add.

        Returns
        -------
        RunModel
            Wrapper stored on the run list.
        """
        self.presenter.add_run(run)
        return self._run_model_for_uid(run.uid)

    def fetch_bundle(
        self,
        x_keys: Sequence[str],
        y_keys: Sequence[str],
        *,
        run: Optional[RunModel] = None,
        norm_keys: Optional[Sequence[str]] = None,
    ) -> PlotBundle:
        """
        Select keys on the plot model and fetch a bundle for a run.

        Parameters
        ----------
        x_keys : sequence of str
            X axis keys.
        y_keys : sequence of str
            Y data keys (first entry is plotted).
        run : RunModel, optional
            Target run. Defaults to the first visible run model.
        norm_keys : sequence of str, optional
            Normalization keys.

        Returns
        -------
        PlotBundle
            Fetched plot payload.

        Raises
        ------
        RuntimeError
            If no run is available.
        ValueError
            If ``y_keys`` is empty.
        """
        if not y_keys:
            raise ValueError("y_keys must contain at least one key")
        run_model = run or self._first_run_model()
        x_list = list(x_keys)
        y_list = list(y_keys)
        norm_list = list(norm_keys or [])
        self.plot.set_selected_keys(x_list, y_list, norm_list)
        plot_data = self.plot.ensure_plot_data(
            run_model,
            x_list[0] if x_list else "",
            y_list[0],
            norm_keys=norm_list,
        )
        return plot_data.get_plot_bundle(cube_view_spec=self.plot.cube_view_spec)

    def _first_run_model(self) -> RunModel:
        models = self.run_list.available_models
        if not models:
            raise RuntimeError("run list has no runs; select or add a run first")
        return models[0]

    def _run_model_for_uid(self, uid: str) -> RunModel:
        for model in self.run_list.available_models:
            if model.uid == uid:
                return model
        raise RuntimeError(f"run {uid!r} was not added to the presenter run list")
