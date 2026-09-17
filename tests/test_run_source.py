"""Tests for the RunSource key-access surface."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from nbs_viewer.models.plot.view_intent import ViewIntent
from nbs_viewer.models.plot.plane.roles import DimRole
from nbs_viewer.models.plot.spec.projection import Projection
from nbs_viewer.models.plot.run.frozen_spectrum import (
    FrozenSpectrum,
    SYNTHETIC_KEY_PREFIX,
)
from nbs_viewer.models.data.key_info import KeyInfo
from nbs_viewer.models.data.memory import MemoryRun
from nbs_viewer.models.plot.spec.bundle import PlotBundle
from nbs_viewer.models.plot.spec.request import PlotRequest
from nbs_viewer.models.plot.spec.region import RectRegion
from nbs_viewer.models.plot.run.source import RunSource, x_dimension
from tests.fixtures.catalog_recipes import image_scan_run
from nbs_viewer.models.sources.fixtures import (
    make_vppem_run,
    vppem_factors,
    vppem_image
)


def _line_bundle(values, x=None, name="profile"):
    x = np.asarray(values if x is None else x, dtype=float)
    y = np.asarray(values, dtype=float)
    return PlotBundle.from_1d(y, [x], [name])


def _frozen_entry(model, key_suffix="abc", y=None, label=None):
    bundle = _line_bundle(y if y is not None else [1.0, 2.0, 3.0])
    return FrozenSpectrum(
        key=f"{SYNTHETIC_KEY_PREFIX}{key_suffix}",
        label=label or "mean(in ROI) · sampleVoltage_VSource",
        bundle=bundle,
        kind="stack_spectrum",
        source_ykey="PCOEdge_image",
        committed_xkey="sampleVoltage_VSource",
        request=PlotRequest(
            uid=model.uid,
            xkeys=("sampleVoltage_VSource",
),
            ykey="PCOEdge_image",
            norm_keys=(),
            view=Projection(
                ndim=2,
                plot_ndim=2,
                roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
                indices=(0, 0)
),
            dims=("dim_1", "dim_2"),
            region=RectRegion(x0=0.0, x1=1.0, y0=0.0, y1=1.0),
            profile_axis=1,
            spatial_reduce="mean"
),
        source_key=("sampleVoltage_VSource", "PCOEdge_image", model.uid)
)


def _plot_request(model, xkeys, ykey, plot_ndim=1, projection=None, **kwargs):
    shape = model.get_shape(ykey)
    if projection is None:
        projection = ViewIntent(plot_ndim=plot_ndim).project(len(shape), shape)
    return PlotRequest(
        uid=model.uid,
        xkeys=tuple(xkeys),
        ykey=ykey,
        norm_keys=tuple(kwargs.pop("norm_keys", ()) or ()),
        view=projection,
        dims=tuple(model.plot_axis_names(ykey, xkeys)),
        transform=kwargs.pop("transform", "") or "",
        **kwargs
)


def test_run_source_alias():
    assert RunSource is RunSource


def test_key_table_catalog_and_frozen(qapp):
    """
    Catalog keys are hinted=True until get_hinted_keys is confirmed.

    Synthetic rows carry synthetic=True and the friendly frozen label.
    render_hint is filled from get_render_mode_hint when present, else None.
    """
    model = RunSource(make_vppem_run())
    entry = _frozen_entry(model)
    model.register_frozen_spectrum(entry)

    table = model.key_table()
    assert "PCOEdge_image" in table
    assert "PCOEdge_stats" in table
    assert "i0" in table
    assert entry.key in table

    image_info = table["PCOEdge_image"]
    assert isinstance(image_info, KeyInfo)
    assert image_info.synthetic is False
    assert image_info.hinted is True
    assert image_info.label == "PCOEdge_image"
    assert image_info.shape == (11, 24, 32)
    assert image_info.render_hint is None

    frozen_info = table[entry.key]
    assert frozen_info.synthetic is True
    assert frozen_info.hinted is False
    assert frozen_info.label == entry.label
    assert frozen_info.shape == (3,
)
    assert frozen_info.render_hint is None


def test_read_frozen_skips_catalog_get_data(qapp):
    model = RunSource(make_vppem_run())
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    get_data = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    model._run.getData = get_data

    np.testing.assert_allclose(model.read(entry.key), [10.0, 20.0, 30.0])
    get_data.assert_not_called()


def test_describe_and_plot_axis_names_answer_different_questions(qapp):
    """
    The description is static; the displayed names follow the X selection.

    They used to be one call, which is why it needed the selection passed in
    and why the answer could not be cached. Here ``PCOEdge_image`` keeps the
    dimensions it declares whatever is selected, while the plot axis names
    rename the event axis after whatever is being plotted against it.
    """
    model = RunSource(make_vppem_run())
    xkeys = ["sampleVoltage_VSource"]

    info = model.describe("PCOEdge_image")
    assert info.shape == (11, 24, 32)
    assert info.dims == ("time", "dim_1", "dim_2")
    assert model.describe("PCOEdge_image").dims == info.dims

    assert model.plot_axis_names("PCOEdge_image", xkeys) == (
        "sampleVoltage_VSource",
        "dim_1",
        "dim_2"
)


def _info(name, **axes):
    return KeyInfo.from_dims(name, tuple(axes), tuple(axes.values()))


@pytest.mark.parametrize(
    "x, expected",
    [
        (_info("en_energy", time=5), "time"),  # a motor on the event axis
        (_info("mca_energies", pixel=3), "pixel"),  # on a detector axis
        (_info("time", time=5), None),  # the axis's own coordinate
        (_info("pixel", time=5), None),  # its name is already an axis
        (_info("en_energy", time=4), None),  # another length
        (_info("en_energy", other=5), None),  # on an axis the key lacks
        (_info("grid", time=5, pixel=3), None),  # not 1-D
        (None, None),  # nothing selected, or not on this run
    ],
)
def test_the_x_rule_is_a_function_of_two_descriptions(x, expected):
    """
    X attaches to its own dimension, or to nothing; nothing is reordered.

    Every refusal leaves the key its own names. The name-already-an-axis case
    is bug 15's second trigger, where renaming the event axis after ``pixel``
    gave a cube two axes called ``pixel``.
    """
    y = _info("det", time=5, pixel=3)

    assert x_dimension(y, x) == expected


def test_load_coords_reads_the_axis_keys_and_never_the_key(qapp):
    """
    What labels an axis is a 1-D read of the key its description names.

    The dimension sliders and the frame an ROI is compiled against both need
    coordinates, and a camera stack is the last thing to read for them. Under
    the X selection the event axis carries the motor's values and name; the
    detector axes, which have no key of their own, carry their indices.
    """
    model = RunSource(make_vppem_run())
    read = []
    original = model.run.getData

    def recording(key, slice_info=None):
        read.append(key)
        return original(key, slice_info)

    model.run.getData = recording
    coords = model.load_coords(
        "PCOEdge_image", None, ["sampleVoltage_VSource"]
    )

    assert "PCOEdge_image" not in read
    assert set(coords) == {"sampleVoltage_VSource", "dim_1", "dim_2"}
    np.testing.assert_allclose(
        coords["sampleVoltage_VSource"].values,
        original("sampleVoltage_VSource")
)
    np.testing.assert_allclose(coords["dim_2"].values, np.arange(32.0))


def test_a_second_x_key_rides_along_as_a_non_dimension_coordinate(qapp):
    """
    Only one key can name an axis; another on the same axis is kept beside it.

    The dimension sliders show it next to the axis's own value -- what the
    analysis this replaced called associated data.
    """
    model = RunSource(make_vppem_run())

    coords = model.load_coords(
        "PCOEdge_image", None, ["sampleVoltage_VSource", "i0"]
    )

    assert coords["sampleVoltage_VSource"].dims == ("sampleVoltage_VSource",
)
    assert coords["i0"].dims == ("sampleVoltage_VSource",
)
    np.testing.assert_allclose(coords["i0"].values, model.run.getData("i0"))


def test_an_x_key_on_a_detector_axis_names_that_axis(qapp):
    """
    The rule follows X's own dimension, whichever it is.

    ``en_energy`` is declared on this fixture's ``pixel`` axis, so selecting
    it plots the columns against energy. The analysis this replaced only ever
    renamed ``time``, so it left them plotted against their index.
    """
    run = image_scan_run(0, n_y=6, n_x=5)
    model = RunSource(run)

    assert model.plot_axis_names("detector_image", ["en_energy"]) == (
        "time",
        "en_energy"
)
    bundle = _plot_request(model, ["en_energy"], "detector_image").plot_bundle(model)
    np.testing.assert_allclose(bundle.x_line, run.getData("en_energy"))
    np.testing.assert_allclose(bundle.y, run.getData("detector_image")[0])


def test_get_plot_bundle_1d_closed_form(qapp):
    model = RunSource(make_vppem_run())
    a, b, c = vppem_factors()
    expected = a * b.mean() * c.mean()
    bundle = _plot_request(model, ["sampleVoltage_VSource"], "PCOEdge_stats").plot_bundle(model)
    assert bundle.render_mode == "line"
    np.testing.assert_allclose(bundle.y, expected)
    np.testing.assert_allclose(
        bundle.x_line, model.read("sampleVoltage_VSource")
    )


def test_get_plot_bundle_index_slice_closed_form(qapp):
    model = RunSource(make_vppem_run())
    spec = Projection(
        ndim=3,
        plot_ndim=2,
        roles=(DimRole.INDEX, DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(4, 0, 0)
)
    bundle = _plot_request(
            model,
            ["sampleVoltage_VSource"],
            "PCOEdge_image",
            plot_ndim=2,
            projection=spec
).plot_bundle(model)
    expected = vppem_image()[4]
    np.testing.assert_allclose(bundle.y, expected[::-1, :])


def test_get_plot_bundle_mean_mean_matches_stats(qapp):
    model = RunSource(make_vppem_run())
    spec = Projection(
        ndim=3,
        plot_ndim=1,
        roles=(DimRole.MEAN, DimRole.MEAN, DimRole.MEAN),
        indices=(0, 0, 0),
        axis_order=(1, 2, 0)
)
    cube_bundle = _plot_request(
            model,
            ["sampleVoltage_VSource"],
            "PCOEdge_image",
            plot_ndim=1,
            projection=spec
).plot_bundle(model)
    stats_bundle = _plot_request(model, ["sampleVoltage_VSource"], "PCOEdge_stats").plot_bundle(model)
    np.testing.assert_allclose(cube_bundle.y, stats_bundle.y)


def test_get_plot_bundle_frozen_uses_read(qapp):
    model = RunSource(make_vppem_run())
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    get_data = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))
    model._run.getData = get_data

    bundle = _plot_request(model, ["sampleVoltage_VSource"], entry.key).plot_bundle(model)
    np.testing.assert_allclose(bundle.y, [10.0, 20.0, 30.0])
    # ``load`` always passes the slice through, so the catalog sees an
    # explicit ``None`` where ``read`` used to omit the argument.
    get_data.assert_called_once_with("sampleVoltage_VSource", None)


# ---------------------------------------------------------------------------
# What the single dispatch has to keep true
# ---------------------------------------------------------------------------
#
# ``RunSource`` used to ask "is this key frozen?" in seven places. Six of them
# now read a fact off the key's description instead, and one -- ``_source`` --
# picks the source that answers. These three cases were reachable but untested,
# which meant the rewrite had nothing to check it against; each was confirmed
# to fail if the branch it exercises is removed.


def test_a_declared_render_mode_reaches_the_bundle(qapp):
    """
    A key's ``render_mode`` hint overrides what the coordinates imply.

    The same image classifies as ``image`` from its coordinates and as
    ``mesh`` when the run says so, which is the whole point of the override.
    The hint now travels on the key's description rather than being looked up
    from the run's plot hints as a fallback, so this is what says the two
    routes give the same answer.
    """
    plain = image_scan_run(0)
    declared = MemoryRun(
        {
            **plain.metadata,
            "plot_hints": {
                "primary": [
                    {"signal": "detector_image", "render_mode": "mesh"}
                ]
            },
        },
        {key: np.asarray(plain.getData(key)) for key in plain.available_keys}
)

    assert declared.render_mode_hint("detector_image") == "mesh"
    assert declared.describe("detector_image").render_hint == "mesh"

    def _mode(run):
        source = RunSource(run)
        return _plot_request(source, ["en_energy"], "detector_image", plot_ndim=2).plot_bundle(source).render_mode

    assert _mode(plain) == "image"
    assert _mode(declared) == "mesh"


def test_a_one_dimensional_frozen_result_is_labelled_with_its_label(qapp):
    """
    A frozen spectrum's axis is named after the ROI it came from.

    Nothing else on the run knows that name -- it is not a data key -- so if
    the bundle does not take it from the description, the axis falls back to
    whatever the reduction happened to leave behind.
    """
    model = RunSource(make_vppem_run())
    entry = _frozen_entry(model, y=[10.0, 20.0, 30.0])
    model.register_frozen_spectrum(entry)
    model._run.getData = MagicMock(return_value=np.array([0.0, 1.0, 2.0]))

    bundle = _plot_request(model, ["sampleVoltage_VSource"], entry.key).plot_bundle(model)

    assert bundle.axis_names == [entry.label]


def test_a_frozen_norm_follows_the_event_axis_index(qapp):
    """
    A frozen stack spectrum is per-event, so it takes Y's event-axis slice.

    A catalog norm is matched to Y's axes *by name*; a frozen one has no name
    in common with anything, so it is sliced with Y's own slice instead. With
    a rank-3 cube plotted as a line, both leading axes are indexed to a single
    event, and the two rules give different answers: the frozen rule divides
    by that event's value, and matching by name raises because a 6-long norm
    cannot broadcast onto a 3-long plot axis.
    """
    run = image_scan_run(0, n_y=6, n_x=5, n_z=3)
    model = RunSource(run)
    entry = _frozen_entry(model, y=[2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
    model.register_frozen_spectrum(entry)
    assert model.describe(entry.key).synthetic is True
    assert model.describe("detector_cube").synthetic is False

    shape = model.get_shape("detector_cube")
    projection = ViewIntent(plot_ndim=1).project(len(shape), shape)
    assert projection.base_slice() == (0, 0, slice(None))

    bundle = PlotRequest(
            uid=model.uid,
            xkeys=("pixel",
),
            ykey="detector_cube",
            norm_keys=(entry.key,
),
            view=projection,
            dims=tuple(model.plot_axis_names("detector_cube", ["pixel"]))
).plot_bundle(model)

    # cube[0, 0, :] is [0, 30, 60]; the frozen norm at event 0 is 2.0.
    np.testing.assert_allclose(bundle.y, [0.0, 15.0, 30.0])
