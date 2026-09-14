"""
The emission matrix for :class:`ViewIntent`, and the guard that it is a model.

Signals here are justified by consumers, not by fields: there is no
``reduce_changed`` because nothing distinguishes a reduce change from any
other, and there *is* an ``orientation_changed`` because two consumers key off
the plot plane's coordinate frame and must not fire when only a slice index
moved. That asymmetry is the content of these tests.
"""

from __future__ import annotations

import pytest

from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.view.spec import DimRole, Projection


def _recorder(intent):
    """
    Return a dict counting each of the intent's three signals.
    """
    fired = {"plot_ndim": 0, "orientation": 0, "changed": 0}
    intent.plot_ndim_changed.connect(
        lambda _n: fired.__setitem__("plot_ndim", fired["plot_ndim"] + 1)
    )
    intent.orientation_changed.connect(
        lambda: fired.__setitem__("orientation", fired["orientation"] + 1)
    )
    intent.changed.connect(
        lambda: fired.__setitem__("changed", fired["changed"] + 1)
    )
    return fired


def test_set_plot_ndim_emits_rank_and_changed(qapp):
    intent = ViewIntent(plot_ndim=1)
    fired = _recorder(intent)

    assert intent.set_plot_ndim(2) is True
    assert fired == {"plot_ndim": 1, "orientation": 0, "changed": 1}


def test_set_axis_order_emits_orientation_and_changed(qapp):
    intent = ViewIntent(plot_ndim=2)
    fired = _recorder(intent)

    assert intent.set_axis_order((1, 0), ["x", "y"]) is True
    assert fired == {"plot_ndim": 0, "orientation": 1, "changed": 1}


def test_follow_xkey_emits_orientation_and_changed(qapp):
    intent = ViewIntent(plot_ndim=2, xkey="x")
    fired = _recorder(intent)

    assert intent.follow_xkey("y") is True
    assert fired == {"plot_ndim": 0, "orientation": 1, "changed": 1}


def test_a_reduce_change_does_not_move_the_plot_plane(qapp):
    """
    Bug 12, stated as a model-level rule.

    Slicing to another index leaves the plot plane's coordinate frame where
    it was, so nothing keyed to that frame may react. When the canvas diffed
    the whole intent instead, every slider tick destroyed the image artist,
    the colorbar, and any live ROI selector.
    """
    intent = ViewIntent(plot_ndim=2, reduce_roles=(DimRole.INDEX,),
                        reduce_indices=(0,))
    fired = _recorder(intent)

    assert intent.set_reduce((DimRole.INDEX,), (3,)) is True
    assert fired == {"plot_ndim": 0, "orientation": 0, "changed": 1}


def test_no_op_mutations_are_silent(qapp):
    """
    Each mutator guards on real change.

    This is the per-field replacement for the whole-object equality guard
    ``PlotSession.set_view_intent`` used to hold, and it is finer: a mutator
    that changes nothing emits nothing, whatever else is set.
    """
    intent = ViewIntent(plot_ndim=2, xkey="x", dim_order=("x", "y"),
                        reduce_roles=(DimRole.SUM,), reduce_indices=(0,))
    fired = _recorder(intent)

    assert intent.set_plot_ndim(2) is False
    assert intent.follow_xkey("x") is False
    assert intent.set_axis_order((0, 1), ["x", "y"]) is False
    assert intent.set_reduce((DimRole.SUM,), (0,)) is False
    assert fired == {"plot_ndim": 0, "orientation": 0, "changed": 0}


def test_changed_fires_last(qapp):
    """
    A consumer connected only to ``changed`` never sees a half-applied state.
    """
    intent = ViewIntent(plot_ndim=1)
    order = []
    intent.plot_ndim_changed.connect(lambda _n: order.append("plot_ndim"))
    intent.changed.connect(lambda: order.append("changed"))

    intent.set_plot_ndim(2)
    assert order == ["plot_ndim", "changed"]


def test_project_still_returns_a_frozen_value(qapp):
    """
    The model is mutable; what it produces is not.

    A projection rides on a ``PlotRequest``, which is the fingerprint of a
    fetch and is compared to decide whether to refetch.
    """
    intent = ViewIntent(plot_ndim=2)
    projection = intent.project(3, (4, 5, 6))

    assert isinstance(projection, Projection)
    with pytest.raises((AttributeError, TypeError)):
        projection.plot_ndim = 1


def test_a_projection_survives_a_later_mutation(qapp):
    """
    Projections are snapshots, so mutating the intent cannot rewrite one
    already handed out -- which is what makes a mutable model safe here.
    """
    intent = ViewIntent(plot_ndim=2)
    before = intent.project(3, (4, 5, 6))

    intent.set_plot_ndim(1)

    assert before.plot_ndim == 2
    assert intent.project(3, (4, 5, 6)).plot_ndim == 1


def test_the_mixed_rank_case_needs_no_throwaway_intent(qapp):
    """
    A key that cannot fill the session plot projects at its own rank.

    Production used to build a temporary intent with ``dataclasses.replace``
    for this; a mutable model cannot supply one, so ``project`` takes the
    override instead.
    """
    intent = ViewIntent(plot_ndim=2, reduce_roles=(DimRole.INDEX,),
                        reduce_indices=(4,))

    image = intent.project(3, (8, 5, 6))
    line = intent.project(1, (11,), plot_ndim=1)

    assert image.plot_ndim == 2
    assert line.plot_ndim == 1
    assert line.roles == (DimRole.PLOT_X,)
    assert intent.plot_ndim == 2


def test_an_invalid_mutation_leaves_the_intent_alone(qapp):
    intent = ViewIntent(plot_ndim=2, reduce_roles=(DimRole.INDEX,),
                        reduce_indices=(1,))
    fired = _recorder(intent)

    with pytest.raises(ValueError):
        intent.set_plot_ndim(3)
    with pytest.raises(ValueError):
        intent.set_reduce((DimRole.INDEX, DimRole.SUM), (0,))

    assert intent.plot_ndim == 2
    assert intent.reduce_indices == (1,)
    assert fired == {"plot_ndim": 0, "orientation": 0, "changed": 0}
