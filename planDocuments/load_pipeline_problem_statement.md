# Where the data load and the pipeline live

**Status: OPEN. Re-derived 2026-09-15 at `3468650`.** Opened after
[`module_organization_plan.md`](archive/module_organization_plan.md) closed.
That plan's terms were "no behaviour changes and no function bodies
rewritten", and at step 7 they stopped fitting: a file had to be given a name
that is a lie because the code behind it is in the wrong shape. This document
records the shape.

**It proposes no work.** No steps, no sequence, no checkboxes. Options
canvassed so far are recorded at the end as *canvassed*, not chosen, and the
decisions that would have to be settled before any of them are listed
separately — leaving those to be discovered mid-step is the failure mode
[`data_contract_review.md`](data_contract_review.md) named.

Summarised as items 5 and 10 of
[`post_refactor_review.md`](post_refactor_review.md); this is the long form.

---

## The question

Four responsibilities are involved in turning a user's selection into a drawn
plot. Two objects hold them, and the split runs through the middle of one
responsibility rather than between two.

| | responsibility | method lines | currently in |
|---|---|---:|---|
| **A** | **key space** — what keys exist, catalog plus frozen, the key table, frozen registration, synthetic-key predicate | 157 | `RunSource` |
| **B** | **key-level access** — `load`, `read`, `describe`, `load_coords`, `plot_axis_names`, `get_shape`, and the `_source(key)` dispatch behind them | 407 | `RunSource` |
| **C** | **block cache** — hold one hyperslab and its norm arrays, decide whether a wanted window is contained, read narrowed | 289 | `RunFetch` |
| **D** | **the pipeline** — plan, load, normalize, reduce to a plane, transform, mask, pack | 174 | `RunFetch` |

`RunSource` is A+B at 640 code lines, plus 46 lines of connect/teardown.
`RunFetch` is C+D at 472.

The question this document exists to answer is **where C and D belong, and
what each is called** — with the constraint that every answer so far has
produced at least one name that does not describe its contents.

---

## What is measured

All figures below are at `3468650`.

### The stages are separated from their only consumer

`fetch/stages.py` is 608 code lines of `DataArray -> DataArray` functions.
**Its only production consumer is `RunFetch`.** Not one other file in the
application calls a stage; the remaining importers are tests.

### `fetch/` is named after the one act none of its files performs

| file | code lines | what it holds | reads storage? |
|---|---:|---|---|
| `fetch/request.py` | 303 | `PlotRequest`, `TraceKey` | no — a description of what to plot |
| `fetch/plan.py` | 231 | `FetchPlan`, `plan_fetch`, `narrow`, `kept_axes` | no — a description of what to read |
| `fetch/stages.py` | 608 | the transforms | no — pure array functions |

The only code that reads storage is `RunFetch._read_block`, which is not in
this package.

This got sharper at `3468650`, not softer: `request.py` used to hold three
builders as well, and all three left — `build_plot_request` was absorbed into
`PlotSession._build_plot_request`, `crop_from_region` became
`RectRegion.to_view_crop`, and `roi_profile_request` became
`PlotRequest.with_roi_profile`. The package is now three files of pure
description and transformation with no constructor and no read among them.

### `RunFetch` is mostly a cache, so no single word names it

**289 of its 463 method lines (62%)** are the block cache: `_load_block`,
`_held_windows`, `_contained_window`, `_narrowed`, `_read_block`,
`_norm_array`, `clear`, `__init__`. The remaining 174 are `get_plot_bundle`
(101), `_plane_frame` (53) and `_render_hint` (20). Those two halves have
different reasons to change, which is the test item 5 of the post-refactor
review asked for before any extraction.

### The pipeline is reached through an object that does not own it

`get_plot_bundle` has **two production callers**, both in `trace.py`, both of
the form `self._run.fetch.get_plot_bundle(request)` — a trace reaching
through the run it holds to an object hanging off it. The other **75** calls
are tests, which use `.fetch` because it is the convenient seam, not because
the application does.

### Neither object delegates to the other

`RunSource` uses its `RunFetch` for exactly three things: construct it in
`__init__`, return it from the `fetch` property, and call `clear()` on it
from two places. `RunFetch` is a client of five `RunSource` methods:
`describe`, `load`, `load_coords`, `plot_axis_names`, `read`.

So this is **layering, not duplication**: `RunFetch._read_block` calls
`RunSource.load` and adds windowing and caching around it. The one place
logic is genuinely re-done is `_norm_array`, which repeats dimension naming
that `RunSource._plot_names` also performs.

### Neither object shrank

Extracting `RunFetch` was supposed to shrink `RunSource`. It is 640 code
lines today, against the 250 that item 5 of the post-refactor review recorded
as its target. **The weight is in B, not A**: key access is 407 method lines
against key space's 157. That matters for which extraction is worth making,
and it is the opposite of what this document estimated before the figure was
measured.

---

## How this surfaced, and why it was not visible earlier

The module organization plan moved files without changing what they do. Three
of its steps ran into the same wall from different directions, and only the
third made it unmistakable:

1. **Step 4** found six `Projection` queries that could not be placed, and
   concluded they were "already home". That was true of those six, and it
   trained the wrong reflex — that an unplaceable function means the question
   is wrong rather than the code.
2. **Step 6** found the ROI profile queries unplaceable for a second reason,
   a would-be `view` ↔ `roi` cycle.
3. **Step 7** hit a name collision between `run/fetch.py` and `fetch/`, and
   the response was to invent `run/pipeline.py` — a file holding one class,
   named after stages that live in a different package. That name is in the
   tree now.

The tell, recorded so it is recognised sooner next time: **needing to invent
a third name to dodge a clash between two existing ones.** When that happens,
the two existing names are usually both describing the wrong carving.

---

## Standing constraints

These are settled and are inputs, not open questions.

- ~~**The block cache stays on the run, and stays single-entry.**~~
  **Re-opened 2026-09-15** at the maintainer's direction. See below.
- **No forwarding models.** A model that mostly re-exposes its children's
  methods is not a worthwhile extraction. `RunSource` handing out `.fetch`
  rather than forwarding to it was a deliberate application of this, and any
  new arrangement is held to the same rule.
- **A free function whose first argument is the thing it operates on belongs
  on that type.** Applied across `geometry`, `fetch/request` and `run/source`
  at `3468650`, which deleted three files and four functions that were only
  indirection. Any new arrangement is held to this too — and it puts a
  question on the list below that was not there before.
- **No runtime import cycles inside `models/plot`, and no function-local
  import used to dodge one.** Enforced by `tests/test_module_boundaries.py`.

---

## The block cache, re-opened

It was a fixed input and is now a question. What it actually is:

**It is a third cache tier, and the only one not named as one.** Below it,
`models/cache/chunkCache.py` holds a byte-bounded LRU slice cache
(`l1_max_bytes`, 128 MB) over a zarr-backed tier. A miss in the block cache
therefore does not usually reach the network — it reaches those.

**So its job is not to avoid I/O.** What it avoids is redoing the labelling
and assembly around a read: the dimension rename, the coordinate attach via
`load_coords`, the array construction. And it holds the norm arrays beside
the block, so toggling a normalization costs one read of the norm key and
nothing thereafter — that was its stated reason for holding the block *as
read* rather than normalized.

**Its key is coarse and its capacity is one.** `FetchPlan.reads_the_same`
compares ykey, xkeys and dims, deliberately ignoring norm keys and which two
axes are drawn; the window is then tested for containment rather than
equality. One entry is held.

### What that buys, and what it costs

Keeping it exactly as it is:

- Invalidation is trivially correct. One owner, one entry, cleared
  synchronously by `RunSource` before it emits `data_changed`. The `clear`
  docstring records why it does not listen for that signal instead: it would
  depend on being connected first.
- Memory is bounded by construction — one block per run, and the norms
  cannot outgrow those toggled while it is held.

Against it:

- **Two traces on one run evict each other.** Different ykeys fail
  `reads_the_same`, so each fetch replaces the other's block, every refresh.
  The fall-through is to the chunk cache rather than to storage, so the cost
  is relabelling and assembly rather than network — but it is paid per
  refresh, per trace, for the whole time both are shown.
- It is **62% of a class named for something else**, which is what started
  this document.
- Three tiers exist and only the lower two are described as tiers anywhere.

### What re-opening it could mean

Not proposals — the shapes the question can take:

1. **Key it per ykey** instead of holding one entry, bounded by count. Fixes
   the eviction pair-wise thrash; costs a bound to choose and an eviction
   rule, which is the thing a single entry exists to avoid needing.
2. **Move it down beside `ChunkCache`**, where the other tiers already live
   and where the byte accounting already exists. Costs the ordering guarantee
   above: the data layer would have to invalidate before the plot layer's
   signal, or the plot layer would keep a `clear()` call reaching down.
3. **Delete it and measure.** If the chunk cache plus relabelling is fast
   enough, tier 0 is not earning its keep, and the norms-beside-the-block
   trick could move to whoever wants it. This is the only option that makes
   something smaller, and it is measurable before it is decided.

---

## Options canvassed, none chosen

Recorded so the thinking is not repeated, not because any is preferred.

**1. `RunSource` delegates all data access to `RunFetch`** — move B into
`RunFetch`. This looked weak on an estimate and looks stronger on the
measurement: `RunSource` would drop to roughly 200 method lines, near the 250
its target named, and `RunFetch` would rise to about 870. Against it: that is
a large object holding three jobs, and B arguably *is* key-space logic —
`_source(key)` dispatching catalog against frozen answers *what this key is*.

**2. Split `RunFetch` on the seam inside it** — a cache the run owns, and
`get_plot_bundle` living beside the stages it sequences, which would make a
file called `pipeline` contain a pipeline and would remove the reach-through
as a consequence rather than as a patch. Costs 75 test call sites; `RunFetch`
and `.fetch` cease to exist. Does not re-fatten `RunSource` only if the cache
stays its own object. Leaves B where it is, so `RunSource` stays at 640.

**3. Minimal** — move `stages.py` beside its only consumer and give `Trace`
the fetch at construction instead of reaching through a run. Two small
changes, no test churn, and `get_plot_bundle` stays on a class that is 62%
cache.

Options 1 and 2 are not exclusive: 1 moves B, 2 splits C from D.

---

## Decisions that must be settled before any of them

1. **Is the cache handed out or private?** If a pipeline function needs a
   block, it needs the cache; whether that is on the public surface or
   reached some other way changes what every option looks like.
2. **Do the request and plan descriptions keep a package, and does it also
   hold `Projection`?** They fetch nothing, so whatever holds them is not
   called `fetch`. See the section below: `Projection` is a *field* of
   `PlotRequest`, and putting them together is blocked by one edge.
3. **Does `.fetch` survive as a name?** 75 tests and two production lines use
   it. It is cheap to change and the cost is not the reason to keep it.
4. **Whose method is `get_plot_bundle`?** New, and raised by the standing
   rule above rather than by any of the options. Its receiver is the fetch
   and its argument is the request, so under that rule it could as
   defensibly be `PlotRequest.bundle_from(source)`. Worth settling
   deliberately rather than inheriting.
5. **Where is a `TraceKey` created?** Item 10 of the post-refactor review.
   Three ways exist to get one and the dominant one involves no request:
   constructed directly from `(uid, xkey, ykey)` in `session.py` at three
   sites and in `image_grid_canvas.py`; derived by `PlotRequest.trace_key`,
   which is `Trace.__init__`'s default; or read off `Trace.trace_key`, which
   `single_canvas.py` uses at eight sites. So `TraceKey` sits in
   `fetch/request.py` beside the constructor that is not the main one, while
   `Trace` and `TraceSet` are elsewhere. Same confusion one layer up.

---

## `Projection` is a field of `PlotRequest`, and they are packages apart

`PlotRequest.view` is a `Projection`. The two are one directory apart because
of when they were written, not because of what they are.

The whole chain is descriptions of one plot at increasing concreteness, each
derived from the one above it by a pure function:

| | what it adds | frozen? | lives in |
|---|---|---|---|
| `ViewIntent` | rank-agnostic session state; a `QObject` with signals | no | top level |
| `Projection` | bound to one key's rank: roles, order, indices, crop | yes | `view/spec.py` |
| `PlotRequest` | the keys, the ROI, the transform | yes | `fetch/request.py` |
| `FetchPlan` | the window to read, and the frames it lands in | yes | `fetch/plan.py` |

`ViewIntent.project()` makes the second, `PlotSession._build_plot_request` the
third, `plan_fetch` the fourth. `PlotAxes` is the same projection spoken in
dimension names. Six of the eight frozen types in `models/plot` are on this
chain or wrap it.

### One edge blocks combining them

Any package holding both `Projection` and `PlotRequest` would import
`geometry`, because `PlotRequest.region` is a `RegionDefinition` and
`mask_mode` is a `MaskMode`. But **`geometry` imports the view vocabulary
back**: `geometry/region.py` takes `PlotAxisName` and `ViewCrop` from
`view`. That is a runtime cycle, and
`tests/test_module_boundaries.py` refuses it.

That edge got stronger at `3468650`, not weaker: `RectRegion.to_view_crop`
means a region now *constructs* a view type as well as naming two.

So combining them is a decision about **where the shared vocabulary lives**,
not about the two packages. The shapes it can take:

1. **`PlotAxisName` and `ViewCrop` move to `geometry`.** Then descriptions →
   geometry one way, and the merge is free. Against: `ViewCrop` is a field of
   `Projection`, so the type a projection carries would live in the package
   the projection does not import.
2. **The vocabulary moves below both** — a third place both import, which is
   a new module holding four aliases and a small dataclass. That is the
   "adds a file, deletes nothing" shape this project distrusts.
3. **`RegionDefinition` stops being a field of `PlotRequest`** — the request
   names a region some other way, and the edge into geometry disappears.
   Largest change, and it touches the ROI path rather than the packaging.
4. **Leave them apart** and accept that the containment crosses a package
   boundary, as it does today.

The `view/` package currently imports nothing else in `models/plot`, and a
test asserts it. Any merge ends that property, which is the thing that made
`view/` safe to depend on from everywhere. Whether the chain being in one
place is worth more than the sink being a sink is the actual question.

---

## Non-goals for this document

- It does not sequence work, and should not grow steps. If work is agreed,
  the sequence belongs in its own document or in the commits.
- It does not revisit the block cache's design, which is settled above.
- It does not cover `MplCanvas`, widget testing, or teardown, which are named
  in the reviews and want their own treatment.

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-15 | Opened, after the module organization plan closed. |
| 2026-09-15 | Re-derived at `3468650`. The original figures were stated as taken at `64d632b` but were in fact read from a working tree that already carried uncommitted work, and one content description was wrong with it: `fetch/request.py` was listed as holding three builders it no longer had. Every figure is now re-measured and the commit named. Two substantive changes rather than corrections: the `fetch/` finding is sharper, because the three builders have since left and the package is now pure description throughout; and `RunSource`'s weight was measured rather than estimated, at 407 method lines of key access against 157 of key space, which is the reverse of the estimate and makes canvassed option 1 stronger than it was written. A fourth decision is added — whose method `get_plot_bundle` should be — raised by the free-function-to-method rule the same commit applied repo-wide. |
