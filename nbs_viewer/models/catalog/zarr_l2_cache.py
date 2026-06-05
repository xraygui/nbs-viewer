"""
Persistent L2 tile cache backed by Zarr.

Phase 1 uses an in-memory store; the same API can target disk later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Optional, Sequence, Set, Tuple, Union

import numpy as np
import zarr
from zarr.storage import MemoryStore

from .tile_indices import (
    tile_global_slice,
    tiles_intersecting,
    total_tile_count,
)

SliceItem = Union[int, slice]


@dataclass
class _DatasetMeta:
    """
    In-memory metadata for one cached array.

    Parameters
    ----------
    shape : tuple of int
        Full array shape.
    l2_chunks : tuple of int
        Nominal Zarr tile size per dimension.
    dtype : np.dtype
        Array dtype.
    tiled_chunks : tuple, optional
        Source chunk layout from Tiled, for fetch planning only.
    completed : set of tuple, optional
        Tile indices that are fully written.
    """

    shape: Tuple[int, ...]
    l2_chunks: Tuple[int, ...]
    dtype: np.dtype
    tiled_chunks: Optional[Tuple] = None
    completed: Set[Tuple[int, ...]] = field(default_factory=set)


class ZarrL2Cache:
    """
    Chunk-complete L2 cache using Zarr tile storage.

    Parameters
    ----------
    l2_chunks : tuple of int, optional
        Nominal tile size per dimension, by default ``(1, 1, 256, 256)``.
    store : zarr storage, optional
        Storage backend; defaults to :class:`zarr.storage.MemoryStore`.
    enabled : bool, optional
        When False, all methods no-op or return misses.
    """

    def __init__(
        self,
        l2_chunks: Tuple[int, ...] = (1, 1, 256, 256),
        store: Optional[MemoryStore] = None,
        enabled: bool = True,
    ):
        self.l2_chunks = tuple(int(c) for c in l2_chunks)
        self.enabled = enabled
        self._store = store if store is not None else MemoryStore()
        self._root = zarr.open_group(store=self._store, mode="a")
        self._meta: Dict[Tuple[str, str], _DatasetMeta] = {}
        self._lock = Lock()

    def _dataset_key(self, run_uid: str, key: str) -> Tuple[str, str]:
        return (run_uid, key)

    def _key_group(self, run_uid: str, key: str):
        if run_uid not in self._root:
            run_group = self._root.create_group(run_uid)
        else:
            run_group = self._root[run_uid]
        if key not in run_group:
            return run_group.create_group(key)
        return run_group[key]

    def register_array(
        self,
        run_uid: str,
        key: str,
        shape: Sequence[int],
        dtype,
        tiled_chunks: Optional[Tuple] = None,
    ) -> zarr.Array:
        """
        Ensure metadata and a Zarr array exist for one dataset.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        shape : sequence of int
            Full array shape.
        dtype
            Numpy dtype or dtype spec.
        tiled_chunks : tuple, optional
            Source chunk layout from Tiled.

        Returns
        -------
        zarr.Array
            The backing Zarr array.
        """
        cache_key = self._dataset_key(run_uid, key)
        shape_tuple = tuple(int(s) for s in shape)
        dtype = np.dtype(dtype)

        with self._lock:
            if cache_key not in self._meta:
                self._meta[cache_key] = _DatasetMeta(
                    shape=shape_tuple,
                    l2_chunks=self.l2_chunks,
                    dtype=dtype,
                    tiled_chunks=tiled_chunks,
                )

            group = self._key_group(run_uid, key)

            if "data" in group:
                return group["data"]

            return group.create_array(
                "data",
                shape=shape_tuple,
                chunks=self.l2_chunks,
                dtype=dtype,
            )

    def open_array(self, run_uid: str, key: str) -> zarr.Array:
        """
        Open an existing Zarr array.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.

        Returns
        -------
        zarr.Array

        Raises
        ------
        KeyError
            If the dataset has not been registered.
        """
        cache_key = self._dataset_key(run_uid, key)
        if cache_key not in self._meta:
            raise KeyError(f"No L2 metadata for {run_uid}:{key}")
        return self._root[run_uid][key]["data"]

    def chunks_intersecting(
        self, run_uid: str, key: str, slice_info: Sequence[SliceItem]
    ) -> list[tuple[int, ...]]:
        """
        Return tile indices overlapping a slice request.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        slice_info : sequence
            Per-dimension slice or index.

        Returns
        -------
        list of tuple
            Tile index tuples.
        """
        meta = self._require_meta(run_uid, key)
        tiles = tiles_intersecting(meta.shape, meta.l2_chunks, slice_info)
        return [tile["chunk_indices"] for tile in tiles]

    def has_chunk(
        self, run_uid: str, key: str, l2_chunk_indices: Tuple[int, ...]
    ) -> bool:
        """
        Return whether a tile is complete in L2.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        l2_chunk_indices : tuple of int
            Tile index per dimension.

        Returns
        -------
        bool
        """
        if not self.enabled:
            return False
        meta = self._meta.get(self._dataset_key(run_uid, key))
        if meta is None:
            return False
        return tuple(l2_chunk_indices) in meta.completed

    def all_complete(
        self,
        run_uid: str,
        key: str,
        l2_chunk_indices: Sequence[Tuple[int, ...]],
    ) -> bool:
        """
        Return whether every listed tile is complete.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        l2_chunk_indices : sequence of tuple
            Tile indices to check.

        Returns
        -------
        bool
        """
        if not self.enabled:
            return False
        if not l2_chunk_indices:
            return True
        return all(self.has_chunk(run_uid, key, idx) for idx in l2_chunk_indices)

    def read_chunk(
        self, run_uid: str, key: str, l2_chunk_indices: Tuple[int, ...]
    ) -> np.ndarray:
        """
        Read one complete tile from L2.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        l2_chunk_indices : tuple of int
            Tile index per dimension.

        Returns
        -------
        np.ndarray

        Raises
        ------
        KeyError
            If the tile is incomplete or missing.
        """
        if not self.has_chunk(run_uid, key, l2_chunk_indices):
            raise KeyError(f"L2 tile incomplete: {run_uid}:{key}:{l2_chunk_indices}")

        meta = self._require_meta(run_uid, key)
        arr = self.open_array(run_uid, key)
        global_slice = tile_global_slice(
            l2_chunk_indices, meta.shape, meta.l2_chunks
        )
        return np.asarray(arr[global_slice])

    def write_chunk(
        self,
        run_uid: str,
        key: str,
        l2_chunk_indices: Tuple[int, ...],
        data: np.ndarray,
    ) -> None:
        """
        Write one complete tile to L2 and mark it complete.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        l2_chunk_indices : tuple of int
            Tile index per dimension.
        data : np.ndarray
            Full tile array.
        """
        if not self.enabled:
            return

        meta = self._require_meta(run_uid, key)
        arr = self.open_array(run_uid, key)
        global_slice = tile_global_slice(
            l2_chunk_indices, meta.shape, meta.l2_chunks
        )
        expected = tuple(
            s.stop - s.start
            for s in global_slice
            if isinstance(s, slice)
        )
        if tuple(data.shape) != expected:
            raise ValueError(
                f"Tile data shape {data.shape} does not match "
                f"expected {expected} for indices {l2_chunk_indices}"
            )

        with self._lock:
            arr[global_slice] = data
            meta.completed.add(tuple(l2_chunk_indices))

    def mark_complete(
        self, run_uid: str, key: str, l2_chunk_indices: Tuple[int, ...]
    ) -> None:
        """
        Mark a tile complete without writing data.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.
        l2_chunk_indices : tuple of int
            Tile index per dimension.
        """
        if not self.enabled:
            return
        meta = self._require_meta(run_uid, key)
        with self._lock:
            meta.completed.add(tuple(l2_chunk_indices))

    def is_complete(self, run_uid: str, key: str) -> bool:
        """
        Return whether every tile in the dataset is complete.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.

        Returns
        -------
        bool
        """
        if not self.enabled:
            return False
        meta = self._meta.get(self._dataset_key(run_uid, key))
        if meta is None:
            return False
        total = total_tile_count(meta.shape, meta.l2_chunks)
        return len(meta.completed) >= total

    def dataset_entries(self) -> list[dict]:
        """
        Return summary records for all registered L2 datasets.

        Returns
        -------
        list of dict
            Each dict has ``run_uid``, ``key``, ``completed``, ``total``,
            and ``fraction`` keys.
        """
        entries = []
        for (run_uid, key), meta in sorted(self._meta.items()):
            total = total_tile_count(meta.shape, meta.l2_chunks)
            completed = len(meta.completed)
            fraction = completed / total if total else 1.0
            entries.append(
                {
                    "run_uid": run_uid,
                    "key": key,
                    "completed": completed,
                    "total": total,
                    "fraction": fraction,
                    "shape": meta.shape,
                    "l2_chunks": meta.l2_chunks,
                }
            )
        return entries

    def tile_counts(self, run_uid: str, key: str) -> Tuple[int, int]:
        """
        Return completed and total tile counts for one dataset.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.

        Returns
        -------
        tuple of int
            ``(completed_tiles, total_tiles)``.
        """
        meta = self._meta.get(self._dataset_key(run_uid, key))
        if meta is None:
            return 0, 0
        total = total_tile_count(meta.shape, meta.l2_chunks)
        return len(meta.completed), total

    def completion_fraction(self, run_uid: str, key: str) -> float:
        """
        Return the fraction of tiles complete for one dataset.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        key : str
            Data key.

        Returns
        -------
        float
            Value in ``[0, 1]``.
        """
        meta = self._meta.get(self._dataset_key(run_uid, key))
        if meta is None:
            return 0.0
        total = total_tile_count(meta.shape, meta.l2_chunks)
        if total == 0:
            return 1.0
        return len(meta.completed) / total

    def clear_run(self, run_uid: str) -> None:
        """
        Remove all L2 data for one run.

        Parameters
        ----------
        run_uid : str
            Run identifier.
        """
        with self._lock:
            keys = [k for r, k in self._meta if r == run_uid]
            for key in keys:
                del self._meta[(run_uid, key)]
            if run_uid in self._root:
                del self._root[run_uid]

    def clear(self) -> None:
        """Remove all cached datasets."""
        with self._lock:
            self._meta.clear()
            for name in list(self._root.keys()):
                del self._root[name]

    def _require_meta(self, run_uid: str, key: str) -> _DatasetMeta:
        cache_key = self._dataset_key(run_uid, key)
        if cache_key not in self._meta:
            raise KeyError(f"No L2 metadata for {run_uid}:{key}")
        return self._meta[cache_key]
