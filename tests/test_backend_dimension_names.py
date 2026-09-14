"""
Every axis of a key gets exactly one name, and it is the key's own.

Three defects of one kind: a layer below the pipeline answering a question
about a key's dimensions with something other than what the key declares.
``BlueskyRun`` named one more axis than the array has (bug 6) and reported
every key as rank 1 (bug 7); ``CatalogRun._analyze_dimensions`` overrode a
key's declared names with a positional guess from the run's motors, which
could name two axes the same thing (bug 15).

The ``BlueskyRun`` tests drive the backend directly against a stub Tiled node,
because no ``MemoryRun`` fixture can reproduce either -- ``MemoryRun`` is the
correct one. The shapes are the maintainer's real runs: a UCAL run that labels
its dims, and a VPPEM run that has none at all and therefore needs inference.
"""

from __future__ import annotations

import numpy as np
import pytest

from nbs_viewer.models.data.bluesky import BlueskyRun
from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.run.source import RunSource
from tests.fixtures.catalog_recipes import _base_metadata, image_scan_run


# The maintainer's real runs. UCAL labels its dims, so inference never runs
# there and it is the ground truth for what inference should produce. VPPEM
# declares none, so inference has to serve it.
UCAL_KEYS = {
    "tes_mca_spectrum": ((72, 800), ("time", "tes_mca_energies")),
    "nexafs_sc": ((72,), ("time",)),
    "en_energy": ((72,), ("time",)),
    "time": ((72,), ("time",)),
}
VPPEM_KEYS = {
    "PCOEdge_image": ((201, 2160, 2560), None),
    "sampleVoltage_VSource": ((201,), None),
    "time": ((201,), None),
}


class _FakeArray:
    """
    One array node of a Tiled run.

    ``dims`` exists only when the beamline labelled it. ``_resolve_dims``
    reads the attribute inside a ``try``, so its absence is how an unlabelled
    run is spelled -- setting it to ``None`` would not be the same thing.
    """

    def __init__(self, shape, dims=None):
        self.shape = shape
        if dims is not None:
            self.dims = dims


class _FakeDataNode:
    """The ``primary/data`` container: a mapping of key name to array."""

    def __init__(self, keys):
        self._arrays = {
            name: _FakeArray(shape, dims) for name, (shape, dims) in keys.items()
        }

    def keys(self):
        return list(self._arrays)

    def __getitem__(self, name):
        return self._arrays[name]


class _FakeRun:
    """A Tiled run addressed by slash-joined path, as ``BlueskyRun`` does."""

    def __init__(self, keys, *, start=None):
        self._data = _FakeDataNode(keys)
        self.metadata = {"start": dict(start or {}), "stop": {}}

    def __getitem__(self, path):
        parts = path.split("/")
        if parts == ["primary", "data"]:
            return self._data
        if parts[:2] == ["primary", "data"] and len(parts) == 3:
            return self._data[parts[2]]
        raise KeyError(path)

    def __getattr__(self, name):
        # ``getRunKeys`` reaches for ``run.primary.descriptors``; a run without
        # them is a supported case there, reported and skipped.
        raise AttributeError(name)


def _bluesky_run(keys, **kwargs):
    return BlueskyRun(_FakeRun(keys, **kwargs), "uid", None)


@pytest.mark.parametrize(
    "key, shape",
    [
        ("PCOEdge_image", (201, 2160, 2560)),
        ("sampleVoltage_VSource", (201,)),
        ("tes_mca_spectrum", (72, 800)),
        ("nexafs_sc", (72,)),
    ],
)
def test_inference_names_every_axis_once_and_leads_with_the_event_axis(key, shape):
    """
    Inferred names must match the array's rank, leading with ``time``.

    ``range(0, ndim)`` produced ``ndim + 1`` names for every key of rank >= 2,
    so a rank-3 camera came back as ``('time','dim_0','dim_1','dim_2')``.
    Consumers pair names with axes using ``zip``, which truncates in silence:
    the camera's three axes were named ``('time','dim_0','dim_1')``, and
    ``dim_0`` is what an unrelated 1-D key gets. Normalization aligns a norm
    array to y *by axis name*, so the collision divides by the wrong axis.
    """
    run = _bluesky_run(VPPEM_KEYS)
    dims = run._infer_dims_from_shape(key, shape)

    assert len(dims) == len(shape)
    assert dims[0] == "time"
    assert len(set(dims)) == len(dims)


def test_inferred_dims_agree_with_a_labelled_run_wherever_the_name_is_knowable():
    """
    Inference's job is to reproduce what a labelled run would have said.

    UCAL is the ground truth. ``nexafs_sc`` must come back exactly right;
    ``tes_mca_spectrum`` must come back at the right rank with the right
    leading name, degrading to a placeholder only for ``tes_mca_energies``,
    which is unknowable without Tiled's metadata. This is the argument for
    the fix -- consistency with ``MemoryRun`` was never the point.
    """
    run = _bluesky_run(VPPEM_KEYS)

    for key, (shape, labelled) in UCAL_KEYS.items():
        inferred = run._infer_dims_from_shape(key, shape)
        assert len(inferred) == len(labelled), key
        assert inferred[0] == labelled[0] == "time", key

    assert run._infer_dims_from_shape("nexafs_sc", (72,)) == ("time",)
    assert run._infer_dims_from_shape("tes_mca_spectrum", (72, 800)) == (
        "time",
        "dim_1",
    )


def test_a_labelled_run_keeps_the_names_it_declares():
    """
    Inference is a fallback, and must stay one.

    ``_resolve_dims`` prefers Tiled's own ``dims``, which is why the defect
    only bit runs lacking them. A fix to inference that started overriding
    real metadata would trade one disagreement for a worse one.
    """
    run = _bluesky_run(UCAL_KEYS)

    assert run._resolve_dims("tes_mca_spectrum") == ("time", "tes_mca_energies")
    assert run._resolve_dims("en_energy") == ("time",)


def test_run_keys_report_each_keys_own_rank():
    """
    ``getRunKeys`` grouped every remaining key under rank 1 (bug 7).

    The grouping is the backend's statement of a key's rank, and the model
    layer trusts it. A 3-D camera filed as rank 1 is the same class of defect
    as bug 6: a backend-specific answer that disagrees with the array.
    """
    run = _bluesky_run(
        VPPEM_KEYS,
        start={"hints": {"dimensions": [[["sampleVoltage_VSource"], "primary"]]}},
    )
    xkeys, ykeys = run.getRunKeys()

    assert xkeys[0] == ["time"]
    assert "sampleVoltage_VSource" in xkeys[1]
    assert ykeys.get(3) == ["PCOEdge_image"]
    assert "PCOEdge_image" not in ykeys.get(1, [])


def _ucal_shaped_run():
    """
    A run with UCAL's metadata shape, in memory.

    ``en_energy`` is the scanned motor: a 1-D key whose own dims are
    ``('time',)``, named in ``start['hints']['dimensions']`` as the coordinate
    to plot against. The detector carries a real second axis, as
    ``tes_mca_spectrum`` does. Written here rather than as a shared recipe
    because what is under test is this exact metadata combination.
    """
    n_events, n_channels = 12, 8
    data = {
        "time": np.arange(n_events, dtype=float),
        "en_energy": np.linspace(200.0, 1000.0, n_events),
        "nexafs_sc": np.linspace(1.0, 2.0, n_events),
        "tes_mca_spectrum": np.arange(
            n_events * n_channels, dtype=float
        ).reshape(n_events, n_channels),
    }
    metadata = _base_metadata(
        0,
        plan_name="ucal_shaped",
        motors=["en_energy"],
        dimensions=[(["en_energy"], "primary")],
        dims={
            "time": ("time",),
            "en_energy": ("time",),
            "nexafs_sc": ("time",),
            "tes_mca_spectrum": ("time", "tes_mca_energies"),
        },
    )
    return MemoryRun(metadata, data)


@pytest.mark.parametrize("ykey", ["nexafs_sc", "tes_mca_spectrum"])
def test_with_no_x_key_selected_a_key_keeps_its_declared_dimensions(ykey):
    """
    No X key selected is the state of a freshly opened run (bug 15).

    ``_analyze_dimensions`` fell back to the run's declared motors and assigned
    them positionally, overriding names the key already declares correctly.
    UCAL settles that this is wrong rather than merely unwanted: ``en_energy``
    is the scanned motor and its dims are ``('time',)``, a key *on* the event
    axis, while ``start['hints']['dimensions']`` names it as the coordinate to
    plot against. Renaming the axis after it contradicts that metadata -- and
    it happened with nothing selected, which is the state on opening a run.
    """
    run = _ucal_shaped_run()
    declared, _ = run.get_dims(ykey, [])

    analyzed = RunSource(run).plot_axis_names(ykey, [])

    assert tuple(analyzed) == declared
    assert analyzed[0] == "time"


def test_a_declared_cube_keeps_its_own_names_with_nothing_selected():
    """
    The same, where the motor's name is also a real axis of the key.

    ``detector_cube`` is ``('time','pixel','dim_2')`` and ``pixel`` is one of
    the run's motors, so the positional fallback both renamed the event axis
    and duplicated a name.
    """
    run = image_scan_run(0)
    declared, _ = run.get_dims("detector_cube", [])

    analyzed = RunSource(run).plot_axis_names("detector_cube", [])

    assert tuple(analyzed) == declared == ("time", "pixel", "dim_2")


def test_no_two_axes_of_one_key_are_given_the_same_name():
    """
    The motor rename could collide with a real dimension of the key.

    ``detector_cube`` is ``('time','pixel','dim_2')`` and ``pixel`` is also a
    selectable motor, so selecting it renamed the event axis to ``pixel`` and
    produced ``('pixel','pixel','dim_2')``. Duplicates are not caught further
    down -- xarray constructs such an array and only warns -- and these names
    are what normalization aligns by, so the second ``pixel`` is a silent
    wrong answer waiting for a norm key.
    """
    run = RunSource(image_scan_run(0))

    # The X rule refuses a key whose name is already an axis, so a duplicate
    # cannot be produced; this pins that it is not.
    for xkeys in ([], ["pixel"], ["en_energy"], ["time"], ["row"]):
        for ykey in ("detector_cube", "detector_image"):
            names = run.plot_axis_names(ykey, xkeys)
            assert len(set(names)) == len(names), (ykey, xkeys, names)


def _second_detector_axis_run():
    """
    A cube whose detector axes are both selectable keys of their own.

    No shipped fixture and no real run seen so far has this, which is why
    bug 16 went unnoticed: ``b`` names the cube's *second* detector axis, and
    selecting it as X moved its name ahead of ``a``'s.
    """
    n_time, n_a, n_b = 3, 4, 5
    data = {
        "time": np.arange(n_time, dtype=float),
        "a": np.linspace(0.0, 1.0, n_a),
        "b": 10.0 + np.arange(n_b, dtype=float) ** 2,
        "cube": np.arange(n_time * n_a * n_b, dtype=float).reshape(
            n_time, n_a, n_b
        ),
    }
    metadata = _base_metadata(
        0,
        plan_name="second_axis",
        dims={
            "time": ("time",),
            "a": ("a",),
            "b": ("b",),
            "cube": ("time", "a", "b"),
        },
    )
    return MemoryRun(metadata, data)


@pytest.mark.parametrize("xkeys", [[], ["a"], ["b"], ["time"]])
def test_selecting_a_detector_axis_as_x_never_reorders_the_names(xkeys, qapp):
    """
    Bug 16: each name stays on the storage axis it describes.

    The ordering rule put ``time`` first, then any selected X key that was
    also a dimension, then the rest -- so selecting ``b`` labelled storage
    axis 1, length 4, as ``b``. ``KeyInfo.from_dims`` checks the count and
    uniqueness of names, not their order, so nothing downstream saw it.
    """
    model = RunSource(_second_detector_axis_run())

    assert model.plot_axis_names("cube", xkeys) == ("time", "a", "b")


def test_a_profile_against_the_second_detector_axis_has_its_values(qapp):
    """
    The consequence of bug 16, through the fetch.

    Plotted against ``b``, the line must run along the axis that is ``b``:
    five points carrying ``b``'s values. With the names reordered, the axis
    wearing ``b``'s name was ``a``'s, four long.
    """
    from nbs_viewer.models.plot.view_intent import ViewIntent
    from tests.test_run_source import _plot_request

    run = _second_detector_axis_run()
    model = RunSource(run)
    names = model.plot_axis_names("cube", ["b"])
    view = ViewIntent(plot_ndim=1, xkey="b").project(3, (3, 4, 5), names)

    bundle = model.fetch.get_plot_bundle(
        _plot_request(model, ["b"], "cube", projection=view)
    )

    np.testing.assert_allclose(bundle.x_line, run.getData("b"))
    np.testing.assert_allclose(bundle.y, run.getData("cube")[0, 0, :])


def test_a_motor_that_names_no_existing_axis_still_renames_the_event_axis():
    """
    The refusal must not disable the rule it guards.

    ``row`` lives on the event axis and collides with nothing, so selecting it
    plots that axis against it, under its name. The array's dimension is
    still ``time`` -- its description says so whatever is selected -- and the
    name is the plot layer's choice of coordinate.
    """
    run = image_scan_run(0)

    names = RunSource(run).plot_axis_names("detector_cube", ["row"])
    assert run.describe("detector_cube").dims == ("time", "pixel", "dim_2")

    assert tuple(names) == ("row", "pixel", "dim_2")
    assert np.shape(run.getData("detector_cube"))[0] == len(run.getData("row"))
