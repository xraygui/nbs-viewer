import numpy as np

from nbs_viewer.models.cache.chunkCache import ChunkCache
from nbs_viewer.models.cache.zarr_l2_cache import ZarrL2Cache


class _FakeAccessor:
    def __init__(self, data: np.ndarray, chunks):
        self.shape = data.shape
        self.chunks = chunks
        self.dtype = data.dtype
        self._data = data

    def read(self, slice=None):
        if slice is None:
            return self._data
        return self._data[slice]


class _FakeRun:
    def __init__(self, uid: str, key: str, accessor: _FakeAccessor):
        self.start = {"uid": uid}
        self._accessor = accessor
        self._key = key

    def __getitem__(self, path):
        if path == ("primary", "data", self._key):
            return self._accessor
        raise KeyError(path)


def _make_cache(
    l2_chunks=(1, 1, 4, 4),
    max_size_bytes=int(1e9),
    l1_max_bytes=128_000_000,
):
    l2 = ZarrL2Cache(l2_chunks=l2_chunks)
    return (
        ChunkCache(
            max_size_bytes=max_size_bytes,
            l1_max_bytes=l1_max_bytes,
            l2=l2,
        ),
        l2,
    )


def test_seeds_zarr_tiles_after_tiled_fetch():
    data = np.arange(256, dtype=np.float32).reshape(1, 1, 16, 16)
    chunks = ((1,), (1,), (8, 8), (8, 8))
    run = _FakeRun("uid-1", "det", _FakeAccessor(data, chunks))
    cache, l2 = _make_cache(l2_chunks=(1, 1, 4, 4))

    slice_info = (0, 0, slice(0, 8), slice(0, 8))
    result = cache.get_data(run, "det", slice_info)

    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    assert result.shape == (8, 8)
    for tile_idx in ((0, 0, 0, 0), (0, 0, 0, 1), (0, 0, 1, 0), (0, 0, 1, 1)):
        assert l2.has_chunk(run.start["uid"], "det", tile_idx)


def test_second_fetch_uses_l1_without_tiled_reads():
    data = np.arange(256, dtype=np.float32).reshape(1, 1, 16, 16)
    accessor = _FakeAccessor(data, ((1,), (1,), (8, 8), (8, 8)))
    run = _FakeRun("uid-1", "det", accessor)
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 4, 4))

    slice_info = (0, 0, slice(0, 4), slice(0, 4))
    cache.get_data(run, "det", slice_info)

    read_count = 0
    original_read = accessor.read

    def counting_read(slice=None):
        nonlocal read_count
        read_count += 1
        return original_read(slice=slice)

    accessor.read = counting_read

    result = cache.get_data(run, "det", slice_info)
    assert result.shape == (4, 4)
    assert read_count == 0
    assert cache.l2_hits == 0


def test_large_tiled_fetch_skips_slice_cache():
    shape = (40, 1, 16, 16)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    chunks = ((1,) * 40, (1,), (16, 16), (16, 16))
    run = _FakeRun("uid-large", "det", _FakeAccessor(data, chunks))
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 4, 4))

    cache.get_data(run, "det", (slice(None), 0, slice(None), slice(None)))

    assert len(cache.slice_cache) == 0


def test_narrowed_roi_slab_cached_for_repeat_slice():
    shape = (50, 5, 512, 1026)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    chunks = ((1,) * 50, (1,) * 5, (256, 256), (256, 256, 256, 256, 2))
    accessor = _FakeAccessor(data, chunks)
    run = _FakeRun("uid-roi", "det", accessor)
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 256, 256))

    slice_info = (48, slice(None), slice(100, 300), slice(200, 500))
    cache.get_data(run, "det", slice_info)
    assert len(cache.slice_cache) == 1

    read_count = 0
    original_read = accessor.read

    def counting_read(slice=None):
        nonlocal read_count
        read_count += 1
        return original_read(slice=slice)

    accessor.read = counting_read

    repeat = cache.get_data(run, "det", slice_info)
    assert repeat.shape == (5, 200, 300)
    assert read_count == 0
    np.testing.assert_array_equal(repeat, data[slice_info])


def test_tiled_fetch_does_not_double_read_for_l2():
    data = np.arange(256, dtype=np.float32).reshape(1, 1, 16, 16)
    accessor = _FakeAccessor(data, ((1,), (1,), (8, 8), (8, 8)))
    run = _FakeRun("uid-1", "det", accessor)
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 4, 4))

    read_count = 0
    original_read = accessor.read

    def counting_read(slice=None):
        nonlocal read_count
        read_count += 1
        return original_read(slice=slice)

    accessor.read = counting_read

    cache.get_data(run, "det", (0, 0, slice(None), slice(None)))
    assert read_count <= 4


def test_l1_tile_eviction_preserves_l2():
    data = np.arange(1024, dtype=np.float32).reshape(1, 1, 32, 32)
    accessor = _FakeAccessor(data, ((1,), (1,), (16, 16), (16, 16)))
    run = _FakeRun("uid-1", "det", accessor)
    cache, l2 = _make_cache(l2_chunks=(1, 1, 8, 8), l1_max_bytes=600)

    slice_info = (0, 0, slice(None), slice(None))
    cache.get_data(run, "det", slice_info)
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)
    assert l2.completion_fraction("uid-1", "det") > 0.0

    read_count = 0
    original_read = accessor.read

    def counting_read(slice=None):
        nonlocal read_count
        read_count += 1
        return original_read(slice=slice)

    accessor.read = counting_read

    cache.get_data(run, "det", (0, 0, slice(0, 8), slice(0, 8)))
    assert read_count == 0
    assert cache.l2_hits >= 1


def test_flip_energy_slices_uses_seeded_l1_tiles():
    shape = (50, 5, 512, 1026)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    chunks = ((1,) * 50, (1,) * 5, (256, 256), (256, 256, 256, 256, 2))
    accessor = _FakeAccessor(data, chunks)
    run = _FakeRun("uid-edge", "det", accessor)
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 256, 256))

    slice_a = (48, slice(None), slice(None), slice(None))
    slice_b = (49, slice(None), slice(None), slice(None))
    cache.get_data(run, "det", slice_a)
    cache.get_data(run, "det", slice_b)
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=30)

    read_count = 0
    original_read = accessor.read

    def counting_read(slice=None):
        nonlocal read_count
        read_count += 1
        return original_read(slice=slice)

    accessor.read = counting_read

    for slice_info in (slice_a, slice_b, slice_a, slice_b):
        result = cache.get_data(run, "det", slice_info)
        assert result.shape == (5, 512, 1026)
        np.testing.assert_array_equal(result, data[slice_info])

    assert read_count == 0


def test_bulk_slab_seed_writes_zarr_without_tile_l1():
    from nbs_viewer.models.cache.tile_indices import total_tile_count

    shape = (8, 1, 16, 16)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    chunks = ((1,) * 8, (1,), (8, 8), (8, 8))
    run = _FakeRun("uid-bulk", "det", _FakeAccessor(data, chunks))
    cache, l2 = _make_cache(l2_chunks=(1, 1, 4, 4), l1_max_bytes=800)

    cache.get_data(run, "det", (slice(None), 0, slice(None), slice(None)))
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    assert l2.completion_fraction("uid-bulk", "det") > 0.0
    assert l2.tile_counts("uid-bulk", "det")[0] > 0


def test_l2_flip_energy_slices_with_edge_width_tiles():
    from nbs_viewer.models.cache.tile_indices import (
        tile_global_slice,
        tiles_intersecting,
    )

    shape = (50, 5, 512, 1026)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    chunks = ((1,) * 50, (1,) * 5, (256, 256), (256, 256, 256, 256, 2))
    run = _FakeRun("uid-edge", "det", _FakeAccessor(data, chunks))
    cache, l2 = _make_cache(l2_chunks=(1, 1, 256, 256))
    cache.chunk_info[(run.start["uid"], "det")] = (shape, chunks)
    cache._ensure_l2_array(run, "det")

    slice_a = (48, slice(None), slice(None), slice(None))
    slice_b = (49, slice(None), slice(None), slice(None))
    for slice_info in (slice_a, slice_b):
        for tile_info in tiles_intersecting(shape, l2.l2_chunks, slice_info):
            tile_idx = tile_info["chunk_indices"]
            global_slice = tile_global_slice(tile_idx, shape, l2.l2_chunks)
            tile_data = data[global_slice]
            l2.write_chunk(run.start["uid"], "det", tile_idx, tile_data)

    for slice_info in (slice_a, slice_b, slice_a, slice_b, slice_a):
        result = cache.get_data(run, "det", slice_info)
        assert result.shape == (5, 512, 1026)
        np.testing.assert_array_equal(result, data[slice_info])


def test_phase3_identical_view_hits_l2_after_background_materialize():
    data = np.arange(256, dtype=np.float32).reshape(1, 1, 16, 16)
    accessor = _FakeAccessor(data, ((1,), (1,), (8, 8), (8, 8)))
    run = _FakeRun("uid-p3", "det", accessor)
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 4, 4))

    slice_info = (0, 0, slice(0, 8), slice(0, 8))
    cache.get_data(run, "det", slice_info)
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    read_count = 0
    original_read = accessor.read

    def counting_read(slice=None):
        nonlocal read_count
        read_count += 1
        return original_read(slice=slice)

    accessor.read = counting_read
    repeat = cache.get_data(run, "det", slice_info)
    assert repeat.shape == (8, 8)
    assert read_count == 0


def test_phase4_expanded_roi_fetches_cold_gap_only():
    shape = (1, 1, 16, 16)
    data = np.arange(256, dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((1,), (1,), (8, 8), (8, 8)))
    run = _FakeRun("uid-p4", "det", accessor)
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 4, 4))

    warm_slice = (0, 0, slice(0, 8), slice(0, 4))
    cold_slice = (0, 0, slice(0, 8), slice(0, 8))
    cache.get_data(run, "det", warm_slice)
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    read_slices = []
    original_read = accessor.read

    def counting_read(slice=None):
        read_slices.append(slice)
        return original_read(slice=slice)

    accessor.read = counting_read
    expanded = cache.get_data(run, "det", cold_slice)
    assert expanded.shape == (8, 8)
    np.testing.assert_array_equal(expanded, data[cold_slice])
    assert read_slices
    assert read_slices[0][3] == slice(4, 8)
    assert read_slices[0][3] != slice(0, 8)


def test_phase3_identical_view_hits_l2_after_background_materialize():
    data = np.arange(256, dtype=np.float32).reshape(1, 1, 16, 16)
    accessor = _FakeAccessor(data, ((1,), (1,), (8, 8), (8, 8)))
    run = _FakeRun("uid-p3", "det", accessor)
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 4, 4))

    slice_info = (0, 0, slice(0, 8), slice(0, 8))
    cache.get_data(run, "det", slice_info)
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    read_count = 0
    original_read = accessor.read

    def counting_read(slice=None):
        nonlocal read_count
        read_count += 1
        return original_read(slice=slice)

    accessor.read = counting_read
    repeat = cache.get_data(run, "det", slice_info)
    assert repeat.shape == (8, 8)
    assert read_count == 0


def test_phase4_expanded_roi_fetches_cold_gap_only():
    shape = (1, 1, 16, 16)
    data = np.arange(256, dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((1,), (1,), (8, 8), (8, 8)))
    run = _FakeRun("uid-p4", "det", accessor)
    cache, l2 = _make_cache(l2_chunks=(1, 1, 4, 4))

    warm_slice = (0, 0, slice(0, 8), slice(0, 4))
    cold_slice = (0, 0, slice(0, 8), slice(0, 8))
    cache.get_data(run, "det", warm_slice)
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    read_slices = []
    original_read = accessor.read

    def counting_read(slice=None):
        read_slices.append(slice)
        return original_read(slice=slice)

    accessor.read = counting_read
    expanded = cache.get_data(run, "det", cold_slice)
    assert expanded.shape == (8, 8)
    np.testing.assert_array_equal(expanded, data[cold_slice])
    assert read_slices
    assert read_slices[0][3] == slice(4, 8)
    assert read_slices[0][3] != slice(0, 8)


def test_phase4_expanded_roi_with_indexed_energy_axis():
    shape = (5, 1, 128, 256)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((1,) * 5, (1,), (64, 64), (64, 64)))
    run = _FakeRun("uid-p4-4d", "det", accessor)
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 32, 32))

    warm_slice = (slice(None), 0, slice(21, 80), slice(23, 150))
    cold_slice = (slice(None), 0, slice(21, 100), slice(23, 238))
    cache.get_data(run, "det", warm_slice)
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    read_slices = []
    original_read = accessor.read

    def counting_read(slice=None):
        read_slices.append(slice)
        return original_read(slice=slice)

    accessor.read = counting_read
    expanded = cache.get_data(run, "det", cold_slice)
    assert expanded.shape == (5, 79, 215)
    np.testing.assert_array_equal(expanded, data[cold_slice])
    assert read_slices
    assert read_slices[0][0] == slice(0, 5)


class _TiledLikeAccessor:
    """
    Accessor that keeps length-1 axes for integer indices like Tiled reads.
    """

    def __init__(self, data: np.ndarray, chunks):
        self.shape = data.shape
        self.chunks = chunks
        self.dtype = data.dtype
        self._data = data

    def read(self, slice=None):
        if slice is None:
            return self._data
        out = self._data[slice]
        if not isinstance(slice, tuple):
            slice = (slice,)
        axis = 0
        for item in slice:
            if isinstance(item, int):
                out = np.expand_dims(out, axis=axis)
            axis += 1
        return out


def test_stack_fetch_after_plane_seed_matches_single_index():
    """
    Warm L1 tiles from a 2D plane must not corrupt stack reads on that axis.
    """
    shape = (10, 5, 64, 64)
    data = (
        np.random.default_rng(1).random(shape).astype(np.float32) * 100 + 1200
    )
    chunks = ((1,) * 10, (1,) * 5, (32, 32), (32, 32))
    run = _FakeRun(
        "uid-stack-seed",
        "det",
        _TiledLikeAccessor(data, chunks),
    )
    cache, _l2 = _make_cache(l2_chunks=(1, 1, 16, 16))
    en, roi = 0, (slice(10, 30), slice(10, 30))
    expected = data[en, :, roi[0], roi[1]]

    cache.get_data(run, "det", (en, 0, slice(None), slice(None)))
    stack = cache.get_data(run, "det", (en, slice(None)) + roi)
    single = cache.get_data(run, "det", (en, 0) + roi)

    assert stack.shape == expected.shape
    np.testing.assert_allclose(stack, expected, rtol=1e-5)
    np.testing.assert_allclose(stack[0], single, rtol=1e-5)
    np.testing.assert_allclose(stack[0], expected[0], rtol=1e-5)
