"""
The block cache, against a stub reader.

``BlockCache`` takes whatever reads a run's keys as a constructor argument,
so none of this needs a catalog, a Qt object or a ``RunSource``. The window
arithmetic that decides whether a read happens at all is the point: it is
most of the class and it touches the reader not at all.

Modelled on ``test_chunk_cache_l2.py``, which tests the data-layer chunk
cache the same way.
"""

from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr

from nbs_viewer.models.plot.run.cache import BlockCache
from nbs_viewer.models.plot.spec.plan import FetchPlan

DIMS = ("time", "row", "col")
SHAPE = (6, 5, 4)


class _StubReader:
    """
    The four methods ``BlockCache`` requires, and a count of the reads.

    Every key is a distinct ramp over ``SHAPE`` so a narrowed block can be
    compared against the same window taken from the whole array.
    """

    def __init__(self, synthetic=()):
        self.loads = []
        self.reads = []
        self._synthetic = set(synthetic)

    def whole(self, key, dims=DIMS):
        """The full array for a key, shaped by the dimensions it has."""
        shape = tuple(SHAPE[DIMS.index(dim)] for dim in dims)
        base = np.arange(int(np.prod(shape)), dtype=float).reshape(shape)
        return base + 1000.0 * (len(key) % 7)

    def load(self, key, slice_info, *, xkeys=(), dims=DIMS):
        self.loads.append((key, tuple(slice_info)))
        dims = tuple(dims)
        values = self.whole(key, dims)[tuple(slice_info)]
        names = [
            dim
            for dim, item in zip(dims, slice_info, strict=True)
            if not isinstance(item, int)
        ]
        coords = {
            name: np.arange(size, dtype=float)
            for name, size in zip(names, values.shape, strict=True)
        }
        return xr.DataArray(values, dims=names, coords=coords)

    def read(self, key, slice_info=None):
        self.reads.append((key, slice_info))
        values = self.whole(key)
        return values if slice_info is None else values[tuple(slice_info)]

    def describe(self, key):
        return SimpleNamespace(synthetic=key in self._synthetic)

    def plot_axis_names(self, key, xkeys):
        return ["time"]


def _plan(slice_info, *, ykey="det", xkeys=(), norm_keys=(), dims=DIMS):
    return FetchPlan(
        ykey=ykey,
        xkeys=tuple(xkeys),
        norm_keys=tuple(norm_keys),
        slice_info=tuple(slice_info),
        dims=tuple(dims),
    )


def _full():
    return _plan((slice(0, 6), slice(0, 5), slice(0, 4)))


def test_a_repeated_plan_is_served_without_a_read():
    reader = _StubReader()
    cache = BlockCache(reader)

    first, _ = cache.block(_full())
    second, _ = cache.block(_full())

    assert len(reader.loads) == 1
    np.testing.assert_array_equal(first.values, second.values)


def test_a_contained_plan_is_narrowed_out_of_the_held_block():
    """
    Shrinking a crop asks for a sub-block of what is in memory.

    The narrowed result must equal the same window of the whole array, or
    the offsets into the held block are wrong.
    """
    reader = _StubReader()
    cache = BlockCache(reader)

    cache.block(_full())
    narrowed, _ = cache.block(
        _plan((slice(0, 6), slice(1, 4), slice(2, 4)))
    )

    assert len(reader.loads) == 1
    expected = reader.whole("det")[:, 1:4, 2:4]
    np.testing.assert_array_equal(narrowed.values, expected)


def test_an_open_ended_held_slice_contains_a_bounded_one():
    reader = _StubReader()
    cache = BlockCache(reader)

    cache.block(_plan((slice(None), slice(None), slice(None))))
    narrowed, _ = cache.block(
        _plan((slice(2, 5), slice(None), slice(None)))
    )

    assert len(reader.loads) == 1
    np.testing.assert_array_equal(
        narrowed.values, reader.whole("det")[2:5, :, :]
    )


@pytest.mark.parametrize(
    "wanted, why",
    [
        ((slice(0, 6), slice(0, 5), slice(0, 4)), "wider on an axis"),
        ((slice(0, 6), slice(1, 5), slice(0, 4)), "starts before the held"),
        ((slice(None), slice(2, 4), slice(0, 4)), "unbounded past the held"),
    ],
)
def test_a_plan_reaching_outside_the_held_block_re_reads(wanted, why):
    reader = _StubReader()
    cache = BlockCache(reader)

    cache.block(_plan((slice(1, 5), slice(2, 4), slice(0, 4))))
    cache.block(_plan(wanted))

    assert len(reader.loads) == 2, why


def test_a_different_index_on_an_indexed_axis_re_reads():
    """
    An integer item indexes its axis away, so it cannot be narrowed into.
    """
    reader = _StubReader()
    cache = BlockCache(reader)

    cache.block(_plan((2, slice(0, 5), slice(0, 4))))
    cache.block(_plan((3, slice(0, 5), slice(0, 4))))

    assert len(reader.loads) == 2


def test_a_different_key_re_reads_even_at_the_same_window():
    reader = _StubReader()
    cache = BlockCache(reader)

    cache.block(_full())
    cache.block(_plan((slice(0, 6), slice(0, 5), slice(0, 4)), ykey="other"))

    assert len(reader.loads) == 2


def test_clear_forces_the_next_plan_to_read():
    reader = _StubReader()
    cache = BlockCache(reader)

    cache.block(_full())
    cache.clear()
    cache.block(_full())

    assert len(reader.loads) == 2


def test_a_norm_is_read_once_and_held_beside_the_block():
    """
    Toggling a normalization already read costs nothing.

    The norm is read against the *held* block, so a later narrower plan
    narrows both by the same window rather than re-reading either.
    """
    reader = _StubReader()
    cache = BlockCache(reader)

    cache.block(_full())
    _, norms = cache.block(_plan(_full().slice_info, norm_keys=("i0",)))
    assert [key for key, _ in reader.loads] == ["det", "i0"]
    assert norms[0].sizes["time"] == 6

    _, again = cache.block(
        _plan((slice(2, 5), slice(0, 5), slice(0, 4)), norm_keys=("i0",))
    )
    assert [key for key, _ in reader.loads] == ["det", "i0"]
    assert again[0].sizes["time"] == 3
    np.testing.assert_array_equal(
        again[0].values, norms[0].values[2:5]
    )


def test_a_synthetic_norm_takes_the_blocks_names_and_no_coordinates():
    """
    A frozen synthetic norm shares no name with anything, so it is named
    after the block's leading axes and aligned by position alone.
    """
    reader = _StubReader(synthetic=("roi",))
    cache = BlockCache(reader)

    _, norms = cache.block(_plan(_full().slice_info, norm_keys=("roi",)))

    assert reader.reads and reader.reads[0][0] == "roi"
    assert norms[0].dims == DIMS
    assert not norms[0].coords
