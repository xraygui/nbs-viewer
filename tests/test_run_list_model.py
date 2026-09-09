"""Tests for RunListItemModel aggregate settings."""

from tests.fixtures.session import HeadlessSession


def test_session_dynamic_update_returns_bool_with_one_run(qapp, app_model):
    """
    PlotSession.dynamic_update must read RunSource.dynamic_update without error.
    """
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="line_scan", runs=1)
    session.select_run(0)

    assert isinstance(session.session.collection.dynamic_update, bool)
