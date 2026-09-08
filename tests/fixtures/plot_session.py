"""Helpers for constructing a plot session and its Qt run-list facade."""

from __future__ import annotations

from typing import Tuple

from nbs_viewer.models.plot.plotModel import PlotModel
from nbs_viewer.models.plot.runListModel import RunListModel


def make_plot_session(
    *,
    is_main_display: bool = False,
    single_selection_mode: bool = False,
) -> Tuple[PlotModel, RunListModel]:
    """
    Build a session and bound run-list in the modern ownership order.

    Parameters
    ----------
    is_main_display : bool, optional
        Whether the session is the main display (auto-shows new runs).
    single_selection_mode : bool, optional
        Whether checking one run unchecks others.

    Returns
    -------
    tuple of (PlotModel, RunListModel)
        Session first, then the Qt list facade bound to it.
    """
    session = PlotModel(
        is_main_display=is_main_display,
        single_selection_mode=single_selection_mode,
    )
    run_list = RunListModel(session)
    return session, run_list
