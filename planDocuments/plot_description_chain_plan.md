# Plot description chain plan

Re-carving `models/plot` so the packages name the chain that is already there.

**Status:** drafted 2026-09-15 at `4c93e34`; all figures measured at that
commit. Answers [`load_pipeline_problem_statement.md`](load_pipeline_problem_statement.md),
which recorded the shape and proposed no work. Written to the conventions in
[`data_contract_review.md`](data_contract_review.md): steps name their files,
functions and call sites, and no step states a count it has not measured.

## Progress

One line per step. A step is **done** only when the whole suite is green at
its commit; nothing is left `xfail`ed across a step boundary.

The commit column is filled in by a follow-up commit, not by the step itself
— a commit cannot carry its own hash, and amending one to add it changes the
hash again.

| | step | status | commit |
|---|---|---|---|
| 1 | Make `plane/` the sink, and kill the cycle | **done** | `b1e33b8` |
| 2 | Form `spec/` | **done** | `f4f9d82` |
| 3 | Cut the two machinery-to-request edges | **done** | `020cf9d` |
| 4 | Reverse the chain, free functions onto their types | **done** | `ee92307` |
| 5a | Extract the block cache, composed over the reader | **open** | |
| 5b | Move the sequencer onto the request | **open** | |
| 6 | Give `Trace` its key | **open** | |

Gating decisions are listed under *Still to decide* below; all of them are
now settled, so no step is blocked. Step 6 is independent of 3–5b and may be
taken at any point.

---

**The block cache is out of scope.** Its three options stay open, and step 5a
is what makes them cheap to evaluate — today they cannot be, because the cache
and the pipeline are one class.

---

## The observation

The problem statement found a chain of descriptions of one plot at increasing
concreteness: `Projection` → `PlotRequest` → `FetchPlan` → `PlotBundle`, with
`ViewIntent` at the top. What it did not name is that there are **two
strands**, and each existing package holds half of each:

| package | chain half | vocabulary half |
|---|---|---|
| `view/` | `Projection`, `PlotAxes` | `DimRole`, `SliceItem`, `PlotAxisName`, `SpatialReduce`, `ViewCrop` |
| `geometry/` | `RegionDefinition`, `PlotBundle` | `PlotViewFrame`, orientation, mask, `RenderMode` |
| `fetch/` | `PlotRequest`, `FetchPlan` | — (and no fetch) |

That is both symptoms in one table. `view/` is simultaneously "the thing
everything imports" (its vocabulary half) and "the thing that cannot merge
with `request`" (its chain half). The `view` ↔ `geometry` cycle is two
half-sinks importing each other.

`view/` was never really a sink: it owns `ViewCrop`, whose only producer,
`RectRegion.to_view_crop`, lives in `geometry`.

### `ViewIntent` is the editor of the chain, not a link in it

It is four descriptions with a mutable holder on top, not five descriptions.
Two tells: it works in **names** (`dim_order: Tuple[str, ...]`) where
`Projection` works in **indices** (`axis_order: Tuple[int, ...]`), and a rung
derived by a pure function does not change vocabulary; and
`ViewIntent.set_reduce_from(projection)` flows state *back up* from the rung
below, which an editor does and a link does not. Its job — persisting intent
across a change of rank, which a rank-bound `Projection` cannot do — is real,
so it keeps its 380 lines and stays outside `spec/`.

### Cut along the strand and the cycle dies

The problem statement's objection to moving `PlotAxisName` and `ViewCrop` down
was that `ViewCrop` is a field of `Projection`, so a projection would not
import the package holding a type it carries. That only binds if `view/` stays
a sink. Split by strand and `Projection` sits *above* the vocabulary and
imports it freely. No third alias module, no touching the ROI path.

**The sink property is not lost, it moves.**
`tests/test_module_boundaries.py::test_the_view_vocabulary_depends_on_nothing_in_the_package`
asserts today that `view/` imports nothing in the package, and its docstring
argues that this is what makes it vocabulary rather than a layer. Step 1
retargets that test to `plane/`, which is a truer sink: the test's own two
worked examples of the smell — `storage_axis_to_plot_axis` taking a frame,
`default_profile_label` being ROI text — were both things that wanted a frame
or a region, and `plane/` *is* the frame.

---

## Decisions settled before step 1

1. **The chain's imports run downward.** Each rung derives the next as a
   method: `PlotRequest.plan()`, `PlotRequest.plot_bundle(reader)`. No rung
   needs a back-reference to its parent; `FetchPlan` stays self-contained,
   which is what makes a plan fully determine a read.
2. **The sequencer's receiver is `PlotRequest`, not `FetchPlan`.**
   `RunFetch.get_plot_bundle` reads nine request attributes (`plane_axes`,
   `region`, `profile_axis`, `plane_request`, `axes`, `transform`,
   `profile_axes`, `mask_mode`, `ykey`) and one plan attribute
   (`region_frame`). The plan is not even an input; it is produced halfway
   through. Settles decision 4 of the problem statement.
3. **`clear()` is not on the reader interface.** `RunSource` holds the
   concrete `CachingReader` and calls `clear()` on it directly, as it holds
   `_fetch` today. The chain sees only read methods and never learns that
   caching exists. This is what keeps the cache question deferrable.
4. **`TraceKey` moves to `trace/`.** Decision 5 of the problem statement.
5. **`RegionDefinition` is on the chain, not in the vocabulary.** It is a
   field of `PlotRequest`, frozen and serializable, and compiles *against* a
   frame rather than being one.
6. **`cached_plane` is not a cache.** Measured: it is the ROI-preview path
   only — `roi/window.py` → `RegionController.cached_parent_bundle_for_preview`
   → `Trace.preview_roi_profile`. `Trace.get_plot_bundle`, the normal draw
   path, never passes it. It stays a keyword argument, documented as an
   ROI-preview optimisation.
7. **`MaskMode` moves to `plane/roles.py`; `ReduceOp` is a duplicate.**
   `view/spec.py`, now `spec/projection.py`, recorded an argument for keeping
   `MaskMode` beside `compile_with_mask_mode`, "the thing it configures". The
   note itself is gone; step 1 carried the surviving half of it to
   `plane/roles.py`. That was true when
   that function was its only consumer. Measured now: it is used in four
   files, and the only use inside `region.py` is the parameter of
   `compile_with_mask_mode`, which step 4 turns into a method anyway —
   `request.py` and `roi/set.py` import from `geometry` purely to type a
   two-valued string. It is plane vocabulary. Separately, `ReduceOp` and
   `SpatialReduce` are both `Literal["sum", "mean"]`: the same type under two
   names, in two packages. `ReduceOp` has exactly one use — the signature of
   `reduce_masked_plane`, which has no production callers — so it dies with
   that function, or is replaced by `SpatialReduce` if the function stays.

### Still to decide, and they gate their steps

- **Does `spec/` have a flat `__init__` facade?** If it re-exports every name,
  step 2 is a rename rather than the deletion it claims. Naming modules at the
  import site (`from ..spec.plan import FetchPlan`) is what makes the rung
  visible where it is used, but it turns ~108 mechanical re-points into hand
  edits. Recommendation: no facade. **Gated step 2; settled — no facade.**
- **Does `RunSource` keep the reader surface, or hand out `.reader`?**
  **Settled — it keeps it.** `RunSource` *is* the reader; there is no
  `KeyReader`. Only the cache is extracted, and by composition. See step 5a.
  **Ungated.**
- **Does `FetchPlan` survive the cache decision?** Not gating — no step
  changes either way — but it should be settled with the cache rather than
  after it. Five of its eight fields are verbatim request copies: both
  `plan_fetch` construction sites write `ykey`, `xkeys`, `norm_keys` and
  `dims` straight from the request, and `plane_axes` is the
  `PlotRequest.plane_axes` property. Only `slice_info`, `plane_frame` and
  `region_frame` are computed, and its one unique behaviour, `reads_the_same`,
  is the block cache key. **Under option 3 of the cache question — delete and
  measure — `FetchPlan` becomes a three-field private intermediate** better
  expressed as a tuple inside `plot_bundle`. The denormalization is
  deliberate: its docstring records that a plan carrying indices but not keys
  forced executors to keep the request beside it. But today the only thing
  needing that self-sufficiency is the cache.

---

## Target tree

```
models/plot/
  plane/          the vocabulary: what maps onto a plot plane, where its
                  cells are, what covers them.  Imports nothing in models/plot.
    roles.py      DimRole, ROLE_LABELS, SLICE_ROLES, SliceItem,
                  PlotAxisName, SpatialReduce, MaskMode, ViewCrop
    orientation.py  RenderMode and the decisions a bundle records
    frame.py      PlotViewFrame
    mask.py       the rasterizers

  spec/           the chain, and the machinery it drives.  Import order is
                  strictly one way, ending at request.py.
    projection.py  Projection, resolve_axis_order
    axes.py        PlotAxes
    region.py      RegionDefinition and subclasses, CompiledRegion
    bundle.py      PlotBundle, .pack/.from_1d/.from_2d      (no request import)
    stages.py      the array functions                      (no request import)
    plan.py        FetchPlan, narrow, kept_axes
    request.py     PlotRequest: .plan(), .plot_bundle(reader)

  run/    source.py (key space + key access = the reader)
          cache.py (BlockCache, composed over a reader)
          collection.py  selection.py  frozen_spectrum.py
  trace/  key.py  trace.py  set.py
  session.py  view_intent.py  region_controller.py  roi/
```

`spec/` imports `plane/`; `run/` and `trace/` import `spec/`; nothing imports
back. `request.py` is last because it is the only module that knows the whole
chain — a sharper property than "no cycles", and assertable in
`tests/test_module_boundaries.py`.

`ViewCrop` goes to `roles.py`, not `frame.py`: its fields are a *storage* bbox
and storage axis indices, while `PlotViewFrame` describes the *displayed*
plane, and putting two coordinate systems in one file is the defect this plan
exists to remove.

### Churn, measured

Counts exclude definition lines and `__init__.py` re-exports.

| | src call sites | test call sites |
|---|---:|---:|
| imports naming `view` / `geometry` / `fetch` | 42 | 108 |
| `.fetch` **property** | **2** (`trace.py:230`, `:267`) | 76 |
| `plan_fetch` | 8 | 14 |
| `prepare_2d_bundle` | 4 | 35 |
| `compile_with_mask_mode` | 5 | 12 |
| `prepare_1d_bundle` | 4 | 4 |
| `build_plot_bundle` | 2 | 4 |
| `copy_plot_bundle` | 2 | 2 |
| `reduce_cached_plane` | 2 | 4 |
| `reduce_masked_plane` | **0** | 2 |
| reader surface (`describe`, `plot_axis_names`, `get_shape`, `load_coords`) outside `run/` | 11 | — |

The 13 other greps for `.fetch` are the *package* path `plot.fetch.request`,
not the property.

---

## Steps

Each step leaves the suite green.

**Paths and line numbers in open steps are kept current.** Steps 1 and 2 moved
every file in the package, so an open step citing `fetch/plan.py` would send a
reader to a path that no longer exists. Open steps below are re-pointed and
re-measured at `211886d`; steps already done keep the paths they were taken
against, because that is what they describe. Line counts are code lines.

### 1. Make `plane/` the sink, and kill the cycle

**Done** at `b1e33b8`.

Create `plane/`. Move `geometry/frame.py` (377), `geometry/orientation.py`
(266) and `geometry/mask.py` (357) into it unchanged. Move out of
`view/spec.py` into a new `plane/roles.py`: `SliceItem`, `SpatialReduce`,
`PlotAxisName`, `DimRole`, `ROLE_LABELS`, `SLICE_ROLES`, `ViewCrop`; and
`MaskMode` out of `geometry/region.py` into the same file.

Two tests assert the structure being bulldozed. Both are part of this step,
and either may be `xfail`ed for the length of the step if that keeps the diff
readable — but not past it:

- `test_the_view_vocabulary_depends_on_nothing_in_the_package` — retarget to
  `plane/` and rewrite the docstring to say why the sink moved. The property
  it defends is worth keeping; the package it names is not.
- `test_a_non_sibling_import_in_a_function_is_not_a_dodge` — hardcodes
  `facts["geometry.mask"]`, which becomes `facts["plane.mask"]`.

**Deletes:** the `view` ↔ `geometry` runtime cycle, and the
`from ..view import PlotAxisName, ViewCrop` line at `geometry/region.py:18`
that was the only edge holding it up.

**New file, motivated:** `plane/roles.py` is what makes `plane/` a real sink.
Without it the vocabulary stays inside a chain module and the cycle survives.

**Not in this step:** no function bodies change; `view/` and `geometry/`
still exist, holding their chain halves and re-exporting from `plane/` so
external importers do not churn yet.

### 2. Form `spec/`

**Done** at `f4f9d82`.

**Decide the facade question first.** Then move into `spec/`: `view/spec.py` →
`projection.py`, `view/axes.py` → `axes.py`, `geometry/region.py` →
`region.py`, `geometry/bundle.py` → `bundle.py`, `fetch/request.py` →
`request.py`, `fetch/plan.py` → `plan.py`, `fetch/stages.py` → `stages.py`.

**Deletes:** the packages `view/`, `geometry/` and `fetch/`, and their three
`__init__.py` re-export lists (12 + 63 + 48 lines) — three names that the
problem statement showed are each a lie in a different direction, `fetch/`
most of all, since it contains no fetch.

**Not in this step:** no code moves between modules and no signature changes.

### 3. Cut the two machinery-to-request edges

**Done** at `020cf9d`.

Two functions carry the entire dependency of the machinery on the chain.

`build_plot_bundle(data, request, *, render_mode_hint, label)` in
`spec/bundle.py` uses `request` at exactly one line — `request.region is not
None`, at `spec/bundle.py:322`. Replace the parameter with
`is_roi_profile: bool`. 2 src, 4 test call sites; the only production caller
is `RunFetch.get_plot_bundle`, which has the request in hand.

`reduce_cached_plane(plane, request, *, label)` in `spec/stages.py` reads
`plane_axes`, `profile_axis`, `spatial_reduce`, `region`, `mask_mode`, and
becomes `PlotRequest.reduce_cached_plane(plane, label)`. 2 src, 4 test call
sites.

What looked like an obstacle is a third move that should happen anyway.
`_plane_axis_arrays(plane, frame)`, a module-private in `stages.py`, is
`reduce_cached_plane`'s only blocker — but it has **one caller, no tests, and
an unannotated `frame` parameter that is entirely redundant**: `frame.shape`
is `plane.y.shape`, `frame.render_mode` is `plane.render_mode`, and
`frame.plot_y_dim` / `plot_x_dim` are hardcoded to 0 and 1 by
`PlotBundle.view_frame()` itself. It also repeats that method's axis-name
padding verbatim. So it becomes **`PlotBundle.axis_arrays()`**, taking no
arguments, sharing the padding with `view_frame()`.

`reduce_cached_plane` then needs only public names — `PlotBundle.view_frame`,
`PlotBundle.axis_arrays`, `materialize_view`, `prepare_1d_bundle`,
`Projection`, `DimRole`, `PlotAxes` — of which `request.py` already imports
the last three. It brings `numpy` and `xarray` into `request.py`, which has
neither today; they arrive here rather than at step 5b, where the sequencer
would have brought them anyway.

**Order within the step matters and it is one commit.** Removing
`reduce_cached_plane` from `stages.py` is what deletes the `stages → request`
edge, and `request.py` gaining `from .stages import materialize_view` is what
adds the opposite one. Split across two commits, the first is a cycle.

**Deletes:** `from .request import PlotRequest` in `stages.py` and the
`TYPE_CHECKING` import of it in `bundle.py`. After this, **no module in
`spec/` below `plan.py` imports `PlotRequest`** — the precondition for step 4.

### 4. Reverse the chain, and put the free functions on their types

**Done.** Six free functions became methods and the `plan` -> `request` edge
reversed: `spec/plan.py` is now `FetchPlan` + `narrow` + `kept_axes` and
imports nothing from `spec/`, while `spec/request.py` carries the planner.
`PlotBundle` gained `from_1d`, `from_2d`, `pack`, `storage_axes` and `copy`,
which makes `run/frozen_spectrum.py` a file about frozen spectra only.
Two departures from what is written below, both noted in the modification
log: `_storage_axes_from_bundle` became the public `PlotBundle.storage_axes`
rather than a private method, because its caller is in another module; and
`copy()` preserves `row_reversed` / `col_reversed`, which the free function
silently dropped.

- `plan_fetch(request, *, plane_frame)` → `PlotRequest.plan(*, plane_frame)`.
  Its 96-line body (`spec/plan.py:113–208`) **moves file**, into
  `spec/request.py`. `spec/plan.py` is then `FetchPlan` + `narrow` +
  `kept_axes`, ~130 lines of its current 226, and no longer imports
  `request.py`. 8 src, 14 test sites.
- `build_plot_bundle(...)` → `PlotBundle.pack(data, *, is_roi_profile,
  render_mode_hint, label)`. 2 / 4.
- `prepare_1d_bundle` → `PlotBundle.from_1d` (4 / 4);
  `prepare_2d_bundle` → `PlotBundle.from_2d` (4 / **35** — the largest single
  rename in the plan).
- `compile_with_mask_mode(frame, region, mask_mode)` →
  `RegionDefinition.compile_masked(frame, mask_mode)`, a concrete base-class
  method calling `self.compile(frame)`. 5 / 12. It cannot become a
  `PlotViewFrame` method: `plane/` must not import `spec/`.
- `copy_plot_bundle(bundle)` and `_storage_axes_from_bundle(bundle)` in
  `run/frozen_spectrum.py` → `PlotBundle.copy()` and a private method beside
  it. 2 / 2. Both are bundle methods sitting in the wrong file.

**Deletes:** six free functions (`_plane_axis_arrays` and
`reduce_cached_plane` went at step 3).

**Deliberately not moved.** `narrow(item: SliceItem, ...)` and
`kept_axes(items: Sequence[SliceItem])` stay free: `SliceItem` is a type alias,
not a class, so the rule cannot apply. `reduce_masked_plane` has **zero
production callers** and two test calls — decide separately whether to delete
it; it is not a put-it-on-its-type item. `x_dimension(y: KeyInfo, ...)` at
`run/source.py:16`, unmoved, is **dropped from this plan**: `KeyInfo` lives in
`models/data/key_info.py`, and a plot-package re-carve should not reach into
the data layer to add a plot-shaped method to a data type.

**Not in this step:** `get_plot_bundle` has not moved; `RunFetch` still holds
it and now calls `PlotRequest.plan()`.

### 5a. Extract the block cache, composed over the reader

**Open**, and no longer gated.

`run/pipeline.py` is 450 code lines; by the problem statement's method-line
measure, 463: 289 of block cache, 101 of `get_plot_bundle`, 53 of
`_plane_frame`, 20 of `_render_hint`.

**`RunSource` is the reader.** `RunFetch` reaches into exactly five of its
methods and nothing else, so the reader surface already exists and does not
need to be moved to find it. Measured per method:

| | method | lines | reaches `RunSource` for |
|---|---|---|---|
| cache | `_held_windows` | 25 | — |
| cache | `_contained_window` | 54 | — |
| cache | `_narrowed` | 39 | — |
| cache | `_load_block` | 52 | — |
| cache | `_read_block` | 46 | `load` |
| cache | `_norm_array` | 55 | `describe`, `load`, `plot_axis_names`, `read` |
| seq | `get_plot_bundle` | 101 | `describe` |
| seq | `_plane_frame` | 53 | `load_coords` |
| seq | `_render_hint` | 20 | `describe` |

Two things follow. The cache's collaborator surface is **four methods**, not
the six a reader would carry — `load_coords` and `get_shape` belong to the
sequencer and leave at 5b. And **170 of the cache's 289 lines reach for
nothing**: the window arithmetic is pure, over `FetchPlan`s and held blocks.

- **`run/cache.py`** — `BlockCache`, taking its reader as a constructor
  argument: `__init__(reader)`, `block(plan) -> (block, norms)` and `clear()`,
  built from `_load_block`, `_held_windows`, `_contained_window`, `_narrowed`,
  `_read_block` and `_norm_array`, ~290 lines out of `pipeline.py`.
- **`run/source.py`** — constructs `BlockCache(self)` and grows a three-line
  `block(plan)`. `clear()` is still called at `run/source.py:184` and `:710`,
  unchanged and still before `data_changed`. No key-access method moves, so
  the 11 production call sites outside `run/` are untouched.
- **Tests** — the window-containment logic gets its first direct tests,
  against a stub reader, exactly as `ChunkCache` is tested against
  `_FakeAccessor` / `_FakeRun` in `tests/test_chunk_cache_l2.py`. Today the
  only test reaching inside is `tests/test_stages.py:859`, calling
  `_load_block` through a real catalog.

**Deletes:** `RunFetch._load_block`, `_held_windows`, `_contained_window`,
`_narrowed`, `_read_block`, `_norm_array` and `clear` — the whole cache half
of the class. `RunFetch` survives this step as a thin sequencer over the
reader and the cache, so the 76 test sites do not churn yet.

**Why not a `KeyReader`.** The rejected shape was `KeyReader` plus
`CachingReader(KeyReader)` overriding `block()`. Two objections, and the
second is decisive. A reader holding a back-reference to `RunSource` for
`_source(key)` and the key table is a forwarding model, which the house rule
forbids: "which keys exist" and "read this key" are one concept with two
verbs. And *inheritance is the arrangement that defeats the goal* — under
`CachingReader(KeyReader)` the cache cannot be constructed without a real
reader, hence a real `CatalogRun`, so the cache would be less testable than
it is now, not more. What makes a cache testable is composition over a narrow
collaborator, which is why `block()` takes its reader as an argument.

**The cost, stated plainly.** `RunSource` does not shrink; it stays ~744
lines, and step 5b's figure below no longer holds. There is a non-artificial
version of the reader split — give the reader the key table outright and
leave `RunSource` a Qt shell over it — but then `available_keys`,
`is_synthetic_key` and `register_frozen_spectrum` move or forward too. That
is a larger change than 5a, churns far more than 11 call sites, and is not in
this plan.

### 5b. Move the sequencer onto the request

**Open.**

`PlotRequest.plot_bundle(reader, *, cached_plane=None, label="")` in
`spec/request.py` — the 101-line sequencer plus `_plane_frame` as a private
`PlotRequest.plane_frame(reader)`. The `reader` is the `RunSource` itself: it
answers the five key-access methods and, after 5a, `block(plan)` as well.
The recursion becomes `self.plane_request.plot_bundle(reader)`: a request delegating to a different
request.

**Deletes:** the class `RunFetch`; the file `run/pipeline.py`, which was the
invented third name step 7 of the module organization plan reached for; the
property `RunSource.fetch` and its 2 src / 76 test sites;
`RunFetch._render_hint`, one line — `describe(ykey).render_hint` — inlined at
its two uses. `RunSource` does **not** drop to the 250 method lines item 5 of
the post-refactor review named: 5a leaves the key access on it deliberately,
and that target is declined rather than missed.

`Trace.get_plot_bundle` (`trace.py:213`) **survives** — it is called from
`plot_worker.py:96` and `single_canvas.py:398` — and its body becomes
`self._request.plot_bundle(self._run.reader, ...)`. Two similar names then
exist at different altitudes: `Trace.get_plot_bundle` (model state) and
`PlotRequest.plot_bundle` (the chain). Rename the Trace one if that reads
badly; do not leave it unexamined.

**Not in this step:** the cache's key, capacity and location are unchanged.

### 6. Give `Trace` its key

**Open.** Independent of steps 3–5b.

Independent of steps 3–5b, and cheaper if taken first.

Create `trace/`: `key.py` holding `TraceKey` moved out of `spec/request.py`,
`trace.py` and `set.py` moved from top level.

**Deletes:** `PlotRequest.trace_key`, which is a **method taking
`fan_out_index`**, not a property — `request.trace_key()` at `trace.py:75` and
`request.trace_key(self._trace_key.fan_out_index)` at `:159`. Its logic needs
a home: `TraceKey.of(request, fan_out_index=0)`, a classmethod in
`trace/key.py`, so `spec/` imports nothing from `trace/`. `trace.py` is the
only reader; `region_controller.py` uses `trace.trace_key`, the `Trace`
property, which is untouched.

---

## Explicitly not in this plan

- The block cache's key, capacity or location. Step 5a is the prerequisite for
  deciding those, not the decision.
- Whether key access (B) belongs on `RunSource` or below it. Settled for
  this plan — it stays on `RunSource` — but only against the alternative 5a
  proposed. The larger version, where a plain model owns the key table and
  `RunSource` becomes a Qt shell over it, is untouched and still open.
- `x_dimension` → `KeyInfo`, which leaves the package.
- Whether `reduce_masked_plane`, which has no production callers, should
  exist. If it goes, `ReduceOp` goes with it; if it stays, it should be typed
  `SpatialReduce` rather than keep a second name for the same literal.
- `ViewIntent`, `RegionController`, `PlotSession` and `roi/` stay at top level
  as the mutable Qt layer. `region_controller.py` is 821 lines and wants its
  own treatment.
- **The `PlotViewFrame` / `PlotBundle` field overlap.** Eight fields are
  shared — `render_mode`, `axis_names`, `extent`, `mesh_x`, `mesh_y`,
  `row_reversed`, `col_reversed`, and `shape` against `y.shape` — with
  `view_frame()` as the 45-line conversion and the two fields it adds,
  `plot_x_dim` and `plot_y_dim`, hardcoded to 1 and 0. The frame is not
  redundant: its fifteen cell-geometry methods are its content, and the ROI
  path needs one built from `load_coords` before any data is read. What is
  redundant is that the bundle *restates* a frame instead of holding one —
  also the root cause of the axis-name padding that `axis_arrays` and
  `view_frame` both open-code. A better target than any chain link, and a
  separate change.
- `MplCanvas`, widget testing and teardown, named in the reviews.

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-15 | Drafted at `4c93e34`. |
| 2026-09-16 | Paths and line numbers in the open steps re-pointed and re-measured at `211886d`, after steps 1 and 2 moved every file in the package. Done steps keep the paths they were taken against. The convention is stated at the head of the Steps section so it does not have to be rediscovered: an open step must send a reader to a path that exists. |
| 2026-09-16 | Progress markers added: a table near the top, a status line on each step, and a settled marker on gating decisions as they are taken. The document had no way to say which steps had landed, which matters more here than usual because step 6 is independent of 3-5b and may be taken out of order. |
| 2026-09-16 | Asked whether every link pulls its weight, before any work started. `ViewIntent` is reclassified as the chain's editor rather than a link: it works in names where `Projection` works in indices, and `set_reduce_from` flows state back up. `FetchPlan` is recorded as the weakest genuine rung — five of eight fields are request pass-throughs and its unique behaviour is the cache key — so its survival is tied to the deferred cache decision and listed with it. The `PlotViewFrame` / `PlotBundle` eight-field overlap is recorded as a non-goal: a real duplication, larger than anything on the chain, and out of scope here. |
| 2026-09-15 | Decision 7 reversed after the maintainer noted that recorded decisions are advisory during a reorganization, not binding. On the merits `MaskMode` is plane vocabulary — four consumers, and its only use in `region.py` is a parameter that step 4 turns into a method — so it moves to `plane/roles.py`. Measuring it also turned up `ReduceOp` and `SpatialReduce` as the same `Literal["sum", "mean"]` under two names in two packages, which the note in `view/spec.py` claims to have cleaned up. Step 1's framing of the two boundary tests is relaxed: they may be xfailed for the length of the step, green by the end of it. |
| 2026-09-17 | Step 5a's gating decision settled, and the step rewritten. The maintainer objected that a non-caching reader reaching back to its parent `RunSource` for every load and key operation is artificial, which is the no-forwarding-models rule. Measuring `RunFetch` per method settled it: it reaches into exactly five `RunSource` methods, the cache half needs only four of them, and 170 of the cache's 289 lines reach for none. So `RunSource` is the reader, `KeyReader` is dropped, and only `BlockCache` is extracted — composed, not inherited. The inheritance in the old shape was the real obstacle to the testability the split was for: `CachingReader(KeyReader)` cannot be built without a real `CatalogRun`, whereas a cache holding its reader can be handed a stub, as `ChunkCache` already is in `tests/test_chunk_cache_l2.py`. The cost is accepted explicitly: `RunSource` does not shrink, and the post-refactor review's 250-method-line target for it is declined rather than missed. |
| 2026-09-16 | Step 4 landed with two departures. `_storage_axes_from_bundle` became `PlotBundle.storage_axes`, public rather than the private method the step called for, because its only caller is `FrozenSpectrum.load_coords` in another module and a leading underscore there would be a private name crossing a boundary — the same objection that shaped step 3. It sits beside `axis_arrays` and the docstring says why the two are different questions rather than one written twice: storage order against display order, edges against centres, and 1-D as well as 2-D. Second, `PlotBundle.copy()` now preserves `row_reversed` and `col_reversed`; `copy_plot_bundle` omitted them, so every copied bundle claimed no axis had been reversed. No test covered it because a frozen bundle is re-read through `storage_axes` and `get_data`, neither of which reads the flags. Also cleaned up in passing: `plane/roles.py` carried a duplicate block of three type aliases and an orphaned half-sentence comment, left by step 1's extraction. |
| 2026-09-15 | Step 3's choice between two awkward options collapsed: the maintainer pointed out that `_plane_axis_arrays` is itself a `PlotBundle` method in the wrong place. Measured and it is stronger than that — its `frame` argument is redundant, every field it reads is on the bundle, and it has one caller and no tests. `reduce_cached_plane` moves onto `PlotRequest` with no private name crossing a boundary, and the step's gating decision is withdrawn. |
| 2026-09-15 | Reviewed step by step before any work started. Call-site counts were recounted excluding definitions and `__init__` re-exports and were overstated throughout — most importantly `.fetch`, which is 2 production sites and not 15, because the earlier count conflated the property with the `plot.fetch.request` package path. Four substantive changes: step 1 now names the two boundary tests it breaks, and records that the sink property moves to `plane/` rather than being given up; `MaskMode`/`ReduceOp` no longer move, honouring a decision recorded in `view/spec.py`; step 3 records that `reduce_cached_plane` cannot simply become a method, because it uses a module-private helper, and offers two ways out; step 5 splits into 5a and 5b so the 76 test sites churn once, late. `x_dimension` is dropped for leaving the package, and three questions that were being settled mid-step are listed as gating their steps. |
