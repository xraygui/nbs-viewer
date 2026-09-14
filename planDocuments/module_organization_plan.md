# Module organization plan

Reorganising `models/plot` so a reader holds less in their head at once.

**Status:** drafted 2026-09-10, **re-derived 2026-09-14** at `f50633a` after
[`data_contract_plan.md`](archive/data_contract_plan.md) completed. The draft's
measurements were taken at `9ecbe11` and are superseded; its step 1 is half
done. Written to the conventions in
[`data_contract_review.md`](data_contract_review.md): steps name their files,
functions and call sites, and no step states a count it has not measured.

## The goal

The refactor asked *does each thing have one implementation?* This pass asks
*can a reader understand one file without opening six others?*

It is **not a rewrite**. No behaviour changes and no function bodies rewritten:
code moves between files, and names change so that where something lives tells
you what altitude it is at. It produces more files and probably more lines.

> **What every step must do.** Make some file easier to read and maintain, and
> say how — which data now sits with the behaviour that operates on it, or
> which name now tells the truth about what it holds.
>
> **Two hard rules**, because these are hazards rather than preferences: no
> runtime import cycles inside `models/plot`, and no function-local import
> used to dodge one.

### The working-set count is a diagnostic, not a target

A file's **working set** is the number of sibling *free functions* it imports.
It is useful for *locating* problems: importing `reduce_before_mask`,
`mask_to_profile` and `materialize_view` from three modules means a reader must
go elsewhere to learn what this file does, which usually means a procedure has
been smeared across the package.

It must not be optimized, because it is trivially gameable: moving those
functions into a class that is only a namespace would drive every count to
zero and improve nothing. **A class is better than a pile of free functions
when it encapsulates — when the data and the methods that operate on it live
together, and the methods really do belong to that data.** That is the win;
the count is only a way of noticing where it is missing.

Two consequences for this plan. A high count is not automatically a defect:
`region`'s seven functions come from *one* partner module, which is a cohesive
pair and needs nothing done to it. And a file that cannot honestly be improved
is left alone and said so — some of this code is genuinely complex, and
reshuffling it to move a number would be the poor optimization this plan is
supposed to avoid.

---

## What the tree measures now

22 files, 10 605 raw / 4 791 code lines, and **267 import statements naming one
of its modules across 74 files** — 178 of them in `tests/`, 24 in `views/`, 64
inside the package. External churn for any rename is therefore small and the
suite verifies it immediately.

### Working sets (files above zero)

| File | code | free fns | from N modules | |
|---|---:|---:|---:|---|
| `run_fetch` | 217 | **12** | 4 | worst; inherited the fetch half |
| `region_controller` | 456 | 9 | 4 | |
| `region` | 285 | 7 | **1** | a module pair, not a spread |
| `plot_bundle` | 339 | 6 | 4 | plus 2 function-local imports |
| `plot_request` | 287 | 6 | 3 | |
| `plot_view_frame` | 187 | 2 | 2 | plus 1 function-local import |
| `trace` | 203 | 2 | 2 | |
| `plot_axes`, `plot_session`, `view_intent` | | 1 | 1 | the healthy shape |
| everything else (12 files) | | 0 | 0 | including `run_source`, `view_spec` |

### Cycles and dodges

- **1 runtime cycle:** `plot_view_frame ↔ region_mesh`.
- **3 function-local sibling imports**, all reaching into `region_mesh`:
  `plot_view_frame.py:332` (`_image_cell_bounds`), `plot_bundle.py:352`
  (`_mesh_separable_edge_grids`), `plot_bundle.py:388` (`_cell_x_bounds_mesh`,
  `_cell_y_bounds_mesh`). The draft found only the first; the other two date
  from view-pipeline step 5 (`e0d2ef1`) and were undercounted, not introduced.
- **2 `TYPE_CHECKING` cycles:** `region_controller ↔ plot_session` (a
  controller naming its parent — expected) and `run_fetch ↔ run_source`, new,
  created by the data-contract split. A fetch that names the source it is
  handed is the same expected shape.
- `plot_geometry ↔ plot_request` is **closed**: `plot_request` no longer
  imports `plot_geometry` at all.

### Files whose names still mislead

`plot_bundle.py` does not define `PlotBundle` — `plot_geometry.py` does. The
`plot_` prefix spans three altitudes and is redundant inside a folder called
`plot`. `display_manager.py` and `presenter.py` are the multi-display shell,
not plotting: **nothing inside `models/plot` imports either**, and their only
production importer is `models/app_model.py`.

### What the data-contract refactor already settled

- **The `run_source` split is done.** `RunFetch` exists, `run_source`'s working
  set is 5 → **0**, and `run_fetch` inherited 12 free functions from 4 modules
  exactly as predicted. What remains of the draft's step 1 is the guard test.
- **`run/`'s contents changed.** `KeyInfo` and the array contract moved to
  `models/data`; `AxisLayout` is deleted; `FrozenSpectrum` did *not* move,
  because it holds a `PlotBundle`. So `run/` is four files, not three.
- **`fetch/` wants one `stages.py`**, not the draft's `reduce.py` +
  `normalize.py`: every stage is now `DataArray -> DataArray` and the split
  stopped being a boundary.

---

## Decisions

Settled here so no step has to stop and ask. Each is reversible; none blocks.

1. **The fetch half is a class.** Settled by execution: `RunFetch`, owned by
   `RunSource` and handed out as `fetch`, with no forwarding method.
2. **`ViewIntent` stays at the top level**, with the other session children.
   The package is organised around the ownership tree, and a reader follows
   `session.py` to its children; `view/` holds the vocabulary the intent is
   expressed in, not the object.
3. **`display_manager.py` and `presenter.py` move to `models/displays/`.**
   Move only — `PlotPresenter`'s design stays as step F left it.
4. **`run/` exists**: `source.py`, `fetch.py`, `frozen_spectrum.py`,
   `identity.py`.
5. ~~**The axis/profile queries stay free functions** taking a
   `Projection`.~~ **Reversed by the maintainer during step 6.** A function
   whose first argument is a `Projection` is a method on it. The nine were
   the same shape as the eight methods the class already carried, so the free
   functions were the inconsistency — and this is the encapsulation this
   plan's own opening names as the win, not the count. What it buys is that
   asking a projection a question costs **no import at all**, which is why
   steps 4 and 6 kept finding these functions hard to place: they had no home
   because they were already home, on the type.
6. **`region_controller` is measured before phase 2, not refactored in it.**
   456 code lines, 28 public members, 6 signals, coupling across 4 modules. It
   is either a coordinator like `PlotSession` or a `run_source`-shaped split,
   and the answer changes where it lives. Step 7 is that measurement.

---

## Phase 1 — split and rename, still flat

### Step 1 — the boundary guard — **landed**

- [x] `tests/test_module_boundaries.py`, asserting **the two hard rules** by
  AST over `nbs_viewer/models/plot/*.py`: no runtime import cycle, and no
  function-local import of a sibling — with an allowlist seeded at exactly the
  three known offenders above, which step 2 empties.
- [x] A script, **not a test**, that prints the working-set table so a step can
  report what moved: `pixi run python -m tools.module_graph`. It is a
  diagnostic: nothing fails when a number rises, because a step may
  legitimately concentrate related functions in one place.
- [x] Deletes nothing.
- **Out of scope:** enforcing a working-set ceiling. A threshold would make the
  count a target, and the count is gameable.

### Step 2 — break the runtime cycle and declare the mask surface — **landed**

- [x] Move the cell geometry from `region_mesh.py` to `plot_view_frame.py`:
  the four the draft named — `_image_cell_bounds`, `_cell_x_bounds_mesh`,
  `_cell_y_bounds_mesh`, `_mesh_separable_edge_grids` — plus the four they
  call, `_data_limits`, `_image_row_y_bounds`, `_mesh_cell_bounds` and
  `_cell_bounds`. They are cell geometry *on a frame*; the rasterizers and
  `cell_centers` stay.
- [x] Delete all three function-local imports (`plot_view_frame.py:332`,
  `plot_bundle.py:352`, `plot_bundle.py:388`) and empty step 1's allowlist.
- [x] Rename the moved functions without their underscore, and update the
  **24 imports of private `region_mesh` names across 9 files** — six test
  files, plus `plot_bundle.py`, `plot_view_frame.py` and `region.py`, which
  means production code reaches for them too and the surface is undeclared
  rather than merely leaky, less `_image_row_y_bounds` and `_cell_bounds`,
  which nothing outside `plot_view_frame` calls.
- [x] Deletes: the runtime cycle (**1 → 0**), the allowlist, and the
  `plot_view_frame ↔ region_mesh` pair, which is now one-way.

### Step 3 — `plot_geometry` and `plot_bundle` stop lying about their contents — **landed**

- [x] `bundle.py`: `PlotBundle`, `prepare_1d_bundle`, `prepare_2d_bundle`,
  `build_plot_bundle`.
- [x] `orientation.py`: `classify_render_mode`, `display_flips`, the extent and
  mesh-grid builders — **and `RenderMode`**, which the draft put in `bundle.py`.
  It travels with the function that produces it, because the alternative is a
  runtime cycle.
- [x] `stages.py`: `apply_normalization`, `apply_transform`, `reduce_to_plane`,
  `reduce_before_mask`, `mask_to_profile`, `materialize_view`,
  `reduce_cached_plane`, `slice_info_for_key` — the whole `DataArray ->
  DataArray` set, which is one concept and one file.
- [x] `plot_bundle.py` and `plot_geometry.py` cease to exist. So does
  `region_controller`'s `from .plot_bundle import PlotBundle`, which named a
  class that file never defined — the lie this step is named for.
- [x] `extent_from_uniform_1d`, `pixel_extent` and `build_mesh_grids` lose
  their underscore, because `bundle` now crosses into them.
- **Out of scope:** the stage bodies, and `PlotBundle`'s fields (open question
  5 in the data-contract plan owns those).

### Step 4 — one mapping, one implementation — **landed**

The draft split both files by *form*: types stay, free functions move to a
file of their own. Measured, that sorts `view_spec`'s fourteen functions —
which answer five different questions — into one bucket and encapsulates
nothing: `view_spec` would end at 287 lines with a working set of 0, and the
new file would open at 0. So there is no new file. Each function goes with
its subject instead:

| what it is | where it goes |
|---|---|
| the one real decision — `resolve_axis_order` | stays; `view_intent` is its only caller |
| construction — `_resolved_roles` | stays; only `Projection.__post_init__` calls it |
| ROI vocabulary — `eligible_profile_axes`, `profile_view_spec`, `profile_storage_axis`, `scan_profile_storage_axis`, `classify_profile_kind`, `is_plot_plane_storage_axis` | ~~`roi/`~~ **stay.** Wrong call, corrected in step 6: each reads a `Projection` and answers a question about a view, and `PlotAxes.to_profile` needs `profile_view_spec`, so moving it makes `view` import `roi` while `roi` already imports `view` — a runtime cycle. Being asked mostly by ROI code does not make a projection query ROI vocabulary. |
| label text — `default_profile_label`, `profile_axis_name` | `roi/`, step 6. Neither takes a `Projection`, which is the line that separates them from the six above; moving `default_profile_label` deletes `view_spec`'s last sibling import |
| request builders — `crop_from_region`, `roi_profile_request` | ~~`roi/`~~ `fetch/request.py`, step 7. Both build a request, and `crop_from_region` is view *cropping*, not ROI: its docstring contrasts its cell-intersects rule with the cell-center rule ROI reduction uses |
| fetch planning — `plan_fetch` | `fetch/plan.py`, step 7 |
| blocked — `spec_from_slice_info` | only caller is `ImageGridCanvas`, deferred |

What is left is a defect, and it is this step:

- [x] Delete `storage_axis_to_plot_axis`'s `frame` parameter and the fallback
  branch that reads the mapping off `frame.plot_x_dim` / `plot_y_dim`. Its own
  docstring says that branch "silently inverts the answer" for any view whose
  plot-axis order is not the identity, so the one function has two
  implementations of one mapping and one of them is wrong. The branch is
  already dead: all five call sites — `views/plot/roi/window.py:995` and
  `:1164`, `plot_request.py:591`, and both asserts in
  `tests/test_roi_profile_fetch.py` — pass `parent_spec`, and two of them
  guard on it being non-`None` first. It then matches
  `plot_axis_to_storage_axis`, which is already the same query on a
  `Projection` alone.
- [x] Deletes: the wrong branch, the `frame` parameter, and
  `view_spec`'s `from .plot_view_frame import PlotViewFrame` — line 737 is its
  only use, so the `view_spec → plot_view_frame` edge goes with it.
- [x] Rename `view_spec.plot_axis_names` to `projected_axis_names`. It means
  *the plot axes of a projection* while `RunSource.plot_axis_names` means *a
  name per storage axis* — two things one import apart, recorded in the
  data-contract plan and never fixed. The rename is nearly free: the free
  function has **three call sites, all in `tests/test_view_spec.py`**, against
  33 for the method.
- **Not deleted:** `projected_axis_names` has no production caller.
  `ViewIntent`'s docstring names it as the check for whether two projected
  keys may share a plot, which is intended and unwired, not dead — the
  `get_hinted_keys` category. It keeps its rename and its test.
- **Out of scope:** making the three index spaces — storage axis, plot axis
  name, display position — distinct types. Two of the three are bare `int`,
  which is what let the wrong branch look plausible; that is a data-contract
  question, not a file-organisation one.

### Step 5 — one definition per type alias — **landed**

- [x] One home each: `SliceItem`, `SpatialReduce` and `PlotAxisName` in
  `view_spec.py`, `MaskMode` in `region.py` beside the
  `compile_with_mask_mode` it configures. Splitting `MaskMode` from the other
  three is deliberate — it is not part of how an array is sliced or oriented,
  and step 6 sends `region.py` to `geometry/` where the rest of its users go.
- [x] Deletes five definitions: `region.py`'s `PlotAxisName`, `stages.py`'s
  `SliceItem` and `MaskMode`, `plot_request.py`'s `SliceItem`, and
  `roi_set.py`'s `MaskMode = str` and `SpatialReduce = str`, which widened two
  of them to "any string" under the same name. Two `typing` imports go with
  them.
- [x] Closes item 7 of [`post_refactor_review.md`](post_refactor_review.md).
- **Out of scope:** `models/cache`'s two `SliceItem` definitions — a different
  package with no dependency either way.

## Phase 2 — move into packages

Mechanical: every hunk is a file rename or an import line. Verified by the
suite plus step 1's guard.

### Step 6 — `geometry/`, `view/`, `roi/` — **landed**

The three with a declared `__init__` surface, done together because their
surfaces are the point: `geometry/` (bundle, orientation, frame, mask) because
outsiders currently import private names from it; `view/` because 63 of
`view_spec`'s 93 name-imports are `Projection`, `DimRole` and `ViewCrop`;
`roi/` because `views/` legitimately needs its small fixed surface.

`roi/` took two of the eight functions step 4 sent to it, not eight — see the
corrected table there. `view/` is `spec.py` and `axes.py`, and imports
nothing else in `models/plot`: `PlotViewFrame` went in step 4 and `MaskMode`
left with `default_profile_label`. That sink property is what makes it
vocabulary rather than a layer, so it is now a test rather than a claim —
and it is a working smell test, since both names that turned out not to
belong here were found by noticing they wanted a frame or a region.

The three surfaces differ in kind, which is worth saying because only one of
them hides anything. `geometry/` exports 26 names and hides about 20: the
`mask_from_*` rasterizers, the per-mode cell bounds, the extent and edge
builders, all reached through `compile_with_mask_mode` and the frame.
`view/` exports 19 and hides one private helper — it exists for
concentration, not concealment, so that the sixty-odd callers who want
`Projection`, `DimRole` and `ViewCrop` say one short thing. `roi/` exports
five because that is what `views/` needs. Tests reach past all three to the
module when they exercise internals, which is deliberate: a test of the
cell-bounds arithmetic should break when that arithmetic moves.

- [x] **`Projection` answers its own questions.** Nine free functions taking
  a `Projection` first became methods, and `spec_from_slice_info` became
  `Projection.from_slice_info`: `storage_axis_for`, `plot_axis_for` (a real
  inverse pair at last), `plot_dim_names`, `is_plot_plane_axis`,
  `eligible_profile_axes`, `scan_axis` and `profile_axis` (properties),
  `profile_kind`, and `to_profile` — which matches the verb
  `PlotAxes.to_profile` already used for the same operation. 32 import
  bindings and 44 calls updated across 12 files. `resolve_axis_order` stays
  free: it decides an axis order before any projection exists.
- [x] Deletes 10 names from `view/`'s surface, 19 → 10, of which 9 are now
  types. Working sets fall with it: `region_controller` 9 → 6,
  `plot_request` 6 → 4, `trace` 2 → 1, `view.axes` 1 → 0, and
  `views/plot/roi/window.py` goes from six imported names to one.

### Step 7 — measure `region_controller`, then `fetch/` and `run/` — **landed**

- [x] **`region_controller` measured — decision 6.** 452 code lines, 31
  members (28 public), 6 signals, 8 private fields. Mapping each public
  member to the fields it reaches, transitively through its own helpers,
  partitions it:

  | members | touch | what they are |
  |---:|---|---|
  | 7 | `_view_crop`, `_view_crop_key` only | the crop |
  | 10 | `_roi_set` + three flags only | the ROI set |
  | 4 | both | `sync_region_state_with_view`, `invalidate_all_region_state`, `on_selected_keys_changed`, `on_plot_ndim_changed` |
  | 7 | neither | resolve a trace, frame or session from outside, and build a request |

  **The verdict is coordinator, with a real seam.** The crop cluster and the
  ROI cluster share *no field*, so the split is available — but the four
  members that touch both are not shared state, they are lifecycle fan-out:
  the view changed, so invalidate and resync both halves. That is what a
  coordinator does. Three of the six signals are emitted from both clusters
  for the same reason.

  So it **stays at the top level with `plot_session.py`**, and the split is
  not done here — decision 6 says measure, not refactor. If it is taken
  later it must hand out its two children rather than forward to them, per
  decision 1's precedent with `RunFetch`; a `RegionController` that
  re-exposed seventeen members would be the forwarding shell this project
  has said repeatedly it does not want.
- [x] `fetch/`: `request.py`, `plan.py`, `stages.py` — **no `pipeline.py`**,
  because there is nothing to put in one. The pipeline is the order the
  stages run in, and decision 1 put that on `RunFetch.get_plot_bundle`.
  `plot_request.py` split along the direction the dependency already ran:
  `plan` needs `PlotRequest`, `request` needs nothing from `plan`. The two
  builders step 4 reassigned here, `crop_from_region` and
  `roi_profile_request`, are in `request.py` with the thing they build. No
  `__init__` surface; every consumer names its module.
- [x] `run/`: `source.py`, **`pipeline.py`**, `frozen_spectrum.py`,
  `identity.py`. Not `fetch.py` as decision 4 had it: `models/plot/fetch/` is
  the package next door, and two things called `fetch` one directory apart is
  the kind of name this plan exists to delete. The distinction is real — that
  package *describes* a fetch, this class *performs* one — and `pipeline` is
  the name the draft wanted for it anyway. `RunFetch` and `.fetch` are
  unchanged, so nothing outside the package moved. No surface; each file
  exports one class.
- [x] Fixed in passing: `frozen_spectrum` annotated with `List` without
  importing it, invisible because `from __future__ import annotations` makes
  annotations strings.

### Step 8 — top level and the shell

- [ ] `plot_session.py` → `session.py`; the other session objects stay put.
- [ ] `display_manager.py` and `presenter.py` → `models/displays/`.
- [ ] Record the final layout, per-file working sets, and the import-site count
  against the 267 measured here.

---

## Not in this plan

`ImageGridCanvas` and `RunDisplayWidget` key ordering are deferred by the
maintainer until those widgets are rewritten. `MplCanvas`'s size, the widget
testing gap (3 of 473 tests), and teardown are named in the reviews and want
their own plans.

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-10 | Drafted. Shape C (split, then move) and per-package re-export policy chosen by the maintainer. The organising finding — that every large module mixes a zero-coupling vocabulary with all-coupling machinery — comes from mapping each member to the siblings it uses. |
| 2026-09-14 | Decision 5 reversed by the maintainer, and acted on in step 6: nine free functions taking a `Projection` are now methods on it, plus a `from_slice_info` constructor. The observation had been made twice — step 4 noted these looked like methods in costume and deferred to the decision, and step 6 then found six of them impossible to place because moving them would cycle. Both difficulties had the same cause: they were already home, on the type, and the placement question was the wrong one. `view/`'s surface is 19 → 10 names, nine of them types; `region_controller` 9 → 6, `plot_request` 6 → 4, `trace` 2 → 1, and the ROI window imports one name where it imported six. Two transcription hazards worth recording for the next mechanical conversion: substituting the receiver name for `self` also rewrote it inside error-message strings and numpydoc parameter entries, and neither shows up as a test failure except where a test matched the message text. 529 tests. |
| 2026-09-14 | Step 7 landed. The `region_controller` measurement is recorded under the step: coordinator-shaped, with a real seam between two state clusters that share no field, and it stays at the top level. Two naming corrections. `fetch/pipeline.py` does not exist — the pipeline is `RunFetch.get_plot_bundle`, so the draft's fourth file had no contents. And `run/fetch.py` is `run/pipeline.py`, because `models/plot/fetch/` already had that name one directory away; `RunFetch` and the `.fetch` attribute are unchanged. Three mechanical hazards worth recording: a regex keyed on `from .fetch` silently resolved to the sibling module rather than the package, an import list derived by comparing two groups missed a name both needed, and neither showed up as a test failure until the code ran. An undefined-name sweep across the package now runs after each move and is what caught the second, plus a pre-existing missing `List` import in `frozen_spectrum`. 30 modules, 4862 code lines, no runtime cycles, 529 tests. |
| 2026-09-14 | Step 6 landed. `view/` is `spec.py` + `axes.py` with a 19-name surface, and a test now asserts the package imports nothing else in `models/plot`. One finding: `profile_storage_axis` has no caller anywhere — the seventeen apparent uses are a `RoiOperation` field and a widget method of the same name, which is a third name collision of the kind step 4 fixed for `plot_axis_names`. Left in place, kept off the surface, and flagged rather than deleted. 27 modules, 4900 code lines, no runtime cycles, no function-local sibling imports, 529 tests. |
| 2026-09-14 | Step 6, first two packages: the guard was taught to walk subpackages first (it globbed one directory, so the moves would have silenced it), then `geometry/` and `roi/` landed. Two corrections to step 4's predicted redistribution, both recorded in its table: six of the eight functions promised to `roi/` stay in `view_spec`, because each reads a `Projection` and `PlotAxes.to_profile` needs `profile_view_spec` — moving it makes `view` import `roi` while `roi` already imports `view` for `SpatialReduce`, which is a runtime cycle. Being asked mostly by ROI code does not make a projection query ROI vocabulary, and that is the distinction the step-4 table got wrong. `crop_from_region` and `roi_profile_request` go to `fetch/` in step 7 instead: both build a request, and `crop_from_region` is view cropping, not ROI. `roi/` is therefore two files and a five-name surface. Two diagnostic bugs the first surface exposed are fixed in the tool: `working_set` now follows re-exports to the defining module, without which every count would have drifted toward zero as files moved while no reader's job got smaller, and `import_sites` now recurses. Surface rows are labelled, since their count measures the door. |
| 2026-09-14 | Step 5 landed. Four aliases, one definition each, and five deleted. No behaviour change: `PlotRequest.__post_init__` already validated both `mask_mode` and `spatial_reduce`, so `roi_set`'s widening to `str` was invisible to the interpreter — which is why it survived, and why narrowing it back is free. It adds one mutual pair, `region ↔ view_spec`: `region` now imports `PlotAxisName` at runtime while `view_spec` still names `MaskMode` under `TYPE_CHECKING` for `default_profile_label`. Not a runtime cycle, and it dissolves in step 6 when that function leaves for `roi/`. 522 tests. |
| 2026-09-14 | Step 4 landed. `view_spec` now imports one name from one sibling, `MaskMode` under `TYPE_CHECKING`, which leaves with `default_profile_label` in step 6. Making the spec required turned a silent fall-through into a raise for a 1-D projection, whose single plot axis had been passing the old `len(plot_order) >= 2` test and reaching the frame; the two ROI-window plane guards now ask `is_plot_plane_storage_axis`, which answers False without a plane, and two tests pin both. One precondition deliberately left alone: `profile_axis_for_roi_span` still refuses to answer without a frame, even though the mapping no longer needs one. Removing it would change when the ROI span axis gets corrected — `set_profile_context` can be handed a spec with no frame — and the plan's goal forbids behaviour changes, so it is recorded here instead of fixed. 522 tests. |
| 2026-09-14 | Step 4 re-scoped before starting, because its `view_spec` bullet sorted 14 functions by syntactic form into one destination and would have encapsulated nothing. Grouped by what they answer, they are five different things, and all but four already have a home in step 6 or step 7, so the step creates no new file. What survives is one defect the draft had not noticed: `storage_axis_to_plot_axis` holds two implementations of one mapping, and its own docstring says the frame branch answers wrong. That branch turns out to be dead at all five call sites, so the step is a deletion. Also measured: the `plot_axis_names` collision is three test call sites, not the wide rename the draft implied, and the free function has no production caller at all — `ViewIntent` names it as the overplot-compatibility check, so it is unwired rather than dead and keeps its test. |
| 2026-09-14 | Step 3 landed. `RenderMode` moved to `orientation.py` rather than `bundle.py` — recorded above with the reason, which is the plan's own first hard rule. Three extent and mesh-grid helpers became public because `bundle` crosses into them. The two test files were renamed with the modules they cover, `test_plot_geometry.py` → `test_bundle.py` and `test_plot_bundle.py` → `test_stages.py`; `test_bundle.py` keeps the render-mode classification tests next to the packing tests rather than splitting them into a `test_orientation.py`, because packing is where classification is applied and the two halves verify one behaviour. One finding about the diagnostic: `run_fetch`'s "from N modules" rose 4 → 5 without its working set changing at all, purely because one file it imports became two. The second column is even more gameable than the first, and neither is a target. `bundle` itself now imports 5 free functions from exactly one partner, which is the cohesive-pair shape the plan already excuses for `region`. 23 modules, 4806 code lines, both hard rules holding, 520 tests passing. |
| 2026-09-14 | Steps 1 and 2 landed. The guard and the diagnostic share one implementation, `tools/module_graph.py`, run as a script and imported by `tests/test_module_boundaries.py`; it reproduces every measurement in this plan (22 modules, 4791 code lines, each working-set row, and 64 inside / 178 `tests/` / 24 `views/` import sites), which is what lets a later step quote a before and an after. Two of this plan's derived totals are off and are corrected above: 12 files sit at zero, not 13, and the import sites measure 268 across 75 files rather than 267 across 74. The guard carries self-tests on throwaway packages, because a silently broken detector is a guard that passes forever. Step 2 moved eight functions rather than four — the four named cannot leave without the four they call, and leaving those behind would have re-pointed the same cycle the other way. `region_mesh`'s working set rose 0 → 3 and `plot_view_frame`'s fell 2 → 1: the rise is the point, since a rasterizer asking a frame where its cells are is the direction that was backwards before. Both hard rules now hold with an empty allowlist, and 520 tests pass. |
| 2026-09-14 | Re-derived at `f50633a` after the data-contract refactor. Measurements retaken: 22 files, 4791 code lines, 267 import sites, and a working-set table in which `run_fetch` has replaced `run_source` as the worst file. Step 1's split is done; what remains of it is the guard. Two function-local imports the draft missed are recorded, the `plot_geometry ↔ plot_request` cycle is closed, and `run/`'s contents changed because `KeyInfo` moved to `models/data` while `FrozenSpectrum` stayed. The draft's six open questions are settled as decisions, and the type-alias consolidation from the previous review is now a step, because it is the one part of this plan that deletes something. |
