import numpy as np
import pytest

from nbs_viewer.models.cache.tile_indices import (
    chunk_grid,
    tile_global_slice,
    tiles_intersecting,
    total_tile_count,
)
from nbs_viewer.models.cache.zarr_l2_cache import ZarrL2Cache


def test_chunk_grid_trailing_tile():
    sizes = chunk_grid((1024, 1026), (256, 256))
    assert sizes[0] == (256, 256, 256, 256)
    assert sizes[1] == (256, 256, 256, 256, 2)


def test_tiles_intersecting_partial_plane():
    shape = (200, 5, 1024, 1026)
    l2_chunks = (1, 1, 256, 256)
    slice_info = (0, 0, slice(100, 200), slice(100, 300))
    tiles = tiles_intersecting(shape, l2_chunks, slice_info)
    indices = {tile["chunk_indices"] for tile in tiles}
    assert indices == {(0, 0, 0, 0), (0, 0, 0, 1)}


def test_zarr_l2_write_read_round_trip():
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 4, 4))
    shape = (2, 2, 8, 8)
    l2.register_array("run-a", "det", shape, "f4")

    tile_idx = (0, 0, 1, 1)
    tile_slice = tile_global_slice(tile_idx, shape, l2.l2_chunks)
    data = np.arange(16, dtype=np.float32).reshape(1, 1, 4, 4)
    l2.write_chunk("run-a", "det", tile_idx, data)

    assert l2.has_chunk("run-a", "det", tile_idx)
    assert l2.read_chunk("run-a", "det", tile_idx).shape == (1, 1, 4, 4)
    np.testing.assert_array_equal(l2.read_chunk("run-a", "det", tile_idx), data)

    arr = l2.open_array("run-a", "det")
    np.testing.assert_array_equal(np.asarray(arr[tile_slice]), data)


def test_completion_fraction():
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 4, 4))
    shape = (1, 1, 8, 8)
    l2.register_array("run-a", "det", shape, "f4")
    total = total_tile_count(shape, l2.l2_chunks)
    assert total == 4

    l2.write_chunk(
        "run-a",
        "det",
        (0, 0, 0, 0),
        np.zeros((1, 1, 4, 4), dtype=np.float32),
    )
    assert l2.completion_fraction("run-a", "det") == 0.25


def test_read_incomplete_tile_raises():
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 4, 4))
    l2.register_array("run-a", "det", (1, 1, 8, 8), "f4")
    with pytest.raises(KeyError):
        l2.read_chunk("run-a", "det", (0, 0, 0, 0))


def test_clear_run_removes_metadata():
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 4, 4))
    l2.register_array("run-a", "det", (1, 1, 8, 8), "f4")
    l2.write_chunk(
        "run-a",
        "det",
        (0, 0, 0, 0),
        np.zeros((1, 1, 4, 4), dtype=np.float32),
    )
    l2.clear_run("run-a")
    assert l2.completion_fraction("run-a", "det") == 0.0
