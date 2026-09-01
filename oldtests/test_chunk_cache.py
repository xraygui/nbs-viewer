import numpy as np

from nbs_viewer.models.cache.chunkCache import ChunkCache


def test_squeeze_indexed_dims_skips_missing_axes():
    result = np.zeros((2160, 2560))
    slice_info = (18, 0, slice(None), slice(None))
    out = ChunkCache._squeeze_indexed_dims(result, slice_info)
    assert out.shape == (2160, 2560)


def test_squeeze_indexed_dims_removes_length_one_axes():
    result = np.zeros((1, 1, 2160, 2560))
    slice_info = (0, 0, slice(None), slice(None))
    out = ChunkCache._squeeze_indexed_dims(result, slice_info)
    assert out.shape == (2160, 2560)


def test_is_monolithic_chunking_single_chunk_per_axis():
    chunks = ((41,), (10,), (2160,), (2560,))
    assert ChunkCache._is_monolithic_chunking(chunks) is True


def test_is_monolithic_chunking_multi_chunk():
    chunks = ((1, 1), (1,), (5, 5), (5, 5))
    assert ChunkCache._is_monolithic_chunking(chunks) is False


def test_chunk_needs_internal_slice_after_api_read():
    chunk = np.zeros((1024, 1026))
    chunk_info = {
        "internal_slices": (0, 0, slice(None), slice(None)),
        "already_sliced": True,
    }
    assert ChunkCache._chunk_needs_internal_slice(chunk, chunk_info) is False


def test_chunk_needs_internal_slice_full_chunk():
    chunk = np.zeros((1, 1, 1024, 1026))
    chunk_info = {
        "internal_slices": (0, 0, slice(None), slice(None)),
    }
    assert ChunkCache._chunk_needs_internal_slice(chunk, chunk_info) is True


def test_chunk_needs_internal_slice_cached_2d_without_flag():
    chunk = np.zeros((1024, 1026))
    chunk_info = {
        "internal_slices": (0, 0, slice(None), slice(None)),
    }
    assert ChunkCache._chunk_needs_internal_slice(chunk, chunk_info) is False


def test_coord_dim_to_array_axis_after_integer_indices():
    internal = (0, 0, 0, slice(0, 512))
    assert ChunkCache._coord_dim_to_array_axis(3, internal) == 0


def test_coord_dim_to_array_axis_2d_slice():
    internal = (0, 0, slice(0, 512), slice(0, 512))
    assert ChunkCache._coord_dim_to_array_axis(2, internal) == 0
    assert ChunkCache._coord_dim_to_array_axis(3, internal) == 1


def test_assemble_result_stitches_width_chunks():
    cache = ChunkCache()
    chunks_needed = [
        {
            "chunk_indices": (0, 0, 0, i),
            "chunk_shape": (1, 1, 512, 512),
            "internal_slices": (0, 0, 0, slice(0, 512)),
            "already_sliced": True,
        }
        for i in range(5)
    ]
    chunks_data = {
        info["chunk_indices"]: np.arange(i * 512, (i + 1) * 512, dtype=float)
        for i, info in enumerate(chunks_needed)
    }
    result = cache._assemble_result(
        chunks_data,
        chunks_needed,
        (10, 3, 2160, 2560),
        (0, 0, 0, slice(0, 2560)),
    )
    assert result.shape == (2560,)
    assert result[0] == 0
    assert result[-1] == 2559


def test_assemble_result_stitches_2d_grid():
    cache = ChunkCache()
    chunks_needed = []
    chunks_data = {}
    for row in range(2):
        for col in range(2):
            idx = (0, 0, row, col)
            chunks_needed.append(
                {
                    "chunk_indices": idx,
                    "chunk_shape": (1, 1, 512, 512),
                    "internal_slices": (
                        0,
                        0,
                        slice(0, 512),
                        slice(0, 512),
                    ),
                    "already_sliced": True,
                }
            )
            chunks_data[idx] = np.full((512, 512), row * 10 + col)

    result = cache._assemble_result(
        chunks_data,
        chunks_needed,
        (10, 3, 2160, 2560),
        (0, 0, slice(0, 1024), slice(0, 1024)),
    )
    assert result.shape == (1024, 1024)
    assert result[0, 0] == 0
    assert result[0, 512] == 1
    assert result[512, 0] == 10
    assert result[512, 512] == 11


def test_evict_lru_removes_slice_cache_when_chunks_empty():
    cache = ChunkCache(max_size_bytes=1000)
    data = np.zeros(100, dtype=np.float32)
    cache_key = ("uid", "det", (0, 0, 0, 0), (0,))
    cache.slice_cache[cache_key] = data
    cache.current_size = data.nbytes
    cache.access_times[cache_key] = 1.0

    assert cache._evict_lru() is True
    assert cache_key not in cache.slice_cache
    assert cache.current_size == 0


def test_flush_l1_to_l2_moves_tiles():
    from nbs_viewer.models.cache.zarr_l2_cache import ZarrL2Cache

    l2 = ZarrL2Cache(l2_chunks=(1, 1, 4, 4))
    cache = ChunkCache(l2=l2, l1_max_bytes=10_000)
    shape = (1, 1, 8, 8)
    cache.chunk_info[("uid", "det")] = (shape, ((1,), (1,), (8, 8), (8, 8)))
    tile = np.arange(16, dtype=np.float32).reshape(1, 1, 4, 4)
    cache.tiles[("uid", "det", (0, 0, 0, 0))] = tile
    cache.l1_tile_size = tile.nbytes
    cache.l1_tile_access_times[("uid", "det", (0, 0, 0, 0))] = 0.0
    l2.register_array("uid", "det", shape, tile.dtype)

    result = cache.flush_l1_to_l2("uid", "det")

    assert result["flushed"] == 1
    assert result["remaining_l1_tiles"] == 0
    assert l2.has_chunk("uid", "det", (0, 0, 0, 0))


def test_assemble_result_integer_index_with_variable_width_tiles():
    from nbs_viewer.models.cache.tile_indices import tiles_intersecting

    cache = ChunkCache()
    shape = (50, 5, 512, 1026)
    l2_chunks = (1, 1, 256, 256)
    slice_info = (49, slice(None), slice(None), slice(None))
    tiles_needed = tiles_intersecting(shape, l2_chunks, slice_info)
    chunks_data = {
        tile_info["chunk_indices"]: np.zeros(tile_info["chunk_shape"], dtype=float)
        for tile_info in tiles_needed
    }
    result = cache._assemble_result(
        chunks_data, tiles_needed, shape, slice_info
    )
    assert result.shape == (5, 512, 1026)
