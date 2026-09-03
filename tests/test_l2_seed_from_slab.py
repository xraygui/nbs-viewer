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


def test_extract_tile_from_slab_with_unsqueezed_hyperslab():
    shape = (114, 5, 1000, 1000)
    slice_info = (slice(None), 2, slice(413, 530), slice(442, 605))
    slab4 = np.random.randn(114, 1, 117, 163).astype(np.float32)
    slab4 = ChunkCache._align_seed_slab(slab4, slice_info)
    assert slab4.shape == (114, 117, 163)
    l2_chunks = (1, 1, 256, 256)
    from nbs_viewer.models.cache.tile_indices import tiles_intersecting

    pending = tiles_intersecting(shape, l2_chunks, slice_info)
    ok = sum(
        1
        for t in pending
        if ChunkCache._extract_tile_from_slab(
            slab4, shape, l2_chunks, slice_info, t["chunk_indices"]
        )
        is not None
    )
    assert ok == len(pending)


def test_l2_miss_seeds_from_slab_and_materializes_l2_in_background():
    shape = (20, 1, 64, 64)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((1,) * 20, (1,), (32, 32), (32, 32)))
    run = _FakeRun("uid-seed", "det", accessor)

    tiled_reads = []
    original_read = accessor.read

    def counting_read(slice=None):
        tiled_reads.append(slice)
        return original_read(slice=slice)

    accessor.read = counting_read
    cache = ChunkCache(l2=ZarrL2Cache(l2_chunks=(1, 1, 16, 16)))
    slice_info = (slice(None), 0, slice(8, 40), slice(10, 50))
    cache.get_data(run, "det", slice_info)

    assert tiled_reads
    assert tiled_reads[0] == slice_info

    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    assert cache.l2.completion_fraction(run.start["uid"], "det") > 0.0
    assert len(tiled_reads) > 1


def test_roi_fetch_materializes_full_l2_tiles_in_background():
    shape = (4, 1, 64, 64)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    run = _FakeRun(
        "uid-roi-l2",
        "det",
        _FakeAccessor(data, ((1,) * 4, (1,), (32, 32), (32, 32))),
    )
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 16, 16))
    cache = ChunkCache(l2=l2, l1_max_bytes=int(1e9))
    slice_info = (0, 0, slice(10, 26), slice(10, 26))

    reads = []
    original_read = run._accessor.read

    def counting_read(slice=None):
        reads.append(slice)
        return original_read(slice=slice)

    run._accessor.read = counting_read
    cache.get_data(run, "det", slice_info)

    assert reads
    assert reads[0] == slice_info

    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    assert cache.l2.completion_fraction("uid-roi-l2", "det") > 0.0
    completed = l2._meta[("uid-roi-l2", "det")].completed
    assert completed
    sample_idx = next(iter(completed))
    tile = l2.read_chunk("uid-roi-l2", "det", sample_idx)
    assert tile.shape == (1, 1, 16, 16)
    assert np.all(np.isfinite(tile))


def test_l2_materialize_batches_tiled_reads():
    shape = (20, 1, 64, 64)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((1,) * 20, (1,), (32, 32), (32, 32)))
    run = _FakeRun("uid-batch-l2", "det", accessor)

    tiled_reads = []
    original_read = accessor.read

    def counting_read(slice=None):
        tiled_reads.append(slice)
        return original_read(slice=slice)

    accessor.read = counting_read
    cache = ChunkCache(
        l2=ZarrL2Cache(l2_chunks=(1, 1, 16, 16)),
        fetch_batch_target_bytes=500_000,
    )
    slice_info = (slice(None), 0, slice(8, 40), slice(10, 50))
    cache.get_data(run, "det", slice_info)
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)

    assert cache.l2.completion_fraction(run.start["uid"], "det") > 0.0
    assert len(tiled_reads) > 1
    assert len(tiled_reads) < 40


def test_roi_does_not_mark_partial_zarr_tiles_complete():
    shape = (4, 1, 32, 32)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    run = _FakeRun("uid-partial", "det", _FakeAccessor(data, ((1,) * 4, (1,), (32,), (32,))))
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 16, 16))
    cache = ChunkCache(l2=l2, l1_max_bytes=int(1e9))

    slice_info = (slice(None), 0, slice(10, 26), slice(10, 26))
    cache.get_data(run, "det", slice_info)

    assert l2.completion_fraction("uid-partial", "det") == 0.0


def test_partial_l1_not_used_for_broader_fetch():
    shape = (4, 1, 32, 32)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    run = _FakeRun("uid-broader", "det", _FakeAccessor(data, ((1,) * 4, (1,), (32,), (32,))))
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 16, 16))
    cache = ChunkCache(l2=l2, l1_max_bytes=int(1e9))

    roi_slice = (slice(None), 0, slice(10, 26), slice(10, 26))
    cache.get_data(run, "det", roi_slice)

    full_slice = (slice(None), 0, slice(0, 32), slice(0, 32))
    result = cache.get_data(run, "det", full_slice)
    expected = data[full_slice]

    np.testing.assert_allclose(result, expected, rtol=1e-5)
    assert not np.isnan(result).any()


def test_roi_does_not_spill_partial_coverage_into_zarr():
    shape = (4, 1, 32, 32)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    run = _FakeRun("uid-spill", "det", _FakeAccessor(data, ((1,) * 4, (1,), (32,), (32,))))
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 16, 16))
    cache = ChunkCache(l2=l2, l1_max_bytes=512)

    roi_slice = (slice(None), 0, slice(10, 26), slice(10, 26))
    cache.get_data(run, "det", roi_slice)

    assert l2.completion_fraction("uid-spill", "det") == 0.0


def test_l2_materialize_fetches_full_tiles_when_transport_is_batched():
    shape = (114, 5, 1000, 1000)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(
        data,
        ((1,) * 114, (1,) * 5, (256, 256, 256, 32), (256, 256, 256, 32)),
    )
    run = _FakeRun("uid-large-roi", "det", accessor)

    tiled_reads = []
    original_read = accessor.read

    def counting_read(slice=None):
        tiled_reads.append(slice)
        return original_read(slice=slice)

    accessor.read = counting_read
    l2 = ZarrL2Cache(l2_chunks=(1, 1, 256, 256))
    cache = ChunkCache(
        l2=l2,
        l1_max_bytes=1,
        fetch_batch_target_bytes=15_000_000,
    )
    slice_info = (slice(None), 0, slice(398, 661), slice(260, 811))
    cache.get_data(run, "det", slice_info)

    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=30)

    assert cache.l2.completion_fraction(run.start["uid"], "det") > 0.0
    assert len(tiled_reads) > 1
    from nbs_viewer.models.cache.tile_indices import tiles_intersecting

    for tile_info in tiles_intersecting(shape, l2.l2_chunks, slice_info):
        tile_idx = tile_info["chunk_indices"]
        assert l2.has_chunk(run.start["uid"], "det", tile_idx)
        tile = l2.read_chunk(run.start["uid"], "det", tile_idx)
        assert tile.shape == tuple(tile_info["chunk_shape"])
        assert np.all(np.isfinite(tile))


def test_get_data_returns_before_background_l2_seed():
    import threading

    shape = (4, 1, 32, 32)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    run = _FakeRun(
        "uid-defer-seed",
        "det",
        _FakeAccessor(data, ((1,) * 4, (1,), (16, 16), (16, 16))),
    )
    cache = ChunkCache(l2=ZarrL2Cache(l2_chunks=(1, 1, 8, 8)))
    gate = threading.Event()
    entered = threading.Event()
    original = cache._background_materialize_tiles

    def blocked(*args, **kwargs):
        entered.set()
        assert gate.wait(timeout=5)
        return original(*args, **kwargs)

    cache._background_materialize_tiles = blocked
    slice_info = (slice(None), 0, slice(None), slice(None))
    result = cache.get_data(run, "det", slice_info)

    assert result.shape == (4, 32, 32)
    assert entered.wait(timeout=5)
    assert cache.l2.completion_fraction(run.start["uid"], "det") == 0.0

    gate.set()
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)
    assert cache.l2.completion_fraction(run.start["uid"], "det") > 0.0


def test_second_view_waits_for_in_flight_l2_seed():
    import threading

    shape = (4, 1, 32, 32)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    run = _FakeRun(
        "uid-wait-seed",
        "det",
        _FakeAccessor(data, ((1,) * 4, (1,), (16, 16), (16, 16))),
    )
    cache = ChunkCache(l2=ZarrL2Cache(l2_chunks=(1, 1, 8, 8)))
    gate = threading.Event()
    entered = threading.Event()
    original = cache._background_materialize_tiles

    def blocked(*args, **kwargs):
        entered.set()
        assert gate.wait(timeout=5)
        return original(*args, **kwargs)

    cache._background_materialize_tiles = blocked

    first = cache.get_data(run, "det", (0, 0, slice(None), slice(None)))
    assert first.shape == (32, 32)
    assert entered.wait(timeout=5)

    second_done = threading.Event()
    second_result = {}

    def fetch_second():
        second_result["data"] = cache.get_data(
            run, "det", (1, 0, slice(None), slice(None))
        )
        second_done.set()

    worker = threading.Thread(target=fetch_second)
    worker.start()
    assert not second_done.wait(0.3)

    gate.set()
    assert second_done.wait(timeout=10)
    worker.join(timeout=5)
    np.testing.assert_array_equal(second_result["data"], data[1, 0])
    cache.wait_for_background_materialize(run.start["uid"], "det", timeout=10)
