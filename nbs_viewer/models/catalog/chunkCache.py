"""
Chunk-aware caching system for efficient data access from chunked array storage.
"""

import time
import numpy as np
import psutil
from typing import Dict, Tuple, Any, Optional, List
from nbs_viewer.utils import print_debug
from concurrent.futures import ThreadPoolExecutor, Future
from threading import Lock

from .chunk_cache_progress import ChunkCacheProgress
from .tile_indices import chunk_grid, tiles_intersecting
from .zarr_l2_cache import ZarrL2Cache


class ChunkCache:
    """
    Central cache for chunked array data across all runs in a catalog.

    This cache is designed to efficiently handle chunked array data by:
    1. Maintaining chunk-level granularity in caching
    2. Using LRU eviction based on access time and memory pressure
    3. Tracking chunk access patterns for potential optimization
    4. Preventing duplicate downloads of in-flight chunk requests

    Parameters
    ----------
    max_size_bytes : int, optional
        Maximum tiled chunk / slice cache size in bytes, by default 512MB
    l1_max_bytes : int, optional
        Maximum L1 tile cache size in bytes, by default 128MB
    min_free_memory : float, optional
        Minimum free system memory to maintain (as fraction), by default 0.2
    """

    def __init__(
        self,
        max_size_bytes: int = 512_000_000,
        l1_max_bytes: int = 128_000_000,
        min_free_memory: float = 0.2,
        l2: Optional[ZarrL2Cache] = None,
        l2_enabled: bool = True,
        l2_chunks: Tuple[int, ...] = (1, 1, 256, 256),
        sync_seed_tile_limit: int = 64,
        large_fetch_chunk_threshold: int = 32,
        progress: Optional[ChunkCacheProgress] = None,
    ):
        # Cache storage
        self.chunks: Dict[Tuple[str, str, Tuple[int, ...]], np.ndarray] = {}
        self.slice_cache: Dict[Tuple, np.ndarray] = {}
        self.tiles: Dict[Tuple[str, str, Tuple[int, ...]], np.ndarray] = {}
        self.chunk_info: Dict[
            Tuple[str, str], Tuple[Tuple[int, ...], Tuple[int, ...]]
        ] = {}

        # Cache configuration
        self.max_size = max_size_bytes
        self.l1_max_bytes = l1_max_bytes
        self.min_free_memory = min_free_memory
        self.current_size = 0
        self.l1_tile_size = 0

        if l2 is not None:
            self.l2 = l2
        elif l2_enabled:
            self.l2 = ZarrL2Cache(l2_chunks=l2_chunks)
        else:
            self.l2 = None
        self.progress = progress
        self.sync_seed_tile_limit = sync_seed_tile_limit
        self.large_fetch_chunk_threshold = large_fetch_chunk_threshold
        self._cache_tiled_fetches = True

        # Access tracking
        self.access_times: Dict[Tuple[str, str, Tuple[int, ...]], float] = {}
        self.access_counts: Dict[Tuple[str, str, Tuple[int, ...]], int] = {}
        self.l1_tile_access_times: Dict[Tuple[str, str, Tuple[int, ...]], float] = {}

        # In-flight request tracking
        self.in_flight_chunks: Dict[Tuple[str, str, Tuple[int, ...]], bool] = {}

        self.fetch_pool = ThreadPoolExecutor(max_workers=4)
        self.background_pool = ThreadPoolExecutor(max_workers=2)
        self.worker_pool = self.fetch_pool
        self.active_requests: Dict[Tuple[str, str, Tuple[int, ...]], Future] = {}
        self._active_l2_seed_jobs: Dict[Tuple[str, str], Future] = {}
        self.request_lock = Lock()

        # Statistics
        self.hits = 0
        self.misses = 0
        self.l2_hits = 0
        self.l2_misses = 0

    def get_data(self, run, key: str, slice_info: Tuple) -> np.ndarray:
        """
        Get data for a specific run/key/slice combination.
        Will fetch chunk info and chunks as needed.

        Parameters
        ----------
        run : BlueskyRun
            The run object containing the data
        key : str
            Data key
        slice_info : tuple
            User's slice request

        Returns
        -------
        np.ndarray
            The requested data
        """
        try:
            # Ensure we have chunk info
            if not self._ensure_chunk_info(run, key):
                raise ValueError(
                    f"Could not get chunk info for {run.start['uid']}:{key}"
                )

            shape, chunks = self.chunk_info[(run.start["uid"], key)]

            if self._is_monolithic_chunking(chunks):
                print_debug(
                    "ChunkCache",
                    f"Monolithic chunking for {key}, using direct slice read",
                    category="cache",
                )
                return self._get_data_sliced(run, key, slice_info)

            if self.l2 is not None and self.l2.enabled:
                l2_result = self._try_get_data_from_l2_tiles(run, key, slice_info)
                if l2_result is not None:
                    return l2_result

            # Convert slice to chunk indices
            try:
                chunks_needed, full_shape = self.get_chunk_indices(
                    run.start["uid"], key, slice_info
                )
                msg = f"Chunk indices: {chunks_needed}, full shape: {full_shape}"
                print_debug("ChunkCache", msg, category="cache")
            except Exception as e:
                raise ValueError(f"Error converting slice to chunks: {str(e)}")

            # Get or fetch required chunks
            try:
                cache_tiled = (
                    len(chunks_needed) <= self.large_fetch_chunk_threshold
                )
                self._cache_tiled_fetches = cache_tiled
                chunks_data = self._get_or_fetch_chunks(run, key, chunks_needed)
                if not chunks_data:
                    raise ValueError("No chunks returned")
            except Exception as e:
                raise ValueError(f"Error fetching chunks: {str(e)}")

            if len(chunks_needed) == 1:
                chunk_info = chunks_needed[0]
                chunk = chunks_data.get(chunk_info["chunk_indices"])
                if chunk is not None and not self._chunk_needs_internal_slice(
                    chunk, chunk_info
                ):
                    result = self._squeeze_indexed_dims(chunk, slice_info)
                else:
                    result = None
            else:
                result = None

            if result is None:
                try:
                    result = self._assemble_result(
                        chunks_data, chunks_needed, full_shape
                    )
                except Exception as e:
                    raise ValueError(f"Error assembling result: {str(e)}")
                result = self._squeeze_indexed_dims(result, slice_info)

            if self.l2 is not None and self.l2.enabled:
                self._seed_l1_tiles_from_slab(run, key, slice_info, result)

            return result

        except Exception as e:
            print_debug("ChunkCache", f"Error in get_data: {str(e)}")
            raise
        finally:
            self._cache_tiled_fetches = True

    def _ensure_l2_array(self, run, key: str) -> None:
        """
        Register array metadata with the L2 cache when enabled.
        """
        if self.l2 is None or not self.l2.enabled:
            return

        run_uid = run.start["uid"]
        shape, tiled_chunks = self.chunk_info[(run_uid, key)]
        data_accessor = run["primary", "data", key]
        dtype = getattr(data_accessor, "dtype", None)
        if dtype is None:
            dtype = np.dtype("float32")
        self.l2.register_array(
            run_uid,
            key,
            shape,
            dtype,
            tiled_chunks=tiled_chunks,
        )

    def _try_get_data_from_l2_tiles(
        self, run, key: str, slice_info: Tuple
    ) -> Optional[np.ndarray]:
        """
        Assemble a result from complete L1/L2 tiles when possible.

        Parameters
        ----------
        run : BlueskyRun
            Run containing the data.
        key : str
            Data key.
        slice_info : tuple
            User slice request.

        Returns
        -------
        np.ndarray or None
            Assembled data when every intersecting tile is complete.
        """
        run_uid = run.start["uid"]
        shape, _ = self.chunk_info[(run_uid, key)]
        self._ensure_l2_array(run, key)

        tiles_needed = tiles_intersecting(shape, self.l2.l2_chunks, slice_info)
        chunks_data = {}
        used_l2 = False
        for tile_info in tiles_needed:
            tile_idx = tile_info["chunk_indices"]
            cache_key = (run_uid, key, tile_idx)
            if cache_key in self.tiles:
                chunk = self.tiles[cache_key]
                self._update_l1_tile_access(cache_key)
            elif self.l2.has_chunk(run_uid, key, tile_idx):
                chunk = self.l2.read_chunk(run_uid, key, tile_idx)
                self._cache_l1_tile(run_uid, key, tile_idx, chunk)
                used_l2 = True
            else:
                self.l2_misses += 1
                return None
            if not self._chunk_needs_internal_slice(chunk, tile_info):
                tile_info["already_sliced"] = True
            chunks_data[tile_idx] = chunk

        if used_l2:
            self.l2_hits += 1
        self.hits += 1
        result = self._assemble_result(chunks_data, tiles_needed, shape)
        return self._squeeze_indexed_dims(result, slice_info)

    def _notify_tiled_fetch_progress(
        self,
        run_uid: str,
        key: str,
        *,
        active: bool,
        pending_chunks: int = 0,
        batch_total: int = 0,
    ) -> None:
        """
        Publish in-flight Tiled chunk fetch status to the optional progress notifier.
        """
        if self.progress is None:
            return
        self.progress.update(
            run_uid, key, pending_chunks, batch_total, active
        )

    def _pending_slab_tiles(
        self,
        run_uid: str,
        key: str,
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
        slice_info: Tuple,
    ) -> List[Dict]:
        """
        List L2-aligned tiles still missing from L1 and L2 for one slab.
        """
        pending: List[Dict] = []
        for tile_info in tiles_intersecting(shape, l2_chunks, slice_info):
            tile_idx = tile_info["chunk_indices"]
            if not self._tile_fully_in_request(
                shape, l2_chunks, slice_info, tile_idx
            ):
                continue
            cache_key = (run_uid, key, tile_idx)
            if cache_key in self.tiles:
                continue
            if self.l2.has_chunk(run_uid, key, tile_idx):
                continue
            pending.append(tile_info)
        return pending

    def _seed_l1_tiles_from_slab(
        self,
        run,
        key: str,
        slice_info: Tuple,
        slab: np.ndarray,
    ) -> None:
        """
        Split a fetched slab into L2-aligned tiles and store them in L1 or L2.

        Small requests are seeded synchronously. Large requests fill L1 once on
        the critical path and enqueue the remaining tiles for background L2
        writes so a full hypercube does not block on thousands of Zarr writes.

        Parameters
        ----------
        run : BlueskyRun
            Run containing the data.
        key : str
            Data key.
        slice_info : tuple
            User slice request that produced ``slab``.
        slab : np.ndarray
            Assembled result array (after indexed-dimension squeeze).
        """
        run_uid = run.start["uid"]
        shape, _ = self.chunk_info[(run_uid, key)]
        self._ensure_l2_array(run, key)
        l2_chunks = self.l2.l2_chunks
        pending = self._pending_slab_tiles(
            run_uid, key, shape, l2_chunks, slice_info
        )
        if not pending:
            return

        if len(pending) <= self.sync_seed_tile_limit:
            seeded_l1 = 0
            seeded_l2 = 0
            for tile_info in pending:
                tile_idx = tile_info["chunk_indices"]
                tile_data = self._extract_tile_from_slab(
                    slab, shape, l2_chunks, slice_info, tile_idx
                )
                stored = self._store_tile(run_uid, key, tile_idx, tile_data)
                if stored == "l1":
                    seeded_l1 += 1
                elif stored == "l2":
                    seeded_l2 += 1
            if seeded_l1 or seeded_l2:
                print_debug(
                    "ChunkCache",
                    f"Seeded {seeded_l1} L1 + {seeded_l2} L2 tiles from slab for {key}",
                    category="cache",
                )
            return

        seeded_l1 = 0
        deferred: List[Dict] = []
        itemsize = slab.dtype.itemsize
        for tile_info in pending:
            tile_idx = tile_info["chunk_indices"]
            cache_key = (run_uid, key, tile_idx)
            tile_size = int(np.prod(tile_info["chunk_shape"]) * itemsize)
            if self.l1_tile_size + tile_size <= self.l1_max_bytes:
                tile_data = self._extract_tile_from_slab(
                    slab, shape, l2_chunks, slice_info, tile_idx
                )
                self.tiles[cache_key] = tile_data
                self.l1_tile_size += tile_size
                self._update_l1_tile_access(cache_key)
                seeded_l1 += 1
            else:
                deferred.append(tile_info)

        if deferred:
            self._enqueue_background_l2_seed(
                run_uid, key, shape, l2_chunks, slice_info, slab, deferred
            )

        print_debug(
            "ChunkCache",
            f"Seeded {seeded_l1} L1 tiles from slab for {key}; "
            f"queued {len(deferred)} tiles for background L2",
            category="cache",
        )

    def _enqueue_background_l2_seed(
        self,
        run_uid: str,
        key: str,
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
        slice_info: Tuple,
        slab: np.ndarray,
        tile_infos: List[Dict],
    ) -> None:
        """
        Queue background L2 writes for tiles that did not fit in L1.
        """
        if not tile_infos:
            return

        job_key = (run_uid, key)
        with self.request_lock:
            existing = self._active_l2_seed_jobs.get(job_key)
            if existing is not None and not existing.done():
                return

            future = self.background_pool.submit(
                self._background_l2_seed_from_slab,
                run_uid,
                key,
                shape,
                l2_chunks,
                slice_info,
                slab,
                tile_infos,
            )
            self._active_l2_seed_jobs[job_key] = future

            def _cleanup(done_future: Future) -> None:
                with self.request_lock:
                    if self._active_l2_seed_jobs.get(job_key) is done_future:
                        del self._active_l2_seed_jobs[job_key]

            future.add_done_callback(_cleanup)

    def _background_l2_seed_from_slab(
        self,
        run_uid: str,
        key: str,
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
        slice_info: Tuple,
        slab: np.ndarray,
        tile_infos: List[Dict],
    ) -> int:
        """
        Write slab tiles to L2 in a worker thread.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        shape : tuple of int
            Full array shape.
        l2_chunks : tuple of int
            Nominal L2 tile size per dimension.
        slice_info : tuple
            User slice that produced ``slab``.
        slab : np.ndarray
            Assembled slab array.
        tile_infos : list of dict
            Tile metadata entries still missing from L1 and L2.

        Returns
        -------
        int
            Number of tiles written to L2.
        """
        self._ensure_l2_array_from_meta(run_uid, key, slab.dtype)
        written = 0
        for tile_info in tile_infos:
            tile_idx = tile_info["chunk_indices"]
            if self.l2.has_chunk(run_uid, key, tile_idx):
                continue
            if (run_uid, key, tile_idx) in self.tiles:
                continue
            tile_data = self._extract_tile_from_slab(
                slab, shape, l2_chunks, slice_info, tile_idx
            )
            if self._write_tile_to_l2(run_uid, key, tile_idx, tile_data):
                written += 1

        print_debug(
            "ChunkCache",
            f"Background L2 seed wrote {written} tiles for {key}",
            category="cache",
        )
        return written

    def _ensure_l2_array_from_meta(
        self, run_uid: str, key: str, dtype: np.dtype
    ) -> None:
        """
        Register L2 metadata from cached chunk info when no run object exists.
        """
        if self.l2 is None or not self.l2.enabled:
            return

        meta_key = (run_uid, key)
        if meta_key not in self.chunk_info:
            return

        shape, tiled_chunks = self.chunk_info[meta_key]
        self.l2.register_array(
            run_uid,
            key,
            shape,
            dtype,
            tiled_chunks=tiled_chunks,
        )

    def _store_tile(
        self,
        run_uid: str,
        key: str,
        tile_indices: Tuple[int, ...],
        data: np.ndarray,
    ) -> Optional[str]:
        """
        Store one complete tile in L1, spilling to L2 when L1 is full.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        tile_indices : tuple of int
            Tile index per dimension.
        data : np.ndarray
            Full tile array.

        Returns
        -------
        str or None
            ``"l1"`` when stored in RAM, ``"l2"`` when written directly to L2,
            or None when the tile could not be stored.
        """
        cache_key = (run_uid, key, tile_indices)
        tile_size = data.nbytes
        if tile_size > self.l1_max_bytes:
            if self._write_tile_to_l2(run_uid, key, tile_indices, data):
                return "l2"
            return None

        if cache_key in self.tiles:
            self.l1_tile_size -= self.tiles[cache_key].nbytes

        while self.l1_tile_size + tile_size > self.l1_max_bytes:
            if not self._evict_lru_l1_tile():
                if self._write_tile_to_l2(run_uid, key, tile_indices, data):
                    return "l2"
                return None

        self.tiles[cache_key] = data
        self.l1_tile_size += tile_size
        self._update_l1_tile_access(cache_key)
        return "l1"

    def _write_tile_to_l2(
        self,
        run_uid: str,
        key: str,
        tile_indices: Tuple[int, ...],
        data: np.ndarray,
    ) -> bool:
        """
        Write one tile directly to L2 without retaining it in L1.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        tile_indices : tuple of int
            Tile index per dimension.
        data : np.ndarray
            Full tile array.

        Returns
        -------
        bool
            True when the tile was written or was already complete in L2.
        """
        if self.l2 is None or not self.l2.enabled:
            return False
        if self.l2.has_chunk(run_uid, key, tile_indices):
            return True

        meta_key = (run_uid, key)
        if meta_key not in self.chunk_info:
            return False

        shape, tiled_chunks = self.chunk_info[meta_key]
        self.l2.register_array(
            run_uid,
            key,
            shape,
            data.dtype,
            tiled_chunks=tiled_chunks,
        )
        self.l2.write_chunk(run_uid, key, tile_indices, np.asarray(data))
        return True

    def _cache_l1_tile(
        self,
        run_uid: str,
        key: str,
        tile_indices: Tuple[int, ...],
        data: np.ndarray,
    ) -> None:
        """
        Store one complete L2-aligned tile in the L1 RAM cache.
        """
        self._store_tile(run_uid, key, tile_indices, data)

    def _update_l1_tile_access(self, cache_key: Tuple[str, str, Tuple[int, ...]]) -> None:
        self.l1_tile_access_times[cache_key] = time.time()

    def _evict_lru_l1_tile(self) -> bool:
        if not self.tiles:
            return False

        lru_key = min(self.l1_tile_access_times.items(), key=lambda x: x[1])[0]
        run_uid, key, tile_indices = lru_key
        chunk = self.tiles[lru_key]
        self._write_tile_to_l2(run_uid, key, tile_indices, chunk)
        self.l1_tile_size -= chunk.nbytes
        del self.tiles[lru_key]
        del self.l1_tile_access_times[lru_key]
        return True

    def _ensure_chunk_info(self, run, key: str) -> bool:
        """
        Ensure chunk info is available, fetching from run if needed.
        """
        cache_key = (run.start["uid"], key)

        if cache_key not in self.chunk_info:
            try:
                data_accessor = run["primary", "data", key]
                chunks = data_accessor.chunks

                # Handle variable-sized chunks
                processed_chunks = []
                for dim_chunks in chunks:
                    if isinstance(dim_chunks, tuple):
                        # Keep all chunk sizes for this dimension
                        processed_chunks.append(dim_chunks)
                    else:
                        # Single chunk size for this dimension
                        processed_chunks.append((dim_chunks,))

                self.chunk_info[cache_key] = (
                    data_accessor.shape,
                    tuple(processed_chunks),
                )
                return True

            except Exception as e:
                print(f"Error getting chunk info: {str(e)}")
                return False
        return True

    @staticmethod
    def _is_monolithic_chunking(chunks: Tuple) -> bool:
        """
        Return True when the array is stored as a single Tiled chunk.

        In this layout one "chunk" is the entire array; fetching by chunk
        index downloads everything. Sliced reads must go through the API.
        """
        chunk_count = 1
        for dim_chunks in chunks:
            if isinstance(dim_chunks, (int, np.integer)):
                chunk_count *= 1
            else:
                chunk_count *= len(dim_chunks)
        return chunk_count == 1

    @staticmethod
    def _request_dim_bounds(s: Any, dim_size: int) -> Tuple[int, int]:
        """
        Return half-open ``[start, stop)`` bounds for one slice request dimension.
        """
        if isinstance(s, slice):
            start = 0 if s.start is None else int(s.start)
            stop = dim_size if s.stop is None else int(s.stop)
            return start, stop
        index = int(s)
        return index, index + 1

    @staticmethod
    def _slab_axes_for_array_dims(slice_info: Tuple) -> Dict[int, int]:
        """
        Map array dimensions still present in a squeezed slab to axis indices.
        """
        mapping: Dict[int, int] = {}
        axis = 0
        for dim, item in enumerate(slice_info):
            if isinstance(item, slice):
                mapping[dim] = axis
                axis += 1
        return mapping

    @staticmethod
    def _tile_fully_in_request(
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
        slice_info: Tuple,
        tile_indices: Tuple[int, ...],
    ) -> bool:
        """
        Return whether a tile's full extent lies inside the requested slice.
        """
        chunks = chunk_grid(shape, l2_chunks)
        for dim, tile_idx in enumerate(tile_indices):
            tile_start = sum(chunks[dim][:tile_idx])
            tile_end = tile_start + chunks[dim][tile_idx]
            req_start, req_stop = ChunkCache._request_dim_bounds(
                slice_info[dim], shape[dim]
            )
            if tile_start < req_start or tile_end > req_stop:
                return False
        return True

    @staticmethod
    def _extract_tile_from_slab(
        slab: np.ndarray,
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
        slice_info: Tuple,
        tile_indices: Tuple[int, ...],
    ) -> np.ndarray:
        """
        Extract one full-rank L2 tile array from a fetched slab.
        """
        chunks = chunk_grid(shape, l2_chunks)
        slab_slices: List[slice] = []
        out_shape: List[int] = []

        for dim, tile_idx in enumerate(tile_indices):
            tile_size = chunks[dim][tile_idx]
            tile_start = sum(chunks[dim][:tile_idx])
            out_shape.append(tile_size)
            item = slice_info[dim]
            if isinstance(item, int):
                continue
            req_start, _ = ChunkCache._request_dim_bounds(item, shape[dim])
            slab_slices.append(slice(tile_start - req_start, tile_start - req_start + tile_size))

        patch = slab[tuple(slab_slices)]
        expanded = patch
        for dim, item in enumerate(slice_info):
            if not isinstance(item, slice):
                expanded = np.expand_dims(expanded, axis=dim)
        return np.asarray(expanded)

    @staticmethod
    def _apply_internal_slices_to_chunk(
        chunk: np.ndarray, internal_slices: Tuple
    ) -> np.ndarray:
        """
        Apply per-tile internal slices and collapse integer-indexed axes.

        L2 tiles are stored at full tile rank. Integer entries in
        ``internal_slices`` are applied as length-1 slices, then squeezed so
        assembly uses the same axis mapping as Tiled ``already_sliced`` chunks.

        Parameters
        ----------
        chunk : np.ndarray
            Tile array before internal indexing.
        internal_slices : tuple
            Per-dimension slice or index within the tile.

        Returns
        -------
        np.ndarray
            Indexed tile array with integer axes removed when length is 1.
        """
        slice_list = []
        for s in internal_slices:
            if isinstance(s, int):
                slice_list.append(slice(s, s + 1))
            else:
                slice_list.append(s)
        chunk = chunk[tuple(slice_list)]
        squeeze_axes = tuple(
            i
            for i, s in enumerate(internal_slices)
            if not isinstance(s, slice) and i < chunk.ndim and chunk.shape[i] == 1
        )
        if squeeze_axes:
            chunk = np.squeeze(chunk, axis=squeeze_axes)
        return chunk

    @staticmethod
    def _chunk_needs_internal_slice(chunk: np.ndarray, chunk_info: Dict) -> bool:
        """
        Return True when internal chunk indexing still needs to be applied.

        Parameters
        ----------
        chunk : np.ndarray
            Cached or fetched chunk array.
        chunk_info : dict
            Chunk metadata from get_chunk_indices.

        Returns
        -------
        bool
            True if ``internal_slices`` should be applied to the chunk.
        """
        if chunk_info.get("already_sliced"):
            return False
        return chunk.ndim >= len(chunk_info["internal_slices"])

    @staticmethod
    def _squeeze_indexed_dims(result: np.ndarray, slice_info: Tuple) -> np.ndarray:
        """
        Remove length-1 axes for integer indices still present after assembly.

        Integer indices in ``slice_info`` may already have been removed by a
        direct Tiled slice read; only squeeze axes that exist and have size 1.

        Parameters
        ----------
        result : np.ndarray
            Assembled array from chunk reads.
        slice_info : tuple
            Original per-dimension indices or slices.

        Returns
        -------
        np.ndarray
            Array with redundant length-1 axes removed.
        """
        if result.ndim == 0:
            return result
        axes = tuple(
            i
            for i, s in enumerate(slice_info)
            if not isinstance(s, slice)
            and i < result.ndim
            and result.shape[i] == 1
        )
        if axes:
            return np.squeeze(result, axis=axes)
        return result

    @staticmethod
    def _slice_cache_key(slice_info: Tuple) -> Tuple:
        """
        Build a hashable cache key from a slice request tuple.
        """
        parts = []
        for item in slice_info:
            if isinstance(item, slice):
                parts.append((item.start, item.stop, item.step))
            else:
                parts.append(item)
        return tuple(parts)

    def _get_data_sliced(self, run, key: str, slice_info: Tuple) -> np.ndarray:
        """
        Read only the requested slice via the Tiled client's slice API.

        Parameters
        ----------
        run : BlueskyRun
            Run containing the data.
        key : str
            Data key.
        slice_info : tuple
            Per-dimension indices or slice objects.

        Returns
        -------
        np.ndarray
            The requested array region.
        """
        run_uid = run.start["uid"]
        cache_key = (run_uid, key, self._slice_cache_key(slice_info))
        if cache_key in self.slice_cache:
            self.hits += 1
            self._update_access(cache_key)
            return self.slice_cache[cache_key]

        self.misses += 1
        data_accessor = run["primary", "data", key]
        data = data_accessor.read(slice=slice_info)
        if hasattr(data, "read"):
            data = data.read()
        result = np.asarray(data)

        nbytes = result.nbytes
        if nbytes <= self.max_size:
            while (
                self.current_size + nbytes > self.max_size
                and not self._evict_lru()
            ):
                pass
            if self.current_size + nbytes <= self.max_size:
                self.slice_cache[cache_key] = result
                self.current_size += nbytes
                self._update_access(cache_key)

        print_debug(
            "ChunkCache",
            f"Direct slice read {key} shape {result.shape} ({nbytes / 1e6:.1f} MB)",
            category="cache",
        )
        return result

    def _global_slice_from_chunk(
        self,
        run_uid: str,
        key: str,
        chunk_indices: Tuple[int, ...],
        internal_slices: Tuple,
    ) -> Tuple:
        """
        Convert chunk-local indices into a global slice for the Tiled API.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        chunk_indices : tuple
            Chunk index per dimension.
        internal_slices : tuple
            Slice within the chunk (from get_chunk_indices).

        Returns
        -------
        tuple
            Global slice tuple for data_accessor.read(slice=...).
        """
        shape, chunks = self.chunk_info[(run_uid, key)]
        global_slice = []
        for dim, (chunk_idx, internal_s) in enumerate(
            zip(chunk_indices, internal_slices)
        ):
            chunk_start = sum(chunks[dim][:chunk_idx])
            if isinstance(internal_s, int):
                global_slice.append(chunk_start + internal_s)
            elif isinstance(internal_s, slice):
                start = internal_s.start if internal_s.start is not None else 0
                stop = (
                    internal_s.stop
                    if internal_s.stop is not None
                    else shape[dim]
                )
                global_slice.append(
                    slice(
                        chunk_start + start,
                        chunk_start + stop,
                        internal_s.step,
                    )
                )
            else:
                global_slice.append(internal_s)
        return tuple(global_slice)

    def _fetch_chunk(
        self, run, key: str, chunk_info: Dict
    ) -> Optional[np.ndarray]:
        """
        Worker function to fetch a single chunk from the data source.
        Also handles caching the chunk data atomically.

        Parameters
        ----------
        run : BlueskyRun
            The run object containing the data
        key : str
            The data key
        chunk_info : dict
            Chunk metadata including chunk_indices and internal_slices.

        Returns
        -------
        Optional[np.ndarray]
            The chunk data if successful, None if failed
        """
        chunk_idx = chunk_info["chunk_indices"]
        internal_slices = chunk_info["internal_slices"]
        try:
            run_uid = run.start["uid"]
            global_slice = self._global_slice_from_chunk(
                run_uid, key, chunk_idx, internal_slices
            )
            print_debug(
                "ChunkCache",
                f"Fetching {key} chunk {chunk_idx} via global slice {global_slice}",
                category="cache",
            )

            data_accessor = run["primary", "data", key]
            chunk_data = data_accessor.read(slice=global_slice)
            if hasattr(chunk_data, "read"):
                chunk_data = chunk_data.read()
            chunk_data = np.asarray(chunk_data)

            if chunk_data is not None and self._cache_tiled_fetches:
                cache_key = (
                    run_uid,
                    key,
                    chunk_idx,
                    self._slice_cache_key(internal_slices),
                )
                nbytes = chunk_data.nbytes
                if nbytes <= self.max_size:
                    self._store_in_slice_cache(cache_key, chunk_data)
            print_debug(
                "ChunkCache",
                f"Chunk {chunk_idx} fetched shape {chunk_data.shape}",
                category="cache",
            )
            chunk_info["already_sliced"] = True
            return chunk_data
        except Exception as e:
            print(f"Error fetching chunk: {str(e)}")
            return None

    def _get_or_fetch_chunks(
        self, run, key: str, chunks_needed: List[Dict]
    ) -> Dict[Tuple[int, ...], np.ndarray]:
        """
        Get chunks from cache or fetch them using the worker pool.

        Parameters
        ----------
        run : BlueskyRun
            The run object containing the data
        key : str
            The data key
        chunks_needed : List[Dict]
            List of chunk information dictionaries

        Returns
        -------
        Dict[Tuple[int, ...], np.ndarray]
            Dictionary mapping chunk indices to chunk data
        """
        result = {}
        futures_to_wait = []
        run_uid = run.start["uid"]
        batch_total = 0

        # First pass: check cache and start fetches for missing chunks
        with self.request_lock:
            for chunk_info in chunks_needed:
                chunk_idx = chunk_info["chunk_indices"]
                cache_key = (run.start["uid"], key, chunk_idx)

                slice_key = (
                    run.start["uid"],
                    key,
                    chunk_idx,
                    self._slice_cache_key(chunk_info["internal_slices"]),
                )
                if slice_key in self.slice_cache:
                    result[chunk_idx] = self.slice_cache[slice_key]
                    chunk_info["already_sliced"] = True
                    self.hits += 1
                    continue

                if cache_key in self.chunks:
                    result[chunk_idx] = self.chunks[cache_key]
                    self.hits += 1
                    continue

                if cache_key in self.active_requests:
                    futures_to_wait.append((chunk_idx, self.active_requests[cache_key]))
                    continue

                self.misses += 1
                future = self.worker_pool.submit(
                    self._fetch_chunk, run, key, chunk_info
                )
                self.active_requests[cache_key] = future
                futures_to_wait.append((chunk_idx, future))

            batch_total = len(futures_to_wait)

        if batch_total > 0:
            self._notify_tiled_fetch_progress(
                run_uid,
                key,
                active=True,
                pending_chunks=batch_total,
                batch_total=batch_total,
            )

        pending_chunks = batch_total
        try:
            for chunk_idx, future in futures_to_wait:
                print_debug(
                    "ChunkCache",
                    f"Waiting for chunk {chunk_idx}",
                    category="cache",
                )
                try:
                    chunk_data = future.result()
                    if chunk_data is not None:
                        result[chunk_idx] = chunk_data
                except Exception as e:
                    print(f"Error waiting for chunk {chunk_idx}: {str(e)}")
                finally:
                    with self.request_lock:
                        cache_key = (run_uid, key, chunk_idx)
                        if cache_key in self.active_requests:
                            del self.active_requests[cache_key]
                    pending_chunks = max(0, pending_chunks - 1)
                    if batch_total > 0:
                        self._notify_tiled_fetch_progress(
                            run_uid,
                            key,
                            active=True,
                            pending_chunks=pending_chunks,
                            batch_total=batch_total,
                        )
        finally:
            if batch_total > 0:
                self._notify_tiled_fetch_progress(
                    run_uid,
                    key,
                    active=False,
                    pending_chunks=0,
                    batch_total=batch_total,
                )

        return result

    def get_chunk_indices(
        self, run_uid: str, key: str, slice_info: Tuple
    ) -> Tuple[List[Dict], Tuple[slice, ...]]:
        """
        Convert a slice request into chunk indices and internal chunk slices.

        Parameters
        ----------
        run_uid : str
            Unique identifier for the run
        key : str
            Data key
        slice_info : tuple
            User's slice request

        Returns
        -------
        tuple
            (chunks_needed, full_shape) where chunks_needed is a list of dicts containing:
            - chunk_indices: tuple of indices for this chunk
            - chunk_shape: actual shape of this chunk
            - internal_slices: how to slice this chunk
            full_shape is the shape of the complete dataset
        """
        if (run_uid, key) not in self.chunk_info:
            raise KeyError(f"No chunk info found for {run_uid}:{key}")

        shape, chunks = self.chunk_info[(run_uid, key)]
        # print_debug("ChunkCache", f"\nSlice conversion debugging:", category="cache")
        # print_debug("ChunkCache", f"Input slice_info: {slice_info}", category="cache")
        # print_debug("ChunkCache", f"Data shape: {shape}", category="cache")
        # print_debug("ChunkCache", f"Chunk sizes: {chunks}", category="cache")

        # Ensure slice_info matches the data dimensionality
        if len(slice_info) != len(shape):
            raise ValueError(
                f"Slice dimensionality ({len(slice_info)}) does not match "
                f"data dimensionality ({len(shape)})"
            )

        # For each dimension, calculate which chunks we need
        chunks_needed = []
        base_chunk_indices = []

        for dim, (s, dim_size, chunk_sizes) in enumerate(
            zip(slice_info, shape, chunks)
        ):
            # print_debug(
            #     "ChunkCache", f"\nProcessing dimension {dim}:", category="cache"
            # )
            # Calculate cumulative positions for chunk boundaries
            positions = [0]
            for size in chunk_sizes:
                positions.append(positions[-1] + size)

            dim_chunks = []
            if isinstance(s, slice):
                # Handle slice request
                start = s.start if s.start is not None else 0
                stop = s.stop if s.stop is not None else dim_size
                # print_debug(
                #     "ChunkCache", f"  Slice request {start}:{stop}", category="cache"
                # )

                # Find chunks that overlap with request
                for chunk_idx, (chunk_start, chunk_end) in enumerate(
                    zip(positions[:-1], positions[1:])
                ):
                    if chunk_start < stop and chunk_end > start:
                        dim_chunks.append(chunk_idx)
                        # print_debug(
                        #     "ChunkCache",
                        #     f"  Chunk {chunk_idx}: pos {chunk_start}:{chunk_end}",
                        #     category="cache",
                        # )
            else:
                # Handle integer index
                pos = 0
                for chunk_idx, size in enumerate(chunk_sizes):
                    if pos <= s < pos + size:
                        internal_idx = s - pos
                        dim_chunks.append(chunk_idx)
                        # print_debug(
                        #     "ChunkCache",
                        #     f"  Index {s} in chunk {chunk_idx} at internal position {internal_idx}",
                        #     category="cache",
                        # )
                        break
                    pos += size

            base_chunk_indices.append(dim_chunks)

        # Generate all combinations of chunk indices
        from itertools import product

        print_debug(
            "ChunkCache",
            f"\nGenerating chunk combinations from: {base_chunk_indices}",
            category="cache",
        )

        for chunk_indices in product(*base_chunk_indices):
            # Calculate the shape and internal slices for this chunk
            chunk_shape = []
            internal_slices = []

            for dim, (chunk_idx, s, dim_size) in enumerate(
                zip(chunk_indices, slice_info, shape)
            ):
                # Get actual chunk size for this dimension
                chunk_size = chunks[dim][chunk_idx]
                chunk_shape.append(chunk_size)

                # Calculate chunk start position
                chunk_start = sum(chunks[dim][:chunk_idx])

                # Calculate internal slice
                if isinstance(s, slice):
                    start = s.start if s.start is not None else 0
                    stop = s.stop if s.stop is not None else dim_size
                    internal_start = max(0, start - chunk_start)
                    internal_stop = min(chunk_size, stop - chunk_start)
                    internal_slices.append(slice(internal_start, internal_stop))
                else:
                    # For integer index, calculate position within chunk
                    internal_slices.append(s - chunk_start)

            chunks_needed.append(
                {
                    "chunk_indices": chunk_indices,
                    "chunk_shape": tuple(chunk_shape),
                    "internal_slices": tuple(internal_slices),
                }
            )
            print_debug("ChunkCache", f"Chunk {chunk_indices}:", category="cache")
            print_debug(
                "ChunkCache", f"  Shape: {tuple(chunk_shape)}", category="cache"
            )
            msg = f"  Internal slices: {tuple(internal_slices)}"
            print_debug("ChunkCache", msg, category="cache")

        return chunks_needed, shape

    @staticmethod
    def _coord_dim_to_array_axis(depth: int, internal_slices: Tuple) -> int:
        """
        Map a chunk-grid coordinate dimension to an array axis.

        Integer indices in ``internal_slices`` collapse axes when data is read
        from Tiled, so coordinate depth does not match array axis index.
        """
        return depth - sum(
            1
            for i in range(depth)
            if not isinstance(internal_slices[i], slice)
        )

    def _assemble_result(
        self,
        chunks_data: Dict[Tuple[int, ...], np.ndarray],
        chunks_needed: List[Dict],
        full_shape: Tuple[int, ...],
    ) -> np.ndarray:
        """
        Assemble chunks into final result array.
        """
        internal_slices = chunks_needed[0]["internal_slices"]

        processed_chunks = {}
        for chunk_info in chunks_needed:
            chunk_idx = chunk_info["chunk_indices"]
            chunk = chunks_data[chunk_idx]

            if self._chunk_needs_internal_slice(chunk, chunk_info):
                chunk = self._apply_internal_slices_to_chunk(
                    chunk, chunk_info["internal_slices"]
                )
            processed_chunks[chunk_idx] = chunk

        chunks = list(processed_chunks.values())
        coords = list(processed_chunks.keys())

        def concat_chunks(chunks_list, coords_list, depth=0):
            if not chunks_list:
                return None
            if depth >= len(coords_list[0]):
                return chunks_list[0]

            groups = {}
            for chunk, coord in zip(chunks_list, coords_list):
                key = coord[depth]
                if key not in groups:
                    groups[key] = ([], [])
                groups[key][0].append(chunk)
                groups[key][1].append(coord)

            results = []
            for key in sorted(groups.keys()):
                group_chunks, group_coords = groups[key]
                result = concat_chunks(group_chunks, group_coords, depth + 1)
                if result is not None:
                    results.append(result)

            if not results:
                return None
            if len(results) == 1:
                return results[0]

            array_axis = self._coord_dim_to_array_axis(depth, internal_slices)
            if array_axis >= results[0].ndim:
                array_axis = results[0].ndim - 1
            return np.concatenate(results, axis=array_axis)

        result = concat_chunks(chunks, coords)
        if result is None:
            raise ValueError("No chunk data to assemble")
        return result

    def get_chunks(
        self, run_uid: str, key: str, chunk_indices: Tuple[int, ...]
    ) -> Optional[np.ndarray]:
        """
        Get cached chunk data if available.

        Parameters
        ----------
        run_uid : str
            Unique identifier for the run
        key : str
            Data key
        chunk_indices : tuple
            Indices identifying the chunk

        Returns
        -------
        np.ndarray or None
            Cached chunk data if available, None otherwise
        """
        cache_key = (run_uid, key, chunk_indices)
        chunk = self.chunks.get(cache_key)

        if chunk is not None:
            self.hits += 1
            # Update access tracking
            self._update_access(cache_key)
            return chunk

        self.misses += 1
        return None

    def cache_chunk(
        self, run_uid: str, key: str, chunk_indices: Tuple[int, ...], data: np.ndarray
    ):
        """
        Cache chunk data, managing memory limits.

        Parameters
        ----------
        run_uid : str
            Unique identifier for the run
        key : str
            Data key
        chunk_indices : tuple
            Indices identifying the chunk
        data : np.ndarray
            Chunk data to cache
        """
        cache_key = (run_uid, key, chunk_indices)

        # Check memory limits
        chunk_size = data.nbytes
        if chunk_size > self.max_size:
            msg = f"Chunk too large to cache: {chunk_size} bytes"
            print_debug("ChunkCache", msg, category="cache")
            return

        # Ensure we have enough memory
        while (
            self.current_size + chunk_size > self.max_size
            or psutil.virtual_memory().percent > (1 - self.min_free_memory) * 100
        ):
            if not self._evict_lru():
                msg = "Cannot free enough memory to cache chunk"
                print_debug("ChunkCache", msg, category="cache")
                print_debug("ChunkCache", self.get_stats(), category="cache")
                return

        # Store the chunk
        self.chunks[cache_key] = data
        self.current_size += chunk_size
        self._update_access(cache_key)

    def set_chunk_info(
        self, run_uid: str, key: str, shape: Tuple[int, ...], chunks: Tuple[int, ...]
    ):
        """
        Set chunk information for a dataset.

        Parameters
        ----------
        run_uid : str
            Unique identifier for the run
        key : str
            Data key
        shape : tuple
            Full shape of the dataset
        chunks : tuple
            Chunk size for each dimension
        """
        self.chunk_info[(run_uid, key)] = (shape, chunks)

    def clear_run(self, run_uid: str):
        """
        Clear all cached data for a specific run.

        Parameters
        ----------
        run_uid : str
            Unique identifier for the run to clear
        """
        # Remove chunk info
        keys_to_remove = [(r, k) for r, k in self.chunk_info.keys() if r == run_uid]
        for key in keys_to_remove:
            del self.chunk_info[key]

        if self.l2 is not None:
            self.l2.clear_run(run_uid)
        if self.progress is not None:
            self.progress.clear()

        # Remove chunks and their tracking info
        chunk_keys = [(r, k, i) for r, k, i in self.chunks.keys() if r == run_uid]
        tile_keys = [(r, k, i) for r, k, i in self.tiles.keys() if r == run_uid]

        with self.request_lock:
            # Cancel any active requests
            for key in chunk_keys:
                if key in self.active_requests:
                    self.active_requests[key].cancel()
                    del self.active_requests[key]

            # Remove cached chunks
            for key in chunk_keys:
                if key in self.chunks:
                    chunk = self.chunks[key]
                    self.current_size -= chunk.nbytes
                    del self.chunks[key]
                if key in self.access_times:
                    del self.access_times[key]
                if key in self.access_counts:
                    del self.access_counts[key]

            for key in tile_keys:
                if key in self.tiles:
                    self.l1_tile_size -= self.tiles[key].nbytes
                    del self.tiles[key]
                if key in self.l1_tile_access_times:
                    del self.l1_tile_access_times[key]

    def clear(self):
        """Clear all cached data and shutdown worker pool."""
        with self.request_lock:
            # Cancel all active requests
            for future in self.active_requests.values():
                future.cancel()
            self.active_requests.clear()

            # Clear cache data
            self.chunks.clear()
            self.tiles.clear()
            self.slice_cache.clear()
            self.chunk_info.clear()
            self.access_times.clear()
            self.access_counts.clear()
            self.l1_tile_access_times.clear()
            self.current_size = 0
            self.l1_tile_size = 0
            self.hits = 0
            self.misses = 0
            self.l2_hits = 0
            self.l2_misses = 0
            if self.l2 is not None:
                self.l2.clear()
            if self.progress is not None:
                self.progress.clear()

        # Shutdown worker pool
        self.worker_pool.shutdown(wait=True)
        # Create new worker pool
        self.worker_pool = ThreadPoolExecutor(max_workers=4)

    def _update_access(self, cache_key: Tuple[str, str, Tuple[int, ...]]):
        """Update access time and count for a chunk."""
        self.access_times[cache_key] = time.time()
        self.access_counts[cache_key] = self.access_counts.get(cache_key, 0) + 1

    def _store_in_slice_cache(
        self, cache_key: Tuple, chunk_data: np.ndarray
    ) -> None:
        """
        Store one Tiled fetch result in the slice cache with LRU eviction.
        """
        nbytes = chunk_data.nbytes
        while (
            self.current_size + nbytes > self.max_size
            and self._evict_lru()
        ):
            pass
        if self.current_size + nbytes <= self.max_size:
            self.slice_cache[cache_key] = chunk_data
            self.current_size += nbytes
            self._update_access(cache_key)

    def _evict_lru(self) -> bool:
        """
        Evict the least recently used tiled chunk or slice-cache entry.

        Returns
        -------
        bool
            True if an entry was evicted, False if nothing remains.
        """
        if not self.access_times:
            return False

        lru_key = min(self.access_times.items(), key=lambda x: x[1])[0]

        if lru_key in self.slice_cache:
            chunk = self.slice_cache[lru_key]
            del self.slice_cache[lru_key]
        elif lru_key in self.chunks:
            chunk = self.chunks[lru_key]
            del self.chunks[lru_key]
        else:
            del self.access_times[lru_key]
            if lru_key in self.access_counts:
                del self.access_counts[lru_key]
            return True

        self.current_size -= chunk.nbytes
        del self.access_times[lru_key]
        if lru_key in self.access_counts:
            del self.access_counts[lru_key]
        return True

    def flush_l1_to_l2(
        self,
        run_uid: Optional[str] = None,
        key: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Spill every L1 tile to L2 and clear the L1 tile cache.

        Parameters
        ----------
        run_uid : str, optional
            Restrict to one run identifier.
        key : str, optional
            Restrict to one data key.

        Returns
        -------
        dict
            Counts of flushed, failed, and remaining L1 tiles.
        """
        flushed = 0
        failed = 0
        for cache_key in list(self.tiles.keys()):
            tile_run_uid, tile_key, tile_indices = cache_key
            if run_uid is not None and tile_run_uid != run_uid:
                continue
            if key is not None and tile_key != key:
                continue

            data = self.tiles[cache_key]
            if self._write_tile_to_l2(tile_run_uid, tile_key, tile_indices, data):
                flushed += 1
            else:
                failed += 1
            self.l1_tile_size -= data.nbytes
            del self.tiles[cache_key]
            del self.l1_tile_access_times[cache_key]

        print_debug(
            "ChunkCache",
            f"Flushed {flushed} L1 tiles to L2"
            + (f" ({failed} failed)" if failed else ""),
            category="cache",
        )
        return {
            "flushed": flushed,
            "failed": failed,
            "remaining_l1_tiles": len(self.tiles),
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns
        -------
        dict
            Dictionary containing cache statistics
        """
        return {
            "size": self.current_size,
            "max_size": self.max_size,
            "l1_max_bytes": self.l1_max_bytes,
            "chunk_count": len(self.chunks),
            "l1_tile_count": len(self.tiles),
            "l1_tile_size": self.l1_tile_size,
            "hits": self.hits,
            "misses": self.misses,
            "l2_hits": self.l2_hits,
            "l2_misses": self.l2_misses,
            "hit_rate": (
                self.hits / (self.hits + self.misses)
                if (self.hits + self.misses) > 0
                else 0
            ),
            "memory_usage": psutil.virtual_memory().percent,
        }

    def format_debug_report(
        self, datasets: Optional[List[Tuple[str, str]]] = None
    ) -> str:
        """
        Build a human-readable cache statistics report.

        Parameters
        ----------
        datasets : list of tuple, optional
            ``(run_uid, key)`` pairs to include L2 dataset detail for.

        Returns
        -------
        str
            Multi-line debug report.
        """
        lines = ["=== ChunkCache stats ==="]
        stats = self.get_stats()
        for name, value in stats.items():
            lines.append(f"  {name}: {value}")

        lines.append("  slice_cache_entries: {}".format(len(self.slice_cache)))
        lines.append("  tiled_chunk_entries: {}".format(len(self.chunks)))

        if self.l2 is not None and self.l2.enabled:
            lines.append("=== L2 Zarr cache ===")
            for entry in self.l2.dataset_entries():
                lines.append(
                    "  {run_uid}/{key}: {completed}/{total} tiles "
                    "({fraction:.1%})".format(**entry)
                )

        if datasets:
            lines.append("=== Requested datasets ===")
            for run_uid, key in datasets:
                fraction = self.l2_completion_fraction(run_uid, key)
                if self.l2 is not None:
                    completed, total = self.l2.tile_counts(run_uid, key)
                    lines.append(
                        f"  {run_uid}/{key}: L2 {completed}/{total} "
                        f"({fraction:.1%})"
                    )
                else:
                    lines.append(f"  {run_uid}/{key}: L2 disabled")

        return "\n".join(lines)

    def l2_completion_fraction(self, run_uid: str, key: str) -> float:
        """
        Return L2 tile completion fraction for one dataset.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.

        Returns
        -------
        float
            Fraction in ``[0, 1]``, or 0 when L2 is disabled.
        """
        if self.l2 is None or not self.l2.enabled:
            return 0.0
        return self.l2.completion_fraction(run_uid, key)
