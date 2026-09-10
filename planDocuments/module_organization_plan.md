# Module organization plan

Reorganising `models/plot` so a reader holds less in their head at once.
Follows [`refactor_plan.md`](refactor_plan.md), which completed 2026-09-10,
and its [`post_refactor_review.md`](post_refactor_review.md), which named
`run_source` and package size as what remains.

**Status:** drafted 2026-09-10, not started, and **superseded in part**.
Discussing step 1 established that `run_source` cannot be fixed by moving
functions — the pipeline's intermediate value has no name, so every stage
re-derives it from loose parameters. That became
[`data_contract_plan.md`](data_contract_plan.md), which runs first and takes
this plan's step 1 with it. Re-derive the rest of this document afterwards
rather than executing it as written; the data-contract plan's **Kept in mind**
section lists what changes.

## The goal, and how it differs from the last plan

The refactor asked *does each thing have one implementation?* This pass asks
*can a reader understand one file without opening six others?*

It is **not a rewrite**. No behaviour changes, no function bodies rewritten.
It moves code between files and renames things so that where something lives
tells you what altitude it is at. It will produce **more files and probably
more lines**; the thing being minimised is how much a reader must hold open at
one time, not the total.

### Invariant 10 does not apply here, and its replacement

The refactor's invariant 10 — *every step names what it deletes* — is what
stopped that work becoming a layer-adding exercise. This pass deletes almost
nothing by design, so that invariant would disqualify every step. It is
replaced, for this plan only, by one that measures the same instinct against a
different quantity:

> **Every step names, before and after, the *reader's working set* of each
> file it touches** — the number of sibling modules whose free functions that
> file uses. A step that does not lower a working set somewhere is not a step
> in this plan.
>
> And two absolutes: **no runtime import cycles inside `models/plot`**, and
> **no function-local import used to dodge one**.

Working set counts *free functions*, not classes, because that is the
distinction the maintainer drew and the measurements confirm. Importing
`RunCollection` and calling `add_runs` on it costs a reader nothing; importing
`reduce_before_mask`, `mask_to_profile` and `materialize_view` means the
reader must go and read another module to know what this one does.

Both are scriptable, so step 1 ships them as a test — the same move as the
refactor's ownership guard.

---

## What the tree measures

Taken at `9ecbe11`. `models/plot` is 20 files, 4889 code lines, and **201
import statements naming one of its modules across 52 files**.

### Working sets today

| File | free fns imported | from N modules | |
|---|---:|---:|---|
| `run_source` | 15 | **5** | worst |
| `plot_bundle` | 9 | 5 | |
| `region_controller` | 9 | 4 | |
| `plot_request` | 7 | 4 | |
| `region` | 7 | **1** | a cohesive pair, not a spread |
| `trace` | 2 | 2 | |
| `plot_session` | 1 | 1 | the healthy shape |
| `view_spec` | 0 | 0 | pure leaf, fan-in of 27 |

`region` shows why the count alone is the wrong metric: seven functions from
*one* partner is a module pair. Fifteen from *five* is a procedure smeared
across a package.

### The finding: files are mixing altitudes

Every member of every large module was mapped to the sibling modules it
actually uses. Four out of four split the same way:

| File | zero-coupling half | all-coupling half |
|---|---|---|
| `view_spec.py` (789) | `Projection`, `ViewCrop`, `DimRole` — 269 | 13 axis/profile queries — 438 |
| `plot_request.py` (603) | `PlotRequest`, `FetchPlan`, `TraceKey`, `narrow` — 310 | `plan_fetch`, `crop_from_region`, `roi_profile_request` — 238 |
| `plot_bundle.py` (758) | `apply_normalization`, `apply_transform`, `slice_info_for_key` — 125 | reduce + ROI mask — 570 |
| `run_source.py` (1193) | `RunSource` key access — 512 | fetch orchestration — 569 |

There are three altitudes in this package and the filenames encode none of
them:

1. **Vocabulary** — value types and pure queries about them. Near-zero sibling
   coupling, very high fan-in.
2. **Machinery** — free functions combining several vocabulary types. All the
   cross-module coupling lives here.
3. **Objects** — long-lived `QObject`s that coordinate.

`run_source.py` is the only file mixing an *object* with *machinery*, which is
exactly why it reads worst.

### `run_source`'s seam is exact

512 raw lines of key access, 569 of fetch orchestration, and the fetch half
reaches into the other through precisely six members:

```
read   load_axes   describe_axes   key_table   get_plot_hints   _frozen_entry
```

That is almost verbatim the surface `session_and_traces_plan.md` documented
for `RunSource` — "`key_table`, `identity`, `read`, `describe_axes`,
`load_axes`". The class has been carrying a second job against its own
declared interface.

### Names that mislead

- **`plot_bundle.py` does not define `PlotBundle`.** `plot_geometry.py` does,
  and since view-pipeline step 7 it also holds `build_plot_bundle`.
- **The `plot_` prefix spans all three altitudes**: `plot_geometry` and
  `plot_view_frame` are display primitives, `plot_request` and `plot_bundle`
  are the pipeline, `plot_session` is the object root. It groups by accident
  of history, and it is redundant inside a folder called `plot`.
- **`display_manager.py` and `presenter.py` are not about plotting.** Fan-in 0
  and 1; nothing in the package imports them back. They are the multi-display
  shell, filed one layer too low.

### One runtime cycle, dodged rather than fixed

`plot_view_frame ↔ region_mesh` is a genuine runtime cycle, survived by a
**function-local import** at `plot_view_frame.py:332`:

```python
from .region_mesh import _image_cell_bounds
```

`_image_cell_bounds` is cell geometry *on a frame*. It belongs with the frame,
not with mask rasterization; moving it removes the cycle and the deferred
import together.

Two more cycles exist and are survivable only because they are
`TYPE_CHECKING`: `region_controller ↔ plot_session` (a controller naming its
parent — expected), and **`plot_geometry ↔ plot_request`, which this project
created in view-pipeline step 7** when `build_plot_bundle` moved to
`plot_geometry`. A cycle broken by `TYPE_CHECKING` is a boundary in the wrong
place, not a solved problem.

### Who actually imports this package

| | views/ | tests/ | other |
|---|---:|---:|---:|
| name-imports | **43** | **258** | 3 |

Production code outside `models/plot` imports 43 names, spread thinly: 12 from
`view_spec`, 12 from `region`, 4 each from `plot_request`, `plot_geometry` and
`plot_view_frame`, then single digits. Everything else is tests.

Two consequences. First, **rewriting import sites is cheap and the suite
verifies it instantly** — 85% of the churn is test files. Second, the modules
with a genuinely healthy shape are visible: `run_source`, `plot_session` and
`view_intent` export exactly *one name each* to the outside world, across 22,
14 and 11 files.

**Tests import 19 private names**, all from `region_mesh` —
`_cell_x_bounds_mesh`, `_cell_y_bounds_mesh`, `_data_limits`,
`_image_cell_bounds`. A module whose real public surface is undeclared and
whose useful functions are marked private.

---

## Target layout

```
models/plot/
│
│   the ownership tree, at the top level, one class per file
├── session.py              PlotSession
├── run_collection.py       RunCollection
├── selection.py            Selection
├── trace.py                Trace
├── trace_set.py            TraceSet
├── region_controller.py    RegionController
│
├── geometry/               "what is drawn, and where"
│   ├── bundle.py           PlotBundle, RenderMode, prepare_1d_bundle, prepare_2d_bundle
│   ├── orientation.py      display_flips, orient_for_display, classify_render_mode,
│   │                       extents, edges, mesh grids, get_render_mode_hint
│   ├── frame.py            PlotViewFrame, frame_for_plane, frame_from_bundle,
│   │                       region_frame_for_bbox, cell bounds
│   └── mask.py             the mask_from_* rasterizers        (was region_mesh)
│
├── view/                   "what the user asked to see"
│   ├── projection.py       DimRole, Projection, ViewCrop, ROLE_LABELS, SLICE_ROLES
│   ├── axes.py             the 13 axis / profile queries
│   └── intent.py           ViewIntent
│
├── roi/                    "what the user drew"
│   ├── region.py           RegionDefinition + shapes + compile_*
│   └── roi_set.py          RoiEntry, RoiOperation, RoiSetModel
│
├── fetch/                  "request → indices → bundle"
│   ├── request.py          PlotRequest, TraceKey, FetchPlan, build_plot_request
│   ├── plan.py             narrow, plan_fetch, crop_from_region, roi_profile_request
│   ├── reduce.py           projection reduce + ROI mask machinery
│   ├── normalize.py        slice_info_for_key, apply_normalization, apply_transform
│   └── pipeline.py         the fetch half of run_source
│
└── run/                    "one run's keys and their data"
    ├── source.py           RunSource
    ├── key_info.py         KeyInfo, RunIdentity, AxisLayout
    └── frozen_spectrum.py  FrozenSpectrum
```

`display_manager.py` and `presenter.py` leave the package entirely.

**Why the session objects stay flat.** They *are* the ownership tree the last
plan spent thirteen steps establishing. A reader opening `models/plot/` should
see that tree first, with the machinery tucked into folders behind it. Putting
them in `session/` would bury the one thing the package is organised around.

### Re-export policy, decided per package

Deciding this per package, as agreed. The 43-vs-258 split is what drives it:
re-exporting to spare *test* imports would be paying the cost of a second way
to import every name — the thing step F just finished removing — for a
benefit that accrues to files the suite rewrites for free.

So the question is only whether a package `__init__` **declares a boundary
worth declaring**, which is a comprehensibility argument, not a churn one.

| Package | `__init__` re-exports? | Why |
|---|---|---|
| `geometry/` | **Yes** | The cycle lives inside it, and outsiders are currently importing four private names from `region_mesh`. A declared surface is what turns three entangled files into one concept and puts `mask.py`'s internals behind a door. |
| `view/` | **Yes** | 49 of its 69 name-imports are three types (`DimRole`, `Projection`, `ViewCrop`). A stable, tiny, genuinely public vocabulary. |
| `roi/` | **Yes** | Small fixed surface — the four region shapes plus `RoiOperation` / `RoiSetModel` — and `views/` legitimately needs it. |
| `fetch/` | **No** | Its only production consumer is `run/source.py`, inside the package. Views import four names. A surface would be declaring a boundary nobody crosses. |
| `run/` | **No** | Each file already exports one class. That is the healthy shape; it needs no help. |
| top level | **No** | Same. |

---

## Phase 1 — split and rename, still flat

The judgment is here. Each step changes which file code lives in, and a
mistake in one is visible on its own rather than buried in import churn.

### Step 1 — the guard, and `run_source`

Ship the measurement first so every later step is checked against it.

- [ ] `tests/test_module_boundaries.py`: no runtime cycles inside
  `models/plot`; no function-local imports of a sibling; working set of every
  file at or below a recorded ceiling. Seed the ceiling at today's maximum
  so it can only ratchet down.
- [ ] Split `run_source.py` at the six-member seam. `RunSource` keeps key
  access; the fetch orchestration moves out with the block cache it owns.
- [ ] Working set: `run_source` **5 → 0**; the new file inherits 5.

**The decision this step turns on** (see open questions): whether the fetch
half becomes a class the source holds, or free functions taking the source.
A class is one forwarding method on `RunSource` — acceptable under the
standing rule, which forbids a model that re-exposes *many* of a child's
methods, not one. The payoff either way is that the pipeline becomes testable
against a six-method fake instead of a whole run.

### Step 2 — `plot_bundle` and `plot_geometry` stop lying

- [ ] `PlotBundle` and the `prepare_*` packers get a file whose name says so.
- [ ] The orientation / render-mode / extent geometry gets its own.
- [ ] `plot_bundle.py`'s two halves separate: pure array ops (125 lines, zero
  sibling coupling) from reduce + ROI mask (570).
- [ ] `build_plot_bundle` moves to sit with the reduce machinery rather than
  the geometry, which **removes the `plot_geometry ↔ plot_request`
  `TYPE_CHECKING` cycle** this project created in view-pipeline step 7.
- [ ] Working set: `plot_bundle` **5 → 3 and 0**.

### Step 3 — `plot_request` and `view_spec` separate types from machinery

- [ ] `PlotRequest` / `FetchPlan` / `TraceKey` / `narrow` (310) from
  `plan_fetch` / `crop_from_region` / `roi_profile_request` (238).
- [ ] `Projection` / `ViewCrop` / `DimRole` (269) from the 13 axis and
  profile queries (438).
- [ ] Working set: `plot_request` **4 → 0 and 4**; `view_spec` unchanged at 0
  but 789 lines become 269 + 438.

### Step 4 — break the real cycle, declare the mask surface

- [ ] Move `_image_cell_bounds` to sit with the frame; delete the
  function-local import at `plot_view_frame.py:332`.
- [ ] Decide the public surface of the mask module and rename the four
  underscore functions that 19 test imports already treat as public — or
  stop the tests reaching for them. Both are defensible; picking one is the
  step.
- [ ] Working set: one runtime cycle **1 → 0**.

## Phase 2 — move into packages

Mechanical. Every diff hunk is a file rename or an import line; no hunk
touches a function body. Verified by the suite plus the step 1 guard.

### Step 5 — `geometry/`, `view/`, `roi/`

The three that get a declared surface. Do them together: they are the bottom
of the stack, and their `__init__` files are the point.

### Step 6 — `fetch/` and `run/`

No `__init__` surface. `run/source.py` is the only production consumer of
`fetch/`.

### Step 7 — top level and the shell

- [ ] `plot_session.py` → `session.py`; the remaining session objects stay put.
- [ ] `display_manager.py` and `presenter.py` leave `models/plot` entirely.
- [ ] Record the final layout, per-file working sets, and the import-site count
  against the 201 measured here.

---

## Open questions — what to discuss before starting

1. **Does the fetch half of `run_source` become a class or free functions?**
   It owns the one-entry block cache, so it wants state. A `BundleFetcher`
   the source holds costs one forwarding method; free functions taking a
   cache object cost a parameter on every call. This is step 1's real content
   and worth settling first.

2. **Where does `ViewIntent` live — `view/` or the top level?** It is a
   `QObject` the session owns, so by the "ownership tree at the top level"
   rule it belongs there; but a reader looking for view state will open
   `view/`. The rule and the reader disagree, which usually means the rule
   is slightly wrong.

3. **Where do `display_manager` and `presenter` go?** `models/displays/`,
   or flat in `models/` next to `app_model.py`? Note this is a *move only* —
   `PlotPresenter`'s design was deliberately left alone in step F and stays
   that way here.

4. **Should `run/` exist at all,** or do `source.py`, `key_info.py` and
   `frozen_spectrum.py` sit flat? Three files is a thin package. The argument
   for it is that `key_info` has fan-in from exactly one module and reads as
   `RunSource`'s private vocabulary.

5. **The 13 axis/profile queries in `view/axes.py` are all functions taking a
   `Projection`.** They were kept off the type deliberately — view-pipeline
   step 7's exit criterion says "`Projection` gains no reduce method". A
   *query* is not a reduce, so some of them could be methods. Worth deciding
   explicitly rather than inheriting a rule written about something else.

6. **Is `region_controller` still one object?** It was not measured for a
   seam in this pass, but its coupling is smeared across 4–5 modules per
   method and it is 455 code lines with 28 public members. It may be a
   coordinator like `PlotSession`, or it may be hiding a split like
   `run_source` was. Measuring it is cheap and should probably happen before
   phase 2 fixes its home.

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-10 | Drafted. Shape C (split, then move) and per-package re-export policy chosen by the maintainer. The organising finding — that every large module mixes a zero-coupling vocabulary with all-coupling machinery — comes from mapping each member to the siblings it uses, not from reading the files. Invariant 10 explicitly replaced for this plan, since a reorganisation deletes nothing. |
