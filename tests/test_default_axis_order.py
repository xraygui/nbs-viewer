"""
The selected X key drives the default plot-axis order.

Both halves of the rule live in ``resolve_axis_order`` and are reached
through ``ViewIntent.project``: the default orientation, and when a manual
arrangement is kept or re-derived. That is the decision the dimension
controls used to make on every rebuild; on the model side it can be tested
without a QWidget (the suite runs on QCoreApplication only).
"""

import pytest

from nbs_viewer.models.plot.view_spec import (
    DimRole,
    ViewIntent,
)
from nbs_viewer.models.plot.runSource import RunSource
from nbs_viewer.models.sources.testSource import create_test_catalog


def _placement(spec, names):
    """Return ``(vertical, horizontal)`` dimension names for a projection."""
    order = spec.plot_axis_order()
    if spec.plot_ndim == 2:
        return names[order[-2]], names[order[-1]]
    return None, names[order[-1]]


def _project(names, xkey=None, plot_ndim=2, dim_order=()):
    intent = ViewIntent(
        plot_ndim=plot_ndim, xkey=xkey or "", dim_order=tuple(dim_order)
    )
    return intent.project(len(names), dim_names=names)


def _trailing(ndim, plot_ndim=2):
    return ViewIntent(plot_ndim=plot_ndim).project(ndim).axis_order


def test_no_selection_keeps_the_trailing_axis_default():
    names = ["x", "dim_1"]
    spec = _project(names, None)
    assert spec.axis_order == _trailing(2)
    assert _placement(spec, names) == ("x", "dim_1")


def test_unknown_x_key_keeps_the_trailing_axis_default():
    names = ["x", "dim_1"]
    assert _project(names, "not_a_dimension").axis_order == _trailing(2)


def test_selected_x_goes_horizontal_on_a_two_dimensional_key():
    names = ["x", "dim_1"]
    spec = _project(names, "x")
    assert _placement(spec, names) == ("dim_1", "x")
    assert spec.roles[names.index("x")] == DimRole.PLOT_X
    assert spec.roles[names.index("dim_1")] == DimRole.PLOT_Y


def test_selected_x_already_horizontal_is_left_alone():
    names = ["x", "dim_1"]
    spec = _project(names, "dim_1")
    assert spec.axis_order == _trailing(2)
    assert _placement(spec, names) == ("x", "dim_1")


def test_slice_axis_selection_leaves_the_plane_alone():
    """
    A camera stack scrubbed by voltage keeps its image plane.

    Without this guard the voltage axis is forced onto the plane and the
    frame is replaced by a voltage-versus-column view.
    """
    names = ["sampleVoltage_VSource", "dim_1", "dim_2"]
    spec = _project(names, "sampleVoltage_VSource")
    assert spec.axis_order == _trailing(3)
    assert _placement(spec, names) == ("dim_1", "dim_2")
    assert spec.roles[0] == DimRole.INDEX


def test_one_dimensional_plot_always_takes_the_selected_x():
    """
    The trailing-axis default plots a detector against its column index.
    """
    names = ["sampleVoltage_VSource", "dim_1", "dim_2"]
    plain = ViewIntent(plot_ndim=1).project(3)
    assert _placement(plain, names) == (None, "dim_2")

    spec = _project(names, "sampleVoltage_VSource", plot_ndim=1)
    assert _placement(spec, names) == (None, "sampleVoltage_VSource")
    assert spec.roles[0] == DimRole.PLOT_X
    assert spec.roles[1] == DimRole.INDEX
    assert spec.roles[2] == DimRole.INDEX


def test_tes_like_layout_comes_from_the_selection():
    """
    The layout the mesh transpose used to fake is now a consequence of the
    user picking en_energy as X.
    """
    names = ["en_energy", "tes_mca_energies"]
    assert _placement(_project(names, "en_energy"), names) == (
        "tes_mca_energies",
        "en_energy",
    )


@pytest.mark.parametrize("plot_ndim", [1, 2])
def test_rule_holds_against_the_shipped_fixtures(plot_ndim):
    """
    Drive the rule with dimension names the data layer actually produces.
    """
    catalog = create_test_catalog(runs=1, include_nd=True)
    seen = 0
    for run in catalog.get_runs():
        source = RunSource(run)
        for ykey in source.available_keys:
            shape = source.get_shape(ykey)
            if len(shape) < 2:
                continue
            for xkey in ("x", "sampleVoltage_VSource"):
                if xkey not in source.available_keys:
                    continue
                names = list(source.describe_axes(ykey, [xkey]).names)
                if xkey not in names:
                    continue
                seen += 1
                spec = _project(names, xkey, plot_ndim=plot_ndim)
                x_axis = names.index(xkey)
                plane = ViewIntent(plot_ndim=plot_ndim).project(
                    len(shape)
                ).plot_axis_order()
                if plot_ndim == 1 or x_axis in plane:
                    assert spec.plot_axis_order()[-1] == x_axis
                else:
                    assert spec.axis_order == _trailing(len(shape), plot_ndim)
    assert seen > 0


# ---------------------------------------------------------------------------
# Manual arrangement versus selection: last one wins.
# ---------------------------------------------------------------------------

NAMES_2D = ["x", "dim_1"]


def test_a_manual_order_is_honoured():
    intent = ViewIntent(plot_ndim=2, xkey="x")
    swapped = intent.project(2, dim_names=NAMES_2D).swap_rows(1)
    manual = intent.with_axis_order(swapped.axis_order, NAMES_2D)

    assert manual.dim_order == ("x", "dim_1")
    assert _placement(manual.project(2, dim_names=NAMES_2D), NAMES_2D) == (
        "x",
        "dim_1",
    )


def test_the_same_selection_keeps_a_manual_order():
    manual = ViewIntent(plot_ndim=2, xkey="x", dim_order=("x", "dim_1"))
    assert manual.follow_xkey("x") is manual


def test_a_different_selection_supersedes_a_manual_order():
    manual = ViewIntent(plot_ndim=2, xkey="x", dim_order=("x", "dim_1"))
    fresh = manual.follow_xkey("y")

    assert fresh.xkey == "y"
    assert fresh.dim_order == ()
    names = ["y", "dim_1"]
    assert _placement(fresh.project(2, dim_names=names), names) == (
        "dim_1",
        "y",
    )


def test_a_rank_change_re_derives_rather_than_half_applying():
    """
    A manual arrangement describes the axes it names, not a position.

    Honouring only the axes a rank change left behind would silently
    reinterpret which one the user meant to be horizontal, so a partial
    match falls back to the selection rule.
    """
    manual = ViewIntent(plot_ndim=2, xkey="x", dim_order=("x", "dim_1"))
    names = ["x", "dim_1", "dim_2"]
    spec = manual.project(3, dim_names=names)

    assert spec.ndim == 3
    # x is a slice axis at rank 3, so the plane keeps its own orientation
    assert _placement(spec, names) == ("dim_1", "dim_2")


def test_switching_plot_dimensions_preserves_a_manual_order():
    from dataclasses import replace

    manual = ViewIntent(plot_ndim=2, xkey="x", dim_order=("x", "dim_1"))
    one_d = replace(manual, plot_ndim=1)
    spec = one_d.project(2, dim_names=NAMES_2D)

    assert spec.plot_ndim == 1
    assert spec.axis_order == (0, 1)
    assert _placement(spec, NAMES_2D) == (None, "dim_1")


def test_the_order_survives_a_key_with_the_same_axes():
    """
    Names, not positions: the arrangement transfers to any key that has the
    axes it names, which a stored permutation could not express.
    """
    manual = ViewIntent(plot_ndim=2, xkey="x", dim_order=("dim_1", "x"))
    for names in (["x", "dim_1"], ["dim_1", "x"]):
        spec = manual.project(2, dim_names=names)
        assert _placement(spec, names) == ("dim_1", "x")
