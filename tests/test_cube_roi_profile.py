"""
ROI profiles taken along a rank-3 cube.

Both test catalogs now carry a 2-D detector key and a 3-D one whose leading
axes mean the same thing, so these paths can be exercised headlessly at all:
until the cube existed, every ROI test ran against a rank-2 plane and the
rank-3 branches of the profile pipeline had no coverage.

The cases below are the ones a user reaches from the UI: the trailing-axis
default plane, and the plane you get after moving the short axis onto a
slider. Every eligible profile axis is exercised in each.
"""

from __future__ import annotations

import numpy as np
import pytest

from nbs_viewer.models.plot.spec.region import RectRegion
from nbs_viewer.models.plot.roi import RoiOperation
from nbs_viewer.models.plot.run.source import RunSource
from tests.fixtures.catalog_recipes import image_scan_run
from tests.fixtures.plot_session import make_plot_session

N_Y, N_X, N_Z = 12, 16, 3


def _session(ykey, *, depth_on_slider=False):
    """
    Return ``(session, run, trace)`` showing ``ykey`` as a 2-D plane.

    Parameters
    ----------
    ykey : str
        ``detector_image`` (rank 2) or ``detector_cube`` (rank 3).
    depth_on_slider : bool, optional
        For the cube, put ``dim_2`` on a slider so the plane is the event
        axis against ``en_energy`` rather than the trailing-axis default.
    """
    session, _ = make_plot_session()
    run = RunSource(image_scan_run(1, n_y=N_Y, n_x=N_X, n_z=N_Z))
    session.collection.add_runs([run])
    session.collection.set_uids_visible({run.uid}, True)
    session.selection.set_selected_keys(["en_energy"], [ykey])
    session.view_intent.set_plot_ndim(2)
    if depth_on_slider:
        # An arrangement is stored by the names the rows show, and those
        # follow the X selection.
        session.view_intent.set_axis_order(
            (2, 0, 1), run.plot_axis_names(ykey, ["en_energy"])
        )
    trace = session.ensure_trace(run, "en_energy", ykey)
    trace.get_plot_bundle()
    return session, run, trace


def _add_roi(session, trace, profile_storage_axis):
    """
    Add an ROI covering the interior of the current plane.
    """
    frame = trace.last_bundle.view_frame()
    n_rows, n_cols = trace.last_bundle.y.shape
    x0, _ = frame.cell_x_bounds(1, 0)
    _, x1 = frame.cell_x_bounds(n_cols - 2, 0)
    y0, _ = frame.cell_y_bounds(1, 0)
    _, y1 = frame.cell_y_bounds(n_rows - 2, 0)
    entry_id = session.region.roi_set.add(
        RectRegion(x0=x0, x1=x1, y0=y0, y1=y1),
        operation=RoiOperation(
            profile_storage_axis=profile_storage_axis,
            spatial_reduce="sum",
            span_full_profile_axis=True,
            label="roi"
),
        view_fingerprint=session.region.resolve_current_view_fingerprint()
)
    return entry_id, frame


def test_the_cube_and_the_image_are_both_selectable():
    """
    The mixed-rank paths need a rank-2 and a rank-3 key on one run.
    """
    run = RunSource(image_scan_run(1, n_y=N_Y, n_x=N_X, n_z=N_Z))

    assert run.get_shape("detector_image") == (N_Y, N_X)
    assert run.get_shape("detector_cube") == (N_Y, N_X, N_Z)
    # ``en_energy`` is declared on the ``pixel`` axis, so selecting it as X
    # plots that axis against it, under its name.
    names = run.plot_axis_names("detector_cube", ["en_energy"])
    assert names == ("time", "en_energy", "dim_2")


def test_the_cube_leading_plane_matches_the_image(qapp):
    """
    The cube's first slab is the image, so the two keys are comparable.

    A test that fetches a cube plane has to know what it should contain, or
    a wrong axis choice reads as merely surprising rather than wrong.
    """
    _s, _r, image = _session("detector_image")
    _s2, _r2, cube = _session("detector_cube", depth_on_slider=True)

    assert image.last_bundle.y.shape == (N_Y, N_X)
    assert cube.last_bundle.y.shape == (N_Y, N_X)
    np.testing.assert_allclose(cube.last_bundle.y, image.last_bundle.y)


@pytest.mark.parametrize("depth_on_slider", [False, True])
def test_every_eligible_profile_axis_previews_on_a_cube(
    qapp, depth_on_slider
):
    """
    Each axis the UI offers must actually produce a profile.

    The profile-axis dropdown is populated from ``eligible_profile_axes``, so
    anything it lists is reachable by one click and must not raise.
    """
    session, _run, trace = _session(
        "detector_cube", depth_on_slider=depth_on_slider
    )
    eligible = trace.request.view.eligible_profile_axes()
    assert eligible, "no profile axis offered for a rank-3 key"

    sizes = {0: N_Y, 1: N_X, 2: N_Z}
    for storage_axis in eligible:
        entry_id, frame = _add_roi(session, trace, storage_axis)
        bundle = session.region.preview_roi_profile(
            entry_id,
            parent_trace=trace,
            parent_frame=frame,
            cached_plane=trace.last_bundle
)
        assert bundle.y.ndim == 1
        assert bundle.y.shape == (sizes[storage_axis],
)
        session.region.roi_set.remove(entry_id)


def test_a_cube_profile_along_the_slider_axis_reads_every_slab(qapp):
    """
    Profiling along the reduce axis is the stack-spectrum case.

    It is the one profile that leaves the drawn plane, so it is also the one
    that silently returns a single slab if the axis is mishandled. The
    fixture scales each slab by a distinct factor, which makes that visible.
    """
    session, _run, trace = _session("detector_cube", depth_on_slider=True)
    entry_id, frame = _add_roi(session, trace, 2)

    bundle = session.region.preview_roi_profile(
        entry_id,
        parent_trace=trace,
        parent_frame=frame,
        cached_plane=trace.last_bundle
)

    assert bundle.y.shape == (N_Z,
)
    # Slabs differ by a strictly increasing factor, so a sum over the same
    # ROI must increase with depth. Equal values would mean one slab was
    # read N_Z times.
    assert len(set(np.round(bundle.y, 9))) == N_Z
    assert np.all(np.diff(bundle.y) > 0)


def test_the_runtime_test_catalog_offers_a_cube():
    """
    The catalog the application loads must carry the 3-D key too.

    The headless fixture and the demo catalog are separate builders, and a
    3-D path that only exists in one of them cannot be reproduced by hand.
    """
    from nbs_viewer.models.sources.testSource import create_runs

    run = RunSource(create_runs(2)[1])

    assert "image" in run.available_keys
    assert "image_cube" in run.available_keys
    assert len(run.get_shape("image")) == 2
    assert len(run.get_shape("image_cube")) == 3


@pytest.mark.parametrize("profile_storage_axis", [0, 1, 2])
def test_one_roi_is_transformed_the_same_way_along_every_axis(
    qapp, profile_storage_axis
):
    """
    Bug 13: the transform used to reach only two of a cube's three axes.

    An ROI drawn along a plane axis was served by masking the cached plane,
    which the transform had already run on; an ROI along the slider axis was
    served by a load whose request carried ``transform=""``. Same cube, same
    ROI, ``y = y * 2``: the plane axes doubled and the slider axis did not.

    The expectation is hand-computed from the plane the user is looking at.
    Every slab of the fixture is the drawn plane plus a constant offset, so
    the whole stack is known once the plane is, and doubling it and summing
    the mask is the whole of what "sum the ROI of what I see" means.
    """
    session, _run, trace = _session("detector_cube", depth_on_slider=True)
    plane = trace.last_bundle.y.copy()

    entry_id, frame = _add_roi(session, trace, profile_storage_axis)
    region = session.region.roi_set.get(entry_id).region
    mask = region.compile_masked(frame, "inside").mask
    assert mask.any()

    plain = session.region.preview_roi_profile(
        entry_id,
        parent_trace=trace,
        parent_frame=frame,
        cached_plane=trace.last_bundle
)

    session.set_transform({"enabled": True, "text": "y * 2"})
    trace.get_plot_bundle()
    doubled = session.region.preview_roi_profile(
        entry_id,
        parent_trace=trace,
        parent_frame=frame,
        cached_plane=trace.last_bundle
)

    np.testing.assert_allclose(doubled.y, 2.0 * plain.y)

    if profile_storage_axis == 2:
        # The slider axis is the one that was wrong, so state its answer
        # outright rather than only relative to the untransformed run.
        slab_offset = float(N_Y * N_X)
        expected = np.array(
            [
                float(np.sum(2.0 * (plane + k * slab_offset)[mask]))
                for k in range(N_Z)
            ]
        )
        np.testing.assert_allclose(doubled.y, expected)
