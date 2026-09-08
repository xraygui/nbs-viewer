"""Regression tests for Y-key selection and view-state consistency."""

from __future__ import annotations

from nbs_viewer.models.plot.view_spec import (
    default_spec,
    spec_for_plot_ndim,
)
from nbs_viewer.models.plot.plot_session import PlotSession
from nbs_viewer.views.dataSource.run_list_item_model import RunListItemModel
from nbs_viewer.models.plot.runSource import RunSource
from nbs_viewer.models.sources.testSource import create_test_catalog


def _test_session():
    run = RunSource(create_test_catalog(1).get_runs()[0])
    plot = PlotSession()
    run_list = RunListItemModel(plot)
    plot.add_run(run)
    x_keys, y_keys, norm_keys = run.run.get_default_selection()
    return run, plot, x_keys, y_keys, norm_keys


def test_set_view_state_clears_cube_view_spec():
    """
    Resetting to 1D must drop a stale 2D cube view spec.

    DimensionControl passes ``cube_view_spec=None`` when only 1D Y keys
    remain selected; leaving the old spec caused 1D fetches to fail.
    """
    _, plot, x_keys, _, norm_keys = _test_session()
    shape = (100, 32)
    spec = spec_for_plot_ndim(default_spec(2, 2), 2, shape)
    plot.set_view_state(dimension=2, cube_view_spec=spec)

    plot.set_view_state(indices=None, dimension=1, cube_view_spec=None)

    assert plot.dimension == 1
    assert plot.cube_view_spec is None
    assert plot.slice is None


def test_y_image_y_selection_sequence():
    """
    Select y, then image, then y again without plot fetch errors.

    Matches the GUI flow where a 2D view spec must not be applied to the
    1D ``y`` field after returning to line plotting.
    """
    run, plot, x_keys, _, norm_keys = _test_session()
    xkey = x_keys[0]

    plot.set_selected_keys(x_keys, ["y"], norm_keys)
    bundle_y = plot.ensure_trace(run, xkey, "y", norm_keys).get_plot_bundle()
    assert bundle_y.render_mode == "line"

    plot.set_selected_keys(x_keys, ["image"], norm_keys)
    plot.set_view_state(dimension=2)
    bundle_image = plot.ensure_trace(
        run, xkey, "image", norm_keys
    ).get_plot_bundle()
    assert bundle_image.render_mode == "image"

    plot.set_selected_keys(x_keys, ["y"], norm_keys)
    plot.set_view_state(indices=None, dimension=1, cube_view_spec=None)
    bundle_y_again = plot.ensure_trace(run, xkey, "y", norm_keys).get_plot_bundle()
    assert bundle_y_again.render_mode == "line"
    assert "dim_1" not in bundle_y_again.axis_names


def test_1d_y_ignored_stale_cube_view_spec_when_both_y_keys_selected():
    """
    A 1D Y key must not use a session 2D cube view spec meant for image.

    When both ``y`` and ``image`` are checked, the global spec follows the
    2D field; 1D series still fetch as lines.
    """
    run, plot, x_keys, _, norm_keys = _test_session()
    xkey = x_keys[0]
    shape = (100, 32)
    spec = spec_for_plot_ndim(default_spec(2, 2), 2, shape)

    plot.set_selected_keys(x_keys, ["y", "image"], norm_keys)
    plot.set_view_state(dimension=2, cube_view_spec=spec)

    bundle_y = plot.ensure_trace(run, xkey, "y", norm_keys).get_plot_bundle()
    bundle_image = plot.ensure_trace(
        run, xkey, "image", norm_keys
    ).get_plot_bundle()

    assert bundle_y.render_mode == "line"
    assert bundle_y.y.ndim == 1
    assert bundle_image.render_mode == "image"
    assert bundle_image.y.ndim == 2
