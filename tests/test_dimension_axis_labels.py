"""Plot-axis role labels must follow the view spec, not the rendered frame."""

import numpy as np

from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.plane.roles import DimRole
from nbs_viewer.models.plot.spec.bundle import prepare_2d_bundle


def test_swapping_plot_rows_swaps_the_roles():
    """
    ``swap_rows`` moves Plot X and Plot Y between storage axes.

    This is the fact the dimension control's labels must read.
    """
    spec = ViewIntent(plot_ndim=2).project(2)
    assert spec.roles == (DimRole.PLOT_Y, DimRole.PLOT_X)

    swapped = spec.swap_rows(1)
    assert swapped.axis_order == (1, 0)
    assert swapped.roles == (DimRole.PLOT_X, DimRole.PLOT_Y)
    assert swapped.plot_axis_order() == (1, 0)


def test_view_frame_plot_dims_are_plane_positions_not_storage_axes():
    """
    ``plot_x_dim`` / ``plot_y_dim`` index the displayed plane, not storage.

    The dimension control used to compare a storage axis against these, which
    gave a fixed Plot X / Plot Y assignment that contradicted the plot once
    the rows were reordered.
    """
    bundle = prepare_2d_bundle(
        np.zeros((4, 6)),
        [np.arange(4.0), np.arange(6.0)],
        ["x", "dim_1"],
        render_mode_hint="image"
)
    frame = bundle.view_frame()
    assert (frame.plot_y_dim, frame.plot_x_dim) == (0, 1)

    # The spec says storage axis 1 is Plot Y after the swap, but the frame
    # still reports plane row 0 / column 1. The two disagree by design.
    swapped = ViewIntent(plot_ndim=2).project(2).swap_rows(1)
    assert swapped.roles[1] == DimRole.PLOT_Y
    assert swapped.roles[1] != DimRole.PLOT_X
    assert frame.plot_x_dim == 1


def test_roles_stay_resolved_for_higher_rank_swaps():
    """
    Reordering a rank-3 view keeps exactly one Plot X and one Plot Y.
    """
    spec = ViewIntent(plot_ndim=2).project(3)
    assert [r.value for r in spec.roles] == ["index", "plot_y", "plot_x"]

    moved = spec.swap_rows(1)
    assert moved.axis_order == (1, 0, 2)
    assert sum(r == DimRole.PLOT_X for r in moved.roles) == 1
    assert sum(r == DimRole.PLOT_Y for r in moved.roles) == 1
    # storage axis 0 left the slice section and became a plot axis
    assert moved.roles[0] == DimRole.PLOT_Y
    assert moved.roles[1] == DimRole.INDEX
    assert moved.roles[2] == DimRole.PLOT_X
