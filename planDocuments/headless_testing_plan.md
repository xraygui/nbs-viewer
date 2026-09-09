# Headless testing infrastructure plan

Successor to the closed `model_ownership_headless_plan.md`, deleted
2026-09-08 and recoverable from `57f6d7b`.
The ownership refactor delivered an H1 model tree (`AppModel` → catalog /
presenter / plot). This plan turns that into **shared test infrastructure**
so unit and integration tests exercise real objects instead of duplicated
`MagicMock` catalog runs.

~~Related: `plot_package_reorganization.md` (mechanical moves; run after
Phase 1 fixtures land so imports stay stable).~~ That plan was absorbed into
[`refactor_plan.md`](refactor_plan.md) and deleted on 2026-09-08
(recoverable from `57f6d7b`); the folder splits it proposed are cancelled.


> **Naming note (2026-09-08).** Refactor step A (`5330b81`) renamed
> `PlotModel` → `PlotSession`, `RunListModel` → `RunListItemModel` and
> `RunModel` → `RunSource`, dropped `presenter.plot` in favour of
> `presenter.session`, and moved the item model to `views/` where
> `RunListView` constructs it — so `PlotPresenter.run_list` no longer
> exists. Names below are updated. Row D6 previously described cache
> status arriving via `PlotPresenter.run_list`; the real path is
> `PlotSession.cache_status_changed` → `PlotPresenter.status_changed`.
> `_StubRunModel`, `CombinedRunModel` and `FrozenRunModel` appear in older
> rows; none of the three exists in the tree and they predate this refactor.

## Status


| Phase | Title                                                     | Status                                  |
| ----- | --------------------------------------------------------- | --------------------------------------- |
| 0     | `oldtests/` quarantine + promote H0 files one-by-one      | Done (H0 + cache promoted; H2 deferred) |
| 1     | Shared fixtures (`conftest.py` + catalog recipes)         | Done                                    |
| 2     | Promote H1 files one-by-one (fixture-backed where needed) | Done                                    |
| 3     | Subsystem wiring tests + ownership AST guard              | Not started                             |
| 4     | Suite hygiene (H2/scripts, CI, README)                    | Not started                             |


## Goals

1. **One headless session primitive** — `AppModel` + in-memory catalog is the
  default way to get a plot session in tests.
2. **Fewer mocks** — replace copy-pasted `_mock_catalog_run` helpers with real
  `MemoryRun` / `MemoryCatalog` data where behavior matters.
3. **Clear test tiers** — H0 (pure numpy), H1 (QObject models, no widgets),
  H2 (Qt widgets / manual scripts); each tier has a place and conventions.
4. **Connection coverage** — every Qt signal edge between subsystems has at
  least one integration test that exercises the **wired path** (not direct
  `add_run` shortcuts). Tracked in the [connection matrix](#connection-coverage-matrix).
5. **Ownership regression guard** — AST inventory from ownership Step 0, folded
  into this plan (Phase 3).

## Non-goals

- Replacing H0 geometry / materialize / cache tests that correctly use raw
arrays or small stubs.
- pytest-qt / full GUI automation (optional later in Phase 4).
- Live Tiled / Kafka tests in CI (keep under `test/` as manual scripts).
- Implementing Step 6c (image grid) or Step 8 (export frontend) — tests may
stub those until product work lands.

---

## Current test landscape (inventory)

### Layout


| Location    | Role                                                         |
| ----------- | ------------------------------------------------------------ |
| `tests/`    | **Active** pytest suite — only promoted, passing tests       |
| `oldtests/` | Quarantine — full legacy suite while we promote file-by-file |
| `test/`     | Manual / IPython scripts (unchanged; not pytest CI)          |


Legacy issues (now in `oldtests/` until promoted or dropped):


| File                             | Issue                                |
| -------------------------------- | ------------------------------------ |
| `test_integration.py`            | Misnamed GUI script, not integration |
| `test_imagegrid_debug.py`        | Live Tiled; network                  |
| `test_plot_dimension_control.py` | Empty placeholder                    |


### Test tiers (approximate)

**H0 — pure logic (~15 files, no Qt required)**

Examples: `test_cube_view.py`, `test_plot_geometry.py`, `test_materialize_view.py`,
`test_region.py`, `test_region_mesh.py`, `test_view_crop.py`,
`test_derived_fetch.py`, `test_hyperslab_batches.py`, `test_fetch_slice_info.py`.

These should **stay** as focused unit tests. Stubs like `_StubRunModel` in
`test_derived_fetch.py` are appropriate when testing fetch/materialize in
isolation.

**H1 — QObject models, no widgets (~12 files)**

Examples: `test_plot_model.py`, `test_plot_model_step3.py`,
`test_roi_preview_commit.py`, `test_run_list_combine_freeze.py`,
`test_plot_presenter.py`, `test_catalog_`*, `test_source_palette.py`,
`test_roi_set.py`, `test_frozen_spectrum.py`, `test_run_list_cache_status.py`.

This is the main migration target: many files still build `RunSource(MagicMock())`
even though `create_runs()` / `MemoryRun` already exist in
`models/sources/testSource.py`.

**H2 — Qt widgets / manual (~4 files)**

Examples: `test_expression_ui.py`, `test_filter_lazy_loading.py`,
`test_log_colormap.py`, `test_integration.py`.

Keep separate; do not block H1 fixture work.

**Cache / L2 (~7 files)**

Examples: `test_chunk_cache.py`, `test_zarr_l2_cache.py`,
`test_l2_materialize_batch.py`, etc.

Mostly self-contained; may later use `MemoryRun` for array sources but not
priority for Phase 1.

### Fixture usage today


| Primitive                                    | Used in                                | Notes                               |
| -------------------------------------------- | -------------------------------------- | ----------------------------------- |
| `create_runs()` / `TestSourceModel`          | 4 test files                           | Canonical in-memory path; underused |
| `MemoryCatalog` directly                     | 3 test files                           | Table ownership tests               |
| `AppModel`                                   | 1 test file (`test_plot_presenter.py`) | Light coverage                      |
| `_mock_catalog_run` (duplicated)             | 4 files                                | ~20 lines each, nearly identical    |
| `MagicMock` run / `last_bundle` injection    | ROI, crop, frozen spectrum tests       | Bypasses real fetch                 |
| Live Tiled (`test/`, `test_imagegrid_debug`) | Manual only                            | Out of CI scope                     |


### Duplication to eliminate

The same `_mock_catalog_run` / `_make_run_model` pattern appears in:

- `tests/test_plot_model_step3.py`
- `tests/test_run_list_combine_freeze.py`
- `tests/test_roi_preview_commit.py` (variant with 2D keys)
- `tests/test_frozen_spectrum.py` (`_mock_run`)

Ownership AST checks are also duplicated:

- `test_roi_preview_commit.py` — no `FrozenSpectrum(` in views
- `test_run_list_combine_freeze.py` — no `CombinedRunModel(` / `FrozenRunModel(`

---

## Target architecture

### Headless session (conceptual)

```text
QApplication, offscreen (session-scoped autouse pytest fixture)
    └── AppModel
          ├── CatalogManagerModel
          │     └── MemoryCatalog  (via TestSourceModel.load / load_and_register)
          └── DisplayManager
                └── PlotPresenter ("main")
                      ├── RunListItemModel
                      └── PlotSession
```

Tests that only need a plot session can use a lighter shortcut:

```text
PlotPresenter("main") + add_run(MemoryRun)   # skips catalog wiring
```

Use the full `AppModel` path when testing catalog selection signals, multi-run
registry, or `active_display` routing.

### Target layout

```text
tests/                     # active suite (grows file-by-file)
  conftest.py              # Phase 1
  fixtures/
    catalog_recipes.py
    session.py
  test_cube_view.py        # promoted H0 (copy from oldtests/, verify)
  test_headless_e2e.py     # Phase 3 (new)
  test_model_ownership.py  # Phase 3 (new)
  ...

oldtests/                  # legacy quarantine (shrinks as files promote)
  test_plot_model_step3.py
  ...

test/                      # manual scripts only (unchanged)
```

Keep `models/sources/testSource.py` as the **production** factory for test
catalogs; `tests/fixtures/catalog_recipes.py` extends it with named recipes
for test-specific shapes (1D line, 2D image, multi-run combine, etc.).

### Catalog recipes (extend `create_runs`)

Today `create_data()` yields 1D keys (`time`, `x`, `y`) plus a 2D `image`
(100×32). Tests that need ROI / cube paths use mocks for `en_energy` /
`detector_image` instead.

Add named recipes, e.g.:


| Recipe         | Keys / shape                                      | Use cases                         |
| -------------- | ------------------------------------------------- | --------------------------------- |
| `line_scan`    | `time`, `y` (1D)                                  | combine/freeze, default keys      |
| `motor_scan`   | `time`, `motor`, `det` (1D)                       | key intersection, x selection     |
| `image_scan`   | `en_energy`, `pixel`, `detector_image` (2D 30×40) | ROI preview/commit, crop, cube 2D |
| `multi_run(n)` | n × `line_scan`                                   | catalog table, selection          |


Recipes return `MemoryRun` lists or a `MemoryCatalog`; they do not require
`AppModel` until the test needs catalog signals.

### `HeadlessSession` helper (optional thin wrapper)

A small class or pytest fixture bundle that exposes:

- `app: AppModel`
- `catalog: MemoryCatalog`
- `presenter: PlotPresenter`
- `session: PlotSession`
- `run_list: RunListItemModel` (built by `RunListView`)

Methods:

- `load_test_catalog(recipe="line_scan", runs=3) -> str` (label)
- `select_run(index=0) -> RunSource` (via `catalog.select_run` + signal path)
- `select_run_direct(run)` (bypass catalog — for plot-only tests)
- `fetch_bundle(x_keys, y_keys) -> PlotBundle` (wraps `ensure_plot_data` +
`get_plot_bundle`)

Implementation should prefer **public model APIs** only (no private attrs
except where tests already rely on them and a public accessor is a separate
cleanup).

---

## Phased work

### Phase 0 — `oldtests/` quarantine + promote H0 files

**Strategy:** move the entire current `tests/` tree to `oldtests/` in one PR.
`tests/` starts empty (or with a `README.md` only). Promote files back
**one at a time**: copy from `oldtests/` → `tests/`, run
`pytest tests/<file>`, fix if needed, commit. Delete from `oldtests/` when
promoted (or leave until batch cleanup — prefer delete-on-promote so
`oldtests/` only holds backlog).

**Depends on:** nothing

**Do**

- [x] `git mv tests/ oldtests/` (preserve history); recreate empty `tests/`
- [x] Add `tests/README.md` — how to promote; `pytest tests/` = active suite
- [x] Configure pytest `testpaths = ["tests"]` in `pyproject.toml`
- [ ] Promote **H0 — promote as-is** (one PR per file or small batches):


| Order | File                            | Notes                |
| ----- | ------------------------------- | -------------------- |
| 1     | `test_cube_view.py`             | Done                 |
| 2     | `test_plot_geometry.py`         |                      |
| 3     | `test_materialize_view.py`      |                      |
| 4     | `test_region.py`                |                      |
| 5     | `test_region_mesh.py`           |                      |
| 6     | `test_view_crop.py`             |                      |
| 7     | `test_view_crop_orientation.py` |                      |
| 8     | `test_derived_fetch.py`         | Keep `_StubRunModel` |
| 9     | `test_fetch_slice_info.py`      |                      |
| 10    | `test_hyperslab_batches.py`     |                      |


- [ ] Promote **cache / L2** (still H0-ish; may need temp dirs):


| Order | File                           |
| ----- | ------------------------------ |
| 11    | `test_chunk_cache.py`          |
| 12    | `test_chunk_cache_progress.py` |
| 13    | `test_chunk_cache_l2.py`       |
| 14    | `test_l2_chunks_for_shape.py`  |
| 15    | `test_l2_seed_from_slab.py`    |
| 16    | `test_l2_materialize_batch.py` |
| 17    | `test_zarr_l2_cache.py`        |


**Defer in `oldtests/` (do not promote in Phase 0)**


| File                             | Disposition                              |
| -------------------------------- | ---------------------------------------- |
| `test_plot_dimension_control.py` | Drop (empty) or implement in Phase 4     |
| `test_integration.py`            | Move to `test/` or `scripts/` in Phase 4 |
| `test_imagegrid_debug.py`        | Move to `test/` in Phase 4               |
| `test_expression_ui.py`          | Phase 4 (H2)                             |
| `test_filter_lazy_loading.py`    | Phase 4 (H2)                             |
| `test_log_colormap.py`           | Phase 4 (H2)                             |
| All H1 files                     | Phase 2 (after fixtures)                 |


**Per-file promote checklist**

1. Copy `oldtests/test_foo.py` → `tests/test_foo.py`
2. `pytest tests/test_foo.py -v`
3. Commit: `tests: promote test_foo from oldtests`
4. Remove `oldtests/test_foo.py`

**Exit criteria**

- [ ] All H0 + cache files promoted; `pytest tests/` green
- [ ] `oldtests/` contains only H1 backlog + deferred H2/scripts
- [ ] `pytest oldtests/` is **not** part of default test run

### Phase 1 — Shared fixtures

**Depends on:** Phase 0 H0 promotion underway (can land after first few H0
files prove the promote workflow)

**Do**

- [x] Add `tests/conftest.py` with session-scoped `qapp` — now an autouse
  `QApplication` on the offscreen platform (`9a567db`), which is what makes
  phases 3–4 reachable at all
- [x] Add `app_model` fixture (fresh `AppModel` per test)
- [x] Add `headless_session` fixture (loads default test catalog, returns helper)
- [x] Add `tests/fixtures/catalog_recipes.py` with `line_scan`, `image_scan`, etc.
- [x] Extend or wrap `create_runs` so recipes are configurable (keys, shapes,
  ```
  metadata hints for N-D cube roles)
  ```
- [x] Smoke test: `tests/test_fixtures_smoke.py`

**Exit criteria**

- [x] `image_scan` recipe → `RunSource.get_plot_bundle` works for 2D without
  ```
  manual `last_bundle` injection
  ```

### Phase 2 — Promote H1 files one-by-one

**Depends on:** Phase 1 fixtures

Promote from `oldtests/` using the same copy → pytest → commit workflow.
**Refactor to fixtures while promoting** (not before). Priority order:


| Order | File                              | Fixture work on promote                    |
| ----- | --------------------------------- | ------------------------------------------ |
| 1     | `test_roi_set.py`                 | None (geometry only)                       |
| 2     | `test_plot_model.py`              | Optional `qapp`; keep `MagicMock` for crop |
| 3     | `test_catalog_table_ownership.py` | `create_runs` already                      |
| 4     | `test_catalog_manager_sources.py` | `qapp` for signals                         |
| 5     | `test_source_palette.py`          | `qapp`                                     |
| 6     | `test_plot_presenter.py`          | `app_model` fixture                        |
| 7     | `test_run_list_cache_status.py`   | `PlotPresenter` + real runs                |
| 8     | `test_run_list_combine_freeze.py` | Replace `_mock_catalog_run` → `line_scan`  |
| 9     | `test_plot_model_step3.py`        | `line_scan` / `image_scan` recipes         |
| 10    | `test_roi_preview_commit.py`      | `image_scan` + real `get_plot_bundle`      |
| 11    | `test_frozen_spectrum.py`         | Real `RunSource` where keys matter          |


**Exit criteria**

- [x] `oldtests/` empty or H2-only
- [x] No duplicated `_mock_catalog_run` in `tests/`
- [x] `pytest tests/` green

---

## Coverage assessment (pre–Phase 3)

Snapshot after Phase 2: **233 tests** in `tests/` (17 H0/cache files, 11 H1
files, 1 fixtures smoke file). `oldtests/` holds H2/deferred scripts only.

### What the suite covers today

Tests are organized by **layer**, not by user workflow. Most files exercise one
model or algorithm in isolation with direct construction (`PlotSession`,
`RunListItemModel`, `MemoryCatalog`) rather than the full `AppModel` tree.


| Layer / concern | Files | What is proven |
| --------------- | ----- | -------------- |
| **H0 — cube / materialize / geometry** | `test_cube_view`, `test_materialize_view`, `test_plot_geometry`, `test_region`, `test_region_mesh`, `test_view_crop`, `test_view_crop_orientation`, `test_derived_fetch`, `test_fetch_slice_info` (~83 tests) | `CubeViewSpec`, `materialize_view`, ROI geometry, crop math, bundle preparation — all without Qt session wiring |
| **H0 — cache / L2** | `test_chunk_cache*`, `test_l2_*`, `test_zarr_l2_cache`, `test_hyperslab_batches` (~65 tests) | Tile assembly, L1/L2 seeding, progress labels, batched hyperslab reads — stub transports / temp zarr |
| **H1 — catalog registry** | `test_catalog_table_ownership`, `test_catalog_manager_sources`, `test_source_palette` (18 tests) | `MemoryCatalog` table ownership; `CatalogManagerModel` source factories, `load` / `load_and_register`, palette signals — **on `CatalogManagerModel` only**, not wired through `AppModel` |
| **H1 — presenter shell** | `test_plot_presenter`, `test_run_list_cache_status` (10 tests) | `DisplayManager` / `PlotPresenter` ownership; `add_run_to_display` adds a run — **bypasses catalog `item_selected` → `AppModel` path**; cache status uses `SimpleNamespace` fakes |
| **H1 — plot session** | `test_plot_model`, `test_plot_model_step3`, `test_roi_set` (23 tests) | `PlotSession` owns `RoiSetModel`; plot-data map lifecycle; visibility / crop invalidation — built with ad-hoc `RunListItemModel` + `MemoryRun`, not `HeadlessSession` |
| **H1 — run list factories** | `test_run_list_combine_freeze`, `test_frozen_spectrum` (25 tests) | `combine_runs` / `freeze_runs` validation; synthetic spectrum fetch/transform — `RunListItemModel` / `RunSource` in isolation |
| **H1 — ROI APIs** | `test_roi_preview_commit` (5 tests) | `preview_roi_profile` / `commit_roi_profile` on real `image_scan` data — ad-hoc `PlotSession` setup, not catalog-selected runs |
| **Fixtures smoke** | `test_fixtures_smoke` (4 tests) | Recipe shapes; **`HeadlessSession.select_run` → run list**; 1D + 2D `fetch_bundle` through `AppModel` + `register_catalog` |

### Signal paths exercised (and gaps)

```text
Intended production path:

  TestSourceModel.load()
      → CatalogManagerModel.register_catalog()
          → catalog.item_selected
              → CatalogManagerModel.run_selected
                  → AppModel._on_run_selected
                      → DisplayManager.add_run_to_display(active_display)
                          → PlotPresenter.session

Shortcut paths used by most H1 unit tests (skip catalog signals):

  create_runs() / image_scan_run() → RunSource → RunListItemModel.add_run()
  DisplayManager.add_run_to_display()          (test_plot_presenter only)
```

| Path segment | Covered? | Where |
| ------------ | -------- | ----- |
| `register_catalog` → `item_selected` wiring | Yes | `test_fixtures_smoke::test_headless_session_catalog_signal_path` |
| `select_run` → run appears on presenter | Yes | smoke + above |
| `fetch_bundle` 1D (`line_scan`) | Yes | smoke |
| `fetch_bundle` 2D (`image_scan`) | Yes | smoke |
| `TestSourceModel.load_and_register` through **`AppModel.catalogs`** | **No** | `test_source_palette` uses bare `CatalogManagerModel` |
| Multi-run selection (2+ runs on run list) | **No** | — |
| `deselect_run` → run removed from presenter | **No** | — |
| `set_active_display` routing | **No** | — |
| Default key selection on plot after catalog select | **Partial** | `test_plot_model_step3::test_default_selection_on_first_run` uses ad-hoc path; not through `HeadlessSession` |
| Combine / freeze on catalog-selected runs | **No** | `test_run_list_combine_freeze` uses direct `add_runs` |
| ROI preview / commit on catalog-selected 2D run | **No** | `test_roi_preview_commit` uses ad-hoc `PlotSession` |
| `motor_scan` recipe | **No** | defined in `catalog_recipes.py`, unused |

### What `test_fixtures_smoke.py` already is

The smoke file validates **fixtures** and proves one wired edge (E06 + E12 +
E19 for a single run). It is not a substitute for systematic connection
coverage. Phase 3 adds **subsystem integration tests** that grow the matrix
one edge at a time.

**Keep in smoke (unchanged):** recipe shape assertions; single-run catalog
signal path; 1D/2D fetch sanity checks.

### Connection coverage matrix

Phase 3 success is defined by this ledger, not by a monolithic “E2E” file.
Each row is one **signal edge** (or direct causal link) between subsystems.
Unit tests prove *behavior inside* a subsystem; wiring tests prove the
*edge* using `AppModel` + `HeadlessSession` (or equivalent) so shortcuts like
`RunListItemModel.add_run()` are not used when the edge under test is
catalog → run list.

**Legend:** ✅ covered · ⚠ partial · ⬜ gap · 🔜 deferred

#### Catalog subsystem (`CatalogManagerModel`, sources, `MemoryCatalog`)


| ID | Connection | Status | Covered by |
| -- | ---------- | ------ | ---------- |
| C1 | `SourceModel.catalog_loaded` → `register_catalog` (via `add_source`) | ✅ | `test_catalog_wiring::test_source_load_registers_catalog_on_app_model` |
| C2 | `register_catalog` wires `catalog.item_selected` → manager | ✅ | `test_fixtures_smoke::test_headless_session_catalog_signal_path` |
| C3 | `register_catalog` wires `catalog.item_deselected` → manager | ✅ | `test_catalog_wiring::test_deselect_run_emits_catalog_and_manager_signals` |
| C4 | `CatalogManagerModel.run_selected` → `AppModel._on_run_selected` | ✅ | smoke + `test_catalog_wiring::test_source_load_then_select_wires_to_presenter` |
| C5 | `CatalogManagerModel.run_deselected` → `AppModel._on_run_deselected` | ✅ | `test_catalog_wiring::test_deselect_run_emits_catalog_and_manager_signals` |
| C6 | `catalog.select_run(uid)` emits `item_selected` | ✅ | smoke |
| C7 | `catalog.deselect_run(uid)` emits `item_deselected` | ✅ | `test_catalog_wiring::test_deselect_run_emits_catalog_and_manager_signals` |
| C8 | `TestSourceModel.load_and_register` on **`AppModel.catalogs`** | ✅ | `test_catalog_wiring::test_load_and_register_on_app_catalogs` |
| C9 | Multi-run selection accumulates UIDs in catalog + run list | ✅ | `test_catalog_wiring::test_multi_run_selection_accumulates_on_run_list` |

#### Display / presenter subsystem (`AppModel`, `DisplayManager`, `PlotPresenter`)


| ID | Connection | Status | Covered by |
| -- | ---------- | ------ | ---------- |
| D1 | `_on_run_selected` → `DisplayManager.add_run_to_display(active_display)` | ✅ | smoke |
| D2 | `_on_run_deselected` → `DisplayManager.remove_run_from_display` | ✅ | `test_catalog_wiring::test_deselect_run_removes_run_from_presenter_run_list` |
| D3 | `add_run_to_display` → `RunListItemModel` gains `RunSource` for run uid | ✅ | smoke + `test_catalog_wiring::test_source_load_then_select_wires_to_presenter` |
| D4 | `remove_run_from_display` → run list loses run | ✅ | `test_catalog_wiring::test_deselect_run_removes_run_from_presenter_run_list` |
| D5 | `set_active_display` routes selection to non-`main` presenter | 🔜 | deferred (6c / multi-view) |
| D6 | `PlotSession.cache_status_changed` → `PlotPresenter.status_changed` | ✅ | `test_run_list_cache_status` — direct emit, not full chain |

#### Run list subsystem (`RunListItemModel` factories on **wired** runs)


| ID | Connection | Status | Covered by |
| -- | ---------- | ------ | ---------- |
| R1 | `RunListItemModel.run_added` → `PlotSession._on_run_added` (keys/transform) | ⚠ | `test_plot_model_step3::test_default_selection_on_first_run` — ad-hoc `add_run`, not catalog |
| R2 | `RunListItemModel.run_removed` → `PlotSession._on_run_removed` (drop plot data) | ⚠ | `test_plot_model_step3::test_remove_run_drops_plot_data` — ad-hoc |
| R3 | `RunListItemModel.visible_runs_changed` → plot data ensure | ⚠ | `test_plot_model_step3` — ad-hoc |
| R4 | `combine_runs` on catalog-selected `RunSource`s | ✅ | `test_run_list_wiring::test_combine_runs_on_catalog_selected_runs` |
| R5 | `freeze_runs` on catalog-selected `RunSource`s | ✅ | `test_run_list_wiring::test_freeze_runs_on_catalog_selected_runs` |
| R6 | `RunSource.frozen_spectra_changed` → run list key refresh | ✅ | `test_run_list_wiring::test_frozen_spectra_changed_refreshes_run_list` |

#### Plot subsystem (`PlotSession`, `PlotDataModel`, fetch)


| ID | Connection | Status | Covered by |
| -- | ---------- | ------ | ---------- |
| P1 | Default X/Y keys on plot after first catalog select | ⚠ | unit only (R1) |
| P2 | `fetch_bundle` 1D on catalog-selected run | ✅ | smoke |
| P3 | `fetch_bundle` 2D on catalog-selected run | ✅ | smoke (`test_image_scan_get_plot_bundle_without_injected_bundle`) |
| P4 | `ensure_plot_data` created when run becomes visible with keys set | ⚠ | unit only |
| P5 | Key intersection updates when second catalog run selected | ⬜ | — |

#### ROI subsystem (`PlotSession` ROI APIs on **wired** 2D session)


| ID | Connection | Status | Covered by |
| -- | ---------- | ------ | ---------- |
| I1 | `preview_roi_profile` on catalog-selected `image_scan` run | ✅ | `test_roi_wiring::test_preview_roi_profile_on_catalog_selected_run` |
| I2 | `commit_roi_profile` → `RunSource.register_frozen_spectrum` | ✅ | `test_roi_wiring::test_commit_roi_profile_registers_frozen_spectrum` |
| I3 | Committed synthetic key fetchable via `fetch_bundle` after commit | ✅ | `test_roi_wiring::test_committed_synthetic_key_fetchable_via_fetch_bundle` |
| I4 | ROI stale / local-profile rejection on wired session | ✅ | `test_roi_wiring::test_preview_rejects_stale_roi_on_wired_session`, `test_commit_rejects_local_profile_on_wired_session` |

**Coverage rule:** when implementing a wiring test, enter through the
subsystem on the **left** of the arrow (e.g. for R4, runs must reach
`RunListItemModel` via C6 → C4 → D1 → D3, not `add_run`).

### Phase 3 test files (by subsystem)

New integration tests — one file per subsystem, grow incrementally. Each PR
can close one or more matrix rows; the matrix is the checklist.


| File | Subsystem | Initial rows to close |
| ---- | --------- | --------------------- |
| `tests/test_catalog_wiring.py` | Catalog + display entry | C1, C3, C5, C7, C8, C9 |
| `tests/test_run_list_wiring.py` | Run list factories on wired runs | R4, R5, R6 |
| `tests/test_plot_wiring.py` | Plot session after catalog select | R1, P1, P4, P5 (re-test via wired path) |
| `tests/test_roi_wiring.py` | ROI on wired 2D session | I1–I4 |
| `tests/test_model_ownership.py` | View construction guard | (AST; separate concern) |

`test_fixtures_smoke.py` stays as fast fixture validation — do not move
matrix rows back into smoke except when a row is already marked ✅ there.

**Not in scope for wiring tests** (covered by H0/H1 unit tests):

- Cube/materialize math, cache/L2, region mesh geometry, view crop transforms
- Combine *validation* edge cases, frozen spectrum fetch edge cases
- Qt widgets / canvas (`oldtests/` H2 backlog)

### Ownership guard — current state vs Phase 3

Three promoted H1 files embed **inline AST scans** (duplicated logic, different
allowlists):


| File | Classes scanned | Allowlist |
| ---- | --------------- | --------- |
| `test_run_list_combine_freeze.py` | `CombinedRunModel`, `FrozenRunModel` | none (must be empty) |
| `test_plot_model_step3.py` | `PlotDataModel` | `image_grid_canvas.py` only |
| `test_roi_preview_commit.py` | `FrozenSpectrum` | none (must be empty) |

A repo scan today finds **one** real violation: `PlotDataModel(` in
`views/plot/mplCanvas/image_grid_canvas.py` (Step 6c deferred). No
`CombinedRunModel`, `FrozenRunModel`, `FrozenSpectrum`, or `RoiSetModel`
construction in `views/`.

Phase 3 `test_model_ownership.py` should:

1. Consolidate the three inline scans into one test with `EXPECTED_VIOLATIONS`
   seeded to the image-grid hit only.
2. Remove the inline AST helpers from the three H1 files.
3. Use the ownership plan’s constructor-call detection (resolve import aliases;
   ignore type annotations).

### Phase 3 — Subsystem wiring tests + ownership guard

**Depends on:** Phase 2

**Strategy:** implement wiring tests **by subsystem**, one file per area.
Each test closes specific rows in the [connection matrix](#connection-coverage-matrix).
PRs can land incrementally (e.g. catalog deselect first, then combine/freeze,
then ROI). Exit when all non-deferred matrix rows are ✅.

**Do**

- [x] Add `tests/test_catalog_wiring.py` — close C1, C3, C5, C7, C8, C9, D2, D4
- [x] Add `tests/test_run_list_wiring.py` — close R4, R5, R6
- [ ] Add `tests/test_plot_wiring.py` — close R1, P1, P4, P5 via wired path
- [x] Add `tests/test_roi_wiring.py` — close I1–I4
- [ ] Add `tests/test_model_ownership.py` (AST guard; `EXPECTED_VIOLATIONS`
  seeded with image-grid `PlotDataModel` only — see
  [Ownership guard](#ownership-guard--current-state-vs-phase-3))
- [ ] Remove inline AST scans from `test_run_list_combine_freeze.py`,
  `test_plot_model_step3.py`, and `test_roi_preview_commit.py`
- [ ] Update connection matrix statuses in this doc as rows close

**Exit criteria**

- [ ] All matrix rows ✅ or 🔜 deferred; no ⬜ gaps except deferred D5
- [ ] Ownership test passes with known violation set
- [ ] No inline AST ownership scans remain in H1 unit files

### Phase 4 — Suite hygiene

**Depends on:** Phase 3

**Do**

- [ ] Relocate deferred H2/scripts from `oldtests/` to `test/` or `scripts/`
- [ ] Delete empty `test_plot_dimension_control.py` or implement
- [ ] `tests/README.md` complete (tiers, fixtures, promote workflow)
- [ ] Optional: pytest markers; GitHub Actions `pytest tests/`

**Exit criteria**

- [ ] Remove `oldtests/` directory entirely
- [ ] `pytest tests/` is the single CI entry point

---

## How headless models simplify testing


| Before                                    | After                                                |
| ----------------------------------------- | ---------------------------------------------------- |
| 20-line `MagicMock` per file              | `headless_session.select_run(0)`                     |
| Inject `plot_data.last_bundle` manually   | `get_plot_bundle()` from real `MemoryRun` data       |
| Build `RunListItemModel` + `PlotSession` ad hoc | `presenter.session` from fixture                        |
| Test catalog and plot in isolation        | Same session object for both                         |
| Unclear whether signal wiring works       | Connection matrix + subsystem wiring tests |


**What does not simplify (and should not be forced)**

- Pure numpy cube/materialize tests — keep array-only setup
- Chunk cache correctness — needs cache-specific fixtures or zarr temps
- GUI expression builder — stays H2 with `QApplication`

---

## Decision log


| Date       | Decision                                                                                               |
| ---------- | ------------------------------------------------------------------------------------------------------ |
| 2026-09-01 | Close ownership plan; this document owns E2E + fixture work                                            |
| 2026-09-01 | `AppModel` + `MemoryCatalog` as default test entry, not raw `PlotPresenter`, when catalog path matters |
| 2026-09-01 | `PlotPresenter`-only shortcut remains valid for plot-unit tests                                        |
| 2026-09-01 | Ownership AST guard is Phase 3, not a blocker for fixtures                                             |
| 2026-09-01 | `test/` manual scripts stay; not merged into `tests/`                                                  |
| 2026-09-01 | Phase 0: quarantine all legacy tests in `oldtests/`; promote H0 one-by-one before fixtures             |
| 2026-09-02 | Test by subsystem; every signal edge tracked in connection matrix; incremental PRs |


---

## PR graph

```text
Phase 0  git mv tests → oldtests; promote H0/cache files one-by-one
  → Phase 1  conftest + catalog recipes
    → Phase 2  promote H1 files one-by-one (fixture refactor each)
      → Phase 3  subsystem wiring tests + connection matrix + test_model_ownership
        → Phase 4  H2/scripts cleanup; delete oldtests/
```

~~Plot package reorg can run in parallel after Phase 0.~~ Cancelled with
`plot_package_reorganization.md`; see the note at the top of this file.

## Modification log


| Date       | Change                                                                        |
| ---------- | ----------------------------------------------------------------------------- |
| 2026-09-01 | Initial plan from ownership closure + test suite inventory                    |
| 2026-09-01 | Restructure: `oldtests/` quarantine + promote workflow; H0 before fixtures    |
| 2026-09-01 | Phase 2 done: all 11 H1 files promoted; `_mock_catalog_run` removed from active suite |
| 2026-09-02 | `test_catalog_wiring.py`: C1–C9 (catalog) + D2/D4 (deselect) matrix rows closed |
| 2026-09-02 | `test_run_list_wiring.py`: R4–R6 matrix rows closed |
| 2026-09-02 | `test_roi_wiring.py`: I1–I4 matrix rows closed |
| 2026-09-01 | Pre–Phase 3 coverage assessment: wiring gaps catalogued in connection matrix |


