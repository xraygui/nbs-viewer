"""Shared pytest fixtures for headless model tests."""

from __future__ import annotations

import os

# Must be set before qtpy imports Qt: it picks the platform plugin at import
# time, and "offscreen" is what lets a real QApplication start with no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

from nbs_viewer.models.app_model import AppModel

from tests.fixtures.session import HeadlessSession


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """
    Headless Qt application instance.

    A real ``QApplication`` on the offscreen platform, not a
    ``QCoreApplication``: it is a subclass, so every model test is unaffected,
    but it also permits constructing a ``QWidget``.

    ``autouse`` because forgetting it is not a test failure. Constructing a
    ``QWidget`` with no ``QApplication`` raises no Python exception -- Qt
    calls ``abort()``, which takes the whole pytest process down with
    SIGABRT and loses every other result in the run. Creating the
    application unconditionally makes that unreachable. Tests may still
    name ``qapp`` explicitly to document that they need Qt.

    Returns
    -------
    QApplication
        Shared application instance for the test session.
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def app_model(qapp):
    """
    Fresh :class:`AppModel` for a single test.

    Parameters
    ----------
    qapp : QApplication
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
