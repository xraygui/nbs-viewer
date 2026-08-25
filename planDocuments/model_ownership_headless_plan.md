# Model ownership and headless readiness plan

Path B refactor: keep domain code under `models/`, enforce **only models create
domain models**, and make the viewer runnable as a model tree without views
(headless H1).

Related context: ROI workbench and materialize plans under `planDocuments/`;
cache extraction (`models/cache/`) is the organizational precedent for later
folder moves.

## Status

| Step | Title | Status |
|------|-------|--------|
| 0 | Baseline and guardrails | Skipped (optional later) |
| 1 | Introduce `PlotModel`; own `RoiSetModel` | Done |
| 2 | Combine / freeze factories on `RunListModel` | Done |
| 3 | Expand `PlotModel`: plot data + key/policy move | Done |
| 4 | ROI preview + commit as model APIs | Done |
| 5 | Catalog table + source models | Not started |
| 6 | Display registry / no `QtWidgets` in models | Not started |
| 7 | Organize under `models/` (mechanical) | Not started |
| 8 | Slim views / canvas (optional polish) | Not started |

**Milestones**

- [x] **A** (after steps 1–4): ROI headless path
- [ ] **B** (after steps 5–6): Catalog → display → plot headless path
- [ ] **C** (steps 7–8): Navigable tree + thin views

## Rules of the road

1. **Only models create domain models.** Views may create Qt proxies / item
   models used purely as view adapters (`ReverseModel`, `FilterModel`,
   metadata `QStandardItemModel`, etc.).
2. **A view that needs a new model asks the model it already holds**
   (e.g. `run_list.roi_set`, `run_list.ensure_plot_data(...)`).
3. **Stay under `models/`** for domain code. Folder splits (`models/roi/`, …)
   come in step 7 after ownership is fixed.
4. **Each step ships with tests** in the same PR when practical. GUI smoke is
   optional until later steps.
5. Do **not** invert the package tree to `feature/{models,views}` unless we
   revisit this plan. Relative imports within `models/` are preferred.
6. **`widgets/` is out of scope for this plan.** It holds self-contained,
   embeddable views meant to be imported by external programs (e.g. via
   entry points) to reuse nbs-viewer functionality. Today that is
   `kafkaViewerTab.py`; more may be added later. Leave `widgets/` alone —
   do not refactor it into `views/`, do not treat it as an internal grab-bag
   to empty, and do not block steps on cleaning model construction there.
   Ownership rules still apply to the main app under `views/` + `models/`.

### Target ownership tree

```text
AppModel
└── DisplayManager
    └── per display (default 1:1 today; N plots per run list later):
          RunListModel              # run membership + visibility + key universe
          PlotModel                 # one plot session bound to a RunListModel
              ├── selected keys, transform, auto_add / retain (plot policy)
              ├── PlotDataModel map                 # step 3
              ├── RoiSetModel                       # step 1 (on PlotModel, not RunList)
              └── view state (cube_view_spec, slice, view_crop)
└── CatalogManagerModel
    └── Source / Catalog
        └── CatalogTableModel                       # step 5
```

**`RunListModel` is for:** collecting runs, which runs are checked/visible,
and the **intersection of catalog keys** among visible runs (the key universe
a plot may choose from). It is **not** the home for artists, ROI geometry,
cube/crop view state, or (eventually) which x/y keys a particular plot uses.

**`PlotModel` is for:** one plot session’s selection and products — selected
keys, `PlotDataModel` instances, ROI set, cube/crop, transform/auto-add
policy. It holds a reference to a `RunListModel` and reacts to that list’s
membership/visibility signals.

Default wiring stays 1:1 (`DisplayManager` creates both together) so today’s
UI does not need multi-plot sharing yet. The split still matters so Step 3
does not cement the wrong parent.

See **“Run list vs plot session”** below for add/remove behavior and
alternatives considered.

### Headless tiers

| Tier | Meaning | Target |
|------|---------|--------|
| H0 | Pure numpy / dataclasses; no Qt | Already largely true for region / materialize / cache |
| H1 | `QObject` / `Signal` models; **no** `QtWidgets` | Steps 1–6 |
| H2 | Full GUI | Existing app; optional qtbot coverage in step 8 |

### Domain-model allowlist (views must not construct)

Update this list if new domain types appear.

- `RoiSetModel`
- `PlotModel`
- `PlotDataModel`
- `RunListModel`
- `RunModel`
- `CombinedRunModel`
- `FrozenRunModel`
- `FrozenSpectrum`
- `CatalogTableModel`
- `ConfigSourceModel`, `URISourceModel`, `ProfileSourceModel`, `KafkaSourceModel`, `ZMQSourceModel`
- `BlueskyCatalog`, `NBSCatalog`, `KafkaCatalog` (and peers)
- `AppModel`, `DisplayManager`, `ChunkCache` (unless explicitly delegated)

Known violations at plan start (inventory baseline for step 0):

| Location | Creates |
|----------|---------|
| `views/plot/imageGridWidget.py` | `PlotDataModel` (temporary exception) |
| `views/catalog/base.py` | `CatalogTableModel` |
| `views/dataSource/dataSource.py` | `*SourceModel` |

Cleared in earlier steps: `RoiSetModel` (Step 1), `CombinedRunModel` /
`FrozenRunModel` (Step 2), `PlotDataModel` in canvas (Step 3; ImageGrid
deferred), `FrozenSpectrum` in views (Step 4).

`widgets/kafkaViewerTab.py` also constructs `RunListModel` / `KafkaCatalog`, but
that package is an intentional external embed surface — **leave alone** (see
rule 6). Do not list it as a violation to clear in steps 0–8.

### Run list vs plot session

`RunListModel` today mixes run-collection concerns with plot-session concerns
(key selection, transform, auto-add, and — in the canvas — `PlotDataModel`
creation). That conflation was reasonable when each display had exactly one
plot. It blocks headless clarity and blocks “several plots sharing one run
list.”

#### Recommended split

| Concern | Owner |
|---------|--------|
| Add/remove/combine/freeze runs | `RunListModel` |
| Run checked / visible for plotting | `RunListModel` |
| Auto-add (check newly added runs) | `RunListModel` |
| Intersection of catalog keys (available key universe) | `RunListModel` (derived from visible runs) |
| Selected x / y / norm keys (incl. default selection) | `PlotModel` |
| Transform, retain-selection | `PlotModel` |
| `PlotDataModel` map (`ensure_plot_data`) | `PlotModel` |
| `RoiSetModel`, cube spec, slice, view crop | `PlotModel` |
| Qt list rows for the run sidebar | `RunListModel` (it is already a `QStandardItemModel`) |

`RunModel` remains a per-run wrapper (data, frozen spectra, fetch). It should
**not** be the long-term owner of “the” plot’s key selection if multiple
`PlotModel`s can share one list; today selection is copied onto every
`RunModel` from the list — acceptable as a transitional sync, but new code
should treat `PlotModel` as the source of truth for keys.

#### What happens when runs are added or removed?

`PlotModel` subscribes to the bound `RunListModel` and applies a fixed
protocol (implement in Step 3; document in `PlotModel` docstring):

1. **`run_removed` / uid removed:** drop all `PlotDataModel`s for that uid;
   do not keep stale artists in the model map.
2. **`visible_runs_changed`:** for newly visible runs, if the plot has a key
   selection and auto-add (or equivalent), `ensure_plot_data` for each
   selected y (and x/norm as today). For newly hidden runs, hide or drop
   their `PlotDataModel`s (match current canvas behavior; prefer drop or
   explicit visibility on the plot-data model — decide in Step 3 and record
   in the decision log).
3. **`available_keys_changed` (from the list):** filter this plot’s selected
   keys to keys that still exist; if the selection changed, refresh plot
   data; if retain-selection is on and the list is empty, keep keys as
   today’s list does.
4. **`run_added`:** membership only until visibility/auto-add decides whether
   plot data appears (same as today’s `_auto_add` / main-display behavior,
   but living on `PlotModel`).

No `PlotModel` mutates another plot’s selection. Shared `RunListModel`
changes are fan-out via signals.

#### Alternatives considered

1. **Keep `PlotDataModel` on `RunListModel`** — simplest code move; wrong
   parent if two canvases share one list; rejected for Step 3.
2. **`PlotDataList` that only holds artists, keys stay on `RunListModel`** —
   half-split; key selection is still plot-global while artists are
   per-plot; confusing when two plots disagree on keys. Rejected as end
   state; acceptable only as a brief intermediate if a PR must stay small.
3. **Fully shareable N plots × 1 list in the first PR** — not required.
   Ship `PlotModel` + 1:1 `DisplayManager` wiring; multi-plot sharing can
   come later without another ownership redesign.
4. **Put `RoiSetModel` on `RunListModel` (old Step 1)** — same wrong-parent
   problem as plot data. **Revised:** Step 1 introduces a thin `PlotModel`
   that owns `RoiSetModel`; Step 3 expands that `PlotModel`.

---

## Step 0 — Baseline and guardrails

**Status:** Skipped (optional later)

One-maintainer call: an AST ownership inventory test is useful later if
regressions appear, but it is not required before Step 1. Resume this step
only if we want automated enforcement; do not block Steps 1+.

### Infrastructure decision

**Mechanism:** a normal **pytest** test (AST scan), not a separate linter or
hand-run script.

| Choice | Rationale |
|--------|-----------|
| pytest under `tests/` | Matches how the suite is already run (`pytest`, dependency already in `pyproject.toml`). No new toolchain. |
| AST scan of `nbs_viewer/views/**/*.py` | Catches `AllowlistedModel(` call sites; ignores imports and comments; excludes `widgets/` (rule 6). |
| Not flake8/ruff plugin | Overkill for one rule; `.flake8` is unused in CI anyway. |
| Not a standalone script | Scripts get forgotten; a failing/xfailing test rides with the rest of the suite. |

**When it runs**

- Whenever someone runs the unit suite locally (same as other tests), e.g.
  `pytest tests/` or `pytest tests/test_model_ownership.py`.
- **Not by hand** as a special checklist step after each edit.
- There is **no GitHub Actions job that runs tests today** (only PyPI publish on
  release). This guardrail therefore does **not** gate PRs until/unless a test
  workflow is added later. That is an optional follow-up outside this step;
  Step 0 does not require adding CI.

**Optional convenience (not required):** a pixi task alias such as
`pytest tests/test_model_ownership.py` for a quick ownership-only check.

**Phasing inside the test**

1. **Inventory mode (Step 0 ship):** test collects all allowlisted constructor
   hits under `views/` and asserts they equal an explicit
   `EXPECTED_VIOLATIONS` frozenset (path + class name, or equivalent). New
   unexpected hits **fail**; clearing a listed hit without updating the set
   **fails** (forces the plan/test to stay in sync).
2. **Shrink the set** in Steps 1–6 as each constructor moves to models.
3. **Empty set:** `EXPECTED_VIOLATIONS` is empty; any hit fails hard. That is
   the end state of Milestone B for view-side construction, not a separate
   lint flip.

Do **not** use a forever-growing `# noqa`-style ignore in production code;
the expected-set in the test file is the single ledger.

**What the scan flags (and what it ignores)**

The check looks for **constructor call sites**, not imports or type
annotations. A view may freely import model classes for typing:

```python
from nbs_viewer.models.plot.runListModel import RunListModel

class RunListView(QWidget):
    def __init__(self, run_list_model: RunListModel, ...):
        ...
```

That is allowed and **must not** fail the test.

| Pattern | Flagged? |
|---------|----------|
| `from ... import RunListModel` | No |
| `run_list_model: RunListModel` / `Optional[RunListModel]` | No |
| `if TYPE_CHECKING: import RunListModel` | No |
| `isinstance(obj, RunListModel)` | No (call is `isinstance`) |
| `RoiSetModel(...)` / `PlotDataModel(...)` | **Yes** |
| `alias = RoiSetModel; alias(...)` after `import RoiSetModel as alias` | **Yes** (resolve import aliases) |

**Simple AST approach:** walk `ast.Call` nodes. If `node.func` is a `Name`
whose id is an allowlisted class (or an alias bound to one via
`ast.ImportFrom` / `ast.Import` in that module), record a hit. Do **not**
treat `ast.Import`, `ast.ImportFrom`, or annotation-only uses (`ast.arg`
annotations, `ast.AnnAssign`, etc.) as violations.

Resolving `import X as Y` aliases in-file is enough; no need for
cross-module type inference. Dynamic construction (`getattr(mod, "RoiSetModel")()`)
is out of scope for Step 0 (rare; catch in review if it appears).

### Do

- [ ] Confirm / extend the domain-model allowlist above
- [ ] Add `tests/test_model_ownership.py` (name flexible) that AST-scans
      `nbs_viewer/views/` for allowlisted **constructor calls** (not imports /
      annotations); resolve simple import aliases; exclude `widgets/`
- [ ] Seed `EXPECTED_VIOLATIONS` from the inventory table above (views only)
- [ ] Document in the test docstring: run via normal pytest; typing imports OK;
      `widgets/` excluded
- [ ] Optional: pixi task for ownership-only pytest

### Non-goals

- No ownership moves yet
- No new CI workflow required for Step 0
- No flake8/ruff custom plugin
- Do not scan or “fix” `widgets/`
- Do not forbid model imports in views for typing or for calling methods on
  injected instances

### Testing goals

- [ ] `pytest tests/test_model_ownership.py` passes with the seeded expected set
- [ ] Adding a fake `RoiSetModel(` in a view file makes the test fail
- [ ] A view file that only imports `RunListModel` for annotations does **not**
      count as a violation
- [ ] Removing a real expected hit without updating the set makes the test fail
- [ ] Rest of suite still green

### Exit criteria

- [ ] Allowlist + inventory pytest exist
- [ ] This section’s infrastructure decision matches what shipped (update the
      modification log if the mechanism changes)

---

## Step 1 — Introduce `PlotModel`; own `RoiSetModel`

**Status:** Done

**Depends on:** none (Step 0 skipped)

### Do

- [x] Add `PlotModel` (name flexible) under `models/plot/`, constructed with a
      `RunListModel` reference (parent = plot model or display-owned)
- [x] `DisplayManager` (or display setup path) creates one `PlotModel` per
      plot display alongside the existing `RunListModel` (keep 1:1 wiring)
- [x] Create `RoiSetModel` inside `PlotModel` (not `RunListModel`); expose
      `plot_model.roi_set`
- [x] Change `PlotControlTab` / controllers / canvas to take `PlotModel` (or
      `plot_model.roi_set`) instead of constructing `RoiSetModel(self)`
- [x] Do **not** yet move key selection, transform, or `PlotDataModel` map
      (that is Step 3); `PlotModel` may be a thin shell that mostly owns ROI

### Non-goals

- No preview/commit logic moves
- No multi-plot sharing of one `RunListModel` in the UI yet
- No file moves into `models/roi/`
- Do not put `RoiSetModel` on `RunListModel`

### Testing goals

- [x] Unit: `PlotModel(run_list)` exposes a non-`None` `roi_set`
- [x] Unit: two `PlotModel`s (even on the same run list) get distinct
      `RoiSetModel`s
- [x] Unit: entry add/remove still emits existing `RoiSetModel` signals
- [x] Existing ROI set tests pass
- [x] Inventory: no `RoiSetModel(` under `views/`
- [ ] Optional manual: draw ROI in UI; overlays still sync

### Exit criteria

- [x] Headless fragment:
      `pm = PlotModel(RunListModel()); pm.roi_set.add_...(…)` works
- [x] Step status → Done; milestone A still open

---

## Step 2 — Combine / freeze factories on `RunListModel`

**Status:** Done

**Depends on:** Step 0; independent of step 1 in principle (can parallelize)

### Do

- [x] Add `RunListModel.combine_runs(...)` (method name flexible) that constructs
      `CombinedRunModel` and calls `add_run`
- [x] Add freeze factory that constructs `FrozenRunModel` and `add_run`
- [x] `RunListView` only gathers selection / method / expression and calls APIs

### Testing goals

- [x] Unit (no widgets): combine adds one combined entry
- [x] Unit: freeze adds expected frozen entries
- [x] Unit: incompatible combine fails in a way the view can surface
- [x] Inventory: no `CombinedRunModel(` / `FrozenRunModel(` in views

### Exit criteria

- [x] Combine/freeze workable from a script holding only `RunListModel`
- [x] Step status → Done

---

## Step 3 — Expand `PlotModel`: plot data + key/policy move

**Status:** Done

**Depends on:** Step 1 (`PlotModel` exists); Step 0

### Do

- [x] Move `PlotDataModel` map onto `PlotModel` (`ensure_plot_data`); canvas /
      image grid request models from `plot_model`, do not construct them
      (ImageGrid temporary exception)
- [x] Implement the run-list → plot-model add/remove/visibility protocol in
      **“Run list vs plot session”** (document choices in the decision log)
- [x] Move plot policy onto `PlotModel`: selected x/y/norm keys, transform,
      retain-selection (leave **available key intersection** and **auto-add**
      on `RunListModel`)
- [x] Update controls (`run_display`, transform, retain) to talk to
      `PlotModel` where appropriate; auto-add + run sidebar stay on
      `RunListModel`
- [x] Keep redraw signal wiring in the view (canvas connects to plot-data
      signals); models stay widget-free
- [x] Transitional: if `RunModel.set_selected_keys` sync remains for
      compatibility, document it as temporary; `PlotModel` is source of truth

**Decision log**

- Owner of `PlotDataModel` map: **`PlotModel`** (not `RunListModel`)
- When a run is **unchecked** but still in the list: **keep** `PlotDataModel`s
  in the map; stop plotting them (views/plot only use visible runs)
- When a run is **removed** from `RunListModel`: **drop** that uid’s
  `PlotDataModel`s from the map
- One PR for map + keys/policy + cube/crop/slice (not 3a/3b)
- Cube / crop / slice ownership: **`PlotModel`** in Step 3 (canvas consumer;
  Step 8 can still slim draw helpers)
- Auto-add: **stays on `RunListModel`**; drives visibility for newly added runs
- Transform, retain-selection: **`PlotModel`**
- Default x/y selection on first run: **`PlotModel`** (per-plot defaults)
- `available_keys` universe: **`RunListModel`**; `PlotModel` filters its
  selected keys on `available_keys_changed` (honor retain-selection)
- Image grid: **temporary exception** — may still construct `PlotDataModel`
  until a later rework; Step 3 clears canvas construction
- `RunModel.set_selected_keys` sync: **kept as temporary** compatibility
  bridge (documented on `PlotModel`)

### Testing goals

- [x] Unit: `ensure_plot_data` twice with same keys returns same instance
- [x] Unit: different keys → different instances
- [x] Unit: removing a run from the list drops that uid’s plot-data entries
- [x] Unit: visibility / auto-add creates plot-data for newly visible runs
      when keys are selected
- [x] Unit: two `PlotModel`s on one `RunListModel` keep independent key
      selections and independent plot-data maps (even if UI is still 1:1)
- [x] Unit: updating slice / `cube_view_spec` on the plot model does not
      require a canvas
- [x] Regression: `test_plot_geometry`, plot-dimension tests still pass
- [x] Inventory: no `PlotDataModel(` in views except temporary
      `imageGridWidget.py` exception
- [x] Unit: uncheck keeps plot-data in map; remove drops it

### Exit criteria

- [x] Headless: `RunListModel` + `PlotModel` → select keys →
      `ensure_plot_data` → fetch/bundle without `MplCanvas`
- [x] Step status → Done

---

## Step 4 — ROI preview + commit as model APIs

**Status:** Done

**Depends on:** Steps 1 and 3 (commit needs run + plot identity)

### Do

- [x] Move build-request / preview-fetch / `FrozenSpectrum` construction out of
      controllers / ROI window into model APIs:
  - preview creation on `PlotDataModel.preview_roi_profile` /
    `build_roi_frozen_spectrum`
  - routing + register on `PlotModel.preview_roi_profile` /
    `commit_roi_profile` / `finalize_roi_commit`
  - shared helper `build_roi_profile_request_from_operation`
- [x] Controllers pass UI state only; they do not call `FrozenSpectrum(...)`
- [x] Rename “derivative” identifiers toward ROI preview/commit
      (`RoiPreviewController`, `RoiPreviewWorker`, `fetch_roi_preview`, …)
- [x] File move to `models/roi/` deferred to Step 7

**Decision log**

- Creation of preview bundles and `FrozenSpectrum` objects: **`PlotDataModel`**
- Public preview / commit / register: **`PlotModel`** (routes to parent
  `PlotDataModel`, then `RunModel.register_frozen_spectrum`)
- `RunModel` remains register-only for frozen spectra
- Shared request helper: `build_roi_profile_request_from_operation` in
  `derived_fetch.py`
- Async: sync model APIs; `QThread` worker stays in views and calls
  `PlotDataModel.preview_roi_profile`
- Rename derivative → ROI naming in this PR; folder move waits for Step 7

### Testing goals

- [x] Unit (H0/H1): synthetic 2D data → ROI entry → preview returns 1D
      `PlotBundle`
- [x] Unit: commit registers synthetic key on `RunModel`; second commit adds
      another key
- [x] Unit: stale / missing region errors come from the model API
- [x] Inventory: no `FrozenSpectrum(` in views
- [x] Review: controllers are wiring + status text only

### Exit criteria

- [x] Headless ROI save path:

  ```text
  RunListModel + PlotModel → add run → configure cube/ROI → preview → commit
  → list frozen keys
  ```

- [x] Step status → Done
- [x] **Milestone A** checkbox above

---
## Step 5 — Catalog table + source models

**Status:** Not started

**Depends on:** Step 0; can parallelize with steps 1–4

### Do

- [ ] `CatalogBase` (or catalog manager) factories / owns `CatalogTableModel`
- [ ] `CatalogManagerModel` (or peer) factories `*SourceModel` from connection
      params; dataSource views submit forms and call `create_…`
- [ ] Qt proxies stay in views

### Testing goals

- [ ] Unit: catalog fixture → table model → row count / roles
- [ ] Unit: source factory returns expected type without widgets (auth callback
      injectable)
- [ ] Inventory: no `CatalogTableModel(` / `*SourceModel(` in views

### Exit criteria

- [ ] Headless: config → source/catalog → table model → run UIDs → hand runs to
      `DisplayManager` / `RunListModel`
- [ ] Step status → Done

---

## Step 6 — Display registry QtWidgets leak + app wiring leftovers

**Status:** Not started

**Depends on:** Steps 1–5 ideally; can start registry cleanup earlier

### Do

- [ ] Remove `QWidget` from `DisplayRegistry` model layer (import path / name
      registry, or move registry to views and register from app shell)
- [ ] Remove any remaining `QtWidgets` imports under `models/` (including
      `PlotDataModel` parent typing if present)
- [ ] Do **not** change `widgets/` as part of this step

### Testing goals

- [ ] Grep/lint: no `qtpy.QtWidgets` under `models/`
- [ ] Unit: `AppModel` + `DisplayManager.register_display` without display
      widgets
- [ ] Inventory clean for allowlisted constructors under `views/`

### Exit criteria

- [ ] **H1 headless** declared: model tree usable without constructing widgets
      (`QT_QPA_PLATFORM=offscreen` OK if a `QApplication` is required by Qt)
- [ ] Step status → Done
- [ ] **Milestone B** checkbox above

---

## Step 7 — Organize under `models/` (mechanical)

**Status:** Not started

**Depends on:** Steps 1–4 at minimum (ROI ownership stable); prefer after 6

### Do

- [ ] Move ROI cluster → `models/roi/` (`region*`, `roi_set`, preview/commit
      helpers)
- [ ] Optionally `models/display/` for `DisplayManager` / registry metadata
- [ ] Optionally nest cube/materialize under `models/plot/` subpackage
- [ ] Temporary shims at old import paths if needed
- [ ] Optionally collapse tiny `views/plot/controls/` checkbox modules (no
      behavior change)

### Testing goals

- [ ] Full unit suite green after import updates
- [ ] Diff is mostly moves + imports

### Exit criteria

- [ ] Folder layout matches ownership tree mental model
- [ ] Step status → Done

---

## Step 8 — Slim views / canvas (optional polish)

**Status:** Not started

**Depends on:** Steps 3–4; prefer after 7

### Do

- [ ] Extract ROI/crop draw helpers from `MplCanvas`
- [ ] Canvas renders `PlotBundle` and shows overlays from `RoiSetModel`
- [ ] Crop apply becomes a model API (`set_view_crop` on run list / session /
      run); canvas does not own long-lived domain crop state

### Testing goals

- [ ] Existing crop / ROI tests pass
- [ ] Unit: crop apply on the model without canvas
- [ ] Optional H2: qtbot for draw toggles

### Exit criteria

- [ ] Canvas is presentation-only for plot/ROI/crop domain state
- [ ] Step status → Done
- [ ] **Milestone C** checkbox above

---

## PR / dependency graph

```text
0 inventory
  → 1 PlotModel shell + RoiSet ownership
    → 2 combine/freeze          (can start after 0 in parallel with 1)
    → 3 PlotModel plot-data + keys/policy
      → 4 ROI preview/commit      ← Milestone A
  → 5 catalog/sources           (parallel after 0)
  → 6 no QtWidgets in models    ← Milestone B
  → 7 folder moves
  → 8 canvas slim               ← Milestone C
```

## Explicit non-goals (until this plan is revised)

- [ ] Inverting packages to `catalog/models` + `catalog/views`
- [ ] Replacing `Signal` with a non-Qt event bus
- [ ] Implementing band projection (should consume new ROI/plot APIs when added)
- [ ] Refactoring or relocating `widgets/` (embeddable entrypoints for external
      programs; leave alone; may grow later)
- [ ] Building a full mock / file-backed catalog as a prerequisite for Step 2
      (see **Future: catalog fixtures for tests** below)

## Future: catalog fixtures for tests

Not required for Step 2 (combine/freeze factories can use stub `RunModel`s).
Worth doing soon for headless Milestone B and any test that needs real
`CatalogRun` / key / `get_plot_data` behavior across multiple runs.

### Option A — Replay Bluesky documents into `KafkaCatalog`

`KafkaCatalog` already ingests `(name, doc)` via `_handle_document` and builds
`KafkaRun`s. A test dispatcher that reads a saved document stream (JSON/msgpack
of start / descriptor / event|event_page / stop) and calls the same handler
would exercise the live Kafka run path without a broker.

**Pros:** Reuses production code; good for streaming/partial-run behavior;
small surface (dispatcher + fixture files).  
**Cons:** Fixture capture and refresh; large/image-heavy runs are bulky;
Kafka-shaped runs may not match Tiled/`BlueskyRun` quirks.

### Option B — File-backed catalog (product + tests)

A `CatalogBase` implementation over on-disk runs (e.g. databroker/tiled
export, msgpack bundles, or a dedicated package layout). Dual use: offline
beamline playback and CI fixtures.

**Pros:** Stable, versionable fixtures; can mirror Tiled-like access if
designed that way; useful outside tests.  
**Cons:** Larger design/implementation; need a clear run file format and
key/data API parity with `BlueskyRun` / `KafkaRun`.

### Suggested sequencing

1. Finish Step 2 with stubs (no catalog fixture dependency).
2. If document replay is easy, add Option A as `tests/fixtures/runs/…` + a
   tiny replay dispatcher for multi-run combine / selection tests.
3. Treat Option B as a real feature when offline catalogs are wanted in the
   app, not only as test scaffolding — tests then consume the same catalog.

## Modification log

| Date | Change |
|------|--------|
| 2026-08-06 | Initial plan from ownership / headless discussion |
| 2026-08-06 | Clarify `widgets/` is intentional embed surface; out of scope |
| 2026-08-06 | Step 0: pytest AST inventory (not hand lint); no CI gate yet |
| 2026-08-06 | Step 0: scan constructor calls only; typing imports allowed |
| 2026-08-06 | Introduce PlotModel vs RunListModel split; revise steps 1 and 3 |
| 2026-08-06 | Skip Step 0 for now; begin Step 1 |
| 2026-08-06 | Step 1 done: PlotModel owns RoiSetModel; views wired |
| 2026-08-06 | Note future Kafka-replay vs file-backed catalog fixtures |
| 2026-08-06 | Step 2 done: combine/freeze factories on RunListModel; view calls APIs |
| 2026-08-07 | Step 3 decisions: one PR; drop on remove; cube/crop/slice on PlotModel; auto-add stays on RunListModel; defaults on PlotModel; ImageGrid deferred |
| 2026-08-07 | Step 3: uncheck keeps plot-data (stop plotting); transform+retain on PlotModel; ImageGrid temporary exception; available_keys filter on PlotModel |
| 2026-08-07 | Step 3 done: PlotModel owns keys, transform, retain, cube/crop/slice, plot-data map; canvas uses ensure_plot_data |
| 2026-08-07 | Step 4 done: PlotDataModel creates ROI preview/FrozenSpectrum; PlotModel routes+registers; derivative→ROI rename; Milestone A |
