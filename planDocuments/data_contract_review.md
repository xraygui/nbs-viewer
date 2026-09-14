# Data contract review

Where the data layer stands after [`data_contract_plan.md`](archive/data_contract_plan.md)
completed on 2026-09-11, measured at `f50633a` rather than remembered. Same
shape as [`post_refactor_review.md`](post_refactor_review.md), which reviewed
the refactor before it.

This is a review, not a plan. Two of its findings are about *how the work was
run* rather than what it produced, and those are the ones worth acting on.

---

## Did it do what it said?

The diagnosis had five claims. All five are now false, which is the result.

| Claim | Then | Now |
|---|---|---|
| The protocol is spelled in three pieces, so one dispatch is written five times | 5 (7 counting every branch) | **1** — `RunSource._source` |
| The pipeline's middle value has no name | 74 parameter slots over 29 names | `xr.DataArray`; slots 78 → 47 at step 4 |
| `_truncate_dim_names` pads names until they fit | 1 consumer patching | deleted; enforced at 1 boundary |
| `AxisLayout` is mostly dead | 5 fields, 1 unread | deleted |
| `models/data` imports upward from `models/plot` | 1 | **0**, pinned by a test |

The plan set itself a test: *does any bespoke type survive step 4?* None did
around the data. `PlotAxes` survives as a *description* derived from the
request, and `PlaneOrientation` — added in step 4 — was deleted by step 4b a
day later. `AxisArray` would have been re-derivation, and the plan says so.

## What it cost

| | Before | Now |
|---|---:|---:|
| Production code lines | 18 925 | 18 963 |
| `models/plot` | 4 889 (20 files) | 4 791 (22 files) |
| `models/data` | 1 524 | 1 581 |
| `RunSource` code lines | 586 | **281** (+ `RunFetch` 217) |
| `CatalogRun` public surface | 31 | **26** |
| Tests collected | 431 | **512** |
| Test code lines | 6 698 | 7 725 |

The public surface counts methods, properties and signals, as step 7 counted
it: that step took it 31 → 27 and step 8 removed one more than it added.

Production is 38 lines larger than when this began. **The refactor is a naming
story, not a deletion story**, and it should be told that way: each step's
deletions were offset by the type or rule that replaced them. What changed is
that an axis's name, its coordinate, and what it is plotted against are now
three separate facts, each established once.

`RunSource` was the previous review's "one object the refactor did not
shrink" — 586 lines against a 250 target. It is 281 with 25 public members,
and the fetch it was carrying is a 217-line object of its own.

## Defects closed

Bugs 6, 7 and 15 (step 1), and bug 16, found while scoping step 8 — all four
are the same defect: a layer below the pipeline disagreeing with a key's own
declared dimensions. Plus four found while working, each reproduced first:

- an in-place transform (`y[y > t] = t`) writing through into the block cache,
  so turning the transform off did not restore the data;
- an ROI profile on a row-reversed image summing the mirror-image rows — a
  regression from step 4b, **found by the maintainer, not by the suite**;
- a norm read from the wrong window, now caught by coordinate values;
- two test fixtures that were internally inconsistent and had never failed.

`KafkaRun` keeps bug 7 deliberately: its `getShape` calls `getData`, so
listing keys would materialize every buffered array on a live stream.

---

## Finding 1: the unreliable parts of a step are the numbers it predicts

Steps were specific about *intent* and unreliable about *scope*, and the
failures cluster in one place: **claims asserted before the step's decisions
were settled**.

| Step | What the step text said | What was true |
|---|---|---|
| 1 | bug 15 is the no-X-key case | it has a second trigger, reachable *with* a selection |
| 2 | `FrozenSpectrum` moves to `models/data` | only the *convention* could move; the class holds a `PlotBundle` |
| 2 | pin `skipna` at the boundary | nothing to pin yet — the reductions were still numpy |
| 4 | `plan_fetch` becomes `PlotRequest.plan_fetch` | it cannot: it needs a frame only the source can build |
| 4 | orientation travels from load to pack | wrong altitude entirely; step 4b undid it a day later |
| 6 | the sketch is "mechanical once step 4 lands" | the sketch predated 4b and 5 and was wrong five ways |
| 7 | the contract goes 8 → 5 | that reduction had already happened in steps 2–3 |
| 8 | contract 4 → 2; ~540 raw lines deleted; most tests unchanged | 4 → 3; 94 raw lines; 28 tests failed at once |

The pattern is not vagueness of language. Every one of these is a **number or
a deletion predicted at drafting time for a step whose decisions were still
open**. The steps that held are the ones re-derived against the tree
immediately before execution — step 4's design pass, step 6's re-derivation,
and step 8's rescope — which is also what the previous review praised.

Three rules follow, and they are cheap:

1. **A step states decisions and names deletions; it does not state a count it
   has not measured.** Where a count is genuinely useful up front, mark it an
   estimate and re-measure at the end. Every "N → M" fact in this plan that was
   written at drafting time was wrong; every one measured at the end was right.
2. **Re-derive a step against the tree immediately before starting it**, and
   record what changed. This is already the practice that works; make it the
   rule rather than the exception.
3. **A step that changes a rule applied application-wide — axis naming,
   coordinate resolution — must name the fixtures and tests that encode the old
   rule as part of its scope.** Step 8 did not, and twenty-eight tests failed at
   once. That was scope discovered late, not a test problem.

## Finding 2: a plan that grows as it lands makes its own later steps expensive

`data_contract_plan.md` grew **332 → 1919 lines across 23 commits**, a 5.8×
increase, to describe a change that left production 38 lines larger.

The cost is not untidiness. **It falls on whoever implements the next step.**
Starting step 5 meant reading past roughly a thousand lines of write-up about
steps 1 to 4 — outcomes, deviations, verification tables — almost none of which
changes what step 5 does. The plan is heaviest exactly when the remaining work
is hardest, and it gets worse with every step that lands. A tight plan is
cheaper to execute, and nothing is lost: the detail is already in the commit
history.

One file carrying three kinds of content is what produces that. Measured by
counting each heading's section:

| Content | Lifetime | Lines |
|---|---|---:|
| Outcome / deviation / verification write-ups | historical the moment they are written | **1348 (70%)** |
| The step lists | live until the step lands | 367 (19%) |
| Diagnosis and decisions | durable — this is the valuable part | 204 (11%) |

The first is the largest by far and the least re-read, and it is duplicated:
every step's outcome is also in its commit message. The durable part — the
argument that chose `xarray`, the two library defaults, the coordinate
decision — is a ninth of the file.

**Convention, applied to this document and proposed for the rest:**

1. A plan holds the argument, the decisions and the steps. When a step lands,
   the plan gets **one paragraph** of outcome; anything longer goes in the
   commit message.
2. Deviations and verification detail belong in the **review**, written once
   per refactor, at the end. This document is 180 lines for eight steps.
3. **A completed plan is archived, not trimmed.** It moves to
   `planDocuments/archive/`, so the active set is what remains at the top
   level and nobody has to open an old plan to find out whether it is done.
   Rewriting history to save lines would be work for its own sake; getting it
   out of the way is the point. Ten links in these documents already point at
   plans that were *deleted* on completion, which is the version of this that
   loses the history instead.
4. Still no new *plan* documents where an existing one can be superseded. A
   review is not a plan.

---

## Still open

Carried forward so nothing depends on remembering it.

**From this refactor.** The frozen synthetic norm is the one array still
aligned by position, and it is a named hole in the coordinate guard. The new
"a one-element hint path names a data key" rule is unverified against a real
hinted run — on Bluesky the old code walked `primary/<path>`, which reaches
config data. Open questions 3 (where `render_mode` finally lives), 5
(`PlotBundle` as a `DataArray`) and 6 (the transform is session-global, so a
frozen spectrum gets it applied twice — measured at 4× under `y * 2`) are
unanswered. Two full-suite runs hung during step 8 and did not recur in nine
later runs; unexplained.

**From the previous review, unchanged.** Duplicated type aliases are worse than
recorded: `SliceItem` ×5, `MaskMode` ×3, `SpatialReduce` ×2, `PlotAxisName` ×2,
with `roi_set.py` still widening two of them to bare `str`. "Show All Keys"
(bug 4) is still dead and `get_hinted_keys` still has no callers — held on the
maintainer's instruction, since it addresses a real problem. Widget tests are
**3 of 473** test functions.

**What this hands the module plan.** `run_source`'s split is done, so that
plan's step 1 is half-complete; the `plot_geometry ↔ plot_request` cycle it
wanted removed is already gone; and `run/`'s contents changed, because
`KeyInfo` moved to `models/data` and `FrozenSpectrum` did not move at all.
Re-derived in [`module_organization_plan.md`](module_organization_plan.md).

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-14 | Written after step 8 closed `data_contract_plan.md`. Numbers measured at `f50633a`. The two process findings are the maintainer's, confirmed against the plan's own text: steps lacked specificity in a specific way — predicted counts and deletions — and the documents grew unwieldy once decision context and post-step review accumulated in them. |
