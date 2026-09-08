# Structural remediation plan

> **Superseded in part (2026-09-08).** Steps 3-8 below assume a
> `models/plot/cube/` and `models/plot/roi/` package split.
> [`view_pipeline_plan.md`](view_pipeline_plan.md) deletes those files
> instead of moving them, and owns the view / crop / ROI / fetch stack.
> **Step 2 and steps 9-12 are unaffected and still live** - CI and the
> ownership guard, the data-layer contract, the `ChunkCache` split, the
> logging sweep, and repo hygiene. Nothing else covers those.


Successor to the closed
`[model_ownership_headless_plan.md](model_ownership_headless_plan.md)`.
Addresses the ranked problems in
`[codebase_problem_statement.md](codebase_problem_statement.md)` by
**interleaving** the pending mechanical package moves from
`[plot_package_reorganization.md](plot_package_reorganization.md)` with small
contract changes at the seams those moves open, then cleaning up what folder
moves cannot reach.

Testing infrastructure work continues under
`[headless_testing_plan.md](headless_testing_plan.md)` Phase 3/4; this plan
consumes those fixtures rather than duplicating them.

## Status


| Step | Title                                                            | Status      |
| ---- | ---------------------------------------------------------------- | ----------- |
| 1    | Delete dead code                                                 | Done        |
| 2    | CI safety net + ownership AST guard                              | Not started |
| 3    | Reorg 7a (`roi/`) + `PlotDataModel` public accessors             | Not started |
| 4    | Reorg 7b (`run/`, presenter split) + single key/visibility truth | Not started |
| 5    | Reorg 7c (`cube/` split) + display-vs-storage contract           | Not started |
| 6    | Reorg 7d (`canvas/`, checkboxes) + teardown discipline           | Not started |
| 7    | Move matplotlib artists off `PlotDataModel`                      | Not started |
| 8    | Split the ROI pipeline off `PlotModel`                           | Not started |
| 9    | Enforceable data-layer contract                                  | Not started |
| 10   | Split `ChunkCache`; fix cache concurrency                        | Not started |
| 11   | Logging and exception sweep                                      | Not started |
| 12   | Config, packaging, and repo hygiene                              | Not started |


**Milestones**

- [ ] **D** (after step 2): every subsequent change is gated by CI and the
  ```
  ownership guard
  ```
- [ ] **E** (after steps 3–6): package layout matches the reorg target trees
  ```
  **and** the four P1 structural problems have a single source of truth
  or an explicit contract
  ```
- [ ] **F** (after steps 7–9): a headless plot frontend and a new catalog
  ```
  backend are both addable without editing `views/`
  ```
- [ ] **G** (after steps 10–12): no 2000-line files; failures are visible

## Rules of the road

1. **Deletion before restructuring.** Do not move or rename code that is
  about to be deleted.
2. **Mechanical slices stay mechanical.** A reorg sub-step is `git mv` +
  import updates + thin `__init__.py`. No behavior change, no leak fixes.
   This is inherited from the reorg document and is not reopened.
3. **Each contract sub-step is its own commit** (ideally its own PR)
  immediately after its paired move, while the code is fresh. Never
   combined into the move commit — a reviewer must be able to read a move
   diff as a move.
4. **Every step ships with tests in the same PR.** Prefer closing a row in
  the [connection matrix](headless_testing_plan.md#connection-coverage-matrix)
   over adding an isolated unit test.
5. `**pytest tests/` green after every commit**, not merely every step. The
  suite is 247 tests in 9.5 s; there is no excuse for batching.
6. **Ownership rules from the closed plan still hold**: only models create
  domain models; domain code stays under `models/`; H1 means no `QtWidgets`
   under `models/`; `widgets/` is out of scope.
7. **Do not widen a step to fix an adjacent smell.** Record it in the problem
  statement and let a later step own it. The problem statement is the
   backlog.
8. **Update the reorg document's status table** as slices land, and correct
  its stale entries (7a/7d are partially done — see step 3).

---

## Step 1 — Delete dead code

**Status:** Done

**Depends on:** nothing

Pure removal. Chosen first because it is the cheapest complexity reduction
available, it shrinks every diff that follows, and it means steps 3–6 do not
move code that should not exist. It is safe to precede CI (step 2) because
every sub-step is verified by the local suite; run `pytest tests/` before and
after each commit.

Evidence and reachability for every item below is recorded in the problem
statement under **Dead and near-dead code**.

### Do

**1a — Cache L1 dict path (~330 lines)**

The dict-based L1 has two dead roots. `get_data` →
`_get_data_l2_pipeline` never calls `_try_get_data_from_l2_tiles`, and
`_finish_slab_fetch` seeds Zarr, not L1.

- [x] Remove `_try_get_data_from_l2_tiles` (`:214–254`)
- [x] Remove `_seed_l1_tiles_from_slab` (`:1241–1329`)
- [x] Remove `_store_tile` (`:1331–1395`), `_store_seeded_tile`
  ```
  (`:1626–1653`), `_evict_lru_l1_tile` (`:1456–1469`),
  `_update_l1_tile_access` (`:1453–1454`) — reachable only from the
  dead roots
  ```
- [x] Remove `_drop_partial_l1_tile` (`:970–982`) and its live call site in
  ```
  `_commit_complete_l2_tile` (`:968`), which becomes a no-op
  ```
- [x] Remove `flush_l1_to_l2` (`:2014–2065`) **and** its only caller,
  ```
  `tests/test_chunk_cache.py:153`
  ```
- [x] Remove attributes `self.tiles`, `partial_l1_tiles`,
  ```
  `l1_tile_access_times`, `l1_tile_size` and their bookkeeping in
  `clear`, `clear_run`, `get_stats`, `format_debug_report`
  ```
- [x] Remove the L1 section of `test/test_catalog.py` (manual script,
  ```
  `:544–576`) — it is the only other consumer
  ```
- [x] Update the class docstring (`:34–35`) which currently explains the
  ```
  retained-but-unused L1
  ```
- [x] **Keep** `_extract_tile_from_slab` and `_align_seed_slab` — both have
  ```
  live call sites (`:942` and six sites respectively)
  ```

**1b — Zero-caller symbols**

- [x] Remove `MplCanvas._debug_plot_state` (`single_canvas.py:1633`, 111
  ```
  lines, 29 prints, no caller). This also removes the last reader of
  `DEBUG_VARIABLES["PRINT_DEBUG"]` in that file.
  ```
- [x] Remove `BlueskyRun._check_data_access` (`data/bluesky.py:88`). Record
  ```
  the `_has_data=None` bug it was meant to prevent as step 9 scope; do
  **not** fix `getData` here.
  ```
- [x] Remove the `plot_data_removed` signal (`plotModel.py:80`) and its emit
  ```
  (`:615`). Zero `.connect` sites exist. If a later step needs removal
  notification it can reintroduce it **with** a consumer.
  ```
- [x] Remove `RunListModel._initialize_runs` (`:68–73`) and its `__init__`
  ```
  call — it iterates `available_runs` when `_run_models` is `{}`.
  ```

**1c — Commented-out and stub code**

- [x] Remove the 28-line commented menu block in `viewer.py:64–91` (a bare
  ```
  `"""` literal wrapping Save Plot / Export Data / Print actions). Their
  handlers, if any, go with them; export belongs to a future frontend
  step, not a dead menu item.
  ```
- [x] Remove the three "not implemented yet" stubs in `mainWidget.py:202–221`
  ```
  (`duplicate_current_display`, `save_display_layout`,
  `apply_display_settings`) and any menu wiring that reaches them.
  ```
- [x] Remove commented debug prints in `run_display.py`, `catalog/base.py`,
  ```
  `runListView.py`, `catalog/kafka.py`, `runSource.py:50`, `:838`,
  `runListModel.py:510`, and the `combinedRunModel.py:264` TODO stub body.
  ```
- [x] Remove unread base caches `_plot_data_cache` / `_dimensions_cache`
  ```
  (`data/base.py:43–44`) and their `clear_caches` bookkeeping.
  ```

**1d — Fix the one latent bug in this territory**

- [x] Add a `dynamic_update` property to `RunModel` returning `self._dynamic`.
  ```
  `RunListModel.dynamic_update` (`:281–283`) reads it and
  `plot_settings.py:85` reads that, so it raises `AttributeError` as soon
  as it is read with a run present. Two lines; restores the obvious
  intent rather than deleting user-facing UI.
  ```

### Non-goals

- No renames, no file moves, no package changes (steps 3–6)
- Do **not** split `ChunkCache` (step 10) — only delete from it
- Do **not** fix `_has_data`, `scanFinished`, or any other data-layer
contract bug (step 9)
- Do **not** start the broader print / except sweep (step 11); only remove
prints that leave with deleted code
- Do **not** collapse near-duplicate APIs (`add_run` / `add_runs` etc.) —
those are renames with call-site churn, better paired with steps 3–6

### Testing goals

- [x] `pytest tests/` green after each of 1a–1d
- [x] Cache suite (`test_chunk_cache`*, `test_l2_`*, `test_zarr_l2_cache`,
  ```
  `test_hyperslab_batches`) green after 1a with only the `flush_l1_to_l2`
  test removed — no other cache test should need changes. If one does,
  the reachability analysis was wrong; stop and re-verify.
  ```
- [x] `ChunkCache.get_stats()` / `format_debug_report()` still return without
  ```
  `KeyError` after L1 keys are dropped
  ```
- [x] New unit: `RunListModel.dynamic_update` returns a bool with one run
  ```
  present (regression for 1d)
  ```
- [x] Manual: launch the GUI, load a 2-D run, page an image grid — confirm no
  ```
  `AttributeError` from removed L1 state
  ```

### Exit criteria

- [x] `chunkCache.py` under ~1810 lines; no `self.tiles` reference remains
- [ ] `rg "_debug_plot_state|_check_data_access|plot_data_removed|_initialize_runs" nbs_viewer/`
  ```
  returns nothing
  ```
- [x] No commented-out code blocks remain in `viewer.py` or `mainWidget.py`
- [x] Step status → Done; problem-statement dead-code inventory struck through

---

## Step 2 — CI safety net + ownership AST guard

**Status:** Not started

**Depends on:** step 1 (so CI does not immediately need updating)

Everything after this step is a refactor. Refactors without CI are how a
green local suite becomes a broken `main`. Today the only workflow is
`python-publish.yml` on release.

### Do

- [ ] Add `.github/workflows/test.yml` running `pytest tests/` on push and
  ```
  pull request. Use pixi (`pixi run pytest tests/`) to match local
  invocation; the suite needs no display and no network.
  ```
- [ ] Move `pytest` out of `[project] dependencies` into a dev/test feature
  ```
  so end users do not install the test runner
  ```
- [ ] Track `.flake8` (currently untracked) or replace it with a `[tool.ruff]`
  ```
  section, and add a lint job. Pick one; do not ship both configs.
  ```
- [ ] Add `tests/test_model_ownership.py` — the AST constructor-call guard
  ```
  specified in
  `[headless_testing_plan.md](headless_testing_plan.md#ownership-guard--current-state-vs-phase-3)`,
  with `EXPECTED_VIOLATIONS` seeded to the single `PlotDataModel(` hit in
  `views/plot/mplCanvas/image_grid_canvas.py`
  ```
- [ ] Remove the three inline AST scans from
  ```
  `test_run_list_combine_freeze.py`, `test_plot_model_step3.py`, and
  `test_roi_preview_commit.py`
  ```
- [ ] Extend the guard to flag `views/` importing `_`-prefixed model symbols,
  ```
  seeded with the known hits from the reorg document's **Private model
  APIs used by views** table
  ```

### Non-goals

- No pytest-qt / GUI automation in CI (testing plan Phase 4)
- No coverage gates or matrix builds; one Python version is enough
- Do not fix the private-API violations here — only inventory them so
steps 3–6 can shrink the set

### Testing goals

- [ ] CI runs and passes on a trivial PR
- [ ] CI **fails** on a PR that adds a fake `RoiSetModel(` in a view
- [ ] Ownership guard fails when a listed violation is cleared without
  ```
  updating `EXPECTED_VIOLATIONS`
  ```
- [ ] Type-annotation-only model imports in views do not trip the guard

### Exit criteria

- [ ] `pytest tests/` gates every PR
- [ ] `EXPECTED_VIOLATIONS` has exactly one constructor entry
- [ ] Private-import expected-set exists and only shrinks from here
- [ ] Step status → Done; **Milestone D**

---

## Step 3 — Reorg 7a (`roi/`) + `PlotDataModel` public accessors

**Status:** Not started

**Depends on:** step 2

**First: correct the reorg document.** It marks 7a and 7d "Not started", but
`views/plot/roi/` already exists holding `window.py`, `types.py`,
`overlays.py`, `preview_canvas.py`, and `RoiController` / `RoiPanel` /
`RoiPreviewController` are gone as separate modules. `views/plot/mplCanvas/`
also exists. Re-inventory before moving anything.

### Do

**3a — Mechanical (from reorg slice 7a)**

- [ ] Re-verify what remains of 7a and update that document's status table
- [ ] Create `models/plot/roi/` and move `region.py`, `region_mesh.py`,
  ```
  `region_reduce.py`, `roi_set.py`, `derived_fetch.py`,
  `frozen_spectrum.py`; fix relative imports
  ```
- [ ] Thin `models/plot/roi/__init__.py` with the public set named in the
  ```
  reorg document
  ```
- [ ] Update `tests/` imports; do not add shims

**3b — Contract: stop views poking `PlotDataModel` privates**

The seam this move opens is the ROI view/model boundary, where the private
reach-through is worst.

- [ ] Add read-only properties to `PlotDataModel`: `key`, `run`, `xkey`,
  ```
  `ykey`, `indices`, `cube_view_spec`
  ```
- [ ] Replace `plot_data._key` / `._run` / `._ykey` / `._xkey` / `._indices`
  ```
  / `._cube_view_spec` in `views/plot/roi/window.py`,
  `views/plot/mplCanvas/single_canvas.py`, and
  `views/plot/mplCanvas/image_grid_canvas.py`
  ```
- [ ] Promote `cube_view._fetch_plot_plane_storage_axes` (`:159`) to public,
  ```
  or point its callers at the existing public
  `derived_fetch.plot_plane_storage_axes` (`:31`) /
  `plot_plane_storage_axes_for_frame` (`:45`), which appear to be the
  same idea already exposed
  ```
- [ ] Promote `derived_fetch._profile_uses_nd_load` (`:273`). Note this is
  ```
  **not** a view leak any more — the only cross-module importer is
  `plotModel.py:38`, since `RoiPreviewController` no longer exists. It is
  a private import across two model modules; make it public as part of
  the `roi/` package boundary rather than as a leak fix.
  ```
- [ ] Replace `dimension_control._dim_names` reach-through from
  ```
  `RoiWindow._dimension_axis_names` (`window.py:317–321`) with a public
  accessor or a model-derived name list
  ```
- [ ] Fix the `PlotDataModel.__init__` docstring, which still says
  ```
  `parent : QWidget`
  ```
- [ ] Shrink the step-2 private-import expected set accordingly

### Non-goals

- Do **not** extract ROI drawing from `MplCanvas` (reorg 7e / step 6)
- Do **not** move `view_crop.py` (stays at `plot/` root, per reorg decision)
- Do **not** move artists off `PlotDataModel` yet (step 7) — only expose
read-only accessors
- Do **not** change any ROI numerics

### Testing goals

- [ ] `from nbs_viewer.models.plot.roi import RoiSetModel, RectRegion` works
- [ ] ROI suite green: `test_roi_set`, `test_region`, `test_region_mesh`,
  ```
  `test_roi_preview_commit`, `test_roi_wiring`, `test_derived_fetch`,
  `test_frozen_spectrum`
  ```
- [ ] Ownership guard private-import set has shrunk
- [ ] Manual: draw an ROI, preview, commit, confirm the synthetic key appears

### Exit criteria

- [ ] `models/plot/roi/` matches the reorg target tree
- [ ] No `plot_data._`-prefixed access remains under `views/`
- [ ] Reorg document 7a status → Done, with real content
- [ ] Step status → Done

---

## Step 4 — Reorg 7b (`run/`, presenter split) + single key/visibility truth

**Status:** Not started

**Depends on:** step 3

This is the highest-value contract pair. Problem-statement item 3 names
selected keys and visibility as the two duplicate-state pairs that cost the
most, and both live in the files this slice moves.

### Do

**4a — Mechanical (from reorg slice 7b)**

- [ ] `models/plot/run/` for `run_model.py`, `run_list_model.py`,
  ```
  `combined_run_model.py`, `frozen_run_model.py`; thin `__init__.py`
  ```
- [ ] Split `displayManager.py` → `presenter.py` + `presenter_manager.py`
  ```
  (class names unchanged; `presenter.py` already exists — merge, do not
  duplicate)
  ```
- [ ] Rename `plotModel.py` → `plot_model.py`, `plotDataModel.py` →
  ```
  `plot_data_model.py`
  ```
- [ ] Sweep imports in `AppModel`, views, tests, and
  ```
  `widgets/kafkaViewerTab.py` (import path only — no behavior change
  there, per ownership rule 6)
  ```

**4b — Contract: one source of truth for selected keys**

- [ ] Delete the `RunModel.set_selected_keys` sync bridge documented as
  ```
  temporary since Step 3 of the ownership plan
  ```
- [ ] Remove `RunModel._selected_x/_y/_norm` and `RunModel.get_selected_keys`
- [ ] Point every reader at `PlotModel.get_selected_keys()`:
  ```
  `DimensionControl.get_shape_info`, `ImageGridCanvas`, and the
  combine/freeze path in `RunListModel`
  ```
- [ ] Keep `RunDisplayWidget`'s unlinked per-run editor working. If it needs
  ```
  per-run key state, that state is **explicitly** owned by the widget as
  view state — not written back into `RunModel`. Record the choice in
  the decision log.
  ```
- [ ] Collapse `PlotModel.selected_keys` (copies) and `get_selected_keys()`
  ```
  (live refs) into one accessor that returns copies
  ```

**4c — Contract: one visibility rule**

- [ ] Remove the `_is_main_display` special case from
  ```
  `RunListModel.visible_runs` (`:610–615`) so `visible_runs` and
  `visible_models` describe the same set
  ```
- [ ] Preserve today's main-display behavior by having the presenter set
  ```
  auto-add / initial visibility explicitly at registration, which is
  already how `single_selection_mode` is handled after Step 6a
  ```
- [ ] Guard the checkbox round-trip: `_on_visible_runs_changed` calls
  ```
  `setCheckState` on every row, which re-enters `_on_item_changed` →
  `set_uids_visible`. Add a `blockSignals` window or an early-out on
  no-op transitions.
  ```
- [ ] Fix `CombinedRunModel`'s duplicate `data_changed` connect — remove the
  ```
  loop at `:69–70` and let `RunModel._connect_run` own it
  ```

### Non-goals

- Do **not** rename `DisplayManager` → `PresenterManager` (reorg decision:
separate later PR)
- Do **not** move presenter files to a top-level `models/presenter/`
- Do **not** unify the cube spec (step 5) or add teardown (step 6)
- Do **not** promote `models/plot/run/` to top-level `models/run/` — the
reorg document makes that conditional on this step landing first

### Testing goals

- [ ] `test_plot_presenter`, `test_run_list_combine_freeze`,
  ```
  `test_plot_model`, `test_plot_model_step3`, `test_run_list_wiring` green
  ```
- [ ] New unit: two `PlotModel`s on one `RunListModel` keep independent key
  ```
  selections, and neither writes to any `RunModel`
  ```
- [ ] New unit: a run missing a selected key no longer causes divergence —
  ```
  there is only one selection to read
  ```
- [ ] New unit: `visible_runs == {m.uid for m in visible_models}` on both a
  ```
  main and a non-main presenter
  ```
- [ ] New unit: `set_uids_visible` on N runs emits `visible_runs_changed`
  ```
  exactly once (re-entrancy regression)
  ```
- [ ] New unit: a `CombinedRunModel` source `data_changed` fires its handler
  ```
  exactly once
  ```
- [ ] Close matrix rows R1–R3 via the wired path (currently ⚠ ad-hoc)

### Exit criteria

- [ ] `rg "set_selected_keys" nbs_viewer/models/plot/run/` returns nothing
- [ ] `_is_main_display` no longer affects a getter's return value
- [ ] Step status → Done

---

## Step 5 — Reorg 7c (`cube/` split) + display-vs-storage contract

**Status:** Not started

**Depends on:** step 4

Problem-statement item 2. The reorg splits `cube_view.py` along the
spec/materialize seam; the contract sub-step makes the index space explicit
while that file is already open.

### Do

**5a — Mechanical (from reorg slice 7c)**

- [ ] Split `cube_view.py` (1256 lines) into `cube/spec.py` and
  ```
  `cube/materialize.py` along the seam enumerated in the reorg document
  ```
- [ ] `cube/__init__.py` re-exports the public set
- [ ] Repoint `roi/derived_fetch`, `view_crop`, `plot_model`,
  ```
  `plot_data_model`, `run/run_model`, and views
  ```
- [ ] Do **not** move `plot_geometry.py` / `plot_view_frame.py` under `cube/`

**5b — Contract: make the index space explicit**

Decide the mechanism first (see **Open decisions** below), then:

- [ ] Give `PlotViewFrame` the storage row/col axis arrays it lacks today, so
  ```
  display → storage mapping is available wherever a frame is available
  ```
- [ ] Route `MaterializeRequest.fetch_context` (`cube_view.py:149–154`)
  ```
  through `storage_bbox_from_display_bbox`, matching
  `fetch_context_with_view_crop` (`view_crop.py:169–174`)
  ```
- [ ] Make the two paths share one narrowing helper so they cannot drift
  ```
  again
  ```
- [ ] Correct the `CompiledRegion.bbox` docstring (`region.py:41–43`) —
  ```
  it is oriented display-plane row/col, not storage indices
  ```
- [ ] Name the two cell-selection rules at their call sites
  ```
  (center-in-rect for ROI reduction, touches-rect for view crop) and
  cross-reference them in both docstrings
  ```
- [ ] Consider `frozen=True` on `PlotBundle` — the only geometry carrier
  ```
  that is still mutable
  ```

### Non-goals

- Do **not** change materialize numerics beyond the bbox mapping fix
- Do **not** unify the two cell rules — they are both correct; only make the
difference legible
- Do **not** refactor `region_mesh` duplication (deferred; record only)

### Testing goals

- [ ] `test_cube_view`, `test_materialize_view`, `test_fetch_slice_info`,
  ```
  `test_derived_fetch`, `test_view_crop`, `test_view_crop_orientation`
  green
  ```
- [ ] **New H0 test with descending axes** (the gap named in the problem
  ```
  statement): an ROI on a flipped-orientation frame produces the same
  storage slices via `fetch_context` and
  `fetch_context_with_view_crop`. This is the test whose absence hid the
  asymmetry.
  ```
- [ ] New unit: `fetch_context` and `fetch_context_with_view_crop` agree on
  ```
  a non-cropped frame for both ascending and descending axes
  ```
- [ ] New unit: round-trip `storage_bbox_from_display_bbox` ∘ inverse is
  ```
  identity on both orientations
  ```

### Exit criteria

- [ ] One narrowing helper serves both fetch paths
- [ ] A descending-axis ROI fetch test exists and passes
- [ ] No docstring claims display-plane values are storage indices
- [ ] Step status → Done

---

## Step 6 — Reorg 7d (`canvas/`, checkboxes) + teardown discipline

**Status:** Not started

**Depends on:** step 5

Problem-statement item 1, the top-ranked structural problem. Paired with the
view-shell move because the canvas is the largest single subscriber.

### Do

**6a — Mechanical (from reorg slice 7d)**

- [ ] `views/plot/canvas/` for `single_canvas`, `renderers`, `plot_worker`
  ```
  (re-inventory: `views/plot/mplCanvas/` already exists and also holds
  `image_grid_canvas`, `image_grid_panel`, `mpl_panel`)
  ```
- [ ] `views/plot/dimension/` for `DimensionControl`
- [ ] Collapse the tiny checkbox controls into `controls/checkboxes.py`
- [ ] Snake_case the remaining view shell files (`plot_widget.py`,
  ```
  `metadata_view.py`, `image_grid_plot_widget.py`)
  ```

**6b — Contract: a teardown convention**

- [ ] Define the convention once and document it in the model package
  ```
  docstring: **any object that connects to a signal it does not own must
  provide `cleanup()`, and its owner must call it on removal.**
  ```
- [ ] `PlotDataModel.cleanup()` disconnects the four `RunModel` signals it
  ```
  connects in `__init__`; `PlotModel.drop_plot_data_for_uid` calls it
  instead of the current bare `try: plot_data.clear() except: pass`
  ```
- [ ] `PlotModel.cleanup()` disconnects from `RunListModel`, from itself, and
  ```
  from every attached run
  ```
- [ ] `PlotPresenter.cleanup()` cascades to its `PlotModel` and
  ```
  `RunListModel`; `DisplayManager.remove_display` calls it
  (`displayManager.py:133`)
  ```
- [ ] `MplCanvas.closeEvent` (or an explicit `cleanup()` called by
  ```
  `PlotDisplay`) disconnects the ~10 model signals wired in `__init__`
  (`single_canvas.py:172–190`) and retires outstanding plot workers
  ```
- [ ] Replace the per-call `QTimer` allocation in `MplCanvas.updatePlot`
  ```
  (`:567–577`) with one owned timer created in `__init__`
  ```
- [ ] Audit `CatalogTableView.cleanup()` (`views/catalog/base.py:784`) — it
  ```
  disconnects only `selectionChanged`, not the filter widget connections
  ```

### Non-goals

- Do **not** slim `MplCanvas` internals or extract ROI drawing (reorg 7e /
a later step) — teardown only
- Do **not** merge `PlotControlTab` into `PlotControls`
- Do **not** move artists off `PlotDataModel` (step 7)

### Testing goals

- [ ] Full suite green after each of 6a, 6b
- [ ] **New wiring test:** register a presenter, add a run, remove the
  ```
  display, then emit `run_added` / `visible_runs_changed` on the run list
  and assert the removed `PlotModel` receives nothing. This is the
  regression test that does not exist today.
  ```
- [ ] New unit: `drop_plot_data_for_uid` leaves zero connections from the
  ```
  dropped `PlotDataModel` to its `RunModel`
  ```
- [ ] New unit: creating and cleaning up N presenters leaves the run list
  ```
  with no growth in receiver count
  ```
- [ ] Manual H2: open several plot tabs, close them, confirm no duplicate
  ```
  fetches and no stale redraws
  ```

### Exit criteria

- [ ] Every connecting model type has `cleanup()`; owners call it
- [ ] Closing a display provably detaches its model tree
- [ ] Reorg document slices 7a–7d all → Done; folder layout matches target
  ```
  trees
  ```
- [ ] Step status → Done; **Milestone E**

---

## Step 7 — Move matplotlib artists off `PlotDataModel`

**Status:** Not started

**Depends on:** step 6

Problem-statement item 6, and the prerequisite for both a headless plot
frontend (ownership Step 8) and the multi-view image grid (ownership Step 6c).
Clears the last ownership allowlist violation.

### Do

- [ ] Introduce a view-side artist map (a `PlotArtistMap` on the canvas, or
  ```
  a plain dict) keyed by `plot_data.key`
  ```
- [ ] Move `set_artist`, `remove_artist_from_axes`, `add_artist_to_axes`,
  ```
  `move_artist_to_axes`, and the artist-clearing half of `clear()` out of
  `PlotDataModel` into that map
  ```
- [ ] Redefine `PlotDataModel.set_visible(bool)` as **session** visibility —
  ```
  the model records intent and emits; the canvas reacts by setting
  artist visibility
  ```
- [ ] Remove `from matplotlib.image import AxesImage` from
  ```
  `plot_data_model.py`, leaving `models/` matplotlib-free except
  `roi/region_mesh.py`'s `matplotlib.path.Path` (accepted; H0-adjacent,
  not Qt)
  ```
- [ ] Rename the canvas `plotArtists` property to `plot_data_map` (it already
  ```
  returns `plot_model.plot_data_map`)
  ```
- [ ] Make `ImageGridCanvas` obtain plot data via
  ```
  `plot_model.ensure_plot_data` instead of constructing `PlotDataModel`
  (`image_grid_canvas.py:393–401`), and move `_make_slice_info`
  (`:263–277`) onto the model side
  ```
- [ ] Empty `EXPECTED_VIOLATIONS` in the ownership guard

### Non-goals

- Do **not** implement N>1 presenters or per-cell `PlotModel`s (that is
ownership Step 6c and can follow immediately after this)
- Do **not** write the headless export frontend here — only unblock it
- Do **not** fix `ImageGridCanvas`'s `figure.clear()` redraw cost; note it as
a perf follow-up

### Testing goals

- [ ] New H1 test: full `ensure_plot_data` → `get_plot_bundle` →
  ```
  `set_visible` cycle with **no** canvas and no matplotlib import in the
  test
  ```
- [ ] Existing plot suite green, including 2-D image and mesh paths
- [ ] Ownership guard passes with an empty expected set
- [ ] Manual H2: hide/show traces, switch 1-D↔2-D, page the image grid

### Exit criteria

- [ ] `rg "matplotlib" nbs_viewer/models/` returns only `region_mesh.py`
- [ ] `EXPECTED_VIOLATIONS` is empty; any new hit fails hard
- [ ] Step status → Done

---

## Step 8 — Split the ROI pipeline off `PlotModel`

**Status:** Not started

**Depends on:** step 7

Problem-statement item 4. `PlotModel` is 1258 lines with ~54 public members
and 12 signals; the reorg explicitly cannot fix this because it needs a class
split, not a file move.

### Do

- [ ] Extract the ROI preview/commit pipeline —
  ```
  `preview_roi_profile` (66), `prepare_roi_commit` (69),
  `commit_roi_profile` (85), `finalize_roi_commit` (66) — into a
  collaborator owned by `PlotModel` (working name `RoiPipeline`), living
  in `models/plot/roi/`
  ```
- [ ] `PlotModel` keeps thin delegating methods so view call sites and the
  ```
  `test_roi_wiring` matrix rows are unchanged
  ```
- [ ] Move region fingerprinting / `invalidate_all_region_state` with it
- [ ] Break the self-signal cascade: `PlotModel` connects its own
  ```
  `selected_keys_changed` to `_on_selected_keys_changed_for_region`,
  which invalidates all crop and ROI state on **every** key change, then
  `request_plot_update` fires too. Make invalidation an explicit call
  from the setter rather than a self-subscription.
  ```
- [ ] Audit the remaining `PlotModel` surface and collapse near-duplicates
  ```
  (`set_view_crop` / `clear_view_crop` / `apply_view_crop_from_region`)
  ```

### Non-goals

- Do **not** change ROI numerics or the preview/commit protocol
- Do **not** split view crop or cube state off `PlotModel` — those are
genuinely plot-session state
- Do **not** rename public methods that views and tests call

### Testing goals

- [ ] `test_roi_preview_commit`, `test_roi_wiring` green **unchanged** — if
  ```
  they need edits, the delegation is not thin enough
  ```
- [ ] New unit: changing a selected key invalidates region state exactly once
- [ ] `PlotModel` public member count materially reduced (record before/after
  ```
  in the decision log)
  ```

### Exit criteria

- [ ] `plot_model.py` under ~700 lines
- [ ] No self-signal subscriptions remain on `PlotModel`
- [ ] Step status → Done

---

## Step 9 — Enforceable data-layer contract

**Status:** Not started

**Depends on:** step 2 (independent of 3–8; can run in parallel)

Problem-statement item 5. This is what unblocks the file-backed offline
catalog and any future backend.

### Do

**9a — Make the interface real**

- [ ] Convert `CatalogRun` (`data/base.py`) and `CatalogBase`
  ```
  (`catalog/base.py`) to genuine ABCs with `@abstractmethod`, replacing
  `pass` stubs and bare `raise NotImplementedError`
  ```
- [ ] Resolve the `to_header` split — base declares an instance method
  ```
  returning `Dict`, every implementation is a `@classmethod` returning a
  column list. Pick the classmethod-returning-columns shape and fix the
  base.
  ```
- [ ] Declare optional capabilities explicitly rather than by absence —
  ```
  `search`, `filter_by_time`, `remove_runs`, `wrap_run` are each missing
  from at least one backend
  ```
- [ ] Delete or implement `filter_by_scantype`, called at `search.py:28` and
  ```
  implemented nowhere
  ```
- [ ] Declare `items_slice` on `CatalogBase` — `CatalogTableModel` already
  ```
  requires it
  ```
- [ ] Add `keys_ready` / `keys_error` to the base so `RunModel` can stop
  ```
  duck-typing with `hasattr` (`runSource.py:65–68`)
  ```
- [ ] Fix `BlueskyRun._has_data = None` returning empty arrays
  ```
  (`bluesky.py:326–327`) and `KafkaRun.scanFinished()` always returning
  true (`kafka.py:310–311`)
  ```
- [ ] Fix `BlueskyRun.getAxis`'s cache key ignoring `slice_info`
  ```
  (`bluesky.py:418–429`) — first call wins, later calls get wrong data
  ```
- [ ] Fix `BlueskyCatalog.search` not invalidating `_wrapped_runs`
  ```
  (`catalog/bluesky.py:196–198`)
  ```
- [ ] Reconcile `getData(indices=)` vs `getData(slice_info=)` and
  ```
  `getAxis(keys)` vs `getAxis(keys, slice_info)` across backends
  ```

**9b — De-duplicate the hint system**

- [ ] Hoist one implementation each of `get_default_selection`,
  ```
  `get_md_value`, `getRunKeys` classification, and `_resolve_dims` into
  the base or a shared module. Memory currently uses a different default-
  selection algorithm, so the same data yields different default axes per
  backend — pick the Bluesky/Kafka behavior and make Memory match.
  ```
- [ ] Centralize the magic hint strings (`"primary"`, `"plot_hints"`,
  ```
  `"object_keys"`, `"normalization"`, `"time"`) in one module
  ```
- [ ] Give `METADATA_MAP` / `METADATA_KEYS` / `DISPLAY_KEYS` a shared schema
  ```
  rather than three parallel per-class tables
  ```

**9c — Remove backend dispatch from views**

- [ ] Replace `isinstance(catalog, KafkaCatalog)` in
  ```
  `catalogSwitcher.py:100–102` and
  `isinstance(source, KafkaSourceModel) or key == "kafka"` in
  `dataSource.py:623–624` with a capability or view-hint declared by the
  catalog / source
  ```
- [ ] Replace `hasattr(self._catalog, "new_run_available")` in
  ```
  `views/catalog/kafka.py:130–132` with a declared streaming capability
  ```
- [ ] Narrow or remove `BlueskyCatalog.__getattr__`'s passthrough to the
  ```
  Tiled client (`catalog/bluesky.py:58–59`)
  ```
- [ ] Move `ReverseModel` and `FilterModel` out of `views/catalog/base.py`
  ```
  into `models/catalog/` — including the chunked lazy filtering at
  `:203–223`
  ```
- [ ] Fix the wrong-layer import: `runListModel.py:4` imports `CatalogRun`
  ```
  from `catalog.base`, where it is only re-exported; it lives in
  `data.base`
  ```

**9d — Prove it**

- [ ] Add the file-backed offline catalog named as a wanted feature in the
  ```
  ownership plan, as the acceptance test for 9a–9c: it must require
  **zero** changes under `views/`
  ```

### Non-goals

- Do **not** rename the camelCase data API (`getData`, `getShape`,
`getRunKeys`) — large call-site churn; separate PR after this
- Do **not** restructure Kafka's threading model (step 10 territory)
- Do **not** move blocking Tiled I/O off the GUI thread here; record it

### Testing goals

- [ ] Instantiating an incomplete `CatalogRun` subclass raises `TypeError`
- [ ] New unit: all three backends return the same default selection shape
  ```
  for equivalent data
  ```
- [ ] New unit: `getAxis` with two different `slice_info` values returns
  ```
  different data
  ```
- [ ] New unit: `search` then `get_runs` returns only filtered UIDs
- [ ] New unit: file-backed catalog loads → `ensure_table_model` → select run
  ```
  → plot bundle, with no view imports
  ```
- [ ] Ownership guard: no `isinstance` on concrete catalog/run types under
  ```
  `views/`
  ```

### Exit criteria

- [ ] A new backend is addable without touching `views/`
- [ ] Hint classification has one implementation
- [ ] Step status → Done; **Milestone F**

---

## Step 10 — Split `ChunkCache`; fix cache concurrency

**Status:** Not started

**Depends on:** step 1 (deletion first — do not split code that is leaving)

After step 1 removes ~330 lines, the remaining seams are the ones the problem
statement enumerates. `tile_indices.py` and `zarr_l2_cache.py` are the
already-proven pattern.

### Do

**10a — Concurrency correctness (before splitting)**

- [ ] Bring hot-path shared state under the lock: `slice_cache`,
  ```
  `chunk_info`, `access_times`, and the hit/miss counters are mutated
  from both the main thread and the 4-worker `fetch_pool`
  ```
- [ ] Close the TOCTOU gap in `_queue_l2_materialize` (`:750–781`), where the
  ```
  lock is released between the duplicate-job check and the submit
  ```
- [ ] Make `ZarrL2Cache` reads lock-consistent with writes —
  ```
  `has_chunk`/`read` do not take `_lock` while `write_chunk` does
  (`zarr_l2_cache.py:220`, `:336–341` vs `:383–385`)
  ```
- [ ] Stop reaching into `ZarrL2Cache` privates from `ChunkCache`
  ```
  (`self.l2._meta` at `:154`, `self.l2._lock` at `:1229–1233`); give
  `ZarrL2Cache` a bulk-seed API so there is one L2 write path
  ```
- [ ] Shut down `background_pool` in `clear()` (`:1966–1967`)

**10b — Extract along the named seams**

- [ ] `TiledTransport` — injectable `read(run, key, slice_info)`; owns the
  ```
  batch pool. This is the missing test seam; `_fetch_from_tiled`
  hard-wires `run["primary", "data", key].read`.
  ```
- [ ] `SlabAssembler` — pure-numpy paste/extract/assemble, absorbing the
  ```
  overlap math currently duplicated four times
  (`_paste_tile_into_slab`, `_paste_gap_into_slab`,
  `_extract_tile_from_slab`, `_cold_gap_slice_info`)
  ```
- [ ] `L2Materializer` — the background job queue and Zarr seeding
- [ ] `AssembledSlabCache` — the `slice_cache` LRU only
- [ ] Replace `List[Dict]` tile metadata with a frozen dataclass; the current
  ```
  dicts are mutated in place (`tile_info["already_sliced"]` at `:245`)
  ```
- [ ] Have `tiles_intersecting` call `request_dim_bounds` instead of
  ```
  reimplementing bound logic (`tile_indices.py:137–138` vs `:235–238`)
  ```
- [ ] Move the shared `_FakeRun` / `_FakeAccessor` into
  ```
  `tests/fixtures/` — currently copy-pasted across four cache tests
  ```

### Non-goals

- Do **not** change cache semantics or eviction policy
- Do **not** decouple `ChunkCacheProgress` from `QObject` (accepted H1
compromise)
- Do **not** rename `chunkCache.py` until the split determines the final
module set

### Testing goals

- [ ] Full cache suite green after each extraction
- [ ] New unit: a fake `TiledTransport` drives `get_data` end-to-end with no
  ```
  real run object
  ```
- [ ] New concurrency test: N parallel `get_data` calls for overlapping
  ```
  slices produce correct data and enqueue each background job once
  ```
- [ ] `wait_for_background_materialize` timeouts replaced or bounded so cache
  ```
  tests are not timing-flaky
  ```

### Exit criteria

- [ ] No module over ~700 lines under `models/cache/`
- [ ] One L2 write path; no `ChunkCache` access to `l2._*`
- [ ] Cache is testable with an injected transport
- [ ] Step status → Done

---

## Step 11 — Logging and exception sweep

**Status:** Not started

**Depends on:** steps 1, 6, 7 (so the sweep does not touch code that is
leaving or moving)

Problem-statement item 9. Mechanical, and deliberately late: the facility
already exists, so this is conversion, and doing it before the moves would
double the work.

### Do

- [ ] Convert the remaining 132 raw `print()` calls to `print_debug` /
  ```
  `logging` with a topic. Order by density: `single_canvas.py` (29 →
  largely gone after steps 1b and 6), `data/kafka.py` (12),
  `data/bluesky.py` (10), `run_display.py` (9), `viewer.py` (9).
  ```
- [ ] Triage the 100 broad `except` handlers into: (a) genuinely optional
  ```
  operations, which get a debug log and a comment stating why; (b) real
  errors, which propagate. Delete the 22 silent `pass` blocks in
  category (b).
  ```
- [ ] Fix the two bare `except:` in `io/export_to_xdi.py:7–14`, `:318–321`
  ```
  (they swallow `KeyboardInterrupt`)
  ```
- [ ] Special-case the 13 consecutive silent passes in
  ```
  `single_canvas.py:1139–1154` — one guarded helper, not 13 blocks
  ```
- [ ] Flip `DEBUG_VARIABLES["PRINT_DEBUG"]` to default `**False**`
- [ ] Make `http_debug.log` opt-in rather than always written to CWD
  ```
  (`viewer.py:380–384`)
  ```
- [ ] Stop dropping exception causes: `runListModel.py:404–408` raises
  ```
  `CombineError(...) from None`
  ```
- [ ] Decide whether `utils.py` should keep the global `AppModel` accessor
  ```
  (`set_top_level_model` / `get_top_level_model`, 8 call sites in
  `views/catalog/base.py` and `views/dataSource/runListView.py`) or
  whether those call sites should take injected models per ownership
  rule 8
  ```

### Non-goals

- No new logging framework; `logging_setup.py` + `print_debug` is the target
- Do not add module docstrings wholesale (34% coverage) — separate task
- Do not convert prints inside `test/` manual scripts

### Testing goals

- [ ] `rg "print\(" nbs_viewer/ | wc -l` → 0 (or an explicitly justified
  ```
  short list, e.g. CLI user output in `viewer.py`)
  ```
- [ ] `rg "except:" nbs_viewer/` → 0
- [ ] Full suite green; no test depends on captured stdout
- [ ] Manual: `--debug-topic` produces the output the old prints did

### Exit criteria

- [ ] Every diagnostic goes through logging with a topic
- [ ] No silent `pass` on a real error path
- [ ] Step status → Done

---

## Step 12 — Config, packaging, and repo hygiene

**Status:** Not started

**Depends on:** step 2 (CI exists to enforce it)

### Do

- [ ] Extend `.gitignore`: `massif.out`*, `memory.xml`, `http_debug.log`,
  ```
  `*.prof.json`, `catalog_config.toml`, editor backups (`*~`)
  ```
- [ ] Remove or relocate untracked strays: `massif.out.484957` (1.3 MB),
  ```
  `memory.xml` (945 KB), `oldtests/http_debug.log`,
  `oldtests/viewer.prof.json`, `oldtests/viewer.prof2.json`,
  `test/kafkaTest.py~`, `test/kafka.yml~`
  ```
- [ ] Track `nbs_viewer/__main__.py` (a valid `python -m nbs_viewer` entry)
  ```
  and `nbs_viewer/io/export_to_xdi.py`, **or** delete them.
  `export_to_xdi.py` imports a nonexistent `export_tools` module and is
  currently broken either way.
  ```
- [ ] Track the nine untracked `planDocuments/` design docs, including this
  ```
  one and the problem statement
  ```
- [ ] Finish testing-plan Phase 4: relocate `oldtests/` H2 files to `test/`
  ```
  or `scripts/`, delete `oldtests/`, so `tests/` is the single root
  ```
- [ ] Move hardcoded defaults into config: `"http://localhost:8000"`
  ```
  (`uriSource.py:61`), `"localhost:5578"` (`zmqSource.py:21–22` and the
  UI label at `dataSource.py:480`)
  ```
- [ ] Move beamline-specific XDI constants (`"NSLS-II"`, `"7-ID-1"`,
  ```
  `"NEXAFS"`, `"SST-1-NEXAFS/1.0"`, `export_to_xdi.py:35–45`, `:275`)
  into config or a beamline profile
  ```
- [ ] Fix the Qt backend inconsistency: `image_grid_panel.py:10` imports
  ```
  `backend_qt5agg` while everything else uses `backend_qtagg`
  ```
- [ ] Fix `ZMQSourceModel`'s docstring, which says "Kafka source model"
  ```
  (`zmqSource.py:8–9`)
  ```
- [ ] Refresh `README.md`: pixi workflow, logging CLI flags, the `tests/`
  ```
  layout. It currently documents `conda install pyqt` and an rsoxs
  profile.
  ```
- [ ] Decide `widgets/kafkaViewerTab.py`'s fate — it prints on import,
  ```
  bypasses `PlotPresenter`, has stale APIs, and is still registered as
  the `nbs-viewer-kafka` console script. Either rewire it to the
  presenter stack or mark it deprecated in `pyproject.toml`. Ownership
  rule 6 says leave the package alone; it does not say ship a broken
  entry point.
  ```

### Non-goals

- No `nbs_viewer/docs/` build (Sphinx etc.) — separate project
- No camelCase → snake_case rename of the data API
- Do not refactor `widgets/` internals; only resolve the entry point

### Testing goals

- [ ] `git status` clean on a fresh checkout after a full test run
- [ ] `pip install` of a built wheel does not pull `pytest`
- [ ] `python -m nbs_viewer` works if `__main__.py` is kept
- [ ] `nbs-viewer-kafka` either works or is gone

### Exit criteria

- [ ] One test root; no stray artifacts; no beamline constants in source
- [ ] Step status → Done; **Milestone G**

---

## PR / dependency graph

```text
1 delete dead code
  → 2 CI + ownership guard                      ← Milestone D
    → 3 reorg 7a  + PlotDataModel accessors
      → 4 reorg 7b  + single key/visibility truth
        → 5 reorg 7c  + display-vs-storage contract
          → 6 reorg 7d  + teardown discipline    ← Milestone E
            → 7 artists off PlotDataModel
              → 8 split ROI pipeline off PlotModel
              → (ownership 6c: N>1 presenter, unblocked by 7)
    → 9 data-layer contract  (parallel with 3–8) ← Milestone F with 7
  → 10 ChunkCache split + concurrency (parallel after 1)
    → 11 logging / exception sweep (after 1, 6, 7)
    → 12 config / packaging / hygiene            ← Milestone G
```

Steps 9 and 10 are independent of the 3–6 chain and of each other. If two
people are working, 9 or 10 is the second track.

## Open decisions

Resolve before the step that needs them; record the outcome in the decision
log.


| Decision                                      | Needed by | Options                                                                                                                                                                                                                                                                                                                                     |
| --------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| How to make index space explicit              | 5b        | (a) add axis arrays to `PlotViewFrame` and always map — smallest diff, keeps one frame type; (b) distinct `DisplayBBox` / `StorageBBox` newtypes — strongest guarantee, touches every bbox call site; (c) require callers to pass axes into `fetch_context` — least invasive, easiest to forget. Recommend (a) now, (b) if bbox bugs recur. |
| Per-run key state for the unlinked run editor | 4b        | (a) view-owned state in `RunDisplayWidget`; (b) an explicit per-run override map on `PlotModel`; (c) drop unlinked mode. Recommend (a) unless the override needs to persist.                                                                                                                                                                |
| `flush_l1_to_l2` removal                      | 1a        | Delete with its test, or keep as an L2 utility decoupled from L1. Recommend delete — its only caller is the test.                                                                                                                                                                                                                           |
| Global `AppModel` accessor                    | 11        | Keep as a pragmatic shim, or inject at the 8 call sites per ownership rule 8. Recommend injection; it is a small diff and the rule already exists.                                                                                                                                                                                          |
| `widgets/kafkaViewerTab.py`                   | 12        | Rewire to presenter, or deprecate the entry point.                                                                                                                                                                                                                                                                                          |
| Top-level `models/run/`                       | after 4   | The reorg document makes this conditional on selected keys leaving `RunModel`, which step 4b does. Revisit then.                                                                                                                                                                                                                            |


## Explicit non-goals (until this plan is revised)

- Inverting packages to `feature/{models,views}` (ownership rule 5)
- Replacing `Signal` with a non-Qt event bus
- Renaming the camelCase data API (`getData`, `getShape`, `getRunKeys`)
- Renaming `DisplayManager` → `PresenterManager` (separate one-line-ish PR)
- Refactoring `widgets/` internals (ownership rule 6)
- An H0 (Qt-free) run-collection type; `QStandardItemModel` on
`RunListModel` remains an accepted H1 compromise
- Removing `matplotlib.path.Path` from `region_mesh.py`
- Matplotlib performance work (blitting, artist reuse, `figure.clear()`
avoidance) — record as follow-up after step 7
- Moving blocking Tiled connect/auth I/O off the GUI thread — real, but
scoped separately from step 9

## Decision log


| Date       | Decision                                                                                             |
| ---------- | ---------------------------------------------------------------------------------------------------- |
| 2026-09-02 | Deletion (step 1) precedes CI (step 2) and all restructuring                                         |
| 2026-09-02 | Reorg slices stay mechanical; each is followed by a paired contract commit rather than being widened |
| 2026-09-02 | Contract pairings fixed: 7a↔private accessors, 7b↔key/visibility truth, 7c↔index space, 7d↔teardown  |
| 2026-09-02 | Steps 9 (data contract) and 10 (cache) are parallel tracks, not blockers for the 3–6 chain           |
| 2026-09-02 | The file-backed offline catalog is the acceptance test for step 9, not a separate feature request    |
| 2026-09-02 | Ownership `EXPECTED_VIOLATIONS` empties in step 7, not by a lint flip                                |


## Modification log


| Date       | Change                                                                             |
| ---------- | ---------------------------------------------------------------------------------- |
| 2026-09-02 | Initial plan from `[codebase_problem_statement.md](codebase_problem_statement.md)` |


