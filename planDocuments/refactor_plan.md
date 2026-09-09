# Refactor plan

The single entry point for the model-layer refactor. This document holds the
goal, the invariants, and the order of work. **Detail lives in the sub-plans**
— keep this file short enough to read before every session.

**Status:** in progress on branch `mesh-transpose-removal` off `image_viewing`.
Suite green at 351 tests.

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
   `session.roi_set`, `session.ensure_trace(...)`.
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
| A | `PlotSession` / `RunListItemModel` rename and move | session & traces | ✅ `5330b81` |
| 5 | Invert the dependency, delete `cube_view.py` | view pipeline | ✅ `e0d2ef1` |
| B | `Trace` | session & traces | ✅ `0aaa133` |
| 6 | Adopt `ViewIntent` | view pipeline | ✅ `505240d` |
| C | Consumer sweep — canvas renders the `TraceSet` | session & traces | ✅ `940d45c` |
| G | `ViewIntent` becomes a model | session & traces | ✅ `63a73f0` |
| D | `RegionController` — crop and ROI are one child | session & traces | ✅ `aba26a3` |
| H | `RunCollection` / `Selection` become models | session & traces | ✅ `85e653b` |
| E | `FrozenRun` / `CombinedRun` become data sources | session & traces | ✅ `766f983` |
| 7 | `plot_bundle.py` | view pipeline | next |
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

Step B moved the artist off the trace, which is what problem-statement
item 6 was blocking on. Two things the sub-plan had left open were only
answerable while writing it: a bundle cache that survives hide/show has to be
invalidated by the run's `data_changed`, not by the request; and a session
that cannot touch artists cannot dispose one, so removal is announced by
`TraceKey` and the canvas performs it. Its `EXPECTED_VIOLATIONS` exit
criterion moved to step C, which is the step that deletes the construction it
names.

Step 6 adopted `ViewIntent` rather than deleting it, but the plan's stated
payoff — mixed-rank bugs 2 and 3 — was already banked by steps 3–4. The real
defect was that the orientation policy had two implementations, and the one
the maintainer chose lived in a widget. The step also had an omitted decision:
`ViewIntent.axis_order` was a rank-bound permutation, so projecting onto
another rank silently discarded the user's orientation — the same bug inside
the type meant to fix it. Axis order is now dimension names plus the X
selection it follows, resolved by one function.

Step C was re-scoped before starting rather than after, then narrowed again.
Two of its six bullets were already closed by step 6 — `DimensionControl`'s
spec ownership, which step 6 had to take to move the axis-order policy out of
a widget, and the 2-D `QMessageBox`, which step 6 *reversed*:
`accepts_plot_ndim` tests how many artists are visible, a fact only the canvas
holds, so relocating it would re-add the artist state step B spent its diff
deleting. Its stated payoff (mixed-rank bugs 2 and 3) was banked by step 3.

The remaining sequence was re-derived on 2026-09-09 rather than executed as
written. Step D said "extract the ROI pipeline" and "keep thin delegating
methods so view call sites are unchanged" — the second half is the forwarding
layer this refactor exists to avoid, and it is affordable to drop because
every heavyweight ROI member has exactly one caller. Working out *why* it was
written that way surfaced the real question, which is what the session is: 94
public members whose consumers partition almost perfectly by concern, and five
`__init__` connections where the session subscribes to its own signals because
there is no second object to talk to. Those five name the missing children.

Two candidate children turned out to be category errors — `ChunkCacheProgress`
is owned by the run and `TiledFetchStatus` is a plain dataclass — and two
turned out to be one: crop and ROI share a lifecycle, a fingerprint, and two
invalidation methods, and holding them apart is what produced the duplication.
Steps G, D and H follow; the sub-plan carries the reasoning and the rules.

Of the four bullets that survived, only the `single_canvas` one shipped. The
image grid is due for a rewrite once the canvas stabilizes, so its bypass and
duplicated shape discovery wait for that — and with them `ViewIntent.fan_out`,
which should be designed against the rewrite rather than retrofitted. The
`"time"`-first key sort stays in `RunDisplayWidget`: ordering keys for display
is not domain policy, and that area is due to grow a sort-by-dimensionality
rule. What landed is the real find — `_do_update_plot` was a second
implementation of `PlotSession._retained_trace_keys`, and the canvas now reads
the session's `TraceSet` instead of rebuilding it every 100 ms.

Step 5 named the types to delete but no destination for the fifteen live
functions in `cube_view.py` that were not types. The import graph settled it —
spec queries to `view_spec.py`, materialize to `plot_bundle.py` — and the two
deviations it forced are recorded in the sub-plan rather than absorbed
silently: `materialize_view` takes a `Projection`, and `build_plot_request`
was renamed rather than deleted.

## Shared backlog

### Bugs found during analysis

Recorded regardless of whether the step that fixes them lands.

| # | Bug | Status |
|---|-----|--------|
| 1 | `CombinedRunSource` does not override `get_plot_bundle`; the inherited path reads `self._run`, set to `runs[0].run`. Combining plots the first run. Silent wrong answer. | open — step E |
| 2 | ROI mask applied in display order to a storage-order array; ND ROI profiles are wrong by an upside-down mask. | ✅ step 3 (`dbe6083`) |
| 3 | `fetch_context` applies a display bbox directly onto storage slices; three of four axis orientations fetch the wrong block. | ✅ step 3 (`dbe6083`) |
| 4 | "Show All Keys" is a no-op. `RunDisplayWidget._show_all` is written and never read. Intended backing is `CatalogRun.get_hinted_keys`, which has zero callers. | open |
| 5 | Unlinked mode double-lists synthetic keys — `available_keys` is catalog plus frozen, so a frozen spectrum gets a catalog row with an X checkbox it should not have. | open |
| 6 | `BlueskyRun._infer_dims_from_shape` uses `range(0, ndim)` where `MemoryRun` uses `range(1, ndim)`, so every dimension receives the previous dimension's `axes` hint when `getAxisHints` is non-empty. Masked by name-list truncation. | open |
| 7 | `BlueskyRun.getRunKeys` ends with `ykeys[1] = all_keys`, so rank-3 camera keys are reported as rank 1 and the two backends disagree about the grouping. | open — own commit |
| 8 | `Trace.needs_fetch` compares whole requests, so changing a transform triggers a database read. | open — moved to step 7. Step 3 sent it to step 4 expecting `cached_plane` to carry it; that was the wrong plane. `cached_plane` is a *packed, post-transform* bundle that `reduce_cached_plane` can only mask down to an ROI profile. Re-applying a transform needs the array as it stood *before* `apply_transform`, which nothing keeps, plus a `needs_fetch` that compares `FetchPlan`s rather than whole requests. Both belong with the step that moves the transform stage. |
| 9 | `RunListView` passed its item model where `DisplayControlWidget` expects a presenter, so constructing any `RunListView` raised `AttributeError`. No test could reach it — the suite cannot build a `QWidget`. | ✅ step A (`5330b81`) |
| 10 | `widgets/kafkaViewerTab.py:68` calls `PlotWidget(run_list_model, plot_model)` against a `(presenter, panel, ...)` signature; raises `TypeError`, so the Kafka tab cannot open. Same class as bug 9. | open — `widgets/` is out of scope (invariant 6) |
| 12 | ✅ Every reduce-slider tick on a 3-D dataset destroys the image artist, the colorbar and any live ROI or crop selector, then rebuilds them. `MplCanvas._prepare_2d_axes` diffs the whole `ViewIntent` against `_last_2d_intent`, so a `reduce_indices` change resets the axes even though the plot plane's coordinate frame did not move. Reproduced under a real `QApplication` with a 4x5x6 cube. | ✅ step G (`63a73f0`) |
| 11 | Deselecting a key left its label in the legend. `PlotSession._dispose_plot_data` popped the trace and called `plot_data.clear()`, so the artist left the axes but the trace was gone from the map before `_do_update_plot` iterated it — the canvas removal branch never ran, and only the *add* path rebuilt the legend. Hiding and removing runs looked fine because both have their own `updateLegend` calls. | ✅ `6d2b3ef` — `_do_update_plot` rebuilds the legend before painting |

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
   `getattr` chain — three private hops through two layers. Needs a declared
   interface on `CatalogRun`, or a move to the cache layer.
   **Deferred by decision (2026-09-09), and deliberately not a `PlotSession`
   child.** `ChunkCacheProgress` is owned by the run, one per run;
   `TiledFetchStatus` is a plain dataclass carried by a signal. The session
   holds neither — it aggregates, and the aggregation is what should move.
   Blocked on a general progress / error / status interface, which does not
   exist yet; the session keeps `_progress_sources`, `_cache_statuses` and
   `cache_status_changed` until it does. **Come back to this** once that
   interface lands.
3. **Teardown.** Nothing in the tree has disciplined teardown
   (`codebase_problem_statement.md` §1). The ownership tree makes it possible;
   whether this branch does it is unresolved.
4. **`KeyInfo.hinted` semantics** — confirm `get_hinted_keys` produces the set
   the "Show All Keys" checkbox was meant to toggle (bug 4).
5. **Fan-out API** for the image grid. When added it lives on `ViewIntent`,
   enumerating INDEX values along one reduce axis. **Deferred to the
   `ImageGridCanvas` rewrite** (see step C) — designing it against today's
   bypass would retrofit an API onto code that is about to be replaced.
6. **`DisplayManager` is nearly `AppModel`.** The remaining difference is
   catalog creation and selection, which `CatalogSwitcher` reaches around to
   get. Worth resolving when step F touches the presenter.

## After this refactor

One thread is deliberately deferred rather than folded into a step.

**Widget-level testing — the next piece of work once the tree stops moving.**
Bugs 9, 10 and 11 were all live crashes or visible misbehaviour that `tests/`
could not reach at the time: the suite ran on `QCoreApplication`, so
constructing a `QWidget` aborted the interpreter. Every one of them was found
by hand or with a throwaway script under a real `QApplication`. Three in one
step is a pattern, not luck — and bug 9 meant the main run list could not be
constructed at all, which no amount of model-side coverage would have caught.

**Partly unblocked 2026-09-09 (`9a567db`).** The obstacle was not structural.
`conftest.py` created a `QCoreApplication`, and a `QWidget` under one makes Qt
call `abort()` — SIGABRT, not a catchable exception, so one widget test would
kill the run. Swapping the fixture to a real `QApplication` on the offscreen
platform (a subclass, so no model test is affected) removes it, with
`QT_QPA_PLATFORM` set in `conftest` before qtpy imports Qt. Nothing outside
pytest is required. The fixture is `autouse` because a widget test that forgets
it aborts the run exactly as before.

Three tests landed with it, each pinning a contract previously verified only by
an uncommitted script, and each mutation-checked: the canvas draws traces the
session created (step C), hide/show keeps the artist and does not refetch
(step B), and the ROI window constructs and populates itself (bugs 9 and 10's
class). Suite 389 → 392.

What remains deferred is the *harness*, not the enabler: a broad widget suite
pinned to today's constructors would still be rewritten by step F. Decide the
general approach then, and give it a plan of its own. Options worth weighing:

- ~~A second pytest process, or an `xdist` group, running under a real
  `QApplication`~~ — **not needed.** One `QApplication` serves both; the two
  tiers coexist in one process without either constraining the other.
- A construction smoke test that builds every top-level widget once. That
  alone would have caught bugs 9 and 10; `test_widgets.py` now does it for
  `RoiWindow` and `MplCanvas`, and extending it to the rest is cheap.
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
  what steps 3 and 4 close. Item 7 (domain policy in views) is mostly gone:
  the `DimensionControl` bullet fell to step 6 and the
  `MplCanvas._do_update_plot` bullet to step C. Two of the remaining three
  are not defects — `run_display.py`'s key sort is display, and
  `views/catalog/base.py`'s proxies are invariant 1's carve-out — so item 7
  reduces to the `ImageGridCanvas` bullet, which its rewrite absorbs.
- **[`structural_remediation_plan.md`](structural_remediation_plan.md)** —
  its steps 3–8 are superseded (they plan folder splits this refactor
  cancels). **Steps 2 and 9–12 are live and independent**: CI and the
  ownership guard, the data-layer contract, the `ChunkCache` split, the
  logging sweep, repo hygiene. They can run in parallel with everything here.
- **[`headless_testing_plan.md`](headless_testing_plan.md)** — test tiers.
  Phases 0–2 done, 3–4 open. **The constraint it records is lifted**
  (`9a567db`): the suite ran on `QCoreApplication`, where constructing a
  `QWidget` aborts the interpreter, and now runs on an offscreen
  `QApplication`. Widget tests belong in `tests/test_widgets.py`; a model-side
  test is still preferable whenever the behaviour can be reached without a
  widget. What remains open there is the shape of a broad widget suite, per
  "After this refactor" above.
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
| 2026-09-08 | Step 3 landed (`dbe6083`); bugs 2 and 3 closed, bug 8 moved to step 4. Step 4 is next. |
| 2026-09-08 | Step 4 landed (`b431c47`); `derived_fetch.py` and `view_crop.py` deleted, steps B and D unblocked, step 5 next. Bug 8 not closed and moved on to step 7 with the reason. A profile-axis / reduction-axis inversion was found and fixed en route. |
| 2026-09-08 | Step A landed (`5330b81`), net −77 lines. Compatibility aliases dropped rather than held for a commit, which also empties step F's alias list. The item model moved to `views/` and `RunListView` now constructs it, so `models/` imports no view code. Bugs 9 and 10 added; 9 closed. Step 5 remains next. |
| 2026-09-08 | Bug 11 fixed (`6d2b3ef`): the legend kept labels for deselected keys. One `updateLegend()` before the paint in `_do_update_plot`. Reproduced and verified with a scratch script under a real `QApplication`; `tests/` cannot reach it, since `MplCanvas` is a `QWidget`. |
| 2026-09-08 | Recorded widget-level testing as the work that follows this refactor, under "After this refactor". Three bugs in one step (9, 10, 11) were unreachable from `tests/`; deferred deliberately so the harness is not written against constructors steps B–F will change. |
| 2026-09-08 | Step 5 landed (`e0d2ef1`). `cube_view.py` (1212 lines) deleted, `ViewSpec` renamed `Projection`, `models/plot/` 20 → 19 files and 5093 → 4960 code lines. Behaviour-preserving; 19 test modules retargeted against the 14 the plan priced. Steps B and 7 are unblocked and 6 needs B, so B is next. |
| 2026-09-09 | Step C audited against the tree before starting. Two bullets superseded by step 6 (one closed, one reversed) and its payoff banked by step 3; the sub-plan records which and why. Four live bullets remain: the canvas x × y × run product, the `ImageGridCanvas` `Trace` bypass, `_get_shape_info`, and the `time`-first sort plus `_make_slice_info`. Open question 5 (`ViewIntent.fan_out`) is now on step C's critical path, not optional. |
| 2026-09-09 | Step C landed (`940d45c`), narrowed to `single_canvas`. `MplCanvas._do_update_plot` was recomputing `PlotSession._retained_trace_keys` and calling `ensure_trace` a second time; it now renders the session's `TraceSet` and decides only visibility. `updatePlotData` and `remove_run_data` deleted; `Trace.dispose` gained the outgoing-signal disconnect the latter had owned. The image grid and `RunDisplayWidget` are deferred by decision — the grid to its own rewrite, which also absorbs open question 5 and the last live half of problem-statement item 7. Suite 361 → 362; `single_canvas.py` 1695 → 1667. |
| 2026-09-09 | Remaining sequence re-derived before starting step D, and the target ownership tree rewritten. Step D as written mandated delegating wrappers, which is the forwarding layer the refactor exists to avoid; asking why surfaced the object-boundary question behind it. Outcome: crop joins the ROI controller (one lifecycle, one fingerprint), `RoiSetModel` stays a sibling (22 of 23 members have external consumers), `ViewIntent` / `RunCollection` / `Selection` become emitting models, and cache aggregation is neither a child nor in scope. New order G, D, H, E, 7, F. Bug 12 found and confirmed while designing G's signals. |
| 2026-09-09 | Step G landed (`63a73f0`). `ViewIntent` is a `QObject` with three signals derived from consumers, not fields; `cube_view_changed` and `MplCanvas._last_2d_intent` are gone. Bug 12 closed and verified both ways under a real `QApplication`. `Projection` and `PlotRequest` stay frozen. One decision the plan had not predicted: `project()` needed a `plot_ndim` override, because the mixed-rank path built a throwaway intent that a mutable model cannot supply. Suite 362 → 374; `view_spec.py` 1018 → 777 with 445 new lines in `view_intent.py`. |
| 2026-09-09 | Step D landed (`aba26a3`). Crop and ROI are one child, `RegionController`, handed out as `session.region` with no delegating methods — 110 references retargeted instead. Two things the plan had not predicted: `cached_parent_bundle_for_preview` was deleted rather than moved, because `_refresh_held_requests` is now wired to every view-change signal and its equality check can no longer fail; and the three-way crop collapse turned out to be one method, since guarding `set_view_crop` on real change is what makes `clear_view_crop` redundant. `MplCanvas.current_view_fingerprint` and `_last_2d_view_crop` deleted. `plot_session.py` 2045 → 1263. Suite 380 → 389. |
| 2026-09-09 | Widget testing partly unblocked (`9a567db`). The `QCoreApplication` fixture, not pytest, was what made `QWidget` construction impossible — a widget under one aborts the process rather than failing a test. `qapp` is now an autouse `QApplication` on the offscreen platform; 389 existing tests unaffected. Three mutation-checked widget tests landed. `headless_testing_plan.md` phases 3–4 keep the harness question; the enabler is done. |
