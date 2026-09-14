"""Regression tests for Y-key selection and view-state consistency."""

from __future__ import annotations

from nbs_viewer.models.plot.view.spec import DimRole
from nbs_viewer.models.plot.plot_session import PlotSession
from nbs_viewer.views.dataSource.run_list_item_model import RunListItemModel
from nbs_viewer.models.plot.run_source import RunSource
from nbs_viewer.models.sources.testSource import create_test_catalog


def _test_session():
    run = RunSource(create_test_catalog(1).get_runs()[0])
    plot = PlotSession()
    run_list = RunListItemModel(plot.collection)
    plot.collection.add_runs([run])
    x_keys, y_keys, norm_keys = run.run.get_default_selection()
    return run, plot, x_keys, y_keys, norm_keys


def test_a_stale_two_dimensional_view_cannot_poison_a_one_dimensional_key():
    """
    The failure this replaces: a rank-2 ``Projection`` held by the session
    was poison for a rank-1 key, so ``DimensionControl`` had to hand the
    session ``cube_view_spec=None`` to detoxify it. A rank-agnostic intent
    has nothing to clear -- it projects onto whatever rank it is asked for.
    """
    run, plot, x_keys, _, norm_keys = _test_session()
    plot.view_intent.set_plot_ndim(2)
    plot.view_intent.set_reduce((DimRole.INDEX,), (7,))
    assert plot.view_intent.plot_ndim == 2

    plot.selection.set_selected_keys(x_keys, ["y"], norm_keys)
    bundle = plot.ensure_trace(run, x_keys[0], "y", norm_keys).get_plot_bundle()
    assert bundle.render_mode == "line"
    assert bundle.y.shape == (100,)


def test_y_image_y_selection_sequence():
    """
    Select y, then image, then y again without plot fetch errors.

    Matches the GUI flow where a 2D view spec must not be applied to the
    1D ``y`` field after returning to line plotting.
    """
    run, plot, x_keys, _, norm_keys = _test_session()
    xkey = x_keys[0]

    plot.selection.set_selected_keys(x_keys, ["y"], norm_keys)
    bundle_y = plot.ensure_trace(run, xkey, "y", norm_keys).get_plot_bundle()
    assert bundle_y.render_mode == "line"

    plot.selection.set_selected_keys(x_keys, ["image"], norm_keys)
    plot.view_intent.set_plot_ndim(2)
    bundle_image = plot.ensure_trace(
        run, xkey, "image", norm_keys
    ).get_plot_bundle()
    assert bundle_image.render_mode == "image"

    plot.selection.set_selected_keys(x_keys, ["y"], norm_keys)
    plot.view_intent.set_plot_ndim(1)
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

    plot.selection.set_selected_keys(x_keys, ["y", "image"], norm_keys)
    plot.view_intent.set_plot_ndim(2)

    bundle_y = plot.ensure_trace(run, xkey, "y", norm_keys).get_plot_bundle()
    bundle_image = plot.ensure_trace(
        run, xkey, "image", norm_keys
    ).get_plot_bundle()

    assert bundle_y.render_mode == "line"
    assert bundle_y.y.ndim == 1
    assert bundle_image.render_mode == "image"
    assert bundle_image.y.ndim == 2
