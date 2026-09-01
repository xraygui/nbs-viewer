import numpy as np

from nbs_viewer.models.cache.chunk_cache_progress import (
    ChunkCacheProgress,
    aggregate_tiled_fetch_label,
    format_l2_cache_status,
)
from nbs_viewer.models.cache.chunkCache import ChunkCache
from nbs_viewer.models.cache.zarr_l2_cache import ZarrL2Cache


class _RecordingProgress(ChunkCacheProgress):
    def __init__(self):
        super().__init__()
        self.updates = []

    def update(self, run_uid, key, pending_tiles, batch_total, active):
        self.updates.append(
            (run_uid, key, pending_tiles, batch_total, active)
        )
        super().update(run_uid, key, pending_tiles, batch_total, active)


class _FakeAccessor:
    def __init__(self, data: np.ndarray, chunks):
        self.shape = data.shape
        self.chunks = chunks
        self.dtype = data.dtype
        self._data = data

    def read(self, slice=None):
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


def test_l2_cache_status_label_active_batch():
    status = format_l2_cache_status("uid", "det", 2, 4, active=True)
    assert status.label_text() == "Fetching 2/4"


def test_l2_cache_status_label_one_remaining():
    status = format_l2_cache_status("uid", "det", 1, 4, active=True)
    assert status.label_text() == "Fetching 3/4"


def test_l2_cache_status_label_idle_is_empty():
    status = format_l2_cache_status("uid", "det", 0, 4, active=False)
    assert status.label_text() == ""


def test_aggregate_tiled_fetch_label_sums_active_batches():
    statuses = [
        format_l2_cache_status("uid-a", "det", 2, 4, active=True),
        format_l2_cache_status("uid-b", "det", 1, 3, active=True),
    ]
    assert aggregate_tiled_fetch_label(statuses) == "Fetching 4/7"


def test_aggregate_tiled_fetch_label_ignores_idle_batches():
    statuses = [
        format_l2_cache_status("uid-a", "det", 2, 4, active=True),
        format_l2_cache_status("uid-b", "det", 0, 4, active=False),
    ]
    assert aggregate_tiled_fetch_label(statuses) == "Fetching 2/4"


def test_chunk_cache_emits_progress_during_tiled_fetch():
    shape = (40, 1, 10, 10)
    data = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    accessor = _FakeAccessor(data, ((1,) * 40, (1,), (10,), (10,)))
    run = _FakeRun("uid-1", "det", accessor)
    progress = _RecordingProgress()
    cache = ChunkCache(
        l2=ZarrL2Cache(l2_chunks=(1, 1, 4, 4)),
        l2_enabled=False,
        fetch_batch_target_bytes=800,
        progress=progress,
    )

    cache.get_data(run, "det", (slice(None), 0, slice(0, 10), slice(0, 10)))

    assert progress.updates
    assert progress.updates[0][3] > 1
    assert progress.updates[-1][4] is False


def test_format_debug_report_includes_l2_entries():
    data = np.arange(256, dtype=np.float32).reshape(1, 1, 16, 16)
    chunks = ((1,), (1,), (8, 8), (8, 8))
    run = _FakeRun("uid-1", "det", _FakeAccessor(data, chunks))
    cache = ChunkCache(l2=ZarrL2Cache(l2_chunks=(1, 1, 4, 4)))
    cache.get_data(run, "det", (0, 0, slice(0, 4), slice(0, 4)))

    report = cache.format_debug_report(datasets=[("uid-1", "det")])
    assert "ChunkCache stats" in report
    assert "L2 Zarr cache" in report
    assert "uid-1/det" in report
    assert "l2_hits" in report
