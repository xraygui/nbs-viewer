"""Shared pytest fixtures for headless model tests."""

from __future__ import annotations

import pytest
from qtpy.QtCore import QCoreApplication

from nbs_viewer.models.app_model import AppModel

from tests.fixtures.session import HeadlessSession


@pytest.fixture(scope="session")
def qapp():
    """
    Headless Qt application instance for QObject-based models.

    Returns
    -------
    QCoreApplication
        Shared application instance for the test session.
    """
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app


@pytest.fixture
def app_model(qapp):
    """
    Fresh :class:`AppModel` for a single test.

    Parameters
    ----------
    qapp : QCoreApplication
        Ensures Qt is initialized before model construction.

    Returns
    -------
    AppModel
        Application root with catalog and display managers.
    """
    return AppModel()


@pytest.fixture
def headless_session(app_model):
    """
    Headless session with a default line-scan catalog loaded.

    Parameters
    ----------
    app_model : AppModel
        Application root model.

    Returns
    -------
    HeadlessSession
        Session helper with catalog registered on the app model.
    """
    session = HeadlessSession(app_model)
    session.load_catalog(recipe="line_scan", runs=3)
    return session
