"""
Map N-D slice requests to fixed-size tile indices and global slices.
"""

from __future__ import annotations

from itertools import product
from typing import Dict, List, Sequence, Tuple, Union

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
