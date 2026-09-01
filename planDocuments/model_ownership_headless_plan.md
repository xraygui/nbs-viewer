# Model ownership and headless readiness plan

**Status: CLOSED (2026-09-01).** H1 model ownership goals are met for the
N=1 path. Follow-up work is tracked in
[`headless_testing_plan.md`](headless_testing_plan.md) (E2E fixtures and test
infrastructure), [`plot_package_reorganization.md`](plot_package_reorganization.md)
(Step 7 layout), and ad-hoc issues for Step 6c / Step 8.

Path B refactor: keep domain code under `models/`, enforce **only models create
domain models**, and make the viewer runnable as a model tree without views
(headless H1).

Related context: ROI workbench and materialize plans under `planDocuments/`;
cache extraction (`models/cache/`) is the organizational precedent for later
folder moves.

## Status (final)

| Step | Title | Status |
|------|-------|--------|
| 0 | Baseline and guardrails | Skipped → moved to [`headless_testing_plan.md`](headless_testing_plan.md) Phase 3 |
| 1 | Introduce `PlotModel`; own `RoiSetModel` | Done |
| 2 | Combine / freeze factories on `RunListModel` | Done |
| 3 | Expand `PlotModel`: plot data + key/policy move | Done |
| 4 | ROI preview + commit as model APIs | Done |
| 5 | Catalog table + source models | Done |
| 6 | Presenter + drop widget registry / no `QtWidgets` in models | Done (6a/6b); **6c deferred** (multi-view / image grid) |
| 7 | Organize under `models/` (mechanical) | Replaced by [`plot_package_reorganization.md`](plot_package_reorganization.md) |
| 8 | Slim views / canvas (optional polish) | Deferred (not blocking H1) |

**Milestones**

- [x] **A** (after steps 1–4): ROI headless path
- [x] **B** (after steps 5–6): Catalog → presenter → plot headless path (model
  tree complete; E2E test harness is follow-up in testing plan)
- [ ] **C** (steps 7–8): Navigable tree + thin views (deferred)

### Closure notes

What shipped: the target ownership tree (`AppModel` → `CatalogManagerModel` /
`DisplayManager` → `PlotPresenter` → `RunListModel` + `PlotModel`), no
`QtWidgets` under `models/`, views consume presenters, catalog and table
ownership on models, ROI/plot-data APIs callable without a canvas.

What remains outside this plan:

- **6c** — N>1 presenter, image grid per-cell `PlotModel`, clear
  `PlotDataModel(` in `image_grid_canvas.py`
- **7** — plot package reorg (`plot_package_reorganization.md`)
- **8** — canvas slim / export frontend
- **Testing** — shared `AppModel` + `MemoryCatalog` fixtures, E2E integration
  tests, ownership AST guard (`headless_testing_plan.md`)
- **`widgets/kafkaViewerTab.py`** — intentional embed surface; stale API, not
  in scope

## Rules of the road

1. **Only models create domain models.** Views may create Qt proxies / item
   models used purely as view adapters (`ReverseModel`, `FilterModel`,
   metadata `QStandardItemModel`, etc.).
2. **A view that needs a new model asks the model it already holds**
   (e.g. `plot_model.roi_set`, `plot_model.ensure_plot_data(...)`, or
   `presenter.plot_models[i]`).
3. **Stay under `models/`** for domain code. Folder splits inside
   `models/plot/` (`plot/roi/`, `plot/run/`, `plot/cube/`, …) are Step 7
   ([`plot_package_reorganization.md`](plot_package_reorganization.md));
   catalog/data/sources layout already landed ahead of Step 5 ownership.
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
7. **`AppModel` is the long-lived root.** It owns `ConfigModel`,
   `CatalogManagerModel`, and a manager of **presenters** (today’s
   `DisplayManager`, to be renamed or reshaped in Step 6). Views must not
   keep a parallel catalog registry alongside `CatalogManagerModel` (today:
   residual dual ownership was cleared in 5b; views renamed to
   `CatalogSwitcher` / `SourceDialog`).
8. **Constructor injection is exclusive.** If a view constructor takes
   `app_model`, do **not** also pass child models (`run_list_model`,
   `plot_model`, `catalogs`, …) in parallel. Either pass `AppModel` and
   resolve children inside, **or** pass only the specific children needed.
   Mixing both is forbidden (current smell: `MainDisplay` /
   `CatalogSwitcher(app_model, run_list_model, …)`).
9. **Frontends are views, including non-Qt ones.** A terminal driver or
   “save plot to disk” path is still a view: it observes models and
   performs I/O. Headless H1 means **no `QtWidgets` in models**, not “no
   view layer.”

### Target ownership tree

```text
AppModel
├── ConfigModel
├── CatalogManagerModel          # source palette + catalog registry (Step 5)
│   ├── sources (palette)        # long-lived SourceModels (one per type / config recipe)
│   │     URI / Profile / Kafka / ZMQ / Test / config entries …
│   │     catalog_loaded ──► register_catalog
│   └── catalogs (label) → CatalogBase
│         └── CatalogTableModel  # owned by the catalog (Step 5a)
└── PresenterManager             # today’s DisplayManager (rename in Step 6)
    └── PlotPresenter (id)       # coordinates 1..N plot sessions; name flexible
          ├── RunListModel       # private if N=1; shared if N>1
          └── PlotModel × N      # each is a full plot session
                ├── selected keys, transform, retain (plot policy)
                ├── PlotDataModel map
                ├── RoiSetModel
                └── view state (cube_view_spec, slice, view_crop)
```

There is **no** domain `Display` type and **no** model-side registry of Qt
widget / “display type” classes. Tabs, image-grid widgets, and export
drivers are frontends that bind to a `PlotPresenter`.

**Naming (views):** `CatalogSwitcher` switches among registered **catalogs**.
`SourceDialog` configures **SourceModels** (factories) to load catalogs.
A `SourceModel` is not a catalog session — one URI source can load many
catalogs over time.

**`CatalogManagerModel` is for:** owning the **source palette** (long-lived
`SourceModel`s), creating sources via typed `create_*` / `create_from_config`,
connecting each source’s `catalog_loaded` to `register_catalog`, holding the
**catalog registry**, and forwarding run selection signals. Expand in place —
do **not** split out a separate `SourceFactory` unless types become a large
plugin surface (entrypoints can hang off the manager later).

**`SourceModel` is for:** how to load a catalog (connect/auth/navigate/wrap).
It is a **QObject** with `catalog_loaded(catalog, label)`. Prefer a `load()`
(or equivalent) that calls `get_source` then emits. Views configure and call
`load`; they do **not** hold `CatalogManagerModel` or call `register_catalog`.
Sources are **long-lived palette members**, not 1:1 with catalogs.

**`CatalogBase` (and peers) own `CatalogTableModel`:** create via something
like `ensure_table_model()` / lazy property so Kafka / Tiled / Memory stay
consistent. Views only attach Qt proxies (`ReverseModel`, filters) to that
table model; they never construct `CatalogTableModel(...)`.

**`CatalogSwitcher` is for:** reacting to manager catalog add/remove signals
and creating/destroying catalog table views. It must **not** register
catalogs after `SourceDialog` returns.

**`PlotPresenter` is for:** creating and coordinating one or more
`PlotModel`s (and their `RunListModel`). It **sets** shared policy across
plot models (e.g. slice indices for a grid); it does **not** extract or
reshape plot arrays. Layout on screen or on disk is the frontend’s job.

- **N = 1 (default today):** presenter creates one `PlotModel` with a
  **private** `RunListModel` (plot may construct the list, or presenter
  passes one it created).
- **N > 1 (multi-view, e.g. slice grid):** presenter creates **one shared**
  `RunListModel` and **N** `PlotModel`s; each plot holds its own slice /
  cube / crop; presenter assigns those parameters consistently.

**`RunListModel` is for:** collecting runs, which runs are checked/visible,
and the **intersection of catalog keys** among visible runs (the key universe
a plot may choose from). It is **not** the home for artists, ROI geometry,
cube/crop view state, or which x/y keys a particular plot uses.

**`PlotModel` is for:** one plot session’s selection and products — selected
keys, `PlotDataModel` instances, ROI set, cube/crop, transform/retain
policy. It holds a reference to a `RunListModel` and reacts to that list’s
membership/visibility signals. Auto-add stays on `RunListModel`. Slice /
cube / crop remain on **each** `PlotModel` (presenter only writes them for
coordination).

See **“Run list vs plot session”** below for add/remove behavior.
See **“Catalog ownership (Step 5 decisions)”** for source/table wiring.
See **“Source palette + catalog_loaded (Step 5d)”** for signal wiring.
See **“Presenter vs multi-view (Step 6 decisions)”** for path-2 / ROI deferral.

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
- `ConfigSourceModel`, `URISourceModel`, `ProfileSourceModel`,
  `KafkaSourceModel`, `ZMQSourceModel`, `TestSourceModel`
- `BlueskyCatalog`, `NBSCatalog`, `KafkaCatalog`, `MemoryCatalog` (and peers)
- `MemoryRun` (and other `CatalogRun` implementations constructed as domain)
- `AppModel`, `CatalogManagerModel`, `PlotPresenter`, `PresenterManager`
  (today’s `DisplayManager`), `ChunkCache` (unless explicitly delegated)

Known violations at plan start (inventory baseline for step 0):

| Location | Creates |
|----------|---------|
| `views/plot/imageGridWidget.py` | `PlotDataModel` (temporary exception) |
| `views/catalog/base.py` | `CatalogTableModel` |
| `views/dataSource/dataSource.py` | `*SourceModel` (incl. `TestSourceModel`) |

Cleared in earlier steps: `RoiSetModel` (Step 1), `CombinedRunModel` /
`FrozenRunModel` (Step 2), `PlotDataModel` in canvas (Step 3; ImageGrid
deferred), `FrozenSpectrum` in views (Step 4).

Cleared in Step 5: `CatalogTableModel(` / `*SourceModel(` under `views/`;
constructor injection rule 8 for `CatalogSwitcher` (5c); source palette +
`catalog_loaded` + reactive switcher (5d).

`widgets/kafkaViewerTab.py` also constructs `RunListModel` / `KafkaCatalog`, but
that package is an intentional external embed surface — **leave alone** (see
rule 6). Do not list it as a violation to clear in steps 0–8.

### Catalog ownership (Step 5 decisions)

Decided (2026-08-26); 5a/5b implemented; 5c/5d follow.

| Concern | Owner |
|---------|--------|
| Create `*SourceModel` from connection / config params | `CatalogManagerModel` (expand in place) |
| Own long-lived source **palette** (one per type / config recipe) | `CatalogManagerModel` (5d) |
| Register / unregister labeled catalogs; forward select signals | `CatalogManagerModel` |
| Emit after successful load | `SourceModel.catalog_loaded` → manager `register_catalog` (5d) |
| Own / create `CatalogTableModel` | `CatalogBase` (and peers), e.g. `ensure_table_model()` |
| Qt proxies / filters for the catalog table | Views only |
| Catalog table / kafka **widgets** | `CatalogSwitcher` reacting to `catalog_added` / `catalog_removed` |
| Parallel `_catalogs` dict in switcher | **Remove** — manager is sole registry (done 5b) |
| `CatalogSwitcher` calling `register_catalog` after dialog | **Forbidden** (5d) |
| `SourceView` holding `CatalogManagerModel` | **Avoid** — prefer signals (5d) |
| `SourceDialog` holding `CatalogManagerModel` | **OK** — iterates palette to build views |
| View ctor: `app_model` + child models together | **Forbidden** (rule 8; 5c) |

**Rejected alternative:** split a separate `SourceFactory` / session type out of
`CatalogManagerModel`. Prefer expanding the existing manager unless source
construction later grows enough to justify a split.

**Rejected alternative:** views hold `CatalogManagerModel` and call
`load_and_register` as the primary GUI path. Prefer
`SourceModel.catalog_loaded` → manager slot. Keep `load_and_register` as an
optional headless/script helper only.

**Auth:** keep auth callbacks injectable on source construction (GUI dialog
from views, or no-op / tokens for headless). Views do not construct the
source model; they may still supply the callback when asking the manager to
create.

### Source palette + catalog_loaded (Step 5d)

Decided (2026-08-26); implement as Step 5d.

**Roles**

- **SourceModel** = long-lived factory/strategy on the manager palette (how to
  load). One URI source can produce many catalogs over time. Not 1:1 with
  catalogs; not what `CatalogSwitcher` lists.
- **Catalog** = durable registry entry; what the switcher lists.
- **SourceDialog** = configures palette sources and triggers `load`.
- **CatalogSwitcher** = reacts to catalog add/remove; builds/tears down views.

**Signal wiring (preferred)**

```text
SourceModel (QObject)
  catalog_loaded(catalog, label)  ──►  CatalogManagerModel.register_catalog

CatalogManagerModel
  catalog_added(label, catalog)   ──►  CatalogSwitcher creates CatalogTableView / KafkaView
  catalog_removed(label)          ──►  CatalogSwitcher removes view
```

When the manager adds a source to the palette, it connects
`source.catalog_loaded` to `register_catalog` (or a thin adapting slot).
`SourceView` configures the source and calls `load()` / equivalent; it does
not register catalogs or hold the manager. `SourceDialog` may hold the
manager to iterate the palette and build views.

**Prerequisite:** `SourceModel` becomes a `QObject` (H1). Subclasses keep
`get_source`; base (or shared) `load(**kwargs)` calls `get_source` then emits
`catalog_loaded`.

**Autoload:** manager configures/loads palette or config sources via `load`
(non-interactive) → same signals → switcher populates with no special
register path.

**Not in scope for 5d:** full entrypoint discovery of source types (can hang
off the palette later); 5c injection cleanup can land with or after 5d.

### Presenter vs multi-view (Step 6 decisions)

Decided (2026-08-26); implement in Step 6 (N=1 now; N>1 when multi-view
lands).

**Path chosen:** for N panels (e.g. a grid of slices), use **N `PlotModel`s
sharing one `RunListModel`**. The presenter assigns per-plot parameters
(slices, etc.); each plot session still owns its own data path via
`ensure_plot_data`. Frontends only lay out panels (or write files).

**Rejected path:** one global `PlotModel` plus a presenter that **extracts**
slices from the cube. That makes the presenter a second data pipeline and
bypasses `PlotDataModel` / ROI APIs per panel.

| Concern | Owner |
|---------|--------|
| Create 1..N `PlotModel`s + run list (private or shared) | `PlotPresenter` |
| Slice / cube / crop source of truth | Each `PlotModel` |
| Assign slices (or other params) across plots | `PlotPresenter` (writes into plot models) |
| Fetch / reshape arrays for panels | **Not** the presenter — each `PlotModel` |
| Screen / disk layout | Frontend (Qt or headless view) |
| Qt widget / entrypoint “display type” registry in models | **None** — remove |
| Domain `Display` bag (run list + plot + type) | **Do not adopt** — drop stub |
| Multi-view ROI | **Deferred**; preferred direction = presenter **syncs** ROIs across plot models’ `RoiSetModel`s |
| Multi-view key/transform policy | Defer with multi-view; likely presenter sync (same pattern as ROI) |

**ROI note:** keep Milestone A as-is (`RoiSetModel` on each `PlotModel`).
Do not implement cross-plot ROI sync until a multi-view presenter needs it.
When that lands, prefer presenter-synced copies over a shared `RoiSetModel`
or primary/mirror special cases unless sync proves too painful.

**`single_selection_mode` and similar:** set as explicit presenter / run-list
policy, not via magic strings like `"image_grid"` from a display-type
registry.

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
3. **Fully shareable N plots × 1 list in the first PlotModel PR** — not
   required then. **Revised (2026-08-26):** N plots × 1 list is the
   multi-view presenter shape; ship N=1 presenter first in Step 6; N>1
   when image-grid / multi-panel needs it.
4. **Put `RoiSetModel` on `RunListModel` (old Step 1)** — same wrong-parent
   problem as plot data. **Revised:** Step 1 introduces a thin `PlotModel`
   that owns `RoiSetModel`; Step 3 expands that `PlotModel`.
5. **Domain `Display` aggregate + model-side widget registry** — rejected;
   “display” is a frontend concept. See Presenter decisions above.
6. **Single `PlotModel` + presenter extracts grid slices** — rejected; see
   Presenter decisions above.

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
- [x] File move of ROI modules deferred to Step 7
      ([`plot_package_reorganization.md`](plot_package_reorganization.md)
      slice 7a: `models/plot/roi/`, not top-level `models/roi/`)

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

**Status:** Done

**Depends on:** Step 0; can proceed now that Steps 1–4 are done

**Already landed (ahead of ownership move):**

- `MemoryRun` / `MemoryCatalog` under `models/data/` and `models/catalog/`
- `TestSourceModel` + helpers under `models/sources/`
- Package splits: `models/catalog/`, `models/data/`, `models/sources/`

These are the preferred Milestone B fixtures (see **Catalog fixtures** below).

### Do

**5a — Table ownership**

- [x] `CatalogBase` (and peers) factories / owns `CatalogTableModel`
      (e.g. `ensure_table_model()` or equivalent lazy API)
- [x] `CatalogTableView` / peers obtain the table model from the catalog;
      Qt proxies stay in views
- [x] Inventory: no `CatalogTableModel(` under `views/`

**5b — Source factories on `CatalogManagerModel` (expand in place)**

- [x] Move `*SourceModel` construction out of `SourceDialog` /
      source views into `CatalogManagerModel` APIs (`create_…` / `load_…`
      from connection params or config entries)
- [x] Auth callback remains injectable; views may pass a GUI callback or
      headless/no-op
- [x] Register created catalogs on the manager; drop
      parallel view-side catalog dict as a second source of truth
- [x] Autoload from config goes through `ConfigModel` /
      `CatalogManagerModel`, not ad-hoc TOML parse + view construction
- [x] Inventory: no `*SourceModel(` under `views/`

**5c — Constructor injection (rule 8)**

- [x] `CatalogSwitcher` takes `app_model` + `display_id` only; resolves
      run list via `display_manager` (no parallel child injection)
- [x] `MainDisplay` already took `app_model` only; passes display_id to
      switcher. Other mixed ctors deferred (PlotWidget / RunListView stay
      children-only)

**5d — Source palette + `catalog_loaded` + reactive switcher**

- [x] Make `SourceModel` a `QObject` with `catalog_loaded(object, str)`
- [x] Add `load(**kwargs)` that runs `get_source` then emits
- [x] `CatalogManagerModel` owns a long-lived source **palette**; on add,
      connect `catalog_loaded` → `register_catalog`
- [x] Emit `catalog_added` / `catalog_removed` (keep `catalogs_changed`)
- [x] `SourceDialog` holds manager, iterates palette, builds `SourceView`s;
      views call `load` / `emit_catalog_loaded` — no `register_catalog`
- [x] `CatalogSwitcher` only reacts to catalog add/remove to create/destroy
      catalog views (including autoload)
- [x] Keep `load_and_register` only as optional headless/script helper

### Non-goals

- No Presenter / widget-registry cleanup (Step 6)
- No ROI folder move (Step 7)
- No separate `SourceFactory` type unless construction later forces a split
- Do not treat file-backed offline catalogs as a Step 5 prerequisite
  (`MemoryCatalog` is enough)
- Do not implement multi-view (N>1) or ROI sync in Step 5
- Do not register one SourceModel per catalog (palette is by type / recipe)
- Source type entrypoints can wait until after 5d palette exists

### Testing goals

- [x] Unit: `MemoryCatalog` fixture → `ensure_table_model` → row count /
      roles without widgets constructing the table model
- [x] Unit: manager source factory returns expected type without widgets
      (auth callback injectable)
- [x] Unit: register catalog on manager; no need for a parallel view-side
      catalog dict
- [x] Inventory: no `CatalogTableModel(` / `*SourceModel(` in views
- [x] Unit (5d): source `load` emits `catalog_loaded`; manager registers
      without the view calling `register_catalog`
- [x] Unit (5d): two loads from one test source → two catalog labels
- [ ] Optional: headless script path below

### Exit criteria

- [ ] Headless:

  ```text
  TestSourceModel / MemoryCatalog
    → CatalogTableModel (via catalog)
    → select / list run UIDs
    → AppModel routes to active presenter / RunListModel + PlotModel
  ```

  (Presenter routing remains Step 6; catalog/table/source path is done.)

- [x] Views submit forms / auth results; they do not construct source or
      catalog table domain models
- [x] `CatalogSwitcher` does not call `register_catalog` (5d)
- [x] Step status → Done (after 5c + 5d)

**Decision log**

- Source construction: **expand `CatalogManagerModel` in place** (not a
  separate factory type)
- API shape: **hybrid C** — typed `create_*` for interactive sources +
  `create_from_config` for TOML `source_type` dispatch
- Sources: **long-lived palette** on the manager (not ephemeral; not 1:1
  with catalogs)
- Registration path: **`SourceModel.catalog_loaded` → manager** (not
  SourceView holding the manager; not CatalogSwitcher after dialog)
- `load_and_register`: **headless helper only** after 5d
- `CatalogTableModel` owner: **`CatalogBase` / catalog peers**
- View injection: **`app_model` XOR specific children** (rule 8; 5c)
- Fixture path for Milestone B: **`MemoryCatalog` / `TestSourceModel`**
- View names: **`CatalogSwitcher`**, **`SourceDialog`**

---

## Step 6 — Presenter + remove widget registry / QtWidgets from models

**Status:** Done (6a/6b); 6c deferred follow-up

**Depends on:** Steps 1–5 ideally; N=1 presenter can start once PlotModel
exists; full H1 after Step 5 inventory is clean

### Decisions (locked)

- **Path 2:** presenter coordinates 1..N `PlotModel`s; does not extract data
- **N=1:** private `RunListModel`; **N>1:** shared `RunListModel`
- **No** domain `Display`; **no** model-side Qt / entrypoint display-type
  registry
- **Frontends** (Qt tabs, image grid, save-to-disk) bind to presenters
- **Multi-view ROI / key sync:** deferred; preferred = presenter syncs
  across plot models when N>1 is implemented

### Do

**6a — Presenter (N=1 first)**

- [x] Introduce `PlotPresenter` (renamed from unused `Display` stub) that
      creates one `PlotModel` and a private `RunListModel`
- [x] Reshape `DisplayManager` to own `id → PlotPresenter` (keep name /
      `display_*` APIs for now; rename in 6b if wanted)
- [x] Drop unused domain `Display` stub / parallel run-list + plot dicts
- [x] `single_selection_mode` is explicit on register/create; frontend
      declares it via `__single_selection_mode__` metadata (no hardcoded
      `image_grid` / `spiral` list in the manager)
- [x] `PlotDisplay` / `MainDisplay` resolve `presenter` then take run list /
      plot from it (minimal rule-8 cleanup)

**6b — Remove model-side widget registry**

- [x] Move entry-point / widget discovery to
      `views/display/frontendRegistry.py` (`FrontendRegistry`)
- [x] GUI shell (`MainWidget`) owns the registry; menus / tab creation use
      `get_frontend_registry()`
- [x] `AppModel` / `DisplayManager` no longer own or validate against widget
      classes; `display_type` is an opaque shell hint only
- [x] No `qtpy.QtWidgets` under `models/`

**6c — Multi-view presenter (deferred; not required for Step 7)**

- [ ] N>1 `PlotModel`s + shared `RunListModel`; presenter assigns slices
- [ ] ROI sync across plot models (preferred direction); record protocol in
      decision log when implemented
- [ ] Image grid stops constructing `PlotDataModel` (clears temporary
      exception) by using per-cell plot models instead

### Non-goals

- Do not block Step 6a/6b on image-grid multi-view
- Do not put a Presenter that extracts cube slices (rejected path)
- Do not change `widgets/` as part of this step

### Testing goals

- [x] Grep/lint: no `qtpy.QtWidgets` under `models/` (6b)
- [x] Unit (6a/6b): register presenter / plot session without loading
      display widgets (no registry on AppModel)
- [x] Unit (6a): N=1 presenter exposes run list + plot model; catalog
      selection can add a run without a canvas
- [ ] When 6c lands: unit N plot models share one run list; independent
      slices; optional ROI sync tests
- [ ] Inventory clean for allowlisted constructors under `views/` (incl.
      clearing ImageGrid `PlotDataModel(` when 6c done)

### Exit criteria

- [x] **H1 headless** for model tree: no widget registry / `QtWidgets` in
      models; presenters usable without entrypoint display classes
- [x] No model-side registry of Qt display classes
- [x] Step status → Done (6c remain follow-up)
- [x] **Milestone B** checkbox above (model path; E2E harness in testing plan)

**Decision log**

- Presenter path: **N PlotModels, shared run list for multi-view** (not
  extract-from-one-plot)
- Widget / display-type registry in models: **removed** (6b: moved to
  `FrontendRegistry` in views; option A)
- Domain `Display`: **not adopted** (became `PlotPresenter`)
- Multi-view ROI: **deferred**; preferred **presenter sync**
- `DisplayRegistry` role: **GUI frontend catalog only** — not required for
  domain/headless; entry points load in the view shell

---

## Step 7 — Organize under `models/` (mechanical)

**Status:** Replaced — execute
[`plot_package_reorganization.md`](plot_package_reorganization.md)
instead of the checklist below.

**Depends on:** Steps 1–4 (ROI ownership stable); 6a/6b preferred so
presenter types exist to place. **6c is not required.**

Catalog/data/sources/cache layout already landed. The remaining work is
grouping `models/plot/` and `views/plot/` (ROI / run / cube / canvas
subpackages, snake_case on move, no import shims). Model–view leaks that
folders cannot fix are inventoried in that document, not cleared here.

### Already done (this plan)

- [x] `models/catalog/` (incl. `memory.py`, `table.py`, bluesky/kafka peers)
- [x] `models/data/` (incl. `MemoryRun`)
- [x] `models/sources/` (incl. `TestSourceModel`)
- [x] `models/cache/`

### Still to do

See slices 7a–7d in the reorganization document (7e optional / Step 8).

Do **not** use the old sketch (`models/roi/` as a top-level sibling,
import shims, presenter as `models/presenter/`). Those were considered
and rejected there.

### Testing goals

- [ ] Full unit suite green after each reorganization slice
- [ ] Diff is mostly moves + imports (+ cube/presenter file splits)

### Exit criteria

- [ ] Folder layout matches the target trees in the reorganization document
- [ ] Step status → Done

---

## Step 8 — Slim views / canvas (optional polish)

**Status:** Not started

**Depends on:** Steps 3–4; prefer after 7

### Do

- [ ] Extract ROI/crop draw helpers from `MplCanvas`
- [ ] Canvas renders `PlotBundle` and shows overlays from `RoiSetModel`
- [ ] Crop apply remains a **`PlotModel`** API (`set_view_crop` already on
      the plot session from Step 3); canvas does not own long-lived domain
      crop state
- [ ] Frontends (including headless export) consume plot/presenter APIs only

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
  → 5 catalog/sources           (5a table · 5b factories · 5c injection · 5d palette+signals)
  → 6 presenter N=1 + drop widget registry  ← Milestone B
      → 6c multi-view presenter + ROI sync (deferred; not required for 7)
  → 7 plot package reorg (see plot_package_reorganization.md; 7a–7d)
  → 8 canvas slim (+ optional 7e ROI/crop extract)  ← Milestone C
```

## Explicit non-goals (until this plan is revised)

- [ ] Inverting packages to `catalog/models` + `catalog/views`
- [ ] Replacing `Signal` with a non-Qt event bus
- [ ] Implementing band projection (should consume new ROI/plot APIs when added)
- [ ] Refactoring or relocating `widgets/` (embeddable entrypoints for external
      programs; leave alone; may grow later)
- [ ] Splitting `CatalogManagerModel` into a separate `SourceFactory` type
      (expand in place unless construction later forces a split)
- [ ] File-backed offline catalog as a prerequisite for Step 5 / Milestone B
      (`MemoryCatalog` covers fixtures)
- [ ] Top-level `models/roi/` or `models/presenter/` packages (Step 7 nests
      those concerns under `models/plot/` instead)
- [ ] Model-side registry of Qt display / plot widget classes
- [ ] Domain `Display` type as RunList+Plot bag
- [ ] Presenter that extracts slice grids from a single PlotModel
- [ ] Multi-view ROI sync before a multi-view presenter exists

## Catalog fixtures

**Primary (landed):** `MemoryRun` + `MemoryCatalog` + `TestSourceModel`.
Use these for Milestone B headless tests and any multi-run catalog → plot
path that does not need Tiled/Kafka specifics.

### Optional — Replay Bluesky documents into `KafkaCatalog`

`KafkaCatalog` already ingests `(name, doc)` via `_handle_document` and builds
`KafkaRun`s. A test dispatcher that reads a saved document stream and calls
the same handler would exercise the live Kafka run path without a broker.
Useful for streaming/partial-run tests; not required for Step 5.

### Optional later — File-backed catalog (product + tests)

A `CatalogBase` over on-disk runs for offline beamline playback. Treat as a
real product feature when wanted; tests can then share it. Not a Step 5
blocker.

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
| 2026-08-26 | Step 5 decisions: expand CatalogManagerModel in place; catalogs own CatalogTableModel; app_model XOR child injection (rules 7–8); MemoryCatalog/TestSource as primary fixtures; Step 5 split 5a/5b/5c; Step 7 partial (catalog/data/sources); Step 6 registry placement left open |
| 2026-08-26 | Step 6 decisions: PlotPresenter path (N PlotModels; shared run list for multi-view); no domain Display; no model-side widget registry; frontends are views incl. non-Qt; multi-view ROI deferred (prefer presenter sync); rule 9 |
| 2026-08-26 | Step 5a done: CatalogBase.ensure_table_model / refresh_table_model; views use catalog-owned CatalogTableModel; Memory/Bluesky search emit data_updated |
| 2026-08-26 | Step 5b done: CatalogManagerModel hybrid C factories (create_* + create_from_config + load_*); ConfigSourceModel thin wrap; views take injected source models; drop DataSourceSwitcher._catalogs |
| 2026-08-26 | Rename DataSourceSwitcher→CatalogSwitcher, DataSourcePicker→SourceDialog; file catalogSwitcher.py; clarify source=factory, catalog=loaded registry |
| 2026-08-26 | Step 5d planned: SourceModel→QObject with catalog_loaded; manager owns long-lived source palette; connect catalog_loaded→register_catalog; CatalogSwitcher reactive via catalog_added/removed; reject SourceView holding manager |
| 2026-08-26 | Step 5c+5d done: CatalogSwitcher(app_model, display_id); SourceModel.load/catalog_loaded; palette on manager; SourceDialog iterates palette; switcher reacts to catalog_added/removed; label uniquify; load_and_register headless-only |
| 2026-08-26 | Step 6a done: PlotPresenter owns private RunListModel+PlotModel; DisplayManager stores presenters; explicit single_selection_mode (frontend `__single_selection_mode__`); PlotDisplay/MainDisplay resolve via get_presenter |
| 2026-08-27 | Step 6b done (option A): DisplayRegistry → views/display/frontendRegistry.FrontendRegistry; MainWidget owns it; AppModel/DisplayManager detached; no QtWidgets under models |
| 2026-08-27 | Step 6c deferred; Step 7 replaced by plot_package_reorganization.md (`models/plot/{roi,run,cube}/`, mirrored `views/plot/roi/`; no top-level `models/roi/`, no shims) |
| 2026-09-01 | Plan closed. Milestone B marked done at model layer; Step 0 AST guard and E2E fixtures moved to headless_testing_plan.md; 6c/7/8 remain as follow-ups |
