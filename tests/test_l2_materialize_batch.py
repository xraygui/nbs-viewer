
from nbs_viewer.models.cache.tile_indices import (
    tile_fully_in_fetch_slice,
    union_l2_tile_fetch_slice,
)


def test_union_l2_tile_fetch_slice_spans_energy_tiles():
    shape = (20, 1, 64, 64)
    l2_chunks = (1, 1, 16, 16)
    tile_indices_list = [(5, 0, 1, 2), (12, 0, 1, 2)]
    fetch_slice = union_l2_tile_fetch_slice(shape, l2_chunks, tile_indices_list)
    assert fetch_slice == (slice(5, 13), slice(0, 1), slice(16, 32), slice(32, 48))


def test_tile_fully_in_fetch_slice():
    shape = (20, 1, 64, 64)
    l2_chunks = (1, 1, 16, 16)
    fetch_slice = (slice(0, 10), 0, slice(0, 32), slice(0, 32))
    assert tile_fully_in_fetch_slice(shape, l2_chunks, (3, 0, 1, 1), fetch_slice)
    assert not tile_fully_in_fetch_slice(
        shape, l2_chunks, (12, 0, 1, 1), fetch_slice
    )
