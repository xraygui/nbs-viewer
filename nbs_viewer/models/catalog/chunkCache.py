"""
Chunk-aware caching system for efficient data access from chunked array storage.
"""

import time
import numpy as np
import psutil
from typing import Dict, Tuple, Any, Optional, List, Set
from nbs_viewer.utils import print_debug
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from threading import Lock

from .chunk_cache_progress import ChunkCacheProgress
from .tile_indices import (
    chunk_grid,
    l2_chunks_for_shape,
    plan_hyperslab_batches,
    request_dim_bounds,
    tiles_intersecting,
    union_l2_tile_fetch_slice,
)
from .zarr_l2_cache import ZarrL2Cache


class ChunkCache:
    """
    Central cache for chunked array data across all runs in a catalog.

    This cache is designed to efficiently handle chunked array data by:
    1. Serving views from an in-memory Zarr store (primary local cache)
    2. Optionally spilling / persisting tiles via the same Zarr API
    3. Fetching cold data from Tiled via byte-budgeted hyperslab reads

    The older dict-based tile L1 (``self.tiles``) is retained but unused on
    the hot path; memory Zarr is the effective L1.
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
        fetch_batch_target_bytes: Optional[int] = 50_000_000,
        progress: Optional[ChunkCacheProgress] = None,
    ):
        # Cache storage
        self.slice_cache: Dict[Tuple, np.ndarray] = {}
        self.tiles: Dict[Tuple[str, str, Tuple[int, ...]], np.ndarray] = {}
        self.partial_l1_tiles: Set[Tuple[str, str, Tuple[int, ...]]] = set()
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
        self.fetch_batch_target_bytes = fetch_batch_target_bytes

        # Access tracking
        self.access_times: Dict[Tuple[str, str, Tuple[int, ...]], float] = {}
        self.l1_tile_access_times: Dict[Tuple[str, str, Tuple[int, ...]], float] = {}

        self.fetch_pool = ThreadPoolExecutor(max_workers=4)
        self.background_pool = ThreadPoolExecutor(max_workers=2)
        self._active_l2_materialize_jobs: Dict[Tuple[str, str], Future] = {}
        self._l2_materialize_job_seq = 0
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
            print_debug("ChunkCache", f"get_data {key}:{slice_info}", category="cache")
            # Ensure we have chunk info
            if not self._ensure_chunk_info(run, key):
                raise ValueError(
                    f"Could not get chunk info for {run.start['uid']}:{key}"
                )

            run_uid = run.start["uid"]
            shape, chunks = self.chunk_info[(run_uid, key)]

            cached_slab = self._lookup_assembled_slab(run_uid, key, slice_info)

            if cached_slab is not None:
                slab = cached_slab
            elif self.l2 is not None and self.l2.enabled:
                self.wait_for_background_materialize(run_uid, key)
                slab = self._get_data_l2_pipeline(
                    run, key, slice_info, run_uid, shape, chunks
                )
            else:
                slab = self._read_tiled_hyperslab(run, key, slice_info)

            return self._finalize_slice_result(slab, slice_info)

        except Exception as e:
            print_debug("ChunkCache", f"Error in get_data: {str(e)}", category="cache")
            raise

    def _l2_chunks(self, run_uid: str, key: str) -> Tuple[int, ...]:
        """
        Return the L2 tile size tuple adapted to one dataset's rank.
        """
        shape, _ = self.chunk_info[(run_uid, key)]
        return l2_chunks_for_shape(shape, self.l2.l2_chunks)

    def _ensure_l2_array(self, run, key: str) -> None:
        """
        Register array metadata with the Zarr local cache when enabled.
        """
        if self.l2 is None or not self.l2.enabled:
            return

        run_uid = run.start["uid"]
        if (run_uid, key) in self.l2._meta:
            return

        shape, tiled_chunks = self.chunk_info[(run_uid, key)]
        print_debug(
            "ensure_l2_array",
            f"registering array {key} with shape {shape} and chunks {tiled_chunks}",
            category="cache",
        )
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

    def _try_get_data_from_zarr(
        self, run, key: str, slice_info: Tuple
    ) -> Optional[np.ndarray]:
        """
        Serve a view from memory Zarr when all intersecting tiles are complete.

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
            Hyperslab from Zarr, or None on a miss.
        """
        if self.l2 is None or not self.l2.enabled:
            return None

        run_uid = run.start["uid"]
        self._ensure_l2_array(run, key)
        if not self.l2.covers_slice(run_uid, key, slice_info):
            self.l2_misses += 1
            return None

        print_debug(
            "ChunkCache",
            f"Zarr hyperslab hit {key}:{slice_info}",
            category="cache",
        )
        result = self.l2.read_hyperslab(run_uid, key, slice_info)
        self.l2_hits += 1
        self.hits += 1
        return self._squeeze_indexed_dims(result, slice_info)

    def _try_get_data_from_l2_tiles(
        self, run, key: str, slice_info: Tuple
    ) -> Optional[np.ndarray]:
        """
        Assemble a result from complete L1/L2 tiles when possible.

        Retained for tests and legacy paths; the hot path uses
        ``_try_get_data_from_zarr`` instead.
        """
        run_uid = run.start["uid"]
        shape, _ = self.chunk_info[(run_uid, key)]
        self._ensure_l2_array(run, key)
        l2_chunks = self._l2_chunks(run_uid, key)

        tiles_needed = tiles_intersecting(shape, l2_chunks, slice_info)
        chunks_data = {}
        used_l2 = False
        for tile_info in tiles_needed:
            tile_idx = tile_info["chunk_indices"]
            cache_key = (run_uid, key, tile_idx)
            if cache_key in self.tiles and cache_key not in self.partial_l1_tiles:
                chunk = self.tiles[cache_key]
                self._update_l1_tile_access(cache_key)
            elif self.l2.has_chunk(run_uid, key, tile_idx):
                chunk = self.l2.read_chunk(run_uid, key, tile_idx)
                self._store_tile(run_uid, key, tile_idx, chunk)
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
        result = self._assemble_result(
            chunks_data, tiles_needed, shape, slice_info
        )
        return self._squeeze_indexed_dims(result, slice_info)

    def _get_data_l2_pipeline(
        self,
        run,
        key: str,
        slice_info: Tuple,
        run_uid: str,
        shape: Tuple[int, ...],
        chunks: Tuple,
    ) -> np.ndarray:
        """
        Memory-Zarr hit path, else partial fill, else Tiled hyperslab + Zarr seed.
        """
        print_debug("ChunkCache", f"get_data_l2_pipeline {key}:{slice_info}", category="cache")
        self._ensure_l2_array(run, key)

        print_debug("ChunkCache", f"trying Zarr hyperslab for {key}:{slice_info}", category="cache")
        zarr_hit = self._try_get_data_from_zarr(run, key, slice_info)
        if zarr_hit is not None:
            print_debug("ChunkCache", f"storing assembled slab for {key}:{slice_info}", category="cache")
            self._store_assembled_slab(run_uid, key, slice_info, zarr_hit, shape)
            return zarr_hit

        print_debug("ChunkCache", f"trying to get data from partial l2 for {key}:{slice_info}", category="cache")
        partial = self._try_get_data_partial_l2(run, key, slice_info)
        if partial is not None:
            print_debug("ChunkCache", f"storing assembled slab for {key}:{slice_info}", category="cache")
            self._store_assembled_slab(run_uid, key, slice_info, partial, shape)
            return partial

        result = self._read_tiled_hyperslab(run, key, slice_info)
        self._finish_slab_fetch(run, key, slice_info, result)
        print_debug("ChunkCache", f"returning result for {key}:{slice_info}", category="cache")
        return result

    def _tile_is_complete(
        self, run_uid: str, key: str, tile_indices: Tuple[int, ...]
    ) -> bool:
        """
        Return whether a tile is available in the Zarr local cache.
        """
        if self.l2 is not None and self.l2.has_chunk(run_uid, key, tile_indices):
            return True
        return False

    def _partition_l2_tiles(
        self, run_uid: str, key: str, tile_infos: List[Dict]
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Split intersecting L2 tiles into warm (complete) and cold (missing).
        """
        warm: List[Dict] = []
        cold: List[Dict] = []
        for tile_info in tile_infos:
            tile_idx = tile_info["chunk_indices"]
            if self._tile_is_complete(run_uid, key, tile_idx):
                warm.append(tile_info)
            else:
                cold.append(tile_info)
        return warm, cold

    @staticmethod
    def _cold_gap_slice_info(
        shape: Tuple[int, ...],
        slice_info: Tuple,
        cold_tiles: List[Dict],
        l2_chunks: Tuple[int, ...],
    ) -> Tuple:
        """
        Build a Tiled hyperslab covering the union of cold tile intersections.
        """
        items = list(slice_info)
        grid = chunk_grid(shape, l2_chunks)
        for dim in range(len(shape)):
            if not isinstance(items[dim], slice):
                continue
            req_start, req_stop = request_dim_bounds(items[dim], shape[dim])
            starts: List[int] = []
            stops: List[int] = []
            for tile_info in cold_tiles:
                tile_idx = tile_info["chunk_indices"][dim]
                tile_start = sum(grid[dim][:tile_idx])
                tile_end = tile_start + grid[dim][tile_idx]
                start = max(req_start, tile_start)
                stop = min(req_stop, tile_end)
                if start < stop:
                    starts.append(start)
                    stops.append(stop)
            if starts:
                items[dim] = slice(min(starts), max(stops))
        return tuple(items)

    @staticmethod
    def _slab_shape(slice_info: Tuple, shape: Tuple[int, ...]) -> Tuple[int, ...]:
        """
        Return the array shape for a slice request before index squeezing.
        """
        out: List[int] = []
        for dim_size, item in zip(shape, slice_info):
            if isinstance(item, slice):
                start, stop = request_dim_bounds(item, dim_size)
                out.append(stop - start)
        return tuple(out)

    def _load_l2_tile_array(
        self, run_uid: str, key: str, tile_indices: Tuple[int, ...]
    ) -> np.ndarray:
        """
        Return a complete tile from the Zarr local cache.
        """
        chunk = self.l2.read_chunk(run_uid, key, tile_indices)
        print_debug(
            "ChunkCache",
            f"Zarr local read {key} tile={tile_indices} shape={chunk.shape}",
            category="cache",
        )
        return chunk

    def _paste_region(
        self,
        target: np.ndarray,
        dest_slices: List[slice],
        source: np.ndarray,
        src_slices: List[slice],
    ) -> None:
        """
        Copy a source array region into a target slab with shape clamping.
        """
        if source.ndim != len(dest_slices):
            return
        clamped_dest: List[slice] = []
        clamped_src: List[slice] = []
        for axis, (dest_sl, src_sl) in enumerate(zip(dest_slices, src_slices)):
            d_len = dest_sl.stop - dest_sl.start
            s_len = src_sl.stop - src_sl.start
            avail = source.shape[axis] - src_sl.start
            use = min(d_len, s_len, avail)
            if use <= 0:
                return
            clamped_dest.append(slice(dest_sl.start, dest_sl.start + use))
            clamped_src.append(slice(src_sl.start, src_sl.start + use))
        target[tuple(clamped_dest)] = source[tuple(clamped_src)]

    def _paste_tile_into_slab(
        self,
        slab: np.ndarray,
        tile_info: Dict,
        tile_data: np.ndarray,
        slice_info: Tuple,
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
    ) -> None:
        """
        Copy one L2 tile intersection into a view-aligned output slab.
        """

        tile_idx = tile_info["chunk_indices"]
        chunk = tile_data
        applied_internal = False
        if self._chunk_needs_internal_slice(chunk, tile_info):
            chunk = self._apply_internal_slices_to_chunk(
                chunk, tile_info["internal_slices"], slice_info
            )
            applied_internal = True
        elif chunk.ndim == len(tile_info["internal_slices"]):
            try:
                chunk = self._apply_internal_slices_to_chunk(
                    chunk, tile_info["internal_slices"], slice_info
                )
                applied_internal = True
            except (IndexError, ValueError):
                return

        grid = chunk_grid(shape, l2_chunks)
        internal_slices = tile_info["internal_slices"]
        dest_slices: List[slice] = []
        src_slices: List[slice] = []
        for dim, item in enumerate(slice_info):
            if isinstance(item, int):
                continue
            req_start, req_stop = request_dim_bounds(item, shape[dim])
            tile_start = sum(grid[dim][: tile_idx[dim]])
            tile_end = tile_start + grid[dim][tile_idx[dim]]
            overlap_start = max(req_start, tile_start)
            overlap_stop = min(req_stop, tile_end)
            if overlap_start >= overlap_stop:
                return
            dest_slices.append(
                slice(overlap_start - req_start, overlap_stop - req_start)
            )
            src_start = overlap_start - tile_start
            src_stop = overlap_stop - tile_start
            if applied_internal:
                internal = internal_slices[dim]
                if isinstance(internal, slice):
                    internal_start = (
                        0 if internal.start is None else internal.start
                    )
                    src_start -= internal_start
                    src_stop -= internal_start
            src_slices.append(slice(src_start, src_stop))
        if chunk.ndim != len(dest_slices):
            raise ValueError(
                f"Tile paste rank mismatch: chunk ndim {chunk.ndim} != "
                f"destination rank {len(dest_slices)} for tile "
                f"{tile_info['chunk_indices']}"
            )
        self._paste_region(slab, dest_slices, chunk, src_slices)

    def _paste_gap_into_slab(
        self,
        slab: np.ndarray,
        gap_data: np.ndarray,
        slice_info: Tuple,
        gap_slice: Tuple,
        shape: Tuple[int, ...],
    ) -> None:
        """
        Copy a cold-gap hyperslab into its position within the full view slab.
        """
        print_debug("paste_gap_into_slab", f"slab shape: {slab.shape}", category="cache")
        print_debug("paste_gap_into_slab", f"gap data shape: {gap_data.shape}", category="cache")
        print_debug("paste_gap_into_slab", f"gap slice: {gap_slice}", category="cache")
        print_debug("paste_gap_into_slab", f"slice info: {slice_info}", category="cache")

        dest_slices: List[slice] = []
        src_slices: List[slice] = []
        for dim, item in enumerate(slice_info):
            if isinstance(item, int):
                continue
            req_start, req_stop = request_dim_bounds(item, shape[dim])
            gap_item = gap_slice[dim]
            gap_start, gap_stop = request_dim_bounds(gap_item, shape[dim])
            overlap_start = max(req_start, gap_start)
            overlap_stop = min(req_stop, gap_stop)
            if overlap_start >= overlap_stop:
                continue
            dest_slices.append(
                slice(overlap_start - req_start, overlap_stop - req_start)
            )
            src_slices.append(
                slice(overlap_start - gap_start, overlap_stop - gap_start)
            )
        if len(dest_slices) != gap_data.ndim:
            return
        self._paste_region(slab, dest_slices, gap_data, src_slices)

    def _try_get_data_partial_l2(
        self, run, key: str, slice_info: Tuple
    ) -> Optional[np.ndarray]:
        """
        Phase 4: assemble warm L1/L2 tiles and fetch only the cold gap from Tiled.
        """
        try:
            return self._assemble_partial_l2(run, key, slice_info)
        except (ValueError, IndexError, TypeError) as exc:
            print_debug(
                "ChunkCache",
                f"Partial L2 assembly failed for {key}: {exc}",
                category="cache",
            )
            return None

    def _assemble_partial_l2(
        self, run, key: str, slice_info: Tuple
    ) -> Optional[np.ndarray]:
        print_debug("assemble_partial_l2", f"slice info: {slice_info}", category="cache")
        run_uid = run.start["uid"]
        shape, _ = self.chunk_info[(run_uid, key)]
        l2_chunks = self._l2_chunks(run_uid, key)
        tiles_needed = tiles_intersecting(shape, l2_chunks, slice_info)
        warm, cold = self._partition_l2_tiles(run_uid, key, tiles_needed)
        if not warm or not cold:
            return None

        gap_slice = self._cold_gap_slice_info(
            shape, slice_info, cold, l2_chunks
        )
        if gap_slice == slice_info:
            return None

        slab_shape = self._slab_shape(slice_info, shape)
        dtype = self._read_dtype(run, key)
        slab = np.empty(slab_shape, dtype=dtype)
        print_debug("assemble_partial_l2", f"pasting warm tiles into slab: {len(warm)}", category="cache")
        for tile_info in warm:
            tile_idx = tile_info["chunk_indices"]
            tile_data = self._load_l2_tile_array(run_uid, key, tile_idx)
            self._paste_tile_into_slab(
                slab,
                tile_info,
                tile_data,
                slice_info,
                shape,
                l2_chunks,
            )
        print_debug("assemble_partial_l2", f"read tiled hyperslab", category="cache")

        gap_data = self._read_tiled_hyperslab(run, key, gap_slice)
        print_debug("assemble_partial_l2", f"squeezing gap dims", category="cache")

        gap_data = self._squeeze_indexed_dims(gap_data, gap_slice)

        print_debug("assemble_partial_l2", f"pasting gap into slab", category="cache")
        self._paste_gap_into_slab(slab, gap_data, slice_info, gap_slice, shape)

        if not np.isfinite(slab).any():
            return None

        self._finish_slab_fetch(run, key, slice_info, slab)
        self.hits += 1
        if any(self.l2.has_chunk(run_uid, key, t["chunk_indices"]) for t in warm):
            self.l2_hits += 1
        return self._squeeze_indexed_dims(slab, slice_info)

    def _read_dtype(self, run, key: str) -> np.dtype:
        """
        Return the storage dtype for one dataset key.
        """
        data_accessor = run["primary", "data", key]
        dtype = getattr(data_accessor, "dtype", None)
        if dtype is None:
            return np.dtype("float32")
        return np.dtype(dtype)

    def _read_tiled_hyperslab(
        self, run, key: str, slice_info: Tuple, store_assembled_slab: bool = True
    ) -> np.ndarray:
        """
        Fetch a hyperslab from Tiled using byte-budgeted batch reads.
        """
        run_uid = run.start["uid"]
        if store_assembled_slab:
            cached = self._lookup_assembled_slab(run_uid, key, slice_info)
            if cached is not None:
                return cached

        shape, _ = self.chunk_info[(run_uid, key)]
        dtype = self._read_dtype(run, key)
        batches, batch_axis = plan_hyperslab_batches(
            slice_info,
            shape,
            dtype.itemsize,
            self.fetch_batch_target_bytes,
        )
        if len(batches) == 1:
            print_debug("read_tiled_hyperslab", f"reading one tiled hyperslab batch", category="cache")
            return self._read_tiled_hyperslab_batch(
                run,
                key,
                slice_info,
                store_assembled_slab=store_assembled_slab,
            )

        batch_total = len(batches)
        self._notify_tiled_fetch_progress(
            run_uid,
            key,
            active=True,
            pending_chunks=batch_total,
            batch_total=batch_total,
        )
        parts: List[Optional[np.ndarray]] = [None] * batch_total
        pending = batch_total
        try:
            futures = {
                self.fetch_pool.submit(
                    self._read_tiled_hyperslab_batch,
                    run,
                    key,
                    batch_slice,
                    False,
                ): index
                for index, batch_slice in enumerate(batches)
            }
            for future in as_completed(futures):
                index = futures[future]
                parts[index] = future.result()
                pending -= 1
                self._notify_tiled_fetch_progress(
                    run_uid,
                    key,
                    active=True,
                    pending_chunks=pending,
                    batch_total=batch_total,
                )
        finally:
            self._notify_tiled_fetch_progress(
                run_uid,
                key,
                active=False,
                pending_chunks=0,
                batch_total=batch_total,
            )

        if batch_axis is None or any(part is None for part in parts):
            raise ValueError(f"Failed to assemble batched hyperslab for {key}")
        print_debug("read_tiled_hyperslab", f"concatenating parts: {len(parts)}, parts shape: {parts[0].shape}, batch axis: {batch_axis}", category="cache")
        result = np.concatenate(parts, axis=batch_axis)
        if store_assembled_slab:
            print_debug("read_tiled_hyperslab", f"storing assembled slab", category="cache")
            self._store_assembled_slab(run_uid, key, slice_info, result, shape)
        print_debug(
            "read_tiled_hyperslab",
            f"Batched hyperslab read {key} shape {result.shape} "
            f"({result.nbytes / 1e6:.1f} MB in {batch_total} batches)",
            category="cache",
        )
        return result

    def _read_tiled_hyperslab_batch(
        self,
        run,
        key: str,
        slice_info: Tuple,
        store_assembled_slab: bool,
    ) -> np.ndarray:
        """
        Issue one Tiled read for a slice tuple without batch orchestration.
        """
        run_uid = run.start["uid"]
        if store_assembled_slab:
            cached = self._lookup_assembled_slab(run_uid, key, slice_info)
            if cached is not None:
                return cached

        self.misses += 1
        result = self._fetch_from_tiled(
            run, key, slice_info, reason="hyperslab"
        )
        shape, _ = self.chunk_info[(run_uid, key)]
        if store_assembled_slab:
            self._store_assembled_slab(run_uid, key, slice_info, result, shape)
        return result

    def _fetch_from_tiled(
        self, run, key: str, slice_info: Tuple, *, reason: str
    ) -> np.ndarray:
        """
        Read array data from Tiled with explicit cache logging.
        """
        t0 = time.perf_counter()
        print_debug(
            "ChunkCache",
            f"Tiled fetch start [{reason}] {key} slice={slice_info}",
            category="cache",
        )
        data_accessor = run["primary", "data", key]
        data = data_accessor.read(slice=slice_info)
        if hasattr(data, "read"):
            data = data.read()
        result = np.asarray(data)
        elapsed = time.perf_counter() - t0
        print_debug(
            "ChunkCache",
            f"Tiled fetch done [{reason}] {key} shape={result.shape} "
            f"({result.nbytes / 1e6:.1f} MB) in {elapsed:.3f}s",
            category="cache",
        )
        return result

    def _queue_l2_materialize(
        self,
        run,
        key: str,
        slice_info: Tuple,
        seed: np.ndarray,
        *,
        tiles: Optional[List[Dict]] = None,
    ) -> None:
        """
        Enqueue background materialization of incomplete L2 tiles touched by a view.
        """
        if self.l2 is None or not self.l2.enabled:
            return

        run_uid = run.start["uid"]
        shape, _ = self.chunk_info[(run_uid, key)]
        l2_chunks = self._l2_chunks(run_uid, key)
        if tiles is None:
            tiles = tiles_intersecting(shape, l2_chunks, slice_info)
        incomplete = [
            tile_info
            for tile_info in tiles
            if not self._tile_is_complete(run_uid, key, tile_info["chunk_indices"])
        ]
        if not incomplete:
            print_debug(
                "ChunkCache",
                f"L2 materialize skip {key}: all {len(tiles)} intersecting tiles complete",
                category="cache",
            )
            return

        job_key = (run_uid, key)
        with self.request_lock:
            existing = self._active_l2_materialize_jobs.get(job_key)
            if existing is not None and not existing.done():
                print_debug(
                    "ChunkCache",
                    f"L2 materialize skip {key}: job already running "
                    f"({len(incomplete)} tiles still pending elsewhere)",
                    category="cache",
                )
                return
            self._l2_materialize_job_seq += 1
            job_id = self._l2_materialize_job_seq

        print_debug(
            "ChunkCache",
            f"L2 materialize queue job={job_id} {key}: "
            f"{len(incomplete)}/{len(tiles)} incomplete tiles, "
            f"seed shape={seed.shape}",
            category="cache",
        )

        with self.request_lock:
            future = self.background_pool.submit(
                self._background_materialize_tiles,
                job_id,
                run,
                key,
                slice_info,
                seed,
                incomplete,
            )
            self._active_l2_materialize_jobs[job_key] = future

            def _cleanup(done_future: Future) -> None:
                with self.request_lock:
                    if (
                        self._active_l2_materialize_jobs.get(job_key)
                        is done_future
                    ):
                        del self._active_l2_materialize_jobs[job_key]

            future.add_done_callback(_cleanup)

    def _background_materialize_tiles(
        self,
        job_id: int,
        run,
        key: str,
        slice_info: Tuple,
        seed: np.ndarray,
        tile_infos: List[Dict],
    ) -> int:
        """
        Materialize incomplete L2 tiles from seed overlap and a full-tile Tiled fetch.

        Runs off the plot critical path: seed fully covered tiles from the
        returned slab, then fetch any remaining partial-edge tiles from Tiled.
        """
        run_uid = run.start["uid"]
        written = 0
        skipped = 0
        failed = 0
        tiled_reads = 0
        tile_total = len(tile_infos)
        t0 = time.perf_counter()
        print_debug(
            "ChunkCache",
            f"L2 materialize start job={job_id} {key}: {tile_total} tiles",
            category="cache",
        )

        shape, _ = self.chunk_info[(run_uid, key)]
        l2_chunks = self._l2_chunks(run_uid, key)
        aligned_seed = np.array(
            self._align_seed_slab(seed, slice_info), copy=True
        )
        self._seed_zarr_from_slab(run, key, slice_info, aligned_seed)

        needs_tiled: List[Dict] = []
        for tile_info in tile_infos:
            tile_idx = tile_info["chunk_indices"]
            if self._tile_is_complete(run_uid, key, tile_idx):
                written += 1
            else:
                needs_tiled.append(tile_info)

        if needs_tiled:
            fetch_slice = union_l2_tile_fetch_slice(
                shape,
                l2_chunks,
                [tile_info["chunk_indices"] for tile_info in needs_tiled],
            )
            print_debug(
                "ChunkCache",
                f"L2 materialize job={job_id} {key}: "
                f"{len(needs_tiled)} tiles need Tiled fetch_slice={fetch_slice}",
                category="cache",
            )
            try:
                slab = self._read_tiled_hyperslab(
                    run, key, fetch_slice, store_assembled_slab=False
                )
                tiled_reads = 1
                aligned = self._align_seed_slab(slab, fetch_slice)
                for tile_info in needs_tiled:
                    tile_idx = tile_info["chunk_indices"]
                    if self._tile_is_complete(run_uid, key, tile_idx):
                        skipped += 1
                        continue
                    try:
                        if self._materialize_l2_tile_from_slab(
                            run_uid,
                            key,
                            tile_idx,
                            fetch_slice,
                            aligned,
                            shape,
                            l2_chunks,
                        ):
                            written += 1
                        else:
                            failed += 1
                    except Exception as exc:
                        failed += 1
                        print_debug(
                            "ChunkCache",
                            f"L2 materialize job={job_id} tile={tile_idx} "
                            f"from fetch failed: {exc}",
                            category="cache",
                        )
            except Exception as exc:
                failed += len(needs_tiled)
                print_debug(
                    "ChunkCache",
                    f"L2 materialize job={job_id} {key} Tiled fetch failed: {exc}",
                    category="cache",
                )

        elapsed = time.perf_counter() - t0
        print_debug(
            "ChunkCache",
            f"L2 materialize done job={job_id} {key}: "
            f"written={written} skipped={skipped} failed={failed} "
            f"tiled_reads={tiled_reads} of {tile_total} tiles in {elapsed:.3f}s",
            category="cache",
        )
        return written

    def _materialize_l2_tile_from_slab(
        self,
        run_uid: str,
        key: str,
        tile_indices: Tuple[int, ...],
        slab_slice: Tuple,
        aligned_slab: np.ndarray,
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
        *,
        require_full_in_request: bool = False,
    ) -> bool:
        """
        Extract one complete L2 tile from a slab and persist it.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        tile_indices : tuple of int
            Tile index per dimension.
        slab_slice : tuple
            Slice request that ``aligned_slab`` was fetched for.
        aligned_slab : np.ndarray
            Slab array with indexed dimensions already squeezed.
        shape : tuple of int
            Full array shape.
        l2_chunks : tuple of int
            L2 tile size per dimension.
        require_full_in_request : bool, optional
            When True, skip tiles whose full extent lies outside ``slab_slice``.

        Returns
        -------
        bool
            True when a complete tile was written to L2.
        """
        if require_full_in_request and not self._tile_fully_in_request(
            shape, l2_chunks, slab_slice, tile_indices
        ):
            return False

        tile_data = self._extract_tile_from_slab(
            aligned_slab,
            shape,
            l2_chunks,
            slab_slice,
            tile_indices,
        )
        if tile_data is None or not np.all(np.isfinite(tile_data)):
            return False
        return self._commit_complete_l2_tile(
            run_uid, key, tile_indices, tile_data
        )

    def _commit_complete_l2_tile(
        self,
        run_uid: str,
        key: str,
        tile_indices: Tuple[int, ...],
        tile_data: np.ndarray,
    ) -> bool:
        """
        Persist one complete tile to the Zarr local cache.

        The dict-based ``self.tiles`` L1 is intentionally not updated.
        """
        cache_key = (run_uid, key, tile_indices)
        self._drop_partial_l1_tile(cache_key)
        return self._write_tile_to_l2(run_uid, key, tile_indices, tile_data)
    def _drop_partial_l1_tile(
        self, cache_key: Tuple[str, str, Tuple[int, ...]]
    ) -> None:
        """
        Remove a partial L1 seed entry so a full tile can replace it in L2.
        """
        if cache_key not in self.partial_l1_tiles:
            return
        if cache_key in self.tiles:
            self.l1_tile_size -= self.tiles[cache_key].nbytes
            del self.tiles[cache_key]
            self.l1_tile_access_times.pop(cache_key, None)
        self.partial_l1_tiles.discard(cache_key)

    def wait_for_background_materialize(
        self, run_uid: str, key: str, timeout: Optional[float] = None
    ) -> None:
        """
        Block until the current L2 materialize job for one dataset finishes.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        timeout : float, optional
            Maximum seconds to wait. Raises ``TimeoutError`` when exceeded.
        """
        job_key = (run_uid, key)
        with self.request_lock:
            future = self._active_l2_materialize_jobs.get(job_key)
        if future is None:
            return
        if future.done():
            future.result()
            return
        print_debug(
            "ChunkCache",
            f"L2 materialize wait {key} timeout={timeout}",
            category="cache",
        )
        try:
            future.result(timeout=timeout)
        except TimeoutError:
            print_debug(
                "ChunkCache",
                f"L2 materialize wait timed out for {key} after {timeout}s",
                category="cache",
            )
            raise
        print_debug(
            "ChunkCache",
            f"L2 materialize wait complete for {key}",
            category="cache",
        )

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
            cache_key = (run_uid, key, tile_idx)
            if cache_key in self.tiles:
                continue
            if self.l2.has_chunk(run_uid, key, tile_idx):
                continue
            pending.append(tile_info)
        return pending

    def _finish_slab_fetch(
        self,
        run,
        key: str,
        slice_info: Tuple,
        slab: np.ndarray,
    ) -> None:
        """
        Queue background Zarr seeding from a fetched slab without blocking.

        The caller already has ``slab`` for the plot critical path. L2 tile
        writes and any remaining edge-tile Tiled fetches run in
        ``_background_materialize_tiles``. A later ``get_data`` for the same
        dataset waits for that job before consulting L2 or partial assembly.

        Parameters
        ----------
        run : BlueskyRun
            Run containing the data.
        key : str
            Data key.
        slice_info : tuple
            User slice request that produced ``slab``.
        slab : np.ndarray
            Assembled view slab before indexed-dimension squeezing.
        """
        aligned = self._align_seed_slab(slab, slice_info)
        print_debug(
            "ChunkCache",
            f"queueing zarr materialize for {key}:{slice_info}",
            category="cache",
        )
        self._queue_l2_materialize(run, key, slice_info, aligned)

    def _seed_zarr_from_slab(
        self,
        run,
        key: str,
        slice_info: Tuple,
        slab: np.ndarray,
    ) -> None:
        """
        Write fully covered tiles from a fetched slab into memory Zarr.

        Partial edge tiles are left for background materialization. The
        dict-based ``self.tiles`` L1 is not populated.

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
        if self.l2 is None or not self.l2.enabled:
            return

        run_uid = run.start["uid"]
        shape, _ = self.chunk_info[(run_uid, key)]
        self._ensure_l2_array(run, key)
        l2_chunks = self._l2_chunks(run_uid, key)
        slab = self._align_seed_slab(slab, slice_info)
        pending = self._pending_slab_tiles(
            run_uid, key, shape, l2_chunks, slice_info
        )
        if not pending:
            return

        if self._can_bulk_seed_zarr(shape, l2_chunks, slice_info, pending):
            self._bulk_seed_zarr(run_uid, key, slice_info, slab, pending)
            return

        seeded = 0
        for tile_info in pending:
            tile_idx = tile_info["chunk_indices"]
            if not self._tile_fully_in_request(
                shape, l2_chunks, slice_info, tile_idx
            ):
                continue
            if self._materialize_l2_tile_from_slab(
                run_uid,
                key,
                tile_idx,
                slice_info,
                slab,
                shape,
                l2_chunks,
                require_full_in_request=True,
            ):
                seeded += 1

        print_debug(
            "ChunkCache",
            f"Seeded {seeded} Zarr tiles from slab for {key}",
            category="cache",
        )

    @staticmethod
    def _can_bulk_seed_zarr(
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
        slice_info: Tuple,
        pending: List[Dict],
    ) -> bool:
        """
        Return whether every pending tile is fully covered by ``slice_info``.
        """
        if not pending:
            return False
        if not all(isinstance(item, slice) for item in slice_info):
            return False
        return all(
            ChunkCache._tile_fully_in_request(
                shape, l2_chunks, slice_info, tile["chunk_indices"]
            )
            for tile in pending
        )

    def _bulk_seed_zarr(
        self,
        run_uid: str,
        key: str,
        slice_info: Tuple,
        slab: np.ndarray,
        pending: List[Dict],
    ) -> None:
        """
        Assign a full-rank slab into Zarr and mark covered tiles complete.
        """
        shape, _ = self.chunk_info[(run_uid, key)]
        expected = tuple(
            request_dim_bounds(item, shape[i])[1]
            - request_dim_bounds(item, shape[i])[0]
            for i, item in enumerate(slice_info)
        )
        if tuple(slab.shape) != expected:
            l2_chunks = self._l2_chunks(run_uid, key)
            seeded = 0
            for tile_info in pending:
                if self._materialize_l2_tile_from_slab(
                    run_uid,
                    key,
                    tile_info["chunk_indices"],
                    slice_info,
                    slab,
                    shape,
                    l2_chunks,
                    require_full_in_request=True,
                ):
                    seeded += 1
            print_debug(
                "ChunkCache",
                f"Seeded {seeded} Zarr tiles from slab for {key}",
                category="cache",
            )
            return

        arr = self.l2.open_array(run_uid, key)
        with self.l2._lock:
            arr[tuple(slice_info)] = slab
            meta = self.l2._require_meta(run_uid, key)
            for tile_info in pending:
                meta.completed.add(tuple(tile_info["chunk_indices"]))

        print_debug(
            "ChunkCache",
            f"Bulk-seeded {len(pending)} Zarr tiles from slab for {key}",
            category="cache",
        )

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
        l2_chunks = self._l2_chunks(run_uid, key)
        slab = self._align_seed_slab(slab, slice_info)
        pending = self._pending_slab_tiles(
            run_uid, key, shape, l2_chunks, slice_info
        )
        if not pending:
            return

        sync_all = len(pending) <= self.sync_seed_tile_limit
        seeded_l1 = 0
        seeded_l2 = 0
        skipped_extract = 0
        deferred: List[Dict] = []
        itemsize = slab.dtype.itemsize

        for tile_info in pending:
            tile_idx = tile_info["chunk_indices"]
            if not sync_all:
                tile_size = int(np.prod(tile_info["chunk_shape"]) * itemsize)
                if self.l1_tile_size + tile_size > self.l1_max_bytes:
                    deferred.append(tile_info)
                    continue

            tile_data = self._extract_tile_from_slab(
                slab, shape, l2_chunks, slice_info, tile_idx
            )
            if tile_data is None:
                skipped_extract += 1
                continue
            stored = self._store_seeded_tile(
                run_uid, key, tile_idx, tile_data, shape, l2_chunks, slice_info
            )
            if stored == "l1":
                seeded_l1 += 1
            elif stored == "l2":
                seeded_l2 += 1

        if sync_all:
            if seeded_l1 or seeded_l2:
                print_debug(
                    "ChunkCache",
                    f"Seeded {seeded_l1} L1 + {seeded_l2} L2 tiles from slab for {key}",
                    category="cache",
                )
            return

        if deferred:
            print_debug(
                "ChunkCache",
                f"Deferred {len(deferred)} tiles from sync L1 seed for {key}; "
                f"background L2 materialize will fill complete tiles",
                category="cache",
            )

        print_debug(
            "ChunkCache",
            f"Seeded {seeded_l1} L1 tiles from slab for {key}; "
            f"deferred {len(deferred)} tiles "
            f"(skipped_extract={skipped_extract})",
            category="cache",
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

        max_evictions = len(self.tiles) + 1
        for _ in range(max_evictions):
            if self.l1_tile_size + tile_size <= self.l1_max_bytes:
                break
            if not self._evict_lru_l1_tile():
                if self._write_tile_to_l2(run_uid, key, tile_indices, data):
                    return "l2"
                print_debug(
                    "ChunkCache",
                    f"L1 store failed for tile={tile_indices}: "
                    f"eviction exhausted with {len(self.tiles)} tiles",
                    category="cache",
                )
                return None
        else:
            print_debug(
                "ChunkCache",
                f"L1 store failed for tile={tile_indices}: "
                f"eviction iteration cap ({max_evictions}) hit",
                category="cache",
            )
            return None

        self.tiles[cache_key] = data
        self.l1_tile_size += tile_size
        self.partial_l1_tiles.discard(cache_key)
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

        cache_key = (run_uid, key, tile_indices)
        if cache_key in self.partial_l1_tiles:
            return False

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
        self.partial_l1_tiles.discard((run_uid, key, tile_indices))
        print_debug(
            "ChunkCache",
            f"L2 local write {key} tile={tile_indices} shape={data.shape}",
            category="cache",
        )
        return True

    def _update_l1_tile_access(self, cache_key: Tuple[str, str, Tuple[int, ...]]) -> None:
        self.l1_tile_access_times[cache_key] = time.time()

    def _evict_lru_l1_tile(self) -> bool:
        if not self.tiles:
            return False

        lru_key = min(self.l1_tile_access_times.items(), key=lambda x: x[1])[0]
        run_uid, key, tile_indices = lru_key
        chunk = self.tiles[lru_key]
        if lru_key not in self.partial_l1_tiles:
            self._write_tile_to_l2(run_uid, key, tile_indices, chunk)
        self.l1_tile_size -= chunk.nbytes
        del self.tiles[lru_key]
        del self.l1_tile_access_times[lru_key]
        self.partial_l1_tiles.discard(lru_key)
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
            req_start, req_stop = request_dim_bounds(slice_info[dim], shape[dim])
            if tile_start < req_start or tile_end > req_stop:
                return False
        return True

    @staticmethod
    def _align_seed_slab(result: np.ndarray, slice_info: Tuple) -> np.ndarray:
        """
        Normalize a Tiled hyperslab to the rank expected by seed extraction.

        Removes length-1 axes for integer indices in ``slice_info`` so slab
        axes align with the non-indexed dimensions only.
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
    def _extract_tile_from_slab(
        slab: np.ndarray,
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
        slice_info: Tuple,
        tile_indices: Tuple[int, ...],
    ) -> Optional[np.ndarray]:
        """
        Extract one full-rank L2 tile array from a fetched slab.

        Returns ``None`` when the tile does not overlap the request.
        """
        chunks = chunk_grid(shape, l2_chunks)
        slab_axis_for_dim: Dict[int, int] = {}
        slab_axis = 0
        for dim, item in enumerate(slice_info):
            if isinstance(item, slice):
                slab_axis_for_dim[dim] = slab_axis
                slab_axis += 1
        if slab_axis != slab.ndim:
            return None

        out_shape = tuple(
            chunks[dim][tile_indices[dim]] for dim in range(len(tile_indices))
        )
        tile_data = np.full(out_shape, np.nan, dtype=slab.dtype)
        slab_indices: List[slice] = [slice(None)] * slab.ndim
        tile_slices: List[slice] = []

        for dim, tile_idx in enumerate(tile_indices):
            tile_start = sum(chunks[dim][:tile_idx])
            tile_size = chunks[dim][tile_idx]
            tile_end = tile_start + tile_size
            item = slice_info[dim]
            if isinstance(item, int):
                if not (tile_start <= item < tile_end):
                    return None
                internal_idx = int(item) - tile_start
                tile_slices.append(
                    slice(internal_idx, internal_idx + 1)
                )
                continue

            req_start, req_stop = request_dim_bounds(item, shape[dim])
            overlap_start = max(req_start, tile_start)
            overlap_stop = min(req_stop, tile_end)
            if overlap_start >= overlap_stop:
                return None
            tile_slices.append(
                slice(overlap_start - tile_start, overlap_stop - tile_start)
            )
            slab_axis = slab_axis_for_dim[dim]
            slab_indices[slab_axis] = slice(
                overlap_start - req_start, overlap_stop - req_start
            )

        patch = np.asarray(slab[tuple(slab_indices)])
        for dim, item in enumerate(slice_info):
            if not isinstance(item, slice):
                patch = np.expand_dims(patch, axis=dim)
        target = tile_data[tuple(tile_slices)]
        if patch.shape != target.shape:
            return None
        tile_data[tuple(tile_slices)] = patch
        return np.asarray(tile_data)

    def _store_seeded_tile(
        self,
        run_uid: str,
        key: str,
        tile_indices: Tuple[int, ...],
        tile_data: np.ndarray,
        shape: Tuple[int, ...],
        l2_chunks: Tuple[int, ...],
        slice_info: Tuple,
    ) -> Optional[str]:
        """
        Store a tile extracted from a seed slab in L1 and optionally L2.
        """
        if self._tile_fully_in_request(shape, l2_chunks, slice_info, tile_indices):
            return self._store_tile(run_uid, key, tile_indices, tile_data)

        cache_key = (run_uid, key, tile_indices)
        tile_size = tile_data.nbytes
        if cache_key in self.tiles:
            self.l1_tile_size -= self.tiles[cache_key].nbytes
        while self.l1_tile_size + tile_size > self.l1_max_bytes:
            if not self._evict_lru_l1_tile():
                return None
        self.tiles[cache_key] = tile_data
        self.l1_tile_size += tile_size
        self.partial_l1_tiles.add(cache_key)
        self._update_l1_tile_access(cache_key)
        return "l1"

    @staticmethod
    def _apply_internal_slices_to_chunk(
        chunk: np.ndarray,
        internal_slices: Tuple,
        slice_info: Optional[Tuple] = None,
    ) -> np.ndarray:
        """
        Apply per-tile internal slices and collapse integer-indexed axes.

        L2 tiles are stored at full tile rank. Integer entries in
        ``internal_slices`` are applied as length-1 slices. Axes are squeezed
        only when the parent ``slice_info`` entry is also an integer index,
        so profile/stack axes requested with ``slice(None)`` keep tile rank.

        Parameters
        ----------
        chunk : np.ndarray
            Tile array before internal indexing.
        internal_slices : tuple
            Per-dimension slice or index within the tile.
        slice_info : tuple, optional
            Original user slice request for the assembled view.

        Returns
        -------
        np.ndarray
            Indexed tile array aligned with non-indexed ``slice_info`` axes.
        """
        slice_list = []
        for s in internal_slices:
            if isinstance(s, int):
                slice_list.append(slice(s, s + 1))
            else:
                slice_list.append(s)
        chunk = chunk[tuple(slice_list)]
        squeeze_axes = []
        for i, s in enumerate(internal_slices):
            if isinstance(s, slice):
                continue
            if i >= chunk.ndim or chunk.shape[i] != 1:
                continue
            if (
                slice_info is not None
                and i < len(slice_info)
                and isinstance(slice_info[i], slice)
            ):
                continue
            squeeze_axes.append(i)
        if squeeze_axes:
            chunk = np.squeeze(chunk, axis=tuple(squeeze_axes))
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
            Tile metadata from ``tiles_intersecting``.

        Returns
        -------
        bool
            True if ``internal_slices`` should be applied to the chunk.
        """
        if chunk_info.get("already_sliced"):
            return False
        return chunk.ndim >= len(chunk_info["internal_slices"])

    @staticmethod
    def _finalize_slice_result(
        result: np.ndarray, slice_info: Tuple
    ) -> np.ndarray:
        """
        Normalize a fetched array to the rank expected by view materialization.
        """
        return ChunkCache._squeeze_indexed_dims(result, slice_info)

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

    def _assembled_slab_cache_key(
        self, run_uid: str, key: str, slice_info: Tuple
    ) -> Tuple:
        """
        Return the slice-cache key for one assembled view slab.
        """
        return (run_uid, key, self._slice_cache_key(slice_info))

    def _lookup_assembled_slab(
        self, run_uid: str, key: str, slice_info: Tuple
    ) -> Optional[np.ndarray]:
        """
        Return a cached assembled slab for an exact slice request.
        """
        cache_key = self._assembled_slab_cache_key(run_uid, key, slice_info)
        if cache_key in self.slice_cache:
            self.hits += 1
            self._update_access(cache_key)
            return self.slice_cache[cache_key]
        return None

    @staticmethod
    def _should_cache_assembled_slab(
        shape: Tuple[int, ...], slice_info: Tuple
    ) -> bool:
        """
        Return whether an assembled slab should be stored in ``slice_cache``.

        Spatially narrowed requests such as ROI bbox fetches are cached so
        repeat materializations with the same ``slice_info`` avoid Tiled.
        Full-axis exploration slabs continue to rely on L1/L2 tiles only.
        """
        for dim_size, item in zip(shape, slice_info):
            if isinstance(item, slice):
                start = 0 if item.start is None else int(item.start)
                stop = dim_size if item.stop is None else int(item.stop)
                if start > 0 or stop < dim_size:
                    return True
        return False

    def _store_assembled_slab(
        self,
        run_uid: str,
        key: str,
        slice_info: Tuple,
        result: np.ndarray,
        shape: Tuple[int, ...],
    ) -> None:
        """
        Store one assembled view slab when the request is cache-worthy.
        """
        if not self._should_cache_assembled_slab(shape, slice_info):
            return
        cache_key = self._assembled_slab_cache_key(run_uid, key, slice_info)
        self._store_in_slice_cache(cache_key, np.asarray(result))

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
        slice_info: Tuple,
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
                    chunk,
                    chunk_info["internal_slices"],
                    slice_info,
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

    def clear_run(self, run_uid: str):
        """
        Clear all cached data for a specific run.

        Parameters
        ----------
        run_uid : str
            Unique identifier for the run to clear
        """
        keys_to_remove = [(r, k) for r, k in self.chunk_info.keys() if r == run_uid]
        for key in keys_to_remove:
            del self.chunk_info[key]

        if self.l2 is not None:
            self.l2.clear_run(run_uid)
        if self.progress is not None:
            self.progress.clear()

        tile_keys = [(r, k, i) for r, k, i in self.tiles.keys() if r == run_uid]

        with self.request_lock:
            for key in tile_keys:
                if key in self.tiles:
                    self.l1_tile_size -= self.tiles[key].nbytes
                    del self.tiles[key]
                if key in self.l1_tile_access_times:
                    del self.l1_tile_access_times[key]
                self.partial_l1_tiles.discard(key)

    def clear(self):
        """Clear all cached data and shutdown the fetch pool."""
        with self.request_lock:
            self.tiles.clear()
            self.partial_l1_tiles.clear()
            self.slice_cache.clear()
            self.chunk_info.clear()
            self.access_times.clear()
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

        self.fetch_pool.shutdown(wait=True)
        self.fetch_pool = ThreadPoolExecutor(max_workers=4)

    def _update_access(self, cache_key: Tuple[str, str, Tuple[int, ...]]):
        """Update access time for a slice-cache entry."""
        self.access_times[cache_key] = time.time()

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
        Evict the least recently used slice-cache entry.

        Returns
        -------
        bool
            True if an entry was evicted, False if nothing remains.
        """
        if not self.access_times:
            return False

        lru_key = min(self.access_times.items(), key=lambda x: x[1])[0]

        if lru_key not in self.slice_cache:
            del self.access_times[lru_key]
            return True

        chunk = self.slice_cache[lru_key]
        del self.slice_cache[lru_key]
        self.current_size -= chunk.nbytes
        del self.access_times[lru_key]
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
            if cache_key in self.partial_l1_tiles:
                failed += 1
            elif self._write_tile_to_l2(tile_run_uid, tile_key, tile_indices, data):
                flushed += 1
            else:
                failed += 1
            self.l1_tile_size -= data.nbytes
            del self.tiles[cache_key]
            del self.l1_tile_access_times[cache_key]
            self.partial_l1_tiles.discard(cache_key)

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
            "slice_cache_count": len(self.slice_cache),
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
                if self.l2 is not None and self.l2.enabled:
                    completed, total = self.l2.tile_counts(run_uid, key)
                    fraction = self.l2.completion_fraction(run_uid, key)
                    lines.append(
                        f"  {run_uid}/{key}: L2 {completed}/{total} "
                        f"({fraction:.1%})"
                    )
                else:
                    lines.append(f"  {run_uid}/{key}: L2 disabled")

        return "\n".join(lines)
