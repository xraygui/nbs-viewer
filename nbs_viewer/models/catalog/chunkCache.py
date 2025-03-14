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
        Maximum cache size in bytes, by default 1GB
    min_free_memory : float, optional
        Minimum free system memory to maintain (as fraction), by default 0.2
    """

    def __init__(self, max_size_bytes: int = 1e9, min_free_memory: float = 0.2):
        # Cache storage
        self.chunks: Dict[Tuple[str, str, Tuple[int, ...]], np.ndarray] = {}
        self.chunk_info: Dict[
            Tuple[str, str], Tuple[Tuple[int, ...], Tuple[int, ...]]
        ] = {}

        # Cache configuration
        self.max_size = max_size_bytes
        self.min_free_memory = min_free_memory
        self.current_size = 0

        # Access tracking
        self.access_times: Dict[Tuple[str, str, Tuple[int, ...]], float] = {}
        self.access_counts: Dict[Tuple[str, str, Tuple[int, ...]], int] = {}

        # In-flight request tracking
        self.in_flight_chunks: Dict[Tuple[str, str, Tuple[int, ...]], bool] = {}

        # Worker pool for fetching chunks
        self.worker_pool = ThreadPoolExecutor(max_workers=4)
        self.active_requests: Dict[Tuple[str, str, Tuple[int, ...]], Future] = {}
        self.request_lock = Lock()

        # Statistics
        self.hits = 0
        self.misses = 0

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
                chunks_data = self._get_or_fetch_chunks(run, key, chunks_needed)
                if not chunks_data:
                    raise ValueError("No chunks returned")
            except Exception as e:
                raise ValueError(f"Error fetching chunks: {str(e)}")

            # Assemble result
            try:
                result = self._assemble_result(chunks_data, chunks_needed, full_shape)
            except Exception as e:
                raise ValueError(f"Error assembling result: {str(e)}")

            # Squeeze out dimensions that were requested with integer indices
            squeeze_dims = [
                i for i, s in enumerate(slice_info) if not isinstance(s, slice)
            ]
            if squeeze_dims:
                result = np.squeeze(result, axis=tuple(squeeze_dims))

            return result

        except Exception as e:
            print_debug("ChunkCache", f"Error in get_data: {str(e)}")
            raise

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

    def _fetch_chunk(
        self, run, key: str, chunk_idx: Tuple[int, ...]
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
        chunk_idx : Tuple[int, ...]
            The chunk indices

        Returns
        -------
        Optional[np.ndarray]
            The chunk data if successful, None if failed
        """
        try:
            print_debug(
                "ChunkCache",
                f"Fetching chunk {chunk_idx} for key {key}",
                category="cache",
            )
            # time.sleep(10)  # Simulate slow data fetching

            data_accessor = run["primary", "data", key]
            chunks = self.chunk_info[(run.start["uid"], key)][1]

            # Build slice tuple for data access
            chunk_slices = []
            for dim, idx in enumerate(chunk_idx):
                chunk_start = sum(chunks[dim][:idx])
                chunk_size = chunks[dim][idx]
                chunk_slices.append(slice(chunk_start, chunk_start + chunk_size))

            chunk_data = data_accessor[tuple(chunk_slices)]
            if hasattr(chunk_data, "read"):
                chunk_data = chunk_data.read()

            # Cache the chunk data if successful
            if chunk_data is not None:
                self.cache_chunk(run.start["uid"], key, chunk_idx, chunk_data)
            print_debug(
                "ChunkCache",
                f"Chunk {chunk_idx} fetched successfully",
                category="cache",
            )
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
        chunks_to_fetch = []

        # First pass: check cache and start fetches for missing chunks
        with self.request_lock:
            for chunk_info in chunks_needed:
                chunk_idx = chunk_info["chunk_indices"]
                cache_key = (run.start["uid"], key, chunk_idx)

                # Check cache first
                if cache_key in self.chunks:
                    result[chunk_idx] = self.chunks[cache_key]
                    self.hits += 1
                    continue

                # Check if there's an active request
                if cache_key in self.active_requests:
                    futures_to_wait.append((chunk_idx, self.active_requests[cache_key]))
                    continue

                # Start new fetch request
                self.misses += 1
                future = self.worker_pool.submit(self._fetch_chunk, run, key, chunk_idx)
                self.active_requests[cache_key] = future
                futures_to_wait.append((chunk_idx, future))
                chunks_to_fetch.append(chunk_info)

        # Wait for all needed chunks
        for chunk_idx, future in futures_to_wait:
            print_debug(
                "ChunkCache",
                f"Waiting for chunk {chunk_idx}",
                category="cache",
            )
            try:
                chunk_data = future.result()
                if chunk_data is not None:
                    # The chunk is already cached by _fetch_chunk
                    result[chunk_idx] = chunk_data
            except Exception as e:
                print(f"Error waiting for chunk {chunk_idx}: {str(e)}")
            finally:
                # Clean up the request tracking
                with self.request_lock:
                    cache_key = (run.start["uid"], key, chunk_idx)
                    if cache_key in self.active_requests:
                        del self.active_requests[cache_key]

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

    def _assemble_result(
        self,
        chunks_data: Dict[Tuple[int, ...], np.ndarray],
        chunks_needed: List[Dict],
        full_shape: Tuple[int, ...],
    ) -> np.ndarray:
        """
        Assemble chunks into final result array.
        """
        # First apply internal slices to each chunk
        processed_chunks = {}
        for chunk_info in chunks_needed:
            chunk_idx = chunk_info["chunk_indices"]
            internal_slices = chunk_info["internal_slices"]
            chunk = chunks_data[chunk_idx]

            # Convert integer indices to size-1 slices to preserve dimensions
            slice_list = []
            for s in internal_slices:
                if isinstance(s, int):
                    slice_list.append(slice(s, s + 1))
                else:
                    slice_list.append(s)

            chunk = chunk[tuple(slice_list)]
            processed_chunks[chunk_idx] = chunk

        chunks = list(processed_chunks.values())
        coords = list(processed_chunks.keys())

        def concat_chunks(chunks_list, coords_list, depth=0):
            if not chunks_list:
                return None
            if depth >= len(chunks_list[0].shape):
                return chunks_list[0]

            # Group chunks by their coordinate at current depth
            groups = {}
            for chunk, coord in zip(chunks_list, coords_list):
                key = coord[depth]
                if key not in groups:
                    groups[key] = ([], [])
                groups[key][0].append(chunk)
                groups[key][1].append(coord)

            # Process each group recursively
            results = []
            for key in sorted(groups.keys()):
                group_chunks, group_coords = groups[key]
                result = concat_chunks(group_chunks, group_coords, depth + 1)
                if result is not None:
                    results.append(result)

            if results:
                # Find the first dimension that varies between chunks
                varying_dim = None
                for i in range(len(coords_list[0])):
                    if len(set(coord[i] for coord in coords_list)) > 1:
                        varying_dim = i
                        break

                # If we found a varying dimension, concatenate along that axis
                if varying_dim is not None:
                    result = np.concatenate(results, axis=varying_dim)
                else:
                    # If no dimension varies, just return the first result
                    result = results[0]
                return result
            return None

        # Concatenate all chunks
        result = concat_chunks(chunks, coords)
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

        # Remove chunks and their tracking info
        chunk_keys = [(r, k, i) for r, k, i in self.chunks.keys() if r == run_uid]

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

    def clear(self):
        """Clear all cached data and shutdown worker pool."""
        with self.request_lock:
            # Cancel all active requests
            for future in self.active_requests.values():
                future.cancel()
            self.active_requests.clear()

            # Clear cache data
            self.chunks.clear()
            self.chunk_info.clear()
            self.access_times.clear()
            self.access_counts.clear()
            self.current_size = 0
            self.hits = 0
            self.misses = 0

        # Shutdown worker pool
        self.worker_pool.shutdown(wait=True)
        # Create new worker pool
        self.worker_pool = ThreadPoolExecutor(max_workers=4)

    def _update_access(self, cache_key: Tuple[str, str, Tuple[int, ...]]):
        """Update access time and count for a chunk."""
        self.access_times[cache_key] = time.time()
        self.access_counts[cache_key] = self.access_counts.get(cache_key, 0) + 1

    def _evict_lru(self) -> bool:
        """
        Evict least recently used chunk.

        Returns
        -------
        bool
            True if a chunk was evicted, False if cache is empty
        """
        if not self.chunks:
            return False

        # Find least recently accessed chunk
        lru_key = min(self.access_times.items(), key=lambda x: x[1])[0]

        # Remove it
        chunk = self.chunks[lru_key]
        self.current_size -= chunk.nbytes
        del self.chunks[lru_key]
        del self.access_times[lru_key]
        if lru_key in self.access_counts:
            del self.access_counts[lru_key]

        return True

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
            "chunk_count": len(self.chunks),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": (
                self.hits / (self.hits + self.misses)
                if (self.hits + self.misses) > 0
                else 0
            ),
            "memory_usage": psutil.virtual_memory().percent,
        }
