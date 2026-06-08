"""
Map N-D slice requests to fixed-size tile indices and global slices.
"""

from __future__ import annotations

from itertools import product
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

SliceItem = Union[int, slice]


def chunk_sizes_per_dim(dim_size: int, chunk_size: int) -> Tuple[int, ...]:
    """
    Compute the extent of each tile along one array dimension.

    Parameters
    ----------
    dim_size : int
        Full axis length.
    chunk_size : int
        Nominal tile size for the axis.

    Returns
    -------
    tuple of int
        Tile lengths; the last entry may be smaller than ``chunk_size``.
    """
    if chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive, got {chunk_size}")
    sizes: List[int] = []
    pos = 0
    while pos < dim_size:
        sizes.append(min(chunk_size, dim_size - pos))
        pos += chunk_size
    return tuple(sizes)


def chunk_grid(shape: Sequence[int], tile_chunks: Sequence[int]) -> Tuple[Tuple[int, ...], ...]:
    """
    Build a per-dimension tile size table from array shape and nominal chunks.

    Parameters
    ----------
    shape : sequence of int
        Full array shape.
    tile_chunks : sequence of int
        Nominal tile size per dimension.

    Returns
    -------
    tuple
        Per-dimension tuples of tile extents, as used by chunk index helpers.
    """
    if len(shape) != len(tile_chunks):
        raise ValueError("shape and tile_chunks must have the same length")
    return tuple(
        chunk_sizes_per_dim(int(dim_size), int(chunk_size))
        for dim_size, chunk_size in zip(shape, tile_chunks)
    )


def tiles_intersecting(
    shape: Sequence[int],
    tile_chunks: Sequence[int],
    slice_info: Sequence[SliceItem],
) -> List[Dict]:
    """
    List tiles overlapping a slice request.

    Parameters
    ----------
    shape : sequence of int
        Full array shape.
    tile_chunks : sequence of int
        Nominal tile size per dimension.
    slice_info : sequence
        Per-dimension slice or index, same length as ``shape``.

    Returns
    -------
    list of dict
        Each dict contains ``chunk_indices``, ``chunk_shape``, and
        ``internal_slices`` compatible with ``ChunkCache._assemble_result``.
    """
    if len(slice_info) != len(shape):
        raise ValueError(
            f"slice dimensionality ({len(slice_info)}) does not match "
            f"data dimensionality ({len(shape)})"
        )

    chunks = chunk_grid(shape, tile_chunks)
    base_chunk_indices: List[List[int]] = []

    for dim, (s, dim_size, dim_chunk_sizes) in enumerate(
        zip(slice_info, shape, chunks)
    ):
        positions = [0]
        for size in dim_chunk_sizes:
            positions.append(positions[-1] + size)

        dim_tiles: List[int] = []
        if isinstance(s, slice):
            start = s.start if s.start is not None else 0
            stop = s.stop if s.stop is not None else dim_size
            for tile_idx, (tile_start, tile_end) in enumerate(
                zip(positions[:-1], positions[1:])
            ):
                if tile_start < stop and tile_end > start:
                    dim_tiles.append(tile_idx)
        else:
            pos = 0
            for tile_idx, size in enumerate(dim_chunk_sizes):
                if pos <= s < pos + size:
                    dim_tiles.append(tile_idx)
                    break
                pos += size

        base_chunk_indices.append(dim_tiles)

    tiles_needed: List[Dict] = []
    for tile_indices in product(*base_chunk_indices):
        tile_shape: List[int] = []
        internal_slices: List[SliceItem] = []

        for dim, (tile_idx, s, dim_size) in enumerate(
            zip(tile_indices, slice_info, shape)
        ):
            tile_size = chunks[dim][tile_idx]
            tile_shape.append(tile_size)
            tile_start = sum(chunks[dim][:tile_idx])

            if isinstance(s, slice):
                start = s.start if s.start is not None else 0
                stop = s.stop if s.stop is not None else dim_size
                internal_start = max(0, start - tile_start)
                internal_stop = min(tile_size, stop - tile_start)
                internal_slices.append(slice(internal_start, internal_stop))
            else:
                internal_slices.append(s - tile_start)

        tiles_needed.append(
            {
                "chunk_indices": tile_indices,
                "chunk_shape": tuple(tile_shape),
                "internal_slices": tuple(internal_slices),
            }
        )

    return tiles_needed


def tile_global_slice(
    tile_indices: Sequence[int],
    shape: Sequence[int],
    tile_chunks: Sequence[int],
) -> Tuple[SliceItem, ...]:
    """
    Global slice covering the full extent of one tile.

    Parameters
    ----------
    tile_indices : sequence of int
        Tile index per dimension.
    shape : sequence of int
        Full array shape.
    tile_chunks : sequence of int
        Nominal tile size per dimension.

    Returns
    -------
    tuple
        Global slice tuple suitable for ``data_accessor.read(slice=...)``.
    """
    chunks = chunk_grid(shape, tile_chunks)
    global_slice: List[SliceItem] = []

    for dim, tile_idx in enumerate(tile_indices):
        tile_start = sum(chunks[dim][:tile_idx])
        tile_size = chunks[dim][tile_idx]
        global_slice.append(slice(tile_start, tile_start + tile_size))

    return tuple(global_slice)


def request_dim_bounds(item: SliceItem, dim_size: int) -> Tuple[int, int]:
    """
    Return half-open ``[start, stop)`` bounds for one slice request item.

    Parameters
    ----------
    item : int or slice
        Per-dimension slice request entry.
    dim_size : int
        Full axis length in storage.

    Returns
    -------
    tuple of int
        ``(start, stop)`` bounds along the axis.
    """
    if isinstance(item, slice):
        start = 0 if item.start is None else int(item.start)
        stop = dim_size if item.stop is None else int(item.stop)
        return start, stop
    index = int(item)
    return index, index + 1


def union_l2_tile_fetch_slice(
    shape: Sequence[int],
    tile_chunks: Sequence[int],
    tile_indices_list: Sequence[Tuple[int, ...]],
) -> Tuple[SliceItem, ...]:
    """
    Build the minimal axis-aligned slice covering full L2 tile extents.

    Parameters
    ----------
    shape : sequence of int
        Full array shape.
    tile_chunks : sequence of int
        Nominal L2 tile size per dimension.
    tile_indices_list : sequence of tuple
        Tile index per dimension for each tile to include.

    Returns
    -------
    tuple
        Global slice tuple whose bounds contain every listed tile entirely.
    """
    if not tile_indices_list:
        raise ValueError("tile_indices_list must be non-empty")

    ndim = len(shape)
    items: List[SliceItem] = []
    for dim in range(ndim):
        starts: List[int] = []
        stops: List[int] = []
        int_values: List[int] = []
        for tile_idx in tile_indices_list:
            global_slice = tile_global_slice(tile_idx, shape, tile_chunks)
            item = global_slice[dim]
            if isinstance(item, slice):
                start = 0 if item.start is None else int(item.start)
                stop = shape[dim] if item.stop is None else int(item.stop)
                starts.append(start)
                stops.append(stop)
            else:
                int_values.append(int(item))

        if int_values and len(int_values) == len(tile_indices_list):
            unique = set(int_values)
            if len(unique) == 1:
                items.append(int_values[0])
                continue
            starts.extend(int_values)
            stops.extend(value + 1 for value in int_values)

        if not starts:
            raise ValueError(f"no tile bounds collected for axis {dim}")
        items.append(slice(min(starts), max(stops)))

    return tuple(items)


def tile_fully_in_fetch_slice(
    shape: Sequence[int],
    tile_chunks: Sequence[int],
    tile_indices: Tuple[int, ...],
    fetch_slice: Sequence[SliceItem],
) -> bool:
    """
    Return whether a tile's full storage extent lies inside a fetch slice.

    Parameters
    ----------
    shape : sequence of int
        Full array shape.
    tile_chunks : sequence of int
        Nominal L2 tile size per dimension.
    tile_indices : tuple of int
        Tile index per dimension.
    fetch_slice : sequence
        Candidate Tiled read slice.

    Returns
    -------
    bool
    """
    if len(fetch_slice) != len(shape):
        return False

    tile_slice = tile_global_slice(tile_indices, shape, tile_chunks)
    for dim, (tile_item, fetch_item) in enumerate(zip(tile_slice, fetch_slice)):
        tile_start, tile_stop = request_dim_bounds(tile_item, shape[dim])
        fetch_start, fetch_stop = request_dim_bounds(fetch_item, shape[dim])
        if tile_start < fetch_start or tile_stop > fetch_stop:
            return False
    return True


def plan_hyperslab_batches(
    slice_info: Sequence[SliceItem],
    shape: Sequence[int],
    itemsize: int,
    target_bytes: int,
) -> Tuple[List[Tuple[SliceItem, ...]], Optional[int]]:
    """
    Split a hyperslab request into byte-budgeted batch reads.

    Batches are aligned to contiguous ranges on the longest slice axis in
    ``slice_info``. Tiled storage chunk geometry is not consulted; callers
    choose ``target_bytes`` to match expected network latency.

    Parameters
    ----------
    slice_info : sequence
        Per-dimension slice or index request.
    shape : sequence of int
        Full array shape.
    itemsize : int
        Storage dtype size in bytes.
    target_bytes : int
        Approximate maximum bytes per batch read.

    Returns
    -------
    batches : list of tuple
        Slice tuples covering the full request without overlap.
    batch_axis : int or None
        Storage axis split across batches, or ``None`` when only one batch.
    """
    if len(slice_info) != len(shape):
        raise ValueError(
            f"slice dimensionality ({len(slice_info)}) does not match "
            f"data dimensionality ({len(shape)})"
        )
    if target_bytes <= 0:
        raise ValueError(f"target_bytes must be positive, got {target_bytes}")
    if itemsize <= 0:
        raise ValueError(f"itemsize must be positive, got {itemsize}")

    spans: List[Tuple[int, int, bool]] = []
    element_count = 1
    for dim_size, item in zip(shape, slice_info):
        start, stop = request_dim_bounds(item, dim_size)
        length = stop - start
        if length <= 0:
            raise ValueError(f"empty slice span on axis with bounds {start}:{stop}")
        element_count *= length
        batchable = isinstance(item, slice) and length > 1
        spans.append((start, stop, batchable))

    total_bytes = element_count * itemsize
    if total_bytes <= target_bytes:
        return [tuple(slice_info)], None

    batchable = [
        (dim, stop - start)
        for dim, (start, stop, ok) in enumerate(spans)
        if ok
    ]
    if not batchable:
        return [tuple(slice_info)], None

    batch_axis = max(batchable, key=lambda item: item[1])[0]
    start, stop, _ = spans[batch_axis]
    span_len = stop - start
    other_elements = element_count // span_len
    elements_per_batch = max(1, int(target_bytes // (itemsize * other_elements)))

    batches: List[Tuple[SliceItem, ...]] = []
    batch_start = start
    while batch_start < stop:
        batch_stop = min(batch_start + elements_per_batch, stop)
        items = list(slice_info)
        items[batch_axis] = slice(batch_start, batch_stop)
        batches.append(tuple(items))
        batch_start = batch_stop

    return batches, batch_axis


def total_tile_count(shape: Sequence[int], tile_chunks: Sequence[int]) -> int:
    """
    Return the number of tiles covering an array shape.

    Parameters
    ----------
    shape : sequence of int
        Full array shape.
    tile_chunks : sequence of int
        Nominal tile size per dimension.

    Returns
    -------
    int
        Product of tile counts along each dimension.
    """
    count = 1
    for dim_size, chunk_size in zip(shape, tile_chunks):
        count *= len(chunk_sizes_per_dim(int(dim_size), int(chunk_size)))
    return count
