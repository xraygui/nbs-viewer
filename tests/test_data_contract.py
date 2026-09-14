"""
What a data source returns: one static description, one labelled array.

Both sources -- a catalog run and a frozen synthetic key -- answer
``describe`` and ``load``. The description says what a key *is* and reads
nothing; the array arrives with its dimensions named and its coordinates
attached. Between them they replace four different ways of asking for key
metadata, and they enforce at the source what a consumer used to patch
downstream by padding a name list until it fit.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from nbs_viewer.models.data.array_contract import (
    ARITHMETIC_JOIN,
    index_placeholders,
    labelled_array,
    surviving_dims,
)
from nbs_viewer.models.data.base import render_mode_hint_for
from nbs_viewer.models.data.key_info import KeyInfo
from nbs_viewer.models.plot.run_source import RunSource
from nbs_viewer.models.sources.fixtures import make_vppem_run
from tests.fixtures.catalog_recipes import image_scan_run


# ---------------------------------------------------------------------------
# The library settings, which are silent-wrong-answer generators by default
# ---------------------------------------------------------------------------


def test_the_arithmetic_join_is_exact():
    """
    xarray's default join drops the rows two arrays do not share.

    Measured before pinning it: a 5-row array divided by a 4-row one returns
    4 rows, with nothing raised. Dividing a detector by a normalization
    channel is the pipeline's most common operation, so a join that quietly
    shortens the answer is the worst available default.
    """
    assert ARITHMETIC_JOIN == "exact"
    assert xr.get_options()["arithmetic_join"] == "exact"

    long = xr.DataArray(np.ones(5), dims=["time"], coords={"time": np.arange(5.0)})
    short = xr.DataArray(np.ones(4), dims=["time"], coords={"time": np.arange(4.0)})
    with pytest.raises(xr.AlignmentError):
        long / short


def test_two_timestreams_on_different_bases_refuse_to_divide():
    """
    The case coordinates exist for, and the reason they are not optional.

    With fly-scanned data each detector is its own timestream, so two keys
    whose axis is named ``time`` no longer share that axis. Equal length is
    what makes it dangerous -- a length mismatch already raises, so the only
    silent failure is two detectors running at the same rate out of phase,
    which is the normal case rather than the exotic one.
    """
    base = np.linspace(0.0, 1.0, 64)
    det = xr.DataArray(np.ones(64), dims=["time"], coords={"time": base})
    other = xr.DataArray(
        np.ones(64), dims=["time"], coords={"time": base + 0.003}
    )

    with pytest.raises(xr.AlignmentError):
        det / other

    # Names alone would not have caught it: same shape, same axis name.
    assert det.shape == other.shape
    assert det.dims == other.dims


# ---------------------------------------------------------------------------
# Enforcement at the boundary
# ---------------------------------------------------------------------------


def test_a_source_that_disagrees_with_its_own_arrays_is_rejected():
    """
    Name count against rank, enforced once where the answer is made.

    A consumer used to pad or truncate the name list until it matched, which
    is what let bug 6 live: a backend naming one axis too many was
    indistinguishable from a backend naming them correctly, and the extra
    name simply fell off the end of a ``zip``.
    """
    with pytest.raises(ValueError, match="rank 2 but 1 dimension names"):
        KeyInfo.from_dims("det", ("time",), (4, 5))
    with pytest.raises(ValueError, match="rank 2 but 3 dimension names"):
        KeyInfo.from_dims("det", ("time", "dim_1", "dim_2"), (4, 5))


def test_two_axes_cannot_be_given_one_name():
    """
    xarray accepts duplicate dims with a warning; the contract does not.

    Its warning says most functionality "is likely to fail silently" -- which
    is not a guard for a pipeline that aligns a normalization array to its
    detector *by axis name*. Bug 15 produced exactly this.
    """
    with pytest.raises(ValueError, match="names two axes the same thing"):
        KeyInfo.from_dims("det", ("pixel", "pixel"), (4, 5))
    with pytest.raises(ValueError, match="duplicate dimension names"):
        labelled_array(np.zeros((4, 5)), ("pixel", "pixel"), name="det")


def test_the_description_carries_names_and_lengths_together():
    """
    One mapping, not a name tuple beside a shape tuple that can disagree.
    """
    info = KeyInfo.from_dims("det", ("time", "pixel"), (4, 5))

    assert info.axes == {"time": 4, "pixel": 5}
    assert info.dims == ("time", "pixel")
    assert info.shape == (4, 5)
    assert info.ndim == 2


# ---------------------------------------------------------------------------
# The two calls, on a catalog run
# ---------------------------------------------------------------------------


def test_describe_answers_the_same_thing_every_time():
    """
    The description depends on the key alone, so it can be cached.

    It used to take the X selection, because the selection renamed the event
    axis -- two different facts in one field. What to plot against is a
    coordinate choice, and it is asked for separately.
    """
    run = image_scan_run(0)
    info = run.describe("detector_cube")

    assert info.dims == ("time", "pixel", "dim_2")
    assert info.shape == (30, 40, 3)
    assert run.describe("detector_cube") == info

    source = RunSource(run)
    for xkeys in ([], ["en_energy"], ["pixel"], ["row"]):
        assert source.describe("detector_cube").dims == info.dims
        # ...while the *displayed* names do follow the selection.
        assert len(source.plot_axis_names("detector_cube", xkeys)) == 3


def test_the_description_says_where_each_coordinate_comes_from():
    """
    Which key supplies an axis's coordinate is static, so it is described.

    A consumer that only needs to label an axis can then read that 1-D key
    and nothing else. Two sources: a plot hint naming one, and a key of the
    axis's own name. An axis with neither has only its index.
    """
    from tests.fixtures.catalog_recipes import mca_scan_run

    assert dict(image_scan_run(0).describe("detector_cube").coords) == {
        "time": ("time",),
        "pixel": ("pixel",),
        "dim_2": ("dim_2",),
    }
    assert dict(make_vppem_run().describe("PCOEdge_image").coords) == {
        "time": ("time",)
    }
    assert dict(mca_scan_run().describe("mca").coords) == {
        "time": ("time",),
        "dim_1": ("mca_energies",),
    }
    walked = ("config", "mca", "mca_energies")
    assert mca_scan_run(hint_path=walked).describe("mca").coords["dim_1"] == walked


def test_load_names_every_axis_and_attaches_the_coordinates_it_has():
    """
    A dimension gets a coordinate when the run holds a 1-D key of that name.

    That is how a labelled Bluesky run spells its axes: ``time`` for the
    event axis, and a detector-internal axis under its own name when the
    beamline supplies one.
    """
    run = image_scan_run(0)
    cube = run.load("detector_cube")

    assert isinstance(cube, xr.DataArray)
    assert cube.dims == ("time", "pixel", "dim_2")
    assert cube.shape == (30, 40, 3)
    assert set(cube.coords) == {"time", "pixel", "dim_2"}
    np.testing.assert_allclose(cube.coords["pixel"].values, run.getData("pixel"))


def test_an_axis_with_no_key_of_its_own_keeps_a_bare_name():
    """
    The guard is strongest where there is real information, and degrades.

    The VPPEM run declares no dims at all, so its camera's detector-internal
    axes are placeholders with nothing behind them. They stay bare, and
    ``exact`` falls back to the shape check it was before -- which is no
    worse than the status quo, and no reason to withhold the coordinate from
    the event axis, which does have one.
    """
    run = make_vppem_run()
    image = run.load("PCOEdge_image")

    assert image.dims == ("time", "dim_1", "dim_2")
    assert set(image.coords) == {"time"}


def test_slicing_drops_the_axes_it_indexes_away_and_slices_the_rest():
    """
    An integer item removes an axis; the coordinates follow the data.

    The surviving names are derived from the same slice tuple the data is
    read with, so the two agree by construction. They used to be two separate
    derivations, which is the shape of most of this plan's bugs.
    """
    run = image_scan_run(0)

    assert surviving_dims(("time", "pixel", "dim_2"), (0, slice(None), 2)) == (
        "pixel",
    )

    sliced = run.load("detector_cube", (slice(2, 6), slice(None), 1))
    assert sliced.dims == ("time", "pixel")
    assert sliced.shape == (4, 40)
    np.testing.assert_allclose(
        sliced.coords["time"].values, run.getData("time")[2:6]
    )

    single = run.load("detector_cube", (3,))
    assert single.dims == ("pixel", "dim_2")
    assert single.shape == (40, 3)


def test_a_normalization_divides_by_coordinate_and_not_by_luck():
    """
    The contract's point, end to end on a fixture.

    Both keys come off the same run through ``load``, so the event axis
    carries the same coordinate values and the division aligns on them.
    """
    run = image_scan_run(0)
    image = run.load("detector_image")
    norm = run.load("en_energy")

    # ``en_energy`` lives on the ``pixel`` axis in this fixture, so alignment
    # picks the right axis rather than the first one that happens to fit.
    assert norm.dims == ("pixel",)
    ratio = image / norm
    assert ratio.dims == ("time", "pixel")
    np.testing.assert_allclose(
        ratio.values, image.values / norm.values[None, :]
    )


@pytest.mark.parametrize(
    "hint_path", [("mca_energies",), ("config", "mca", "mca_energies")]
)
@pytest.mark.parametrize("xkeys", [[], ["en_energy"]])
def test_a_plot_hint_supplies_the_coordinate_of_the_axis_it_names(
    hint_path, xkeys, qapp
):
    """
    Plot-hint ``axes`` give a detector axis its coordinate.

    Every backend implements this path and, until this fixture, nothing
    exercised it. ``mca``'s bins have no key of their own name; the run's plot
    hints say ``mca_energies`` supplies them. Plotted along its bins, the line
    must run against those energies -- unevenly spaced, so an index range in
    their place does not pass -- whatever is selected as X, since X lives on
    the event axis.
    """
    from tests.fixtures.catalog_recipes import mca_scan_run
    from tests.test_run_source import _plot_request

    run = mca_scan_run(hint_path=hint_path)
    model = RunSource(run)

    bundle = model.fetch.get_plot_bundle(_plot_request(model, xkeys, "mca"))

    np.testing.assert_allclose(bundle.x_line, run.getData("mca_energies"))
    np.testing.assert_allclose(bundle.y, run.getData("mca")[0])


# ---------------------------------------------------------------------------
# The same two calls, on the other source
# ---------------------------------------------------------------------------


def test_a_frozen_key_answers_the_same_protocol(qapp):
    """
    One protocol over both sources, which is what collapses the dispatch.

    ``RunSource`` branched on "is this frozen?" in five separate methods. A
    union performed once is an abstraction; performed five times it is a
    copy.
    """
    from tests.test_frozen_spectrum import _frozen_entry, _run_model

    model = _run_model()
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)

    info = model.describe(entry.key)
    assert info.synthetic is True
    assert info.shape == (3,)

    loaded = model.load(entry.key)
    assert isinstance(loaded, xr.DataArray)
    assert loaded.dims == info.dims
    np.testing.assert_allclose(loaded.values, [10.0, 20.0, 30.0])

    sliced = model.load(entry.key, (slice(1, None),))
    np.testing.assert_allclose(sliced.values, [20.0, 30.0])


def test_read_returns_bare_values_and_still_checks_them(qapp):
    """
    The pipeline is still numpy, so ``read`` drops the labels -- not the checks.

    It asks for no coordinates, because each one costs a read of its own key
    that a caller discarding the labels gains nothing from.
    """
    model = RunSource(make_vppem_run())

    values = model.read("PCOEdge_image")
    assert isinstance(values, np.ndarray)
    assert values.shape == (11, 24, 32)

    model._run.get_dims = lambda key, xkeys: (("time", "dim_1"), {})
    with pytest.raises(ValueError, match="a source must agree"):
        model.read("PCOEdge_image")


# ---------------------------------------------------------------------------
# What moved, and what it closed
# ---------------------------------------------------------------------------


def test_render_mode_hint_override():
    """
    Moved down with ``describe``: it reads run metadata and nothing else.
    """
    hints = {
        "primary": [
            {
                "signal": "detector_image",
                "render_mode": "mesh",
            }
        ]
    }
    assert render_mode_hint_for(hints, "detector_image") == "mesh"
    assert render_mode_hint_for(hints, "other") is None
    assert image_scan_run(0).render_mode_hint("detector_image") is None


def test_the_data_layer_imports_nothing_from_the_plot_layer():
    """
    The violation this step closed, pinned so it cannot reopen.

    ``models/data/bluesky.py`` imported a key-prefix convention upward from
    ``models/plot``. The convention moved down; the class that follows it did
    not, because it carries a ``PlotBundle`` and belongs where that does.
    """
    data_root = Path(__file__).resolve().parents[1] / "nbs_viewer" / "models" / "data"
    offenders = []
    for path in sorted(data_root.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "models.plot" in node.module or node.module.startswith("..plot"):
                    offenders.append(f"{path.name}: {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "models.plot" in alias.name:
                        offenders.append(f"{path.name}: {alias.name}")
    assert offenders == []


def test_index_placeholders_replace_a_stored_field():
    """
    ``arange`` per axis, derived when a caller wants it.

    It used to be a field on every description, built and carried whether or
    not anything read it.
    """
    assert [len(a) for a in index_placeholders((3, 5))] == [3, 5]
    np.testing.assert_allclose(index_placeholders((3,))[0], [0.0, 1.0, 2.0])
