# Zarr L2 cache implementation plan

Track implementation of a persistent on-disk chunk cache for low-latency N-D data exploration in nbs-viewer.

**Status:** Phase 1–1b implemented; **Phase 1c** (slab-seed L1, spill-on-evict L2) implemented; Phase 2+ not started

**Scope:** `ChunkCache` / `ZarrL2Cache` only. The plotting stack already holds the current view in `PlotBundle` form — that is out of scope here.

## Background

N-D hypercube plotting increasingly relies on slicing, summing, and axis manipulation via:

- `nbs_viewer/models/catalog/chunkCache.py` — chunk-aware fetch, RAM cache, parallel Tiled reads
- `nbs_viewer/models/plot/cube_view.py` — `CubeViewSpec`, `apply_cube_view` reductions

The current `ChunkCache` is an in-memory cache mixing keyed slice results and Tiled chunk fragments. Evicted or new views re-fetch from Tiled over the network, which is too slow for interactive exploration of large datasets (~10 GB).

### Typical data and access patterns

Representative detector arrays are **4D**, e.g. shape `(200, 5, 1024, 1026)`:

- Dims 0–1: small scan/metadata axes (energy, detector index, …)
- Dims 2–3: large spatial image axes

Two dominant read patterns conflict if forced into a single physical layout:

| Phase | Typical read | Shape needed |
|-------|----------------|--------------|
| **A — image view** | `arr[i, j, :, :]` or sum over dims 0–1 | `(1024, 1026)` |
| **B — ROI cube** | `arr[:, :, y0:y1, x0:x1]` after ROI selection | `(200, 5, roi_h, roi_w)` |

The practical answer is to **return the exact view slab from Tiled on a cache miss**, then **populate L2 incrementally in the background** so later `getData` calls can assemble from local tiles.

### Exploration workflow (target)

1. Display a full `(1024, 1026)` image (sum or slice on dims 0–1)
2. Select a spatial ROI and slice / sum through the `(200, 5)` cube
3. Expand ROI or change axis roles; repeat with low latency once data is local
4. Revisit prior views without re-hitting Tiled

**Goal:** Minimal network on each new view; durable L2 so overlapping exploration runs at disk/RAM speed.

### Revised problem framing

| Bottleneck | Priority |
|------------|----------|
| **Network fetch from Tiled** | Primary — dominates interactive latency |
| **L1 tile eviction** | Secondary — solved by L2 persistence |
| **Local Zarr chunk geometry** | Tertiary — once data is on disk, SSD reads are ms-scale |

L2 chunk size mainly controls **background amplification** (how much extra data we pull after each interaction), not local read speed.

### Plot layer (out of scope)

The plotting pipeline already acts as the ephemeral view buffer:

```
PlotDataModel.get_plot_bundle()
  → RunModel.get_plot_bundle()  →  getData / ChunkCache
PlotWorker
  → data_ready  →  renderers (mpl_canvas, imageGridWidget, …)
```

`PlotBundle` carries the array for the current view and already handles invalidation when the view changes. **`get_data` does not need a view cache.** This plan only adds L1/L2 beneath `BlueskyRun.getData`.

## Problem analysis

### What already works

`ChunkCache` already:

- Maps slice requests to storage chunk indices (`get_chunk_indices`)
- Fetches minimal regions per chunk via `internal_slices` on the Tiled read path
- Fetches in parallel (`ThreadPoolExecutor`, in-flight dedup)
- Uses Tiled slice API for direct reads (`_get_data_sliced`)

### Current bottlenecks

| Issue | Detail |
|-------|--------|
| **Network re-fetch** | Explored regions lost when RAM cache evicts |
| **No persistent L2** | Explored regions are lost across sessions |
| **Keyed `slice_cache`** | View-shaped entries do not align with L2 tiles; not reusable across view changes |
| **Blocking on full-chunk write** | Any L2 write on the critical path would delay the plot |

### Approaches explicitly rejected for v1

| Approach | Why not |
|----------|---------|
| **Placeholder / sparse L2** | Sub-chunk validity tracking is complex and error-prone |
| **Keyed view cache in ChunkCache** | `PlotBundle` already covers this; view keys do not compose for L1 |
| **Match Tiled chunk shape as L2 layout** | Tiled may use `(1,1,1024,1026)` planes; poor fit for incremental ROI fill |
| **Blocking critical path on L2 writes** | User must see data as soon as Tiled responds |

## Architecture

### Tiered cache (ChunkCache scope only)

```
get_data(slice_info)
  │
  ├─ CACHE HIT:  all overlapping L2 tiles in L1 or L2 (complete)
  │              → assemble from tiles → return
  │
  └─ CACHE MISS: Tiled read(exact view slab)  → return immediately
                 → enqueue background: materialize each touched L2 tile
```

```
Tiled / network
      │
      │  miss: exact view slab (one read)
      ▼
  L1: ChunkCache tile RAM (LRU)     complete L2-aligned tiles only
      │
      │  write-behind (async)
      ▼
  L2: persistent Zarr store         spatial tiles + completion.json
```

| Tier | Role |
|------|------|
| **L1** | Hot **complete L2 tiles** in RAM; LRU (`l1_max_bytes`) |
| **L2** | Durable tiles; chunk-granular completion; evict whole `{run_uid}/{key}` |

L2 is populated **lazily by exploration**. A view can return before any L2 tile for that request is complete.

### Fast path (target behaviour — Phase 3+)

Phases 1–2 use a simpler blocking fetch while L2 plumbing is proven; see **Phased delivery** below.

On **cache miss** (Phase 3 interim rule: all-or-nothing), `get_data` must:

1. Issue **one Tiled read** for the **exact** `slice_info` slab the view needs (same as `_get_data_sliced` today).
2. **Return** that array as soon as Tiled responds — do not wait for L2 tiles.
3. **Enqueue** background work to materialize every **L2 chunk** intersecting `slice_info` (full tile extent each).

On **cache hit**, all intersecting L2 tiles are complete in L1 and/or L2:

1. Read tiles, assemble to the requested shape, return.
2. No Tiled call.

Phase 3 uses **all-or-nothing** hits (any incomplete tile → whole-request Tiled slab). Phase 4 relaxes this to **partial assembly** (warm tiles from L1/L2 + Tiled fetch for gaps only).

### L1: tile cache only

```text
(run_uid, key, l2_chunk_indices)  →  np.ndarray   # full tile, e.g. (200, 5, 256, 256)
```

- Only **complete** tiles (same atomic unit as L2).
- **Retire** `slice_cache` and Tiled-keyed `chunks` as part of this work.

### Two grids: Tiled fetch vs L2 storage

| Grid | Purpose |
|------|---------|
| **Tiled (critical miss)** | Single exact `slice_info` read |
| **L2 / L1** | Fixed `l2_chunks` tiles + `completion.json` |

Background `materialize_chunk` uses the L2 grid and may fetch full tile extents from Tiled. The critical path uses neither Tiled chunk assembly nor per-tile fetches.

### Critical path vs background (detailed)

```
get_data(slice_info)
  │
  ├─ CRITICAL PATH
  │    1. tiles = l2.chunks_intersecting(slice_info)
  │    2. If every tile in tiles is complete (L1 or L2):
  │         assemble from tiles → return
  │    3. Else (cache miss):
  │         result = tiled.read(slice=slice_info)   # exact view slab
  │         return result
  │    4. queue_materialize(tiles, seed=result)    # non-blocking
  │
  └─ BACKGROUND (ThreadPoolExecutor)
       For each incomplete tile in tiles:
         materialize_chunk(tile, seed=result)
           → seed overlap from result where possible
           → tiled_fetch(full tile extent) for remainder
           → write L2 → mark_complete → promote L1
```

**Rules (Phase 3+):**

1. Critical path **never waits** on background materialization or L2 writes.
2. **Phase 3:** incomplete tile → whole-request miss → Tiled fast path. **Phase 4:** fetch only gaps.
3. Validity is **chunk-granular** (`completion.json`). No sub-chunk validity.
4. `seed` is the critical-path array **captured at enqueue** (for background overlap copy only).

### Example ROI workflow

```
User requests  [:, :, 100:200, 100:300]

Cache miss:     Tiled → (200, 5, 100, 200)  →  return immediately
                PlotBundle built upstream as today
Background:     materialize L2 tiles covering that region (full 256×256 extents)

User expands to [:, :, 100:300, 100:300]

Cache hit?      if tiles for 100:200 region are complete → assemble from L1/L2
                + cache miss on new strip → Tiled delta slab OR full slab per step 3
Background:     materialize newly touched tiles
```

### Integration points

| Location | Role |
|----------|------|
| `BlueskyCatalog.__init__` | Creates shared `ChunkCache()` (L1) |
| `BlueskyRun.getData` | Delegates to `chunk_cache.get_data` |
| `ChunkCache.get_data` | Hit: L1/L2 tiles. Miss: Tiled exact slab + background queue |
| `RunModel._fetch_plot_arrays` | Phase 2b: ROI → `to_fetch_slice_info` before `getData` |
| `RunModel.get_plot_bundle` | Unchanged bundle flow; fetch slice narrows with ROI |
| `PlotWorker` | Unchanged; `data_ready` → renderers |

Plot stack (`CubeViewSpec`, `apply_cube_view`, `PlotBundle`) unchanged.

## Core design decisions

| Topic | Decision |
|-------|----------|
| Critical miss path | **One Tiled read** = exact `slice_info` slab; return immediately |
| Critical hit path | Assemble from **complete** L1/L2 tiles only |
| Background | **Full L2 tile** materialization; async; seed from critical-path array |
| L1 | `ChunkCache` — complete L2 tiles only, LRU |
| L2 | Zarr; fixed spatial tiles e.g. `(1, 1, 256, 256)` |
| Completion | Per L2 chunk in `completion.json`; Phase 3: whole-request miss; Phase 4: partial |
| L2 store (early) | **In-memory** Zarr (`MemoryStore`) in Phase 1; swap to `DirectoryStore` after validation |
| View buffering | **PlotBundle** (existing) — not part of this plan |
| Framework | `ZarrL2Cache` + refactor `ChunkCache`; no Dask for v1 |

### L2 chunk shape rationale

For `(200, 5, 1024, 1026)` with `l2_chunks = (1, 1, 256, 256)`:

| Pattern | Critical path (miss) | Background per touched tile |
|---------|---------------------|----------------------------|
| Full image | One Tiled plane read | Seed 20 tiles from result locally (Phase 2) |
| ROI cube | One Tiled hyperslab | Async full `(200, 5, 256, 256)` tile from Tiled |

`tiled_chunks` in `meta.json` is informational; background fetches use L2 tile extents.

## New component: `ZarrL2Cache`

Suggested module: `nbs_viewer/models/catalog/zarr_l2_cache.py`

### On-disk layout

```
{cache_root}/
  {run_uid}/
    {data_key}/
      meta.json          # shape, l2_chunks, tiled_chunks, dtype, source revision
      completion.json    # L2 chunk indices complete (set or bitmap)
      data.zarr/
```

### API surface

```python
class ZarrL2Cache:
    def __init__(self, root: Path, max_bytes: int | None = None): ...

    def open_array(self, run_uid, key, shape, l2_chunks, dtype) -> zarr.Array: ...

    def has_chunk(self, run_uid, key, l2_chunk_indices) -> bool: ...

    def read_chunk(self, run_uid, key, l2_chunk_indices) -> np.ndarray: ...

    def write_chunk(self, run_uid, key, l2_chunk_indices, data: np.ndarray) -> None: ...

    def mark_complete(self, run_uid, key, l2_chunk_indices) -> None: ...

    def chunks_intersecting(
        self, run_uid, key, slice_info
    ) -> list[tuple[int, ...]]: ...

    def all_complete(self, run_uid, key, l2_chunk_indices) -> bool: ...

    def is_complete(self, run_uid, key) -> bool: ...

    def completion_fraction(self, run_uid, key) -> float: ...

    def clear_run(self, run_uid) -> None: ...

    def evict_lru_runs(self) -> None: ...
```

### `ChunkCache` integration

**`get_data(run, key, slice_info)`:**

```python
tiles = l2.chunks_intersecting(run_uid, key, slice_info)
if l2.all_complete(run_uid, key, tiles):
    return assemble_from_l1_l2(tiles, slice_info)
result = tiled_read_exact(run, key, slice_info)
queue_materialize(tiles, seed=result)
return result
```

**`materialize_chunk(run, key, l2_chunk_indices, seed=None)`** (background):

1. If L2 `has_chunk` → promote to L1; return
2. Build full tile: copy `seed` overlap + `tiled_fetch(full_extent(tile))` for gaps
3. `write_chunk` → `mark_complete` → L1 promote

**Retire:** `slice_cache`, Tiled-keyed `chunks` → L2-indexed `tiles` dict.

**Whole-dataset fast path** (when `is_complete`):

```python
return np.asarray(l2.open_array(...)[slice_info])
```

## Configuration

| Setting | Default | Purpose |
|---------|---------|---------|
| `cache_root` | `~/.cache/nbs-viewer/data` | L2 root (Phase 1: unused if `l2_store=memory`) |
| `l2_store` | `memory` → `disk` | Phase 1 in-memory; flip after spill tests pass |
| `l2_enabled` | `True` | Toggle L2 tier |
| `l2_chunks` | `(1, 1, 256, 256)` | L1/L2 tile shape |
| `l2_max_bytes` | e.g. 100 GB | Evict whole datasets (disk only) |
| `l1_max_bytes` | 1 GB → reduced in Phase 2 | L1 tile LRU; shrink to force L2 spill |
| `l2_background_workers` | 4 | Write-behind pool (Phase 3+) |

## Background materialization

**Implicit (default):** every cache-miss `get_data` enqueues touched incomplete tiles.

**Explicit (optional UI):**

```python
def materialize_all(self, run, key, progress_callback=None) -> Future:
    """Fetch all missing L2 tiles without blocking UI."""
```

## Thread safety and consistency

- Per-L2-chunk write lock
- Write-then-mark in `completion.json`
- In-flight dedup on `(run_uid, key, l2_chunk_indices)`
- `clear_run`: delete L2 dir + matching L1 keys

## Phased delivery

Incremental rollout: prove L2 tiering in memory before changing critical-path latency or persisting to disk.

```
Phase 1   in-memory Zarr L2 behind L1 (blocking tile fetch, write-through) — superseded by 1c
Phase 1b  download progress indicator (background / completion_fraction)
Phase 1c  slab-seed L1 from Tiled result; L2 spill on L1 eviction only (no double Tiled fetch)
Phase 2   shrink L1 → verify spill to L2
Phase 2b  ROI spatial bounds in fetch slice_info (prerequisite for Phase 3)
Phase 3   Tiled hyperslab fast path + async background tile materialization — **implemented**
Phase 4   partial critical path (L1/L2 tiles + Tiled gaps) — **implemented**
Later     disk store, seed-from-slab, materialize_all, eviction, revision checks
```

### Phase 1 — In-memory Zarr L2 behind L1

**Goal:** `ZarrL2Cache` API and L1↔L2 tiering without disk I/O or critical-path changes.

- `ZarrL2Cache` backed by `zarr.storage.MemoryStore` (same interface as future `DirectoryStore`)
- Refactor L1 to tile keys `(run_uid, key, l2_chunk_indices)`; retire `slice_cache` when ready
- `completion.json` logic in memory (dict/set; persist format stubbed for disk)
- Unit tests with mocked Tiled + in-memory Zarr

**Win:** Validates tile grid, completion tracking, and L2 read/write before async or disk complexity.

**Not in Phase 1:** non-blocking return, Tiled exact-slab fast path, partial assembly.

### Phase 1c — Slab-seed L1, spill-on-evict L2 (Option C)

**Goal:** Restore pre-L2 critical-path latency while keeping L2-aligned L1 tiles.

- **Critical path:** Tiled fetch + assemble (unchanged); then `_seed_l1_tiles_from_slab` splits the result into L2-aligned tiles in **L1 only** (no extra Tiled reads, no L2 writes)
- **Revisit:** assemble from L1 tiles when every intersecting tile is in L1; else L1+L2; else Tiled
- **Eviction:** `_evict_lru_l1_tile` → `_spill_l1_tile_to_l2` (write-behind persistence)
- Tile assembly no longer requires `all_complete` in L2; per-tile L1-or-L2 availability

**Win:** Single Tiled round-trip on miss; energy-slice flipping hits L1; L2 is cold overflow only.

**Deferred:** background proactive L2 warm (optional Phase 3 optimization).

### Phase 1b — Download progress indicator

**Goal:** Visibility into background / incremental loading before Phase 3 async work.

- Expose `completion_fraction(run_uid, key)` and/or in-flight chunk count from `ChunkCache` / `ZarrL2Cache`
- Signal or callback suitable for status bar / plot UI (e.g. `QProgressBar`, status label)
- Update during tile materialization (Phase 1: synchronous writes still update fraction; Phase 3: background queue)

**Win:** Manual testing feedback (“is the cache warming?”) during Phases 2–3.

**Implemented UI hook:** `PlotWidget.cache_status_label` sits above the debug button row and shows **in-flight Tiled fetches** for the current L2 materialize batch (e.g. `Fetching det from Tiled: 2 chunks remaining (2/4 loaded)`). **Cache Stats** button prints `ChunkCache.format_debug_report()` including whole-dataset L2 completion.

### Phase 2 — Shrink L1 and test spill to L2

**Implemented (partial):** default `l1_max_bytes=128MB` (separate from 512MB tiled chunk cache); large slab seeds fill L1 on the critical path then queue remaining tiles for background L2 writes (`sync_seed_tile_limit=64`); Tiled fetch progress wired to plot status label.

**Goal:** Prove L2 is the spill tier when L1 pressure evicts tiles.

- Reduce default `l1_max_bytes` (e.g. 1 GB → 64–128 MB) under test config
- Manual + automated: fetch more tiles than L1 holds → L1 evicts → re-request → served from L2 without Tiled
- Metrics: L1 evictions, L2 hits, Tiled call count

**Win:** Confirms two-tier RAM behaviour before relying on L2 for interactive exploration.

### Phase 2b — ROI in fetch (`slice_info`) — **required before Phase 3**

**Status:** Implemented — `MaterializeRequest.to_fetch_slice_info` / `fetch_context` narrow plot-plane axes; `RunModel._fetch_plot_arrays` uses narrowed slices before `getData`; cropped `PlotViewFrame` keeps `materialize_view` aligned with bbox loads. Tiled still fetches whole intersecting chunks.

**Goal:** Spatial ROI bounds flow into `getData` / `chunk_cache.get_data`, not only post-fetch masking.

#### Current behaviour (problem)

Today the fetch path loads the **full** spatial extent, then applies ROI in `materialize_view`:

1. `CubeViewSpec.to_load_slice_info()` — non-`INDEX` axes get `slice(None)` (full 1024×1026 plane).
2. `RunModel._fetch_plot_arrays` → `getData(ykey, slice_info)` fetches that full hyperslab.
3. `materialize_view` compiles ROI on `PlotViewFrame` and applies `np.where(mask, y, np.nan)` (`_materialize_roi_plane`, `_materialize_roi_profile` in `cube_view.py`).

That is correct for correctness but wrong for cache design:

- Phase 3 fast path issues **one Tiled read = `slice_info`**. If `slice_info` still means full spatial axes, every ROI view downloads the entire image.
- L2 tiles intersecting the ROI cannot warm incrementally; background materialization tracks the full plane grid.
- Tile cache keys align to storage indices; mask-on-full-array does not narrow what `chunks_intersecting` sees.

#### Target behaviour

When `MaterializeRequest.region` is set (and `region_frame` is available at fetch time):

1. Compile region → `CompiledRegion` with `bbox` on the parent plot plane (`region_mesh` / `region.py`).
2. Map plot-plane row/col bounds to **storage-axis slice ranges** on the parent's `PLOT_Y` / `PLOT_X` storage dimensions.
3. Build `slice_info` with those ranges on spatial axes; other axes unchanged (`INDEX` indices, `slice(None)` on reduce/profile axes per spec).
4. `getData` / `ChunkCache` receive the narrowed hyperslab, e.g. `[:, :, 100:200, 100:300]` instead of `[:, :, :, :]`.
5. **Post-fetch mask** may still apply for pixels outside the ROI but inside the bbox (and for future non-rect regions); fetch is bbox-limited, not full-field.

New or extended API (coordinate with [`materialize_view_refactor_plan.md`](materialize_view_refactor_plan.md)):

```python
def to_fetch_slice_info(
    self,
    *,
    region_frame: PlotViewFrame | None = None,
    region: RegionDefinition | None = None,
    mask_mode: str = "inside",
) -> tuple[SliceItem, ...]:
    """slice_info for getData; narrows plot-plane storage axes when region is set."""
```

Call site: `RunModel._fetch_plot_arrays` (and norm fetches) when `materialize_request.region` is set — **before** `getData`, not inside `materialize_view` only.

#### Phase scope

| In scope | Out of scope (later) |
|----------|----------------------|
| Rectangular ROI bbox → storage slices | Polygon ROI fetch clipping |
| Profile (`plot_ndim=1`) and plane (`plot_ndim=2`) materialize requests | Sub-bbox mask-only pixels without bbox shrink |
| Image + mesh `PlotViewFrame` bbox mapping | Threshold / imported masks |

#### Testing

- Unit: `to_fetch_slice_info` maps known rect on `PlotViewFrame` → expected storage slices
- Integration: ROI profile fetch calls Tiled with narrowed `slice_info`; `materialize_view` mask still matches pre-change output on rect ROI
- Manual: network/logging shows smaller read than full `(1024, 1026)` plane

**Win:** Phase 3 fast path and L2 tile intersection operate on the bytes the view actually needs.

**Phases 1–2 may defer this** — full-extent fetch + post-fetch mask remains valid while proving L1/L2 tiering.

### Phase 3 — Tiled hyperslab fast path + background chunk loading

**Status:** Implemented — when L2 is enabled, `get_data` uses one `_read_tiled_hyperslab` on miss, returns immediately, and `_queue_l2_materialize` fills complete L2 tiles in the background via `_materialize_l2_tile` (full tile Tiled read + L2/L1 store). Identical narrowed views still hit assembled-slab `slice_cache`; warm datasets hit `_try_get_data_from_l2_tiles`.

**Goal:** Critical path returns on first Tiled response; L2 fills asynchronously.

- **Cache hit (unchanged):** all intersecting tiles complete → assemble from L1/L2
- **Cache miss (new):** `tiled.read(slice=slice_info)` exact view slab → **return immediately**
- `queue_materialize(tiles, seed=result)` on ThreadPoolExecutor — no blocking on L2 writes
- `materialize_chunk`: full tile from Tiled (+ seed overlap copy where applicable)
- **All-or-nothing hit rule** remains: one missing tile → full Tiled slab for the view

**Win:** Plot latency = one Tiled round-trip on miss; cache warms in background.

### Phase 4 — Partial critical-path fetch

**Status:** Implemented — `_try_get_data_partial_l2` assembles warm L1/L2 tiles, fetches only the cold-gap hyperslab (`_cold_gap_slice_info`), merges into the view slab, and queues background materialization for cold tiles only.

**Goal:** Avoid re-fetching the whole view slab when only a subset of tiles is cold.

- Partition intersecting tiles into **warm** (L1/L2 complete) vs **cold**
- Critical path: assemble warm tiles + **minimal Tiled fetch** for the sub-slab covering cold regions only (may be one hyperslab or per-gap reads — spike in this phase)
- Background: materialize newly touched cold tiles as in Phase 3
- Seed from assembled + fetched regions where tile extent overlaps

**Win:** ROI expansion and overlapping views avoid redundant network for already-cached tiles.

**Example:** `[:, :, 100:300, 100:300]` with tiles for `100:200` warm → assemble that portion from L1/L2 + Tiled fetch only `200:300` strip.

### Later (post Phase 4)

| Item | Notes |
|------|-------|
| **Disk `DirectoryStore`** | Swap store backend; persist `completion.json` + `meta.json` |
| **Seed from critical-path slab** | Background splits returned hyperslab into tiles without re-fetching overlap |
| **Whole-dataset fast path** | `is_complete` → `zarr[slice_info]` |
| **`materialize_all` UI** | Explicit “cache locally” using progress from Phase 1b |
| **Delta tile fill in background** | Fetch only tile strips not in `seed` |
| **Disk quota + revision invalidation** | `l2_max_bytes`, Tiled metadata mismatch |

## Reuse vs. new code

| Reuse as-is | Add or change |
|-------------|----------------|
| `_get_data_sliced` / Tiled `read(slice=...)` | **Critical miss path** |
| `get_chunk_indices` math | L2 variant with `l2_chunks` |
| `_assemble_result` | Tile assembly from L1/L2 |
| Thread pool, in-flight dedup | `queue_materialize` / `materialize_chunk` |
| `clear_run` | L2 dirs + L1 tiles |
| `slice_cache`, Tiled `chunks` | **Remove** |

## Testing (by phase)

| Phase | Tests |
|-------|-------|
| **1** | L2 MemoryStore read/write; `has_chunk` / `mark_complete`; L1 miss → L2 hit promotes; mocked Tiled |
| **1b** | `completion_fraction` increases as tiles written; signal fires on UI thread |
| **2** | Small `l1_max_bytes`: eviction → re-fetch hits L2 not Tiled; stats counters |
| **2b** | ROI fetch `slice_info` ⊂ full extent; materialized output matches pre-change rect ROI |
| **3** | Miss returns before background `mark_complete`; second identical view hits L1/L2 |
| **4** | Mixed warm/cold: Tiled call size < full view slab; assembled result matches full fetch |
| **Manual** | Image → ROI → expand across phases 3–4; watch progress UI |

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Phase 1 scope creep | Defer fast path and async to Phase 3 explicitly |
| MemoryStore ≠ disk semantics | Phase 2 spill tests + explicit disk swap checklist |
| All-or-nothing redundant fetch (Phase 3) | Accepted interim; Phase 4 partial path |
| Background amplification | Tune `l2_chunks` |
| Stale cache | Revision in `meta.json` (disk phase) |

## Related work

- **Materialize view refactor** (`materialize_view_refactor_plan.md`) — **Phase 2b coordinates here**: `MaterializeRequest`, `to_load_slice_info` / new `to_fetch_slice_info`, `RunModel._fetch_plot_arrays`
- **ROI analysis plan** (`roi_analysis_plan.md`) — `CompiledRegion.bbox`, `PlotViewFrame`; fetch narrowing implements “bbox-limited reads” alluded to in materialize plan performance notes
- **PlotBundle / PlotWorker** — view lifetime and render; no changes required for Phase 1
- **Dask:** Only for 100+ GB fused pipelines

## Open questions

**Before Phase 1**

1. Default `l2_chunks` — `(1, 1, 256, 256)` vs per-detector config
2. Retire `slice_cache` in Phase 1 or defer until Phase 3 fast path

**Before Phase 1b**

3. Progress UI placement — status bar vs plot panel vs per-run indicator
4. Granularity — per-`key` fraction vs per-chunk count

**Before Phase 2**

5. Test `l1_max_bytes` value that reliably forces eviction without breaking normal use

**Before Phase 2b**

6. `to_fetch_slice_info` on `CubeViewSpec` vs `MaterializeRequest` vs shared helper
7. Mesh vs image frame: confirm bbox row/col → storage index mapping for `tes_mca_energies`-style keys

**Before Phase 3**

8. Confirm Phase 2b merged; non-ROI views still use full-extent `slice_info`

**Before Phase 4**

9. Spike: one Tiled hyperslab for union of cold gaps vs multiple smaller reads
10. Assembly order when warm + cold tiles are stitched on critical path

**Before disk migration (later)**

11. Cache directory — XDG vs configurable path
12. Auto `materialize_all` on open vs implicit fill only
