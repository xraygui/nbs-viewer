# Plot package reorganization

> **Superseded on file splits (2026-09-08).**
> [`view_pipeline_plan.md`](view_pipeline_plan.md) deletes `cube_view.py`,
> `view_crop.py` and `derived_fetch.py` rather than splitting them into
> `cube/` and `roi/` packages, so the target trees here no longer apply to
> `models/plot/`. Retained for its inventory of private model APIs used by
> views, which is still the best record of that surface.


Replaces the Step 7 checklist in
[`model_ownership_headless_plan.md`](model_ownership_headless_plan.md).
Catalog / data / sources / cache layout is already done; this document is the
remaining package work, focused on `models/plot/` and `views/plot/`.

Step 6c (multi-view presenter) is deferred and is **not** a prerequisite.
This reorg must not implement N>1, ROI sync, or ImageGrid-per-cell
`PlotModel`s.

**Goal:** related code lives together, the folder tree matches how we already
think about ownership (`PlotPresenter` → `PlotModel` / `RunListModel` → ROI /
cube / crop), and a newcomer can find “the ROI model” or “the canvas
renderers” without opening a 1.7k-line file. Model–view leaks that folder
moves cannot fix are inventoried at the end as follow-up work (mostly Step 8
and small ownership PRs).

## Status

| Slice | Title | Status |
|-------|-------|--------|
| 7a | ROI packages (`models/plot/roi/`, `views/plot/roi/`) | Not started |
| 7b | Run package + presenter files + snake_case session modules | Not started |
| 7c | Cube spec / materialize split | Not started |
| 7d | View shell grouping (`canvas/`, controls collapse) | Not started |
| 7e | Canvas ROI/crop extraction (optional; overlaps Step 8) | Not started |

## Constraints (from the ownership plan)

These still apply; this document does not reopen them.

1. Domain code stays under `models/`. Do **not** invert to
   `feature/{models,views}`.
2. Only models create domain models. Views may import model types for
   typing and to call methods on injected instances.
3. Relative imports within `models/` are preferred.
4. `widgets/` is out of scope.
5. H1 headless means **no `QtWidgets` in models**, not “no Qt” and not
   “no view layer.” `QObject` / `Signal` / `QStandardItemModel` /
   `QAbstractTableModel` in models are accepted.
6. Mechanical reorg: behavior-preserving. Diff should be moves, import
   updates, and file splits along existing seams — not feature work.

## Why the current layout is hard to reason about

`models/plot/` is a flat bag of 17 modules (~8.7k lines) that mix four
different concerns:

| Concern | Examples | Who owns it |
|---------|----------|-------------|
| Session orchestration | `PlotPresenter`, `DisplayManager`, `PlotModel`, `PlotDataModel` | Presenter / plot session |
| Run collection | `RunListModel`, `RunModel`, combine / freeze | Presenter (private list) |
| N-D view / fetch | `cube_view`, `view_crop`, `plot_geometry`, `plot_view_frame` | `PlotModel` |
| ROI geometry + preview | `region*`, `roi_set`, `derived_fetch`, `frozen_spectrum` | `PlotModel.roi_set` + plot-data APIs |

`views/plot/` is the same problem on the other side: 23 files, with
`mpl_canvas.py` at 1747 lines holding plot update, workers, renderers,
ROI selectors, crop selectors, and overlays; ROI UI scattered as
`roi_*.py` siblings of `plotWidget.py`. Tiny checkbox controls are
already in `controls/`, which is the grouping pattern to copy.

Newer geometry files use `snake_case.py`; older session files use
`camelCase.py` (`plotModel.py`, `runListModel.py`, `displayManager.py`).
That split is accidental (age), not semantic, and it makes grep / import
muscle memory unreliable.

`catalog/`, `data/`, `sources/`, and `cache/` already demonstrate the
intended pattern: a subpackage named for a concern, with the public types
near the top of that folder.

## Design principles

1. **Group by ownership concern, not by type of class.** `RoiSetModel`
   and `RectRegion` belong together even though one is a `QObject` and
   the other is a frozen dataclass. `PlotPresenter` belongs next to
   `PlotModel`, not in a new top-level `models/presenter/` package
   (see alternatives).
2. **Mirror model and view packages where the feature is paired.** ROI
   is the clearest pair: `models/plot/roi/` and `views/plot/roi/`. Cube
   spec is model-only; dimension controls stay in views. Do not create
   empty view folders just for symmetry.
3. **Public types at the package boundary; internals one file down.**
   `from nbs_viewer.models.plot.roi import RoiSetModel, RectRegion` is
   the target import for other packages. Inside `models/plot/`, relative
   imports of submodules are fine (`from .roi.roi_set import RoiSetModel`).
4. **Do not introduce import cycles to get a pretty tree.** `roi/region`
   must stay free of cube imports (true today). Cube materialize may
   import region. ROI preview fetch may import cube. `view_crop` sits at
   `plot/` root because both cube fetch and `PlotModel` session state use
   it.
5. **Rename files to `snake_case` when we move them.** One import update
   per file is cheaper than move-then-rename. Class names stay
   (`PlotModel`, `RunListModel`, `DisplayManager`).
6. **No compatibility shims.** Call sites are in-tree (`nbs_viewer/`,
   `tests/`, `planDocuments/` examples). Update imports in the same PR.
   Shims would hide the new layout and become the next cleanup.
7. **Do not “fix” model–view leaks in these PRs** unless a split is
   impossible otherwise. Record them (see **Remaining model–view
   leaks**) and leave behavior identical.
8. **Keep folders shallow.** Two levels under `models/plot/`
   (`plot/roi/region.py`) is enough. Do not nest `roi/region/rect.py`.

## Alternatives considered

### A. `models/roi/` as a sibling of `models/plot/`

This is what the original Step 7 checklist sketched.

- **For:** ROI types are reusable in principle; a top-level package
  matches `cache/`.
- **Against:** `RoiSetModel` is owned by `PlotModel`. Every current
  caller is plot-session code. A top-level `models/roi/` implies an
  independent subsystem we do not have. Cache earned a top-level package
  because `models/data/` consumes it independently of any plot session.

**Decision:** `models/plot/roi/`. Revisit a top-level `models/roi/` only
if a non-plot consumer appears (e.g. a headless reduction CLI that never
constructs `PlotModel`).

### B. `models/presenter/` as a sibling of `models/plot/`

Matches the AppModel tree (`PresenterManager` beside `CatalogManagerModel`).

- **For:** ownership-tree fidelity.
- **Against:** the presenter *is* plot-session orchestration
  (`RunListModel` + `PlotModel`). It is ~340 lines today. A top-level
  package for two classes adds navigation cost without clarifying
  dependencies. `catalog/` and `sources/` are top-level because many
  non-plot callers use them.

**Decision:** keep presenter modules under `models/plot/`. Split
`displayManager.py` into `presenter.py` + `presenter_manager.py`. Do
**not** rename `DisplayManager` → `PresenterManager` in this reorg
(API churn in `AppModel`, views, tests). File names carry the new
vocabulary; the class rename can be a later one-line-ish PR.

### C. `models/run/` as a sibling of `models/plot/`

`RunListModel` is used by catalog routing and `RunListView`, not only by
the canvas.

- **For:** run collection is conceptually above a single plot session,
  especially once 6c shares one list across N plots.
- **Against:** `RunModel` still mixes catalog-run wrapping with plot
  fetch (`get_plot_data`, transform, selected-keys sync). Moving the
  folder without slimming `RunModel` just relocates the conflation.
  `models/plot/run/` already groups the files for findability.

**Decision:** `models/plot/run/` now. A top-level `models/run/` is
reasonable **after** selected-keys fully leave `RunModel` (documented
temporary bridge on `PlotModel`).

### D. Invert to `plot/{models,views}`

Forbidden by ownership-plan rule 5. Restated here so we do not “fix”
findability that way. Cross-layer pairing is done by matching subfolder
names (`plot/roi/` on both sides), not by merging packages.

### E. Collapse tiny checkbox controls vs leave them

Original Step 7 listed this as optional. Four modules
(`auto_add`, `dynamic_update`, `lock_aspect`, `retain_selection`) are
~50–60 line wrappers around `CheckboxFormControl`.

- **Leave them:** one class per file is easy to open from a stack trace.
- **Collapse:** `controls/checkboxes.py` (or keep files but they add
  noise in a 23-file folder).

**Decision:** collapse into `views/plot/controls/checkboxes.py` in slice
7d. `transform.py` and `run_display.py` stay separate (real UI). `base.py`
stays.

### F. Import shims at old paths

**Decision:** no shims. The package is not a public library surface
beyond `widgets/` (untouched). Tests and in-tree views update in the
same PR.

## Target trees

### Models (`nbs_viewer/models/plot/`)

```text
models/plot/
  __init__.py                 # re-export session types only (optional, thin)
  plot_model.py               # PlotModel
  plot_data_model.py          # PlotDataModel
  plot_geometry.py            # PlotBundle, render-mode classification
  plot_view_frame.py          # PlotViewFrame, frame_from_bundle
  view_crop.py                # ViewCrop + apply/fetch helpers
  presenter.py                # PlotPresenter
  presenter_manager.py        # DisplayManager (class name unchanged)
  cube/
    __init__.py               # CubeViewSpec, DimRole, materialize_view, …
    spec.py                   # CubeViewSpec, roles, profile-spec helpers
    materialize.py            # MaterializeRequest, materialize_view, apply
  run/
    __init__.py               # RunModel, RunListModel, Combined, Frozen
    run_model.py
    run_list_model.py
    combined_run_model.py
    frozen_run_model.py
  roi/
    __init__.py               # RoiSetModel, RegionDefinition, shapes, …
    region.py
    region_mesh.py
    region_reduce.py
    roi_set.py
    derived_fetch.py          # ROI preview/commit fetch helpers
    frozen_spectrum.py        # FrozenSpectrum dataclass + synthetic keys
```

`view_crop.py` stays at `plot/` root: it is plot-session state (on
`PlotModel`) that cube fetch and ROI preview both consume. It is not an
ROI (crop is rectangle-only 2-D extraction; ROI is 1-D reduction) and it
is not only a cube-spec type.

`frozen_spectrum.py` lives under `roi/` because `PlotDataModel` creates
it from an ROI commit. `FrozenRunModel` stays under `run/` because it is
a run-list membership type. `is_synthetic_key` is re-exported from
`roi/__init__.py` (today `models/data/bluesky.py` imports it from
`plot.frozen_spectrum`).

### Views (`nbs_viewer/views/plot/`)

```text
views/plot/
  __init__.py
  plot_widget.py              # PlotWidget shell
  plot_controls.py            # PlotControls (tab host)
  plot_control_tab.py         # PlotControlTab (settings / dimension / crop)
  image_grid_widget.py        # ImageGrid frontend (stays; 6c will rework)
  metadata_view.py            # Metadata tab (Qt adapter models; OK in views)
  canvas/
    __init__.py
    mpl_canvas.py             # MplCanvas + NavigationToolbar
    mpl_renderers.py
    plot_worker.py
  dimension/
    __init__.py
    plot_dimension.py         # DimensionControl + row widgets
  controls/
    __init__.py
    base.py
    checkboxes.py             # AutoAdd, DynamicUpdate, LockAspect, Retain
    transform.py
    run_display.py
  roi/
    __init__.py
    panel.py                  # RoiPanel (crop launcher + open-window)
    controller.py             # RoiController (crop + stale)
    preview_controller.py     # RoiPreviewController
    preview_canvas.py         # RoiPreviewCanvas + RoiPreviewWorker
    window.py                 # RoiWindow
    types.py                  # RoiTypeSpec + matplotlib selectors
    overlays.py               # overlay artists for region shapes
```

`metadata_view.py` stays under `views/plot/` because `PlotControls` hosts
it. It is not plot-geometry; it is a sibling tab. Moving it to
`views/dataSource/` would split a widget from its parent for little gain.

`image_grid_widget.py` stays a plot frontend next to `plot_widget.py`.
Do not bury it under `canvas/`; it is its own display widget, not a
helper of `MplCanvas`.

### What we are not moving

| Path | Why |
|------|-----|
| `models/app_model.py` | App root; already the right place |
| `models/catalog/`, `data/`, `sources/`, `cache/` | Done |
| `views/display/` | Frontend registry + display tabs; not plot internals |
| `views/dataSource/`, `views/catalog/` | Catalog / source UI |
| `views/common/panel.py` | Shared chrome |
| `widgets/` | Embed surface (ownership rule 6) |
| Tests as a mirrored tree | Update imports; optional `tests/plot/` later |

## File map (current → proposed)

### `models/plot/`

| Current | Proposed | Notes |
|---------|----------|--------|
| `plotModel.py` | `plot_model.py` | Session owner |
| `plotDataModel.py` | `plot_data_model.py` | |
| `plot_geometry.py` | `plot_geometry.py` | Unchanged path aside from package |
| `plot_view_frame.py` | `plot_view_frame.py` | |
| `view_crop.py` | `view_crop.py` | Stay at plot root |
| `cube_view.py` | `cube/spec.py` + `cube/materialize.py` | Slice 7c |
| `displayManager.py` | `presenter.py` + `presenter_manager.py` | Split classes |
| `runSource.py` | `run/run_model.py` | |
| `runListModel.py` | `run/run_list_model.py` | |
| `combinedRunModel.py` | `run/combined_run_model.py` | |
| `frozenRunModel.py` | `run/frozen_run_model.py` | |
| `region.py` | `roi/region.py` | |
| `region_mesh.py` | `roi/region_mesh.py` | |
| `region_reduce.py` | `roi/region_reduce.py` | |
| `roi_set.py` | `roi/roi_set.py` | |
| `derived_fetch.py` | `roi/derived_fetch.py` | |
| `frozen_spectrum.py` | `roi/frozen_spectrum.py` | |

### `views/plot/`

| Current | Proposed | Notes |
|---------|----------|--------|
| `plotWidget.py` | `plot_widget.py` | |
| `plotControl.py` | `plot_controls.py` | Match class `PlotControls` |
| `plot_control_tab.py` | `plot_control_tab.py` | |
| `imageGridWidget.py` | `image_grid_widget.py` | |
| `metadataView.py` | `metadata_view.py` | |
| `mpl_canvas.py` | `canvas/mpl_canvas.py` | |
| `mpl_renderers.py` | `canvas/mpl_renderers.py` | |
| `plot_worker.py` | `canvas/plot_worker.py` | |
| `plotDimensionWidget.py` | `dimension/plot_dimension.py` | |
| `controls/*.py` (tiny checkboxes) | `controls/checkboxes.py` | 7d |
| `controls/base.py` | `controls/base.py` | |
| `controls/transform.py` | `controls/transform.py` | |
| `controls/run_display.py` | `controls/run_display.py` | |
| `roi_panel.py` | `roi/panel.py` | Drop redundant `roi_` prefix inside package |
| `roi_controller.py` | `roi/controller.py` | |
| `roi_preview_controller.py` | `roi/preview_controller.py` | |
| `roi_preview_canvas.py` | `roi/preview_canvas.py` | |
| `roi_window.py` | `roi/window.py` | |
| `roi_types.py` | `roi/types.py` | |
| `roi_overlays.py` | `roi/overlays.py` | |

Inside `views/plot/roi/`, filenames drop the `roi_` prefix because the
package already says ROI. Class names stay (`RoiPanel`, `RoiController`,
…). Same idea as `models/catalog/table.py` holding `CatalogTableModel`.

## Package `__init__.py` policy

New subpackages get a **thin** `__init__.py` that re-exports types other
packages actually import. Do not re-export private helpers
(`_fetch_plot_plane_storage_axes`, `_profile_uses_nd_load`).

Suggested public sets:

- `models.plot.roi`: `RoiSetModel`, `RoiEntry`, `RoiOperation`,
  `RegionDefinition`, `RectRegion`, `EllipseRegion`, `PolygonRegion`,
  `AxisSliceRegion`, `CompiledRegion`, `region_from_dict`,
  `FrozenSpectrum`, `is_synthetic_key`,
  `build_roi_profile_request_from_operation`, `fetch_roi_preview`
- `models.plot.run`: `RunModel`, `RunListModel`, `CombinedRunModel`,
  `FrozenRunModel`, `CombinationMethod`, `CombineError`
- `models.plot.cube`: `CubeViewSpec`, `DimRole`, `MaterializeRequest`,
  `default_spec`, `resolve_roles`, `spec_for_plot_ndim`,
  `materialize_view`, `apply_cube_view`, and the profile-spec helpers
  views already call (`eligible_profile_axes`, `profile_axis_name`, …)
- `models.plot` (optional): `PlotModel`, `PlotDataModel`, `PlotPresenter`,
  `DisplayManager` — only if we want `from nbs_viewer.models.plot import
  PlotModel`. Not required; explicit submodule imports are fine.

Views subpackages may use empty `__init__.py` (current style for
`views/plot/`). Re-exports are more useful on the model side because
tests import model types heavily.

## Cube split (slice 7c) — seam

`cube_view.py` is 1256 lines mixing a frozen spec language with numpy
reduction. The split is along types that already exist:

**`cube/spec.py` (no region compile, no reduction)**

- `DimRole`, `ROLE_LABELS`, `SLICE_ROLES`
- `CubeViewSpec` and its methods
- `resolve_roles`, `default_spec`, `spec_from_slice_info`,
  `spec_for_plot_ndim`
- Axis mapping: `plot_axis_to_storage_axis`, `storage_axis_to_plot_axis`,
  `is_plot_plane_storage_axis`
- Profile *spec* helpers: `eligible_profile_axes`, `profile_view_spec`,
  `display_plane_profile_spec`, `classify_profile_kind`, …

**`cube/materialize.py`**

- `MaterializeRequest`
- `_narrow_fetch_slice`, plot-plane storage-axis resolution (today
  `_fetch_plot_plane_storage_axes` — see leaks: promote when views stop
  importing the private name)
- `_materialize_without_region`, `_materialize_roi_profile`,
  `materialize_view`, `apply_cube_view`, reduce helpers

`cube/__init__.py` re-exports so existing `from
nbs_viewer.models.plot.cube_view import CubeViewSpec, materialize_view`
becomes `from nbs_viewer.models.plot.cube import CubeViewSpec,
materialize_view`.

Do **not** move `plot_geometry.py` / `plot_view_frame.py` under `cube/`.
They describe a rendered 1-D/2-D `PlotBundle`, which 1-D line plots use
without any cube spec.

## Presenter split (slice 7b) — seam

`displayManager.py` already contains two classes with a blank line
between them. Move `PlotPresenter` to `presenter.py` and
`DisplayManager` to `presenter_manager.py`. `DisplayManager` imports
`PlotPresenter`; no cycle.

Keep `display_added` / `register_display` / `AppModel.display_manager`
names. Renaming the **class** is a separate, optional PR after this
reorg (many view docstrings and tests say `DisplayManager`).

## Execution slices

Each slice is one PR. Do not combine 7a with 7c; ROI folders are the
easy win and should land first so later cube work imports from
`models.plot.roi`.

### Shared mechanical recipe (every slice)

1. `git mv` (preserve blame).
2. Fix in-package relative imports.
3. Grep-update `nbs_viewer/`, `tests/`, and code-like citations in
   `planDocuments/` that would otherwise lie.
4. Add/adjust thin `__init__.py` re-exports for that package.
5. `pytest tests/` green.
6. No behavior changes, no new APIs, no leak fixes.

### Slice 7a — ROI packages

**Do**

- [ ] Create `models/plot/roi/` and move the six ROI model modules
      (see file map). Update relative imports (`plot_view_frame` becomes
      `..plot_view_frame`; `cube_view` stays `..cube_view` until 7c).
- [ ] Create `views/plot/roi/` and move the seven ROI view modules;
      drop the `roi_` filename prefix.
- [ ] Thin `models/plot/roi/__init__.py` public exports.
- [ ] Update tests (`test_roi_set.py`, `test_region.py`,
      `test_region_mesh.py`, `test_roi_preview_commit.py`,
      `test_derived_fetch.py`, `test_frozen_spectrum.py`, and any
      import of `derived_fetch` / `region`).

**Non-goals**

- Do not extract ROI methods from `MplCanvas` (7e / Step 8).
- Do not move `view_crop.py`.
- Do not change `RoiController` crop-apply logic.

**Testing**

- [ ] Full unit suite green
- [ ] `from nbs_viewer.models.plot.roi import RoiSetModel, RectRegion`
      works
- [ ] No remaining `models.plot.roi_set` / `views.plot.roi_window` imports

**Why this slice first:** it is the grouping everyone already expects,
touches a coherent cluster, and unblocks “look in `plot/roi/`” without
waiting on cube or presenter naming.

### Slice 7b — Runs, presenter files, snake_case session modules

**Do**

- [ ] `models/plot/run/` for the four run modules; thin `__init__.py`
- [ ] Split `displayManager.py` → `presenter.py` + `presenter_manager.py`
- [ ] Rename remaining camelCase plot-root modules (`plot_model.py`,
      `plot_data_model.py`)
- [ ] Update `AppModel`, views, tests, `widgets/kafkaViewerTab.py`
      imports for the new module paths (**do not** change widget
      behavior or construction; rule 6 is about not refactoring that
      package, not about skipping an import path update)

**Non-goals**

- Do not rename `DisplayManager` / `display_manager`.
- Do not move presenter to `models/presenter/`.
- Do not drop `RunModel.set_selected_keys` sync.

**Testing**

- [ ] `test_plot_presenter.py`, `test_run_list_combine_freeze.py`,
      `test_plot_model.py`, `test_plot_model_step3.py` green
- [ ] Full suite green

**Why combined:** these files all live at the plot-session root; one
import sweep is less painful than three.

### Slice 7c — Cube package

**Do**

- [ ] Split `cube_view.py` along the seam above into `cube/spec.py` and
      `cube/materialize.py`
- [ ] Re-export from `cube/__init__.py`
- [ ] Point ROI `derived_fetch`, `view_crop`, `plot_model`,
      `plot_data_model`, `run_model`, and views that import `cube_view`
      at `models.plot.cube`

**Non-goals**

- Do not promote `_fetch_plot_plane_storage_axes` (leak; record only).
- Do not change materialize numerics.

**Testing**

- [ ] `test_cube_view.py`, `test_materialize_view.py`,
      `test_fetch_slice_info.py`, `test_derived_fetch.py`,
      `test_view_crop.py` green
- [ ] Full suite green

**Why after 7a:** materialize imports `roi.region`; cleaner once `roi/`
exists.

### Slice 7d — View shell grouping

**Do**

- [ ] `views/plot/canvas/` for `mpl_canvas`, `mpl_renderers`,
      `plot_worker`
- [ ] `views/plot/dimension/` for `DimensionControl`
- [ ] Collapse the four checkbox modules into `controls/checkboxes.py`
- [ ] Snake_case remaining view shell files (`plot_widget.py`,
      `plot_controls.py`, `image_grid_widget.py`, `metadata_view.py`)

**Non-goals**

- Do not slim `MplCanvas` internals.
- Do not merge `PlotControlTab` into `PlotControls`.

**Testing**

- [ ] `test_plot_dimension_control.py` (if it imports the widget module)
      plus full suite
- [ ] GUI smoke optional

**Why last of the mechanical slices:** view imports are fewer than model
imports; doing models first means views land on the final model paths
once.

### Slice 7e — Canvas ROI/crop extraction (optional)

This is the overlap with ownership-plan Step 8 (“extract ROI/crop draw
helpers from `MplCanvas`”). Include it here only if we want
`views/plot/roi/` to contain *all* ROI view code in the same effort.

**Recommended shape (if we do it):** move selector/overlay methods from
`MplCanvas` into helpers in `views/plot/roi/` that take `canvas` /
`axes` / `RoiSetModel`. Prefer functions or a small helper object over
a mixin (`RoiCanvasMixin` plus `QWidget` MRO is a needless footgun).

**Do not do 7e in the same PR as 7a.** 7a is a folder move; 7e is a
class split and will fight review.

If 7e slips, Step 8 still owns it. The ROI *folder* is still a win
without it: window, panel, controllers, types, overlays are already
separate files.

## Remaining model–view leaks

Folder moves do not fix these. They are the reason the tree can look
clean while headless testing is still awkward. None of these are in
scope for 7a–7d.

### Constructor / ownership (allowlist)

| Location | Leak | Follow-up |
|----------|------|-----------|
| `views/plot/imageGridWidget.py` | Constructs `PlotDataModel(...)` into a private `plotArtists` dict | Step 6c: per-cell `PlotModel.ensure_plot_data` |
| `widgets/kafkaViewerTab.py` | Constructs `RunListModel` / `PlotModel` | Out of scope (embed surface) |

No other allowlisted constructors remain under `views/` from Steps 1–5.

### Domain logic living in views

| Location | What it does | Why it is a leak | Follow-up |
|----------|----------------|------------------|-----------|
| `RoiController._on_apply_crop_requested` | Resolves plot-plane storage axes, loads dimension axes from `model._run`, calls `view_crop_from_region`, writes crop via canvas | Crop construction is domain; the view should pass a `RectRegion` (and maybe the visible plot-data identity) into a `PlotModel` API | Step 8 or a small “crop apply on PlotModel” PR: e.g. `plot_model.apply_view_crop_from_region(region, plot_data)` |
| `DimensionControl` | Holds `_cube_view_spec`, mutates it, then pushes through `canvas.update_view_state` → `plot_model.set_view_state` | Parallel spec: widget copy vs `PlotModel.cube_view_spec`. Controllers already fall back across `dimension_control._cube_view_spec` / `plot_model` / `canvas._cube_view_spec` | Treat `PlotModel` as sole spec; widget is an editor that reads/writes the model. Canvas should not be the write path |
| `MplCanvas.update_view_state` | UI validation (QMessageBox if multiple 2-D datasets) **and** `plot_model.set_view_state` | Mixes presentation policy with session mutation | Canvas validates and calls model; or model rejects and view shows the dialog |
| `RoiPreviewController._parent_spec` | Same triple lookup as `RoiController` | View reconstructing “what is the cube spec?” | Read `plot_model.cube_view_spec` only |
| `RoiWindow` | Imports `eligible_profile_axes`, `build_roi_profile_request_from_operation`, etc. to populate controls | Acceptable *if* it only displays model-derived choices; watch for request-building that duplicates `PlotModel` APIs | Keep UI mapping; any new request assembly goes on the model (Step 4 already moved preview/commit) |

### Private model APIs used by views

Views should not import `_`-prefixed model symbols. Today:

| View | Private import / attribute |
|------|----------------------------|
| `RoiController` | `cube_view._fetch_plot_plane_storage_axes`; `PlotDataModel._run`, `._ykey`, `._xkey`, `._key` |
| `RoiPreviewController` | `derived_fetch._profile_uses_nd_load`; `plot_data._cube_view_spec`, `._indices`, `._key`; `canvas._cube_view_spec`, `._slice`, `._active_workers` |
| `DimensionControl` | `canvas._dimension`, `canvas._last_view_frame` |
| `ImageGridWidget` | `plot_data._run`, `._key` |

Follow-up: promote the few functions views truly need (`plot_plane_storage_axes`
already exists publicly in `derived_fetch` and is the same idea as
`_fetch_plot_plane_storage_axes`), and give `PlotDataModel` public
read-only properties (`key`, `run`, `xkey`, `ykey`) instead of
`_`-attribute poking.

### Matplotlib artists on the domain model (largest H1 hole)

`PlotDataModel` still:

- imports `matplotlib.image.AxesImage`
- stores `self.artist`
- implements `clear` / `set_visible` / `set_artist` /
  `remove_artist_from_axes` / `add_artist_to_axes` / `move_artist_to_axes`
- documents itself as plotting onto an `MplCanvas`

That is view state on a domain object. Headless tests that call
`ensure_plot_data` → `get_plot_bundle` work **despite** this, as long as
they never call `set_artist`. ImageGrid and `MplCanvas` both treat
`.artist` as the handle for “is this drawn.”

Follow-up (Step 8, and a prerequisite for a honest headless plot
frontend): artist map lives on the canvas (or a view-side
`PlotArtistMap` keyed by `plot_data.key`). `PlotDataModel` keeps
`last_bundle`, signals, and fetch APIs. `set_visible` on the model
should mean “this series is visible in the session,” not
`artist.set_visible`.

Related leftover: `PlotDataModel.__init__` docstring still says
`parent : QWidget`.

### Dual key-selection source of truth

`PlotModel` is the source of truth for x/y/norm keys (Step 3), with
`RunModel.set_selected_keys` as a temporary compatibility bridge.
Views that still *read* `run_model.get_selected_keys()` as if it were
authoritative:

- `DimensionControl.get_shape_info`
- `ImageGridWidget` (several methods)
- `RunDisplayWidget` in unlinked mode (intentional per-run UI; still
  writes back through mixed plot/run setters)
- `MplCanvas._debug_plot_state`

Follow-up: read `plot_model.get_selected_keys()` everywhere except the
explicit unlinked-run editor. Drop the bridge once freeze/combine and
ImageGrid do not need per-run copies.

### Qt item model as domain run list (accepted H1 compromise)

`RunListModel` subclasses `QStandardItemModel`. That is allowed under
H1 (not `QtWidgets`) and matches “Qt list rows for the run sidebar”
from the ownership plan. It does mean a fully headless script still
pulls in `QtGui`. Not a Step 7 item. A future H0 run-collection type
would be a different project.

`CatalogTableModel` as `QAbstractTableModel` is the same compromise on
the catalog side (already in `models/catalog/`).

### Matplotlib in models (H0 vs H1)

`region_mesh.py` imports `matplotlib.path.Path` for polygon masks. That
is not a Qt widget and is testable without a QApplication, but it is
not “pure numpy” H0. Leave it; replacing `Path.contains_points` is
unrelated to package layout.

### Leftover naming that confuses navigation

| Smell | Where | Follow-up |
|-------|-------|-----------|
| `derivative_controller` alias | `PlotControlTab`, `PlotWidget` | Delete alias after 7a (pure cleanup; can ride with 7a if the diff stays obvious) |
| `RoiPanel` titled “Crop” | `PlotControlTab` | Accurate for the inline panel; not a package issue |
| `DisplayManager` managing presenters | `presenter_manager.py` after 7b | Class rename later |
| `plotArtists` property on canvas | returns `plot_model.plot_data_map` | Rename to `plot_data_map` when artists move off the model |

### Injection / shell (outside plot folders, still relevant)

- `PlotWidget` / `RunListView` take child models only (allowed).
- `PlotDisplay.setup_models` resolves presenter then constructs
  `RunListView(run_list_model, display_manager, display_id)` — mixed
  presenter + manager. Rule 8 cleanup for another PR, not this reorg.
- `image_grid` still cannot be a headless N-plot presenter (6c).

## What “headless model tree” looks like after this reorg

Unchanged capability (already true after Steps 1–6b):

```text
DisplayManager / PlotPresenter
  → RunListModel + PlotModel
      → ensure_plot_data → PlotBundle
      → roi_set.add_… → preview_roi_profile → commit_roi_profile
```

What the reorg changes: the imports in that script become

```python
from nbs_viewer.models.plot.presenter_manager import DisplayManager
from nbs_viewer.models.plot.roi import RectRegion, RoiOperation
from nbs_viewer.models.plot.cube import default_spec
```

instead of a flat `models.plot` of 17 names. It does **not** by itself
make ImageGrid or artist-bearing `PlotDataModel` headless.

## Testing goals (all slices)

- [ ] `pytest tests/` green after each slice
- [ ] Diff is moves + imports (+ the cube/presenter file splits)
- [ ] No new `QtWidgets` under `models/`
- [ ] No new allowlisted constructors under `views/`
- [ ] `widgets/kafkaViewerTab.py` still imports successfully (path-only
      change)

Optional later (not required to close Step 7):

- [ ] Ownership-plan Step 0 AST inventory, including a check that
      `views/` does not import `models..._*private*` names — only after
      the private-API leaks are actually closed

## Exit criteria (Step 7 done)

- [ ] Slices 7a–7d landed (7e optional / Step 8)
- [ ] Folder layout matches the target trees above
- [ ] This document’s decision log matches what shipped (update if a
      recommended alternative was chosen instead)
- [ ] Ownership-plan Step 7 status → Done, with a pointer here
- [ ] Milestone C still waits on Step 8 (canvas slim + artist move)

## Decision log

| Topic | Decision |
|-------|----------|
| ROI package location | `models/plot/roi/` and `views/plot/roi/` (not top-level `models/roi/`) |
| Presenter package | Stay under `models/plot/`; split files; keep class `DisplayManager` |
| Run package | `models/plot/run/` (not top-level `models/run/` yet) |
| Cube | `models/plot/cube/{spec,materialize}.py` |
| `view_crop` | Stay at `models/plot/view_crop.py` |
| `FrozenSpectrum` | `models/plot/roi/frozen_spectrum.py` |
| `FrozenRunModel` | `models/plot/run/frozen_run_model.py` |
| Import shims | None |
| File naming | `snake_case.py` on move; class names unchanged |
| Checkbox controls | Collapse in 7d |
| Canvas ROI extraction | Optional 7e; default to Step 8 |
| Feature-folder inversion | Rejected |
| Leak fixes in 7a–7d | Rejected (inventory only) |

## Modification log

| Date | Change |
|------|--------|
| 2026-08-27 | Initial plan to replace ownership-plan Step 7; 6c deferred |
