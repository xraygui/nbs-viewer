"""
The region child: ownership, the crop guard, and the wiring back to the session.

Crop and ROI are one lifecycle, so they are one object. What this file pins is
the *boundary* — what the controller owns, the two things it borrows, and the
one thing it announces — because that boundary is what stops the session from
regrowing a forwarding layer.
"""

from __future__ import annotations

import ast
from pathlib import Path


from nbs_viewer.models.plot.session import PlotSession
from nbs_viewer.models.plot.region_controller import RegionController
from nbs_viewer.models.plot.run.source import RunSource
from nbs_viewer.models.plot.view.spec import ViewCrop
from tests.fixtures.catalog_recipes import image_scan_run
from tests.fixtures.plot_session import make_plot_session


def _crop(bbox=(0, 2, 0, 3)):
    return ViewCrop(storage_bbox=bbox, plot_y_axis=0, plot_x_axis=1)


def test_the_session_owns_one_region_child(qapp):
    session, _ = make_plot_session()

    assert isinstance(session.region, RegionController)
    assert session.region.roi_set is not None
    # Handed out, not forwarded.
    assert not hasattr(session, "roi_set")
    assert not hasattr(session, "preview_roi_profile")
    assert not hasattr(session, "set_view_crop")


def test_each_session_gets_its_own_region_and_roi_set(qapp):
    first, _ = make_plot_session()
    second, _ = make_plot_session()

    assert first.region is not second.region
    assert first.region.roi_set is not second.region.roi_set


def test_setting_the_same_crop_twice_announces_once(qapp):
    """
    The mutator guards on real change, as the intent's mutators do.

    That guard is what let ``clear_view_crop`` be deleted: it was a null
    check wrapped around ``set_view_crop(None)``.
    """
    session, _ = make_plot_session()
    seen = []
    session.region.view_crop_changed.connect(seen.append)

    assert session.region.set_view_crop(_crop(), ("x", "y", "uid")) is True
    assert session.region.set_view_crop(_crop(), ("x", "y", "uid")) is False
    assert len(seen) == 1

    assert session.region.set_view_crop(None) is True
    assert session.region.set_view_crop(None) is False
    assert len(seen) == 2


def test_a_crop_change_rewrites_held_requests_before_the_repaint(qapp):
    """
    The session's half of a crop edit.

    The crop rides on every request, so the controller announces and the
    session rewrites — it owns the traces, the controller does not. Order is
    load-bearing: a repaint scheduled before the rewrite would fetch the old
    projection.
    """
    session, _ = make_plot_session()
    run = RunSource(image_scan_run(1, n_y=6, n_x=8, n_z=3))
    session.collection.add_runs([run])
    session.collection.set_uids_visible({run.uid}, True)
    session.selection.set_selected_keys(["en_energy"], ["detector_image"])
    session.view_intent.set_plot_ndim(2)
    trace = next(iter(session.traces.values()))
    key = trace.trace_key.as_tuple()

    seen = []
    session.request_plot_update.connect(
        lambda: seen.append(trace.request.view.crop)
    )
    session.region.set_view_crop(_crop((1, 4, 2, 6)), key)

    assert seen, "request_plot_update did not fire"
    assert seen[0] is not None, "repaint was scheduled before the rewrite"
    assert trace.request.view.crop is not None


def test_leaving_two_d_invalidates_region_state(qapp):
    session, _ = make_plot_session()
    reasons = []
    session.region.region_invalidation_requested.connect(reasons.append)

    session.view_intent.set_plot_ndim(2)
    assert reasons == []

    session.view_intent.set_plot_ndim(1)
    assert reasons == ["switched out of 2D mode"]


def test_a_selection_change_invalidates_region_state(qapp):
    """
    A different Y key is a different plane, so nothing drawn survives.

    This used to be the session subscribing to its own
    ``selected_keys_changed``; it is now a connection between two objects.
    """
    session, _ = make_plot_session()
    run = RunSource(image_scan_run(1, n_y=6, n_x=8, n_z=3))
    session.collection.add_runs([run])
    session.selection.set_selected_keys(["en_energy"], ["detector_image"])

    reasons = []
    session.region.region_invalidation_requested.connect(reasons.append)
    session.selection.set_selected_keys(["en_energy"], ["detector_cube"])

    assert reasons == ["field selection changed"]


def test_the_session_holds_no_roi_or_crop_state(qapp):
    """
    Guard against the forwarding layer regrowing.

    Step D deleted the delegating methods rather than keeping them, on the
    grounds that every heavyweight ROI member had exactly one caller. This
    fails if any of that state comes back onto the session.
    """
    session = PlotSession()
    banned = {
        "_view_crop",
        "_view_crop_key",
        "_roi_set",
        "_roi_draw_enabled",
        "_ellipse_circle_locked",
    }
    present = banned & set(vars(session))

    assert present == set(), f"region state back on the session: {present}"


def test_the_session_defines_no_region_methods():
    """
    The session may wire the child and hand it out; it may not re-export it.

    ``region`` and ``_on_view_crop_changed`` are the wiring: one accessor and
    the session's half of a crop edit. Anything else named for ROI, crop or
    fingerprints would be a delegating method.
    """
    source = Path(__file__).resolve().parents[1] / (
        "nbs_viewer/models/plot/session.py"
    )
    tree = ast.parse(source.read_text())
    cls = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "PlotSession"
    )
    allowed = {"region", "_on_view_crop_changed"}
    offenders = [
        n.name
        for n in cls.body
        if isinstance(n, ast.FunctionDef)
        and n.name not in allowed
        and any(
            token in n.name.lower()
            for token in ("roi", "crop", "region", "fingerprint")
        )
    ]

    assert offenders == [], f"delegating region methods on the session: {offenders}"


def test_the_canvas_holds_no_second_fingerprint_policy():
    """
    ``MplCanvas.current_view_fingerprint`` was ``resolve_current_view_fingerprint``
    written again against the canvas's own bundle. One policy, in the model.
    """
    source = Path(__file__).resolve().parents[1] / (
        "nbs_viewer/views/plot/mplCanvas/single_canvas.py"
    )
    tree = ast.parse(source.read_text())
    names = {
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
    }

    assert "current_view_fingerprint" not in names
