# Codebase problem statement

**Status: OPEN (2026-09-02).** Written after the ownership refactor closed
([`model_ownership_headless_plan.md`](model_ownership_headless_plan.md)) and
Phase 2 of the testing plan
([`headless_testing_plan.md`](headless_testing_plan.md)) landed, while
[`plot_package_reorganization.md`](plot_package_reorganization.md) is still
pending.

This document records **what is wrong and why it matters**. It proposes no
work. The remediation sequence lives in
[`structural_remediation_plan.md`](structural_remediation_plan.md).

## Purpose

The ownership refactor answered **who creates what**. It did not answer three
other questions, and those three are what actually break when a feature is
added:

| Question | Answered? | Where the gap shows |
|----------|-----------|---------------------|
| Who *creates* domain objects? | Yes (Steps 1–6b) | — |
| Who *owns the truth* for a fact? | **No** | 8 pairs of hand-synced duplicate state |
| Who *tears down* a subscription? | **No** | 11 of 92 files contain any `.disconnect` |
| What is the *contract* at a boundary? | **No** | display-vs-storage indices; `CatalogRun` stubs |

The pending package reorganization addresses **findability**, which is real
but is the least urgent of the four. This document exists so the reorg is not
mistaken for having addressed the rest.

## What is healthy (protect this)

Not everything needs work. These are assets, and several proposed changes are
valuable mainly because they protect them.

- **`pytest tests/` is 247 tests, green, in 9.5 s**, with no `QApplication`
  and no network. This is the single most valuable thing the recent work
  produced.
- **`models/` has zero `qtpy.QtWidgets` imports** and exactly **one**
  matplotlib import, in `region_mesh.py` (a function-level
  `from matplotlib.path import Path`). H1 holds. The second import,
  `plotDataModel.py:8`, went with session-plan step B.
- **The geometry / cube / materialize layer is mostly pure numpy** with frozen
  dataclasses (`CubeViewSpec`, `MaterializeRequest`, `PlotViewFrame`,
  `ViewCrop`, `CompiledRegion`) and ~83 tests that need no fixtures.
- **`tile_indices.py` and `zarr_l2_cache.py` are already extracted** from
  `chunkCache.py` with pure functions and an injectable store — the
  demonstrated pattern for the rest of that file.
- **Structured logging exists** (`logging_setup.py`, `print_debug` with 189
  call sites, `--debug-topic` CLI). The problem is the parallel raw-print
  path, not a missing facility.
- **`catalog/`, `data/`, `sources/`, `cache/` package layout is done** and is
  the template the reorg plan copies.

## Problem ranking

Ranked by impact on maintainability and on the cost of adding a feature
without breaking the base. P1 items are structural: they make every future
change riskier. P2 items are abstraction quality: they make specific
categories of feature expensive. P3 items compound slowly.

| # | Problem | Tier | Primary cost |
|---|---------|------|--------------|
| 1 | No teardown discipline | P1 | Every new subscriber leaks; double-fire |
| 2 | Display-vs-storage index contract is implicit | P1 | Silent wrong data in N-D features |
| 3 | Eight pairs of hand-synced duplicate state | P1 | New code reads the stale copy |
| 4 | Three god classes at the feature-add points | P1 | Every feature touches 1000+ line files |
| 5 | Data layer interface is not enforceable | P2 | New backend requires editing views |
| 6 | ~~`PlotDataModel` owns matplotlib artists~~ | P2 | ✅ closed by session-plan step B — `Trace` holds no artist, `MplCanvas` owns a `TraceKey` → artist map |
| 7 | Domain policy still in views | P2 | Parallel spec state; untestable policy |
| 8 | No CI | P2 | Refactors have no automated safety net |
| 9 | 132 `print()`, 100 broad `except`, 22 silent `pass` | P3 | Failures are invisible |
| 10 | Naming split; stale plan docs | P3 | Grep and checklists are unreliable |

---

## P1 — Structural

### 1. No teardown discipline

Signals are connected liberally and disconnected almost nowhere. Only **11 of
92** files contain a `.disconnect` call, and there is **no `closeEvent` or
`cleanup`** on `MplCanvas`, `PlotWidget`, or `PlotDisplay`.

Confirmed instances:

- ~~**`PlotDataModel.__init__`** subscribes to four `RunModel` signals and
  never disconnects~~ — ✅ closed. The subscription is down to one
  (`RunSource.data_changed`), and session-plan step B added
  `Trace.dispose`, which `TraceSet.discard` calls on every removal, so
  `drop_traces_for_uid` and `rebuild` both disconnect.
- **`DisplayManager.remove_display`** (`displayManager.py:133`) drops the
  presenter with no teardown, so a closed tab's `PlotModel` stays subscribed
  to its `RunListModel`.
- **`PlotModel`** connects to `RunListModel`, to itself
  (`cube_view_changed`, `selected_keys_changed`), and to per-run
  `plot_update_needed`. Only per-run detach exists; there is no `cleanup()`.
- **`CombinedRunModel` double-connects.** It connects each source run's
  `data_changed` in its own loop (`combinedRunModel.py:69–70`) and then
  `super().__init__` reaches `RunModel._connect_run`, which connects the same
  signals again (`:88–92`). Every combined run fires its handler twice.
- **`MplCanvas.updatePlot`** allocates a fresh `QTimer` per call and connects
  `timeout` each time (`single_canvas.py:567–577`).

**Why this is #1.** It is not one bug, it is a missing convention. Every new
subscriber inherits it — a new tab, a new canvas type, the per-cell
`PlotModel`s that Step 6c requires. These failures are also invisible to the
current suite: nothing asserts that closing a display leaves no live
connections. They surface as drift and double-fetch during a beamtime, which
is the worst possible place to discover them.

### 2. Display-plane vs storage-index is an unwritten contract

This is where silent wrong-data bugs live, which is worse than a crash.

Two ROI fetch paths disagree. `view_crop.fetch_context_with_view_crop`
correctly maps display bbox → storage bbox before narrowing slices:

```169:174:nbs_viewer/models/plot/view_crop.py
    storage_roi = storage_bbox_from_display_bbox(
        display_bbox,
        crop.row_axis,
        crop.col_axis,
        region_frame.shape,
    )
```

`MaterializeRequest.fetch_context` applies the display bbox **directly** onto
storage-axis slice items with no mapping:

```149:154:nbs_viewer/models/plot/cube_view.py
        items[plot_y_axis] = _narrow_fetch_slice(
            items[plot_y_axis], r0, r1, region_frame.n_plot_y
        )
        items[plot_x_axis] = _narrow_fetch_slice(
            items[plot_x_axis], c0, c1, region_frame.n_plot_x
        )
```

`storage_bbox_from_display_bbox` detects the flip by testing whether
`row_axis` / `col_axis` ascend (`plot_geometry.py:202–205`). `PlotViewFrame`
carries only `shape`, `render_mode`, `axis_names`, `plot_x_dim`,
`plot_y_dim`, `extent`, `mesh_x`, `mesh_y` — **no axis arrays**. So the
non-crop path cannot perform the mapping even in principle. This is a missing
field on a type, not an oversight in one function.

Compounding it:

- **`CompiledRegion.bbox` is misdocumented.** `region.py:41–43` says
  "storage indices"; the value is oriented display-plane row/col.
- **Two correct-but-different cell rules coexist.** ROI reduction uses
  center-in-rect (`region_mesh.mask_from_data_rect`); view crop uses
  touches-rect (`region_mesh` covering-rect helpers). Both are documented.
  Nothing in the type system keeps them apart.
- **No test covers the flipped case.** `tests/test_fetch_slice_info.py` uses
  ascending `np.arange` axes and asserts internal consistency, never storage
  correctness against `storage_bbox_from_display_bbox`.

Every queued N-D feature lands here: band projection
([`band_projection_plan.md`](band_projection_plan.md)), the multi-view image
grid (Step 6c), ROI sync.

### 3. Eight pairs of hand-synced duplicate state

Each pair is a place where new code reads the stale copy. Confirmed:

| Fact | Location A | Location B |
|------|-----------|------------|
| Selected x/y/norm keys | `PlotModel._current_*_keys` | `RunModel._selected_*` |
| Visible run set | `RunListModel._visible_runs` | `RunModel._is_visible` + `QStandardItem` check state |
| Cube view spec | `PlotSession._cube_view_spec` | `DimensionControl._cube_view_spec`, `canvas._cube_view_spec` (the `Trace` copy went with step B — it reads `request.view`) |
| Slice / dimension | `PlotSession._slice`, `_dimension` | ~~each trace's `_indices`, `_dimension`~~ — ✅ deleted in step B; a trace reads `request.view` |
| Transform | `PlotModel._transform` | `RunModel._transform_text` + `Interpreter` |
| Per-trace visibility | `Trace._visible` (now the single intent) | `artist.get_visible()`, set *from* the trace since step B, + `RunSource._is_visible` |
| Available key universe | `RunListModel.available_keys` (intersection) | each `RunModel.available_keys` |
| Norm keys | `PlotSession` selection | ~~`PlotDataModel._norm_keys`~~ — ✅ deleted in step B; a trace reads `request.norm_keys` |

The three that matter most:

**Selected keys diverge silently.** `PlotModel` stores what the user picked
and pushes it down; `RunModel.set_selected_keys` **filters** to that run's
`available_keys` (`runSource.py:865–879`). After a sync the two disagree for
any run missing a key. Views are split on which they read —
`DimensionControl.get_shape_info` and `ImageGridCanvas` read the run copy.
The ownership plan documents this as a temporary bridge; it is the
highest-value temporary thing in the tree to delete.

**`visible_runs` and `visible_models` return different sets.**

```599:615:nbs_viewer/models/plot/runListModel.py
    def visible_models(self) -> List[RunModel]:
        return [
            model
            for model in self._run_models.values()
            if model.uid in self._visible_runs
        ]

    @property
    def visible_runs(self) -> Set[str]:
        """Get visible run UIDs"""
        if self._is_main_display:
            return set(self._run_models.keys())
        else:
            return self._visible_runs
```

`PlotModel` uses **both** — `visible_runs` at `:621`, `visible_models` at
`:1190`. On the main display those disagree. Fifteen call sites across models
and views pick one arbitrarily.

**The cube spec exists in four places.** The reorg document already notes
that ROI controllers do a triple fallback lookup across
`dimension_control._cube_view_spec` / `plot_model` / `canvas._cube_view_spec`.

### 4. Three god classes, sitting exactly where features get added

| Class | File | Size | Concerns tangled |
|-------|------|------|------------------|
| `ChunkCache` | `models/cache/chunkCache.py` | 2137 lines, 63 methods | L1 dict cache, Zarr L2, Tiled transport, slab geometry, background materialize, assembled-slab LRU, progress, ops/debug |
| `MplCanvas` | `views/plot/mplCanvas/single_canvas.py` | 1743 lines, 92 methods | Qt sizing, mpl rendering, plot orchestration, workers, ROI/crop interaction, autoscale, legend, 111-line debug dump |
| `PlotModel` | `models/plot/plotModel.py` | 1258 lines, ~54 public members, 12 signals | key selection, transform, N-D view state, plot-data map, view crop, ROI CRUD, ROI preview/commit pipeline, region fingerprinting |

Longest `PlotModel` methods: `commit_roi_profile` (85), `prepare_roi_commit`
(69), `apply_view_crop_from_region` (66), `preview_roi_profile` (66),
`finalize_roi_commit` (66). Longest cache methods:
`_background_materialize_tiles` (104), `_seed_l1_tiles_from_slab` (89),
`_read_tiled_hyperslab` (84).

The reorg plan is right that splitting files by concern helps navigation. It
will not fix `PlotModel`: the four-method ROI preview/commit pipeline needs to
become a collaborator that `PlotModel` delegates to, which is a class split,
not a file move.

Concurrency in `ChunkCache` deserves separate mention. One `request_lock`
covers the job registry and `clear()`. The hot-path dicts (`slice_cache`,
`chunk_info`, `access_times`, counters) are read and written from both the
main thread and a 4-worker `fetch_pool` with no lock. `_queue_l2_materialize`
releases the lock between its duplicate-job check and the submit
(`chunkCache.py:750–781`), so two concurrent `get_data` calls can enqueue the
same background job. `background_pool` is never shut down in `clear()`.
`ChunkCache` also reaches into `ZarrL2Cache` privates (`self.l2._meta` at
`:154`, `self.l2._lock` at `:1229–1233`), creating a second write path to L2
that bypasses `write_chunk` validation.

---

## P2 — Abstraction quality

### 5. The data layer's interface is not enforceable, so backends leak into views

`CatalogBase` imports `ABC` and `abstractmethod` but inherits only `QObject`
and uses bare `raise NotImplementedError`. `CatalogRun` is a plain `QObject`
whose contract methods are `pass` stubs — a subclass that forgets `getData`
returns `None` rather than failing loudly.

Concrete contract breaks:

- **`to_header` has two incompatible signatures.** Base declares an instance
  method returning `Dict` (`data/base.py:140–149`); every implementation is a
  `@classmethod` returning a list of column names.
- **Capabilities are uneven and undeclared.** `KafkaCatalog` has no `search`
  and no `filter_by_time`. `search.py:28` calls `filter_by_scantype`, which
  is implemented **nowhere** in the repo. `CatalogTableModel` assumes
  `items_slice` exists, which `CatalogBase` never declares.
- **`BlueskyRun._has_data` starts as `None`** and `_check_data_access()` is
  defined (`bluesky.py:88`) but never called, so `getData` can return an
  empty array before any access attempt (`:326–327`).
- **`KafkaRun.scanFinished()` is always true** — `_stop_doc = {}` is set in
  `__init__` and the check is `hasattr` (`kafka.py:79` vs `:310–311`).

The consequence is visible in views, which dispatch on concrete type:

```100:102:nbs_viewer/views/dataSource/catalogSwitcher.py
        if isinstance(catalog, KafkaCatalog):
            return KafkaView(catalog, self.display_id)
        return CatalogTableView(catalog, self.display_id)
```

and `RunModel` duck-types async key loading with
`hasattr(self._run, "keys_ready")` (`runSource.py:65–68`). **A file-backed
offline catalog — already named as a wanted feature — cannot be added without
editing view code.**

Alongside this, `get_default_selection`, `get_md_value`, `getRunKeys`, and
`_resolve_dims` are each implemented two or three times across
`bluesky.py` / `kafka.py` / `memory.py` with divergent behavior. Memory picks
default keys by a different algorithm than the other two, so the same data
yields different default axes depending on backend.

### 6. ~~`PlotDataModel` owns matplotlib artists~~ ✅

**Closed by session-plan step B.** It was the only matplotlib import under
`models/` and it owned `self.artist` plus `set_artist`, `clear`,
`remove_artist_from_axes`, `add_artist_to_axes` and `move_artist_to_axes`,
with `set_visible(bool)` meaning `artist.set_visible`.

`Trace` now holds request identity, `last_bundle` and visibility intent only;
`MplCanvas` and `ImageGridCanvas` each own a `TraceKey` → artist map. A
headless plot frontend is unblocked, and a full `ensure_trace` →
`get_plot_bundle` → `set_visible` cycle is tested in an interpreter that never
imports matplotlib.

What did **not** close with it: `ImageGridCanvas` still constructs a `Trace`
directly (`image_grid_canvas.py`), so the ownership allowlist still has one
entry. The artist was never the reason — the bypass is the private
`(uid, image_idx)` fan-out map, which `intent.fan_out()` absorbs in
session-plan step C.

### 7. Domain policy still lives in views

- ~~**`DimensionControl`** builds and mutates the spec, then pushes it through
  `canvas.update_view_state`~~ — ✅ closed by view-pipeline step 6. It reads
  `session.driving_projection()` and sends gestures back; it holds no view
  state. `get_shape_info`'s policy half is `PlotSession.driving_axes`, and it
  now decides only which sliders are shown — the fetch path projects the
  session intent onto each key's own rank.
- **`MplCanvas._do_update_plot`** computes the x × y × run cartesian product
  that drives `ensure_trace` (`single_canvas.py:584–607`), and shows a
  `QMessageBox` for the 2-D multi-dataset rule (`:422–437`).
- **`ImageGridCanvas`** builds slice tuples in `_make_slice_info`
  (`:263–277`) and calls `figure.clear()` on every page change (`:333–342`).
- **`run_display.py:191–193`** sorts `"time"` to the front of the key list.
- **`views/catalog/base.py`** holds `ReverseModel` and `FilterModel`,
  including chunked lazy filtering (`:203–223`) — proxy logic in a view
  package.

### 8. No CI

The only workflow is `.github/workflows/python-publish.yml`, on release
publish. **Nothing runs the 247 fast tests on a PR.** The pending reorg
therefore has no automated safety net beyond running the suite locally.

Separately, `pytest>=9.0.3,<10` is listed in `[project] dependencies`, so end
users install the test runner. `.flake8` exists but is untracked and not
enforced.

---

## P3 — Compounding hygiene

### 9. Print and exception noise, concentrated in hot paths

132 raw `print()` calls and 100 broad `except Exception` / bare `except`, of
which 22 silently `pass`.

| File | `print(` | broad `except` | silent `pass` |
|------|---------:|---------------:|--------------:|
| `views/plot/mplCanvas/single_canvas.py` | 29 | 17 | 13 |
| `views/plot/metadataView.py` | — | 16 | 2 |
| `models/data/kafka.py` | 12 | — | — |
| `models/data/bluesky.py` | 10 | 8 | — |

The 13 silent passes in `single_canvas.py` are consecutive, in one
selector-teardown method (`:1139–1154`). `io/export_to_xdi.py` has two bare
`except:` (which also swallow `KeyboardInterrupt`). `utils.py`
`DEBUG_VARIABLES["PRINT_DEBUG"]` defaults to **`True`**.

The facility to fix this already exists — this is a sweep, not a design
problem.

### 10. Naming split and stale plan documents

28 camelCase filenames vs 64 snake_case, mixing inside single directories
(`plot_geometry.py` beside `plotModel.py`; `zarr_l2_cache.py` beside
`chunkCache.py`). The legacy camelCase data API (`getData`, `getShape`,
`getRunKeys`, `getAxis`) sits under snake_case plot code. The reorg plan
already covers filenames; the data-layer method names are a separate,
larger rename.

**The reorg plan is behind reality.**
[`plot_package_reorganization.md`](plot_package_reorganization.md) marks
slices 7a and 7d "Not started", but `views/plot/roi/` and
`views/plot/mplCanvas/` already exist, and `RoiController`, `RoiPanel`, and
`RoiPreviewController` are gone as separate modules. `views/plot/roi/` today
holds `window.py`, `types.py`, `overlays.py`, `preview_canvas.py`. That
matters because the document is the working checklist.

---

## Dead and near-dead code (inventory)

Removal is the cheapest available complexity reduction. Verified by
reachability, not by grep alone.

### Cache L1 dict path — ~330 lines, two dead roots

`chunkCache.py:34–35` states the dict L1 is "retained but unused on the hot
path." Reachability confirms it: `get_data` → `_get_data_l2_pipeline` calls
`_try_get_data_from_zarr`, `_try_get_data_partial_l2`,
`_read_tiled_hyperslab`, `_finish_slab_fetch`. It never calls
`_try_get_data_from_l2_tiles`, and `_finish_slab_fetch` seeds Zarr
(`_seed_zarr_from_slab`), not L1.

| Symbol | Lines | Only reached from |
|--------|------:|-------------------|
| `_try_get_data_from_l2_tiles` | 214–254 (41) | `test/test_catalog.py` (manual, not collected) |
| `_seed_l1_tiles_from_slab` | 1241–1329 (89) | `test/test_catalog.py` |
| `_store_tile` | 1331–1395 (65) | the two dead roots above |
| `_store_seeded_tile` | 1626–1653 (28) | `_seed_l1_tiles_from_slab` |
| `_evict_lru_l1_tile` | 1456–1469 (14) | `_store_tile`, `_store_seeded_tile` |
| `_update_l1_tile_access` | 1453–1454 (2) | dead roots |
| `_drop_partial_l1_tile` | 970–982 (13) | live path (`_commit_complete_l2_tile:968`) but a no-op once the set is always empty |
| `flush_l1_to_l2` | 2014–2065 (52) | `tests/test_chunk_cache.py:153` only — an **active** test |

Plus attributes `self.tiles`, `partial_l1_tiles`, `l1_tile_access_times`,
`l1_tile_size` and their bookkeeping in `clear`, `clear_run`, `get_stats`,
`format_debug_report` (~25 lines).

**Must be kept** — shared with live paths: `_extract_tile_from_slab` (also
called from `_materialize_l2_tile_from_slab:942`) and `_align_seed_slab`
(six live call sites).

**Correction to an earlier estimate:** this is ~330 lines, roughly 15% of the
file — not the ~800 lines first suggested.

### Zero-caller symbols

| Symbol | Location | Note |
|--------|----------|------|
| `_debug_plot_state` | `single_canvas.py:1633` | 111 lines, 29 prints, **no caller** |
| `_check_data_access` | `data/bluesky.py:88` | no caller; its absence causes the `_has_data=None` bug |
| `plot_data_removed` | `plotModel.py:80`, emitted `:615` | **zero** `.connect` sites in `nbs_viewer/` or `tests/` |
| `_initialize_runs` | `runListModel.py:68–73` | iterates `available_runs` from `__init__` when `_run_models` is `{}` |

### Commented-out and stub code

- `viewer.py:64–91` — a 28-line block of menu actions (Save Plot, Export
  Data, Print) commented out by wrapping in a bare `"""` string literal.
- `mainWidget.py:202–221` — three TODO stubs (`duplicate_current_display`,
  `save_display_layout`, `apply_display_settings`) whose bodies `print`
  "not implemented yet".
- `combinedRunModel.py:264` — `pass  # TODO: Implement, no concept of
  dynamic updates for combined runs`.
- Commented debug prints in `run_display.py`, `catalog/base.py`,
  `runListView.py`, `catalog/kafka.py`, `runSource.py:50`, `:838`,
  `runListModel.py:510`.

### Latent bug in the same territory

`RunListModel.dynamic_update` reads a property that does not exist:

```281:283:nbs_viewer/models/plot/runListModel.py
    def dynamic_update(self) -> bool:
        """..."""
        return all(model.dynamic_update for model in self._run_models.values())
```

`RunModel` defines `set_dynamic` and `_dynamic` but **no `dynamic_update`
property**. This works today only because `all()` over an empty dict is
`True`. `plot_settings.py:85` reads it at widget construction, so it raises
`AttributeError` the moment it is read with a run present.

### Near-duplicate API to collapse

- `RunListModel`: `add_run` / `add_runs`, `remove_run` / `remove_uids`,
  `set_run_visible` / `set_uids_visible`, camelCase `getHeaderLabel`.
- `PlotModel`: `selected_keys` (property, returns copies) vs
  `get_selected_keys()` (returns live internal lists).
- `views/dataSource/dataSource.py`: seven near-identical `*SourceView`
  subclasses.
- `_FakeRun` / `_FakeAccessor` copy-pasted across four cache test modules.
- Base caches `_plot_data_cache` and `_dimensions_cache` (`data/base.py:43–44`)
  are never read; every subclass keeps its own parallel caches.

---

## Why the package reorganization does not fix any of this

[`plot_package_reorganization.md`](plot_package_reorganization.md) is
explicitly and correctly scoped as behavior-preserving: "moves, import
updates, and file splits along existing seams — not feature work." Its own
"Remaining model–view leaks" section already inventories items 6 and 7 above
and defers them.

So the reorg is not wrong — it is **insufficient on its own**, and it should
not be widened. The plan in
[`structural_remediation_plan.md`](structural_remediation_plan.md) keeps each
mechanical slice narrow and pairs it with a small contract change at the seam
that slice has just opened, so the same code is not read twice.

## Non-goals for this document

- Proposing solutions or sequencing (see the remediation plan).
- Re-litigating closed ownership decisions (no feature-folder inversion, no
  non-Qt event bus, no top-level `models/roi/`).
- Auditing `widgets/` beyond noting `kafkaViewerTab.py` is stale — it remains
  an intentional embed surface (ownership rule 6).
- Performance work. Matplotlib full-redraw and `figure.clear()` smells are
  noted under item 7 as evidence of view/model tangling, not as a perf task.

## Modification log

| Date | Change |
|------|--------|
| 2026-09-02 | Initial problem statement from full-codebase audit |
| 2026-09-02 | Corrected dead L1 cache estimate from ~800 to ~330 lines after reachability check; recorded `_extract_tile_from_slab` / `_align_seed_slab` as live |
