import numpy as np

from nbs_viewer.models.cache.chunkCache import ChunkCache
from nbs_viewer.models.cache.tile_indices import (
    plan_hyperslab_batches,
    storage_axis_to_result_axis,
)


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


def test_plan_hyperslab_batches_single_under_budget():
    slice_info = (slice(0, 226), 0, slice(10, 130), slice(20, 200))
    shape = (226, 1, 1000, 1000)
    batches, batch_axis = plan_hyperslab_batches(slice_info, shape, 4, 50_000_000)
    assert batch_axis is None
    assert batches == [slice_info]


def test_plan_hyperslab_batches_none_disables_splitting():
    slice_info = (slice(None), slice(None), slice(None))
    shape = (4, 2160, 2560)
    batches, batch_axis = plan_hyperslab_batches(slice_info, shape, 2, None)
    assert batch_axis is None
    assert batches == [slice_info]


def test_plan_hyperslab_batches_splits_first_axis():
    slice_info = (slice(0, 226), 0, slice(10, 130), slice(20, 200))
    shape = (226, 1, 1000, 1000)
    batches, batch_axis = plan_hyperslab_batches(slice_info, shape, 4, 500_000)
    assert batch_axis == 0
    assert len(batches) > 1
    covered = sum(batch[0].stop - batch[0].start for batch in batches)
    assert covered == 226


def test_plan_hyperslab_batches_prefers_first_over_longest_axis():
    slice_info = (slice(None), slice(None), slice(None))
    shape = (4, 2160, 2560)
    batches, batch_axis = plan_hyperslab_batches(slice_info, shape, 2, 15_000_000)
    assert batch_axis == 0
    assert len(batches) == 4
    assert all(batch[0].stop - batch[0].start == 1 for batch in batches)
    assert all(batch[1] == slice(None) for batch in batches)
    assert all(batch[2] == slice(None) for batch in batches)


def test_storage_axis_to_result_axis_after_leading_integer_index():
    slice_info = (0, slice(None), slice(0, 120), slice(0, 180))
    assert storage_axis_to_result_axis(slice_info, 1) == 0


def test_plan_hyperslab_batches_maps_batch_axis_after_integer_index():
    slice_info = (0, slice(None), slice(0, 120), slice(0, 180))
    shape = (1, 226, 120, 180)
    batches, batch_axis = plan_hyperslab_batches(slice_info, shape, 4, 500_000)
    assert batch_axis == 0
    assert len(batches) > 1
    covered = sum(batch[1].stop - batch[1].start for batch in batches)
    assert covered == 226


def test_batched_hyperslab_disabled_issues_single_read():
    shape = (4, 10, 12)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((4,), (10,), (12,)))
    run = _FakeRun("uid-no-batch", "det", accessor)

    read_slices = []
    original_read = accessor.read

    def counting_read(slice=None):
        read_slices.append(slice)
        return original_read(slice=slice)

    accessor.read = counting_read
    cache = ChunkCache(l2_enabled=False, fetch_batch_target_bytes=None)
    slice_info = (slice(None), slice(None), slice(None))
    result = cache.get_data(run, "det", slice_info)

    assert result.shape == shape
    np.testing.assert_array_equal(result, data)
    assert read_slices == [slice_info]


def test_batched_hyperslab_with_leading_integer_index():
    shape = (1, 226, 120, 180)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((1,), (1,) * 226, (1024,), (1024,)))
    run = _FakeRun("uid-leading-index", "det", accessor)

    read_slices = []
    original_read = accessor.read

    def counting_read(slice=None):
        read_slices.append(slice)
        return original_read(slice=slice)

    accessor.read = counting_read
    cache = ChunkCache(l2_enabled=False, fetch_batch_target_bytes=500_000)
    slice_info = (0, slice(None), slice(0, 120), slice(0, 180))
    result = cache.get_data(run, "det", slice_info)

    assert result.shape == (226, 120, 180)
    expected = data[(0, slice(None), slice(0, 120), slice(0, 180))]
    np.testing.assert_array_equal(result, expected)
    assert 1 < len(read_slices) < 226
    assert sum(item[1].stop - item[1].start for item in read_slices) == 226


def test_batched_hyperslab_limits_tiled_reads():
    shape = (226, 1, 120, 180)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((1,) * 226, (1,), (1024,), (1024,)))
    run = _FakeRun("uid-batch", "det", accessor)

    read_slices = []
    original_read = accessor.read

    def counting_read(slice=None):
        read_slices.append(slice)
        return original_read(slice=slice)

    accessor.read = counting_read
    cache = ChunkCache(l2_enabled=False, fetch_batch_target_bytes=500_000)
    slice_info = (slice(None), 0, slice(0, 120), slice(0, 180))
    result = cache.get_data(run, "det", slice_info)

    assert result.shape == (226, 120, 180)
    np.testing.assert_array_equal(result, data[(slice(None), 0, slice(0, 120), slice(0, 180))])
    assert 1 < len(read_slices) < 226
    assert sum(item[0].stop - item[0].start for item in read_slices) == 226


def test_batched_hyperslab_emits_progress():
    shape = (40, 1, 10, 10)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((1,) * 40, (1,), (10,), (10,)))
    run = _FakeRun("uid-progress", "det", accessor)

    from nbs_viewer.models.cache.chunk_cache_progress import ChunkCacheProgress

    class _RecordingProgress(ChunkCacheProgress):
        def __init__(self):
            super().__init__()
            self.updates = []

        def update(self, run_uid, key, pending_tiles, batch_total, active):
            self.updates.append((pending_tiles, batch_total, active))
            super().update(run_uid, key, pending_tiles, batch_total, active)

    progress = _RecordingProgress()
    cache = ChunkCache(
        l2_enabled=False,
        fetch_batch_target_bytes=800,
        progress=progress,
    )
    cache.get_data(run, "det", (slice(None), 0, slice(0, 10), slice(0, 10)))

    assert progress.updates
    assert progress.updates[0][1] > 1
    assert progress.updates[-1] == (0, progress.updates[0][1], False)
