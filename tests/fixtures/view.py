"""
Test-only helper for expressing a view intent as a concrete projection.

Production has one direction: ``ViewIntent.project`` binds session state to a
key's rank. Nothing lifts a :class:`Projection` back into an intent, and the
converter that used to do it (``ViewIntent.from_view_spec``) was deleted with
the rest of the rank-bound view state.

Tests still want to say "set the session up so this key projects to *this*",
because that is the shape their assertions are written in. Doing it here keeps
the conversion out of the production surface, where it would be a bridge
between two representations of the same thing.

:func:`apply_projection` is the form to reach for once a session exists. The
session owns one live intent and mutates it, so a test cannot hand it a
replacement; it states the projection it wants and the helper drives the same
mutators production does.
"""

from __future__ import annotations

from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.view.spec import DimRole, Projection, SLICE_ROLES


def intent_from_projection(projection: Projection) -> ViewIntent:
    """
    Build the intent whose projection onto ``projection.ndim`` recovers it.

    Parameters
    ----------
    projection : Projection
        Concrete view to express as session state.

    Returns
    -------
    ViewIntent
        Intent carrying the same plot rank, reduce policy and axis order.
    """
    roles = []
    indices = []
    for storage_axis in projection.slice_axis_order():
        role = projection.roles[storage_axis]
        roles.append(role if role in SLICE_ROLES else DimRole.INDEX)
        indices.append(projection.indices[storage_axis])
    names = tuple(f"__axis_{a}" for a in range(projection.ndim))
    return ViewIntent(
        plot_ndim=projection.plot_ndim,
        reduce_roles=tuple(roles),
        reduce_indices=tuple(indices),
        dim_order=tuple(names[a] for a in projection.axis_order),
    )


def apply_projection(intent: ViewIntent, projection: Projection) -> None:
    """
    Drive an existing intent to the state that recovers ``projection``.

    The session owns one live :class:`ViewIntent`, so a test sets up a view by
    mutating it rather than by substituting one. Uses the same mutators
    production does, which means the emission matrix is exercised on the way.

    Parameters
    ----------
    intent : ViewIntent
        The session's live intent.
    projection : Projection
        Concrete view to express as session state.
    """
    wanted = intent_from_projection(projection)
    intent.set_plot_ndim(wanted.plot_ndim)
    intent.set_reduce(wanted.reduce_roles, wanted.reduce_indices)
    names = tuple(f"__axis_{a}" for a in range(projection.ndim))
    intent.set_axis_order(projection.axis_order, names)
