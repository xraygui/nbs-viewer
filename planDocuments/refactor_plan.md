# Refactor plan

The single entry point for the model-layer refactor. This document holds the
goal, the invariants, and the order of work. **Detail lives in the sub-plans**
— keep this file short enough to read before every session.

**Status:** in progress on branch `mesh-transpose-removal` off `image_viewing`.
Suite green at 350 tests.

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
| 3 | Orientation once after load, one planner, one mask | view pipeline | ✅ `dbe6083` |
| 4 | One request, no side channels | view pipeline | ✅ `b431c47` |
| A | `PlotSession` / `RunListItemModel` rename and move | session & traces | ✅ |
| 5 | Invert the dependency, delete `cube_view.py` | view pipeline | next |
| B | `Trace` | session & traces | unblocked |
| 6 | Adopt `ViewIntent`, or delete it | view pipeline | after 5, needs B |
| C | Consumer sweep — canvas `TraceSet`, `DimensionControl` pushes intent | session & traces | after 6 |
| D | Extract the ROI pipeline off the session | session & traces | unblocked |
| E | Re-home `CombinedRunSource` / `FrozenRunSource` | session & traces | independent |
| 7 | `plot_bundle.py` | view pipeline | after 5 |
| F | Final deletions and renames | session & traces | last |

Step 3 could not be sliced: the fetch narrowing and the ROI mask were wrong
in ways that cancelled, so fixing one alone made things worse. It landed as
one non-behaviour-preserving commit; see the view pipeline plan's findings,
including the one decision point the plan had not predicted.

Step 4 shipped its own content in full but **did not close bug 8**, which
step 3 had moved into it on a wrong premise; see the bug table.

Step A was a rename, but the plan's mechanics for it contradicted invariant 1:
having `PlotPresenter` construct the item model would have made `models/`
import `views/`. `RunListView` builds it instead. Counting consumers is what
settled it, and the count also found bugs 9 and 10; see the sub-plan.

## Shared backlog

### Bugs found during analysis

Recorded regardless of whether the step that fixes them lands.

| # | Bug | Status |
|---|-----|--------|
| 1 | `CombinedRunSource` does not override `get_plot_bundle`; the inherited path reads `self._run`, set to `runs[0].run`. Combining plots the first run. Silent wrong answer. | open — step E |
| 2 | ROI mask applied in display order to a storage-order array; ND ROI profiles are wrong by an upside-down mask. | ✅ step 3 |
| 3 | `fetch_context` applies a display bbox directly onto storage slices; three of four axis orientations fetch the wrong block. | ✅ step 3 |
| 4 | "Show All Keys" is a no-op. `RunDisplayWidget._show_all` is written and never read. Intended backing is `CatalogRun.get_hinted_keys`, which has zero callers. | open |
| 5 | Unlinked mode double-lists synthetic keys — `available_keys` is catalog plus frozen, so a frozen spectrum gets a catalog row with an X checkbox it should not have. | open |
| 6 | `BlueskyRun._infer_dims_from_shape` uses `range(0, ndim)` where `MemoryRun` uses `range(1, ndim)`, so every dimension receives the previous dimension's `axes` hint when `getAxisHints` is non-empty. Masked by name-list truncation. | open |
| 7 | `BlueskyRun.getRunKeys` ends with `ykeys[1] = all_keys`, so rank-3 camera keys are reported as rank 1 and the two backends disagree about the grouping. | open — own commit |
| 8 | `PlotDataModel.needs_fetch` compares whole requests, so changing a transform triggers a database read. | open — moved to step 7. Step 3 sent it to step 4 expecting `cached_plane` to carry it; that was the wrong plane. `cached_plane` is a *packed, post-transform* bundle that `reduce_cached_plane` can only mask down to an ROI profile. Re-applying a transform needs the array as it stood *before* `apply_transform`, which nothing keeps, plus a `needs_fetch` that compares `FetchPlan`s rather than whole requests. Both belong with the step that moves the transform stage. |
| 9 | `RunListView` passed its item model where `DisplayControlWidget` expects a presenter, so constructing any `RunListView` raised `AttributeError`. No test could reach it — the suite cannot build a `QWidget`. | ✅ step A |
| 10 | `widgets/kafkaViewerTab.py:68` calls `PlotWidget(run_list_model, plot_model)` against a `(presenter, panel, ...)` signature; raises `TypeError`, so the Kafka tab cannot open. Same class as bug 9. | open — `widgets/` is out of scope (invariant 6) |
| 11 | Deselecting a key left its label in the legend. `PlotSession._dispose_plot_data` pops the trace and calls `plot_data.clear()`, so the artist leaves the axes but the trace is gone from `plot_data_map` before `_do_update_plot` iterates it — the canvas removal branch never ran, and only the *add* path rebuilt the legend. Hiding and removing runs looked fine because both have their own `updateLegend` calls. | ✅ `_do_update_plot` now rebuilds the legend before painting |

Fixed during this refactor: `RunModel.get_plot_data` raised; normalizing an
N-D y key by a lower-rank norm key raised; `visible_runs` and `visible_models`
disagreed; mesh ND ROI raised on a shape mismatch; image cell bounds ignored
the cell index; plot-axis row labels did not follow a manual reorder; the
trailing-axis default plotted a rank-3 detector against its own column index;
an ROI reaching past an active crop raised a shape mismatch instead of taking
the intersection; committing a crop read coordinate arrays from the database
it did not need; "span full profile axis" widened the reduction axis instead
of the profile axis whenever the X-key selection put the plot axes out of
storage order, which also inverted the ROI window's full-height / full-width
buttons.

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

## After this refactor

One thread is deliberately deferred rather than folded into a step.

**Widget-level testing — the next piece of work once the tree stops moving.**
Bugs 9, 10 and 11 were all live crashes or visible misbehaviour that `tests/`
structurally cannot reach: the suite runs on `QCoreApplication`, so
constructing a `QWidget` aborts the interpreter. Every one of them was found
by hand or with a throwaway script under a real `QApplication`. Three in one
step is a pattern, not luck — and bug 9 meant the main run list could not be
constructed at all, which no amount of model-side coverage would have caught.

Decide the general approach then, and give it a plan of its own. Options worth
weighing:

- A second pytest process, or an `xdist` group, running under a real
  `QApplication`, so widget tests and headless model tests coexist without
  either constraining the other.
- A construction smoke test that builds every top-level widget once. That
  alone would have caught bugs 9 and 10.
- Pushing more view logic model-side so it needs no widget at all — which is
  what steps B and C already do for the trace set and the canvas, and is why
  waiting is the cheaper order.

Deliberately not a step above: the ownership tree is still moving, and a
harness pinned to today's constructors would have to be rewritten by step F.
`headless_testing_plan.md` phases 3–4 are the natural home for it.

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
  script under a real `QApplication`. Closing this gap properly is the work
  described under "After this refactor" above.
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
| 2026-09-08 | Step 3 landed; bugs 2 and 3 closed, bug 8 moved to step 4. Step 4 is next. |
| 2026-09-08 | Step 4 landed (`b431c47`); `derived_fetch.py` and `view_crop.py` deleted, steps B and D unblocked, step 5 next. Bug 8 not closed and moved on to step 7 with the reason. A profile-axis / reduction-axis inversion was found and fixed en route. |
| 2026-09-08 | Step A landed, net −77 lines. Compatibility aliases dropped rather than held for a commit, which also empties step F's alias list. The item model moved to `views/` and `RunListView` now constructs it, so `models/` imports no view code. Bugs 9 and 10 added; 9 closed. Step 5 remains next. |
| 2026-09-08 | Bug 11 fixed: the legend kept labels for deselected keys. One `updateLegend()` before the paint in `_do_update_plot`. Reproduced and verified with a scratch script under a real `QApplication`; `tests/` cannot reach it, since `MplCanvas` is a `QWidget`. |
| 2026-09-08 | Recorded widget-level testing as the work that follows this refactor, under "After this refactor". Three bugs in one step (9, 10, 11) were unreachable from `tests/`; deferred deliberately so the harness is not written against constructors steps B–F will change. |
