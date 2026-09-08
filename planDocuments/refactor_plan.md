# Refactor plan

The single entry point for the model-layer refactor. This document holds the
goal, the invariants, and the order of work. **Detail lives in the sub-plans**
— keep this file short enough to read before every session.

**Status:** in progress on branch `mesh-transpose-removal` off `image_viewing`.
Suite green at 337 tests.

## The diagnosis, in one sentence

**No object could be handed a description of a plot**, so fetch took ten
parameters, state was mirrored across four objects, and trace identity omitted
the view — which meant every feature that varied the view built a second
pipeline.

`PlotRequest` is that description. The rest of this refactor is letting the
class structure fall out of it, and deleting what the absence forced.

## Invariants

Carried forward from the closed ownership plan. These bind every step.

1. **Only models create domain models.** Views may create Qt proxies used
   purely as view adapters (`ReverseModel`, `FilterModel`, item models).
2. **A view that needs a model asks the model it already holds** —
   `session.roi_set`, `session.ensure_plot_data(...)`.
3. **Domain code stays under `models/`.** No `QtWidgets` imports there.
4. **Each step ships with its tests in the same PR.**
5. **No `feature/{models,views}` tree inversion.**
6. **`widgets/` is out of scope.** It holds embeddable views for external
   programs. Leave it alone.
7. **`AppModel` is the long-lived root** — `ConfigModel`,
   `CatalogManagerModel`, and a manager of presenters.
8. **Constructor injection is exclusive.** A view takes `AppModel` *or* the
   specific children it needs, never both.
9. **Frontends are views, including non-Qt ones.** Headless means no
   `QtWidgets` in models, not no view layer.

And two learned during this work:

10. **Every step names what it deletes.** A step whose main content is a new
    module, a bridge type, or a `*_from_legacy` converter is not a step in
    this refactor. Measure it: `git ls-tree` file and line counts before and
    after.
11. **A replacement type must not import the type it replaces.** A new layer
    that converts back to the old one before the old code runs can never
    cause a deletion. Check the import direction.

## Sub-plans

| Sub-plan | Scope |
|----------|-------|
| [`view_pipeline_plan.md`](view_pipeline_plan.md) | How a request becomes storage indices and those indices become a `PlotBundle`. View spec, crop, ROI, fetch, orientation. |
| [`session_and_traces_plan.md`](session_and_traces_plan.md) | Who owns what. `PlotSession`, the list adapter, `Trace`, the consumer sweep, re-homing, final renames. |

They interleave; the order below is the merged sequence.

## Order of work

| # | Step | Sub-plan | Status |
|---|------|----------|--------|
| 1 | Delete the mesh transpose | view pipeline | ✅ `321bf53` |
| 2 | Selection-driven default axis order | view pipeline | ✅ `11c7a0d` |
| 3 | Orientation once after load, one planner, one mask | view pipeline | next |
| 4 | One request, no side channels | view pipeline | |
| A | `PlotSession` / `RunListItemModel` rename and move | session & traces | independent, any time |
| 5 | Invert the dependency, delete `cube_view.py` | view pipeline | after 4 |
| B | `Trace` | session & traces | after 4 |
| 6 | Adopt `ViewIntent`, or delete it | view pipeline | after 5, needs B |
| C | Consumer sweep — canvas `TraceSet`, `DimensionControl` pushes intent | session & traces | after 6 |
| D | Extract the ROI pipeline off the session | session & traces | after 4 |
| E | Re-home `CombinedRunSource` / `FrozenRunSource` | session & traces | independent |
| 7 | `plot_bundle.py` | view pipeline | after 5 |
| F | Final deletions and renames | session & traces | last |

Step 3 is the only one that cannot be sliced: the fetch narrowing and the ROI
mask are both wrong today in ways that cancel, so fixing one alone makes
things worse. See the view pipeline plan's findings.

## Shared backlog

### Bugs found during analysis

Recorded regardless of whether the step that fixes them lands.

| # | Bug | Status |
|---|-----|--------|
| 1 | `CombinedRunSource` does not override `get_plot_bundle`; the inherited path reads `self._run`, set to `runs[0].run`. Combining plots the first run. Silent wrong answer. | open — step E |
| 2 | ROI mask applied in display order to a storage-order array; ND ROI profiles are wrong by an upside-down mask. | open — step 3 |
| 3 | `fetch_context` applies a display bbox directly onto storage slices; three of four axis orientations fetch the wrong block. | open — step 3 |
| 4 | "Show All Keys" is a no-op. `RunDisplayWidget._show_all` is written and never read. Intended backing is `CatalogRun.get_hinted_keys`, which has zero callers. | open |
| 5 | Unlinked mode double-lists synthetic keys — `available_keys` is catalog plus frozen, so a frozen spectrum gets a catalog row with an X checkbox it should not have. | open |
| 6 | `BlueskyRun._infer_dims_from_shape` uses `range(0, ndim)` where `MemoryRun` uses `range(1, ndim)`, so every dimension receives the previous dimension's `axes` hint when `getAxisHints` is non-empty. Masked by name-list truncation. | open |
| 7 | `BlueskyRun.getRunKeys` ends with `ykeys[1] = all_keys`, so rank-3 camera keys are reported as rank 1 and the two backends disagree about the grouping. | open — own commit |
| 8 | `PlotDataModel.needs_fetch` compares whole requests, so changing a transform triggers a database read. | open — step 3 |

Fixed during this refactor: `RunModel.get_plot_data` raised; normalizing an
N-D y key by a lower-rank norm key raised; `visible_runs` and `visible_models`
disagreed; mesh ND ROI raised on a shape mismatch; image cell bounds ignored
the cell index; plot-axis row labels did not follow a manual reorder; the
trailing-axis default plotted a rank-3 detector against its own column index.

### Open questions

1. **Live data invalidation.** Bundle caches must invalidate on
   `data_changed`. Specify the rule before step B.
2. **Cache status aggregation** discovers `run._chunk_cache.progress` by
   `getattr` chain. Needs a declared interface on `CatalogRun`, or move it to
   the cache layer.
3. **Teardown.** Nothing in the tree has disciplined teardown
   (`codebase_problem_statement.md` §1). The ownership tree makes it possible;
   whether this branch does it is unresolved.
4. **`KeyInfo.hinted` semantics** — confirm `get_hinted_keys` produces the set
   the "Show All Keys" checkbox was meant to toggle (bug 4).
5. **Fan-out API** for the image grid. When added it lives on `ViewIntent`,
   enumerating INDEX values along one reduce axis.
6. **`DisplayManager` is nearly `AppModel`.** The remaining difference is
   catalog creation and selection, which `CatalogSwitcher` reaches around to
   get. Worth resolving when step F touches the presenter.

## Reference documents

Not sub-plans; not on the critical path. Kept because nothing else covers
them.

- **[`codebase_problem_statement.md`](codebase_problem_statement.md)** — the
  ranked problem inventory. Still the backlog. Item 2 (display vs storage) is
  what steps 3 and 4 close; item 7 (domain policy in views) is what step C
  closes.
- **[`structural_remediation_plan.md`](structural_remediation_plan.md)** —
  its steps 3–8 are superseded (they plan folder splits this refactor
  cancels). **Steps 2 and 9–12 are live and independent**: CI and the
  ownership guard, the data-layer contract, the `ChunkCache` split, the
  logging sweep, repo hygiene. They can run in parallel with everything here.
- **[`headless_testing_plan.md`](headless_testing_plan.md)** — test tiers.
  Phases 0–2 done, 3–4 open. Note the hard constraint: the suite runs on
  `QCoreApplication`, so **constructing a `QWidget` in `tests/` aborts the
  interpreter**. Move logic model-side to test it, or drive it from a scratch
  script under a real `QApplication`.
- **[`zarr_l2_cache_plan.md`](zarr_l2_cache_plan.md)** — cache internals,
  phase 2+ open.
- Feature plans, untouched by this refactor and blocked on it:
  [`roi_workbench_plan.md`](roi_workbench_plan.md),
  [`roi_analysis_plan.md`](roi_analysis_plan.md),
  [`band_projection_plan.md`](band_projection_plan.md),
  [`derived_spectra_plan.md`](derived_spectra_plan.md).

## Modification log

| Date | Change |
|------|--------|
| 2026-09-08 | Written. Absorbs the live parts of `model_core_refactor_plan.md`, `plot_session_list_adapter_plan.md`, `model_ownership_headless_plan.md`, `plot_package_reorganization.md` and `layout.md`, all deleted in the same commit and recoverable from `57f6d7b`. |
