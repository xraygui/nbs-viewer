"""The selected X key drives the default plot-axis order."""

import pytest

from nbs_viewer.models.plot.cube_view import (
    DimRole,
    default_spec,
    default_spec_for_selection,
    spec_for_shape_and_selection,
)
from nbs_viewer.models.plot.runSource import RunSource
from nbs_viewer.models.sources.testSource import create_test_catalog


def _placement(spec, names):
    """Return ``(vertical, horizontal)`` dimension names for a spec."""
    order = spec.plot_axis_order()
    if spec.plot_ndim == 2:
        return names[order[-2]], names[order[-1]]
    return None, names[order[-1]]


def test_no_selection_keeps_the_trailing_axis_default():
    names = ["x", "dim_1"]
    spec = default_spec_for_selection(2, 2, names, None)
    assert spec.axis_order == default_spec(2, 2).axis_order
    assert _placement(spec, names) == ("x", "dim_1")


def test_unknown_x_key_keeps_the_trailing_axis_default():
    names = ["x", "dim_1"]
    spec = default_spec_for_selection(2, 2, names, "not_a_dimension")
    assert spec.axis_order == default_spec(2, 2).axis_order


def test_selected_x_goes_horizontal_on_a_two_dimensional_key():
    names = ["x", "dim_1"]
    spec = default_spec_for_selection(2, 2, names, "x")
    assert _placement(spec, names) == ("dim_1", "x")
    assert spec.roles[names.index("x")] == DimRole.PLOT_X
    assert spec.roles[names.index("dim_1")] == DimRole.PLOT_Y


def test_selected_x_already_horizontal_is_left_alone():
    names = ["x", "dim_1"]
    spec = default_spec_for_selection(2, 2, names, "dim_1")
    assert spec.axis_order == default_spec(2, 2).axis_order
    assert _placement(spec, names) == ("x", "dim_1")


def test_slice_axis_selection_leaves_the_plane_alone():
    """
    A camera stack scrubbed by voltage keeps its image plane.

    Without this guard the voltage axis is forced onto the plane and the
    frame is replaced by a voltage-versus-column view.
    """
    names = ["sampleVoltage_VSource", "dim_1", "dim_2"]
    spec = default_spec_for_selection(3, 2, names, "sampleVoltage_VSource")
    assert spec.axis_order == default_spec(3, 2).axis_order
    assert _placement(spec, names) == ("dim_1", "dim_2")
    assert spec.roles[0] == DimRole.INDEX


def test_one_dimensional_plot_always_takes_the_selected_x():
    """
    The trailing-axis default plots a detector against its column index.
    """
    names = ["sampleVoltage_VSource", "dim_1", "dim_2"]
    assert _placement(default_spec(3, 1), names) == (None, "dim_2")

    spec = default_spec_for_selection(3, 1, names, "sampleVoltage_VSource")
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
    spec = default_spec_for_selection(2, 2, names, "en_energy")
    assert _placement(spec, names) == ("tes_mca_energies", "en_energy")


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
                spec = default_spec_for_selection(
                    len(shape), plot_ndim, names, xkey
                )
                x_axis = names.index(xkey)
                plane = default_spec(len(shape), plot_ndim).plot_axis_order()
                if plot_ndim == 1 or x_axis in plane:
                    assert spec.plot_axis_order()[-1] == x_axis
                else:
                    assert spec.axis_order == default_spec(
                        len(shape), plot_ndim
                    ).axis_order
    assert seen > 0


# ---------------------------------------------------------------------------
# spec_for_shape_and_selection: when the default is re-derived, and when the
# order in use is left alone. This is the decision DimensionControl makes on
# every rebuild; it lives on the model side so it can be tested without a
# QWidget (the suite runs on QCoreApplication only).
# ---------------------------------------------------------------------------

NAMES_2D = ["x", "dim_1"]


def _first(names=NAMES_2D, xkey="x", plot_ndim=2):
    return spec_for_shape_and_selection(
        None,
        ndim=len(names),
        plot_ndim=plot_ndim,
        dim_names=names,
        xkey=xkey,
        derived_from_xkey=None,
    )


def test_first_call_derives_from_the_selection():
    spec, derived = _first()
    assert derived == "x"
    assert _placement(spec, NAMES_2D) == ("dim_1", "x")


def test_same_selection_keeps_the_order_in_use():
    spec, derived = _first()
    reordered = spec.swap_rows(1)
    assert _placement(reordered, NAMES_2D) == ("x", "dim_1")

    kept, still = spec_for_shape_and_selection(
        reordered,
        ndim=2,
        plot_ndim=2,
        dim_names=NAMES_2D,
        xkey="x",
        derived_from_xkey=derived,
    )
    assert kept.axis_order == reordered.axis_order
    assert still == "x"


def test_a_different_selection_re_derives():
    spec, derived = _first()
    reordered = spec.swap_rows(1)

    names = ["y", "dim_1"]
    fresh, now = spec_for_shape_and_selection(
        reordered,
        ndim=2,
        plot_ndim=2,
        dim_names=names,
        xkey="y",
        derived_from_xkey=derived,
    )
    assert now == "y"
    assert _placement(fresh, names) == ("dim_1", "y")


def test_a_rank_change_re_derives():
    spec, derived = _first()
    names = ["x", "dim_1", "dim_2"]
    fresh, now = spec_for_shape_and_selection(
        spec,
        ndim=3,
        plot_ndim=2,
        dim_names=names,
        xkey="x",
        derived_from_xkey=derived,
    )
    assert fresh.ndim == 3
    assert now == "x"
    # x is now the slice axis, so the plane keeps its own orientation
    assert _placement(fresh, names) == ("dim_1", "dim_2")


def test_switching_plot_dimensions_preserves_a_manual_order():
    spec, derived = _first()
    reordered = spec.swap_rows(1)

    one_d, _ = spec_for_shape_and_selection(
        reordered,
        ndim=2,
        plot_ndim=1,
        dim_names=NAMES_2D,
        xkey="x",
        derived_from_xkey=derived,
    )
    assert one_d.plot_ndim == 1
    assert one_d.axis_order == reordered.axis_order
    assert _placement(one_d, NAMES_2D) == (None, "dim_1")
