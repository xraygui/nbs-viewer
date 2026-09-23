"""Shared pytest fixtures for headless model tests."""

from __future__ import annotations

import os
import weakref

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


@pytest.fixture(autouse=True)
def shutdown_chunk_caches():
    """
    Stop every :class:`ChunkCache` a test created before the next one starts.

    Nothing in the application shuts a cache down, so without this a
    background L2 materialize job keeps running into later tests. It writes
    tiles through Zarr's process-global event loop while holding
    ``ZarrL2Cache._lock``, and Zarr waits on that write with no timeout, so
    a test that has already reported success can wedge one that runs
    minutes later. That was a roughly one-in-twenty-five hang of the full
    suite, and it never reproduced when the cache tests ran on their own --
    the job that hangs you belongs to a test that has already finished.

    Caches are constructed inside test bodies and inside catalog models, so
    there is no handle to collect; the fixture wraps the constructor and
    keeps weak references instead. Shutting down waits for in-flight jobs,
    which is what turns the test boundary into a real barrier.
    """
    from nbs_viewer.models.cache.chunkCache import ChunkCache

    caches: weakref.WeakSet = weakref.WeakSet()
    original = ChunkCache.__init__

    def tracking_init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        caches.add(self)

    ChunkCache.__init__ = tracking_init
    try:
        yield
    finally:
        ChunkCache.__init__ = original
        for cache in list(caches):
            cache.shutdown()


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
