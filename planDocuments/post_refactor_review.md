# Post-refactor review

Where the codebase stands after [`refactor_plan.md`](archive/refactor_plan.md)
completed on 2026-09-10, measured rather than remembered. Every number here
was taken from the tree at `f7780fb` against the branch point `6dcb5ef`, and
every claim about a defect was reproduced before it was written down.

This is a review, not a plan. It says what is true now, what is still wrong,
and in what order the remaining work is worth doing. Anything that becomes a
work item should get its own plan.

---

## Did the refactor do what it said?

The diagnosis was one sentence:

> **No object could be handed a description of a plot**, so fetch took ten
> parameters, state was mirrored across four objects, and trace identity
> omitted the view — which meant every feature that varied the view built a
> second pipeline.

All four clauses are now false.

- **`PlotRequest` exists and is the whole description.**
  `RunSource.get_plot_bundle(request, *, cached_plane=None, label="")` — three
  parameters, two of them optional and neither carrying view state. The
  `region_frame` / `parent_spec` / `view_crop` side channels are gone.
- **State is not mirrored.** `PlotSession` holds 17 public members and 4
  signals over five children, each owning the state it announces.
- **Trace identity is explicit.** `TraceKey` names the long-lived object;
  `PlotRequest` fingerprints the fetch; changing view, crop or transform
  reuses the artist.
- **The second pipelines are gone.** `derived_fetch.py`, `view_crop.py` and
  `cube_view.py` were deleted outright — 1848 lines — and step 7 removed the
  last duplicate, the load path's own ROI reduce.

### The invariants hold, and this is the clearest result

Checked against the tree, not assumed:

| Invariant | Status |
|---|---|
| 3. No `QtWidgets` under `models/` | ✅ zero occurrences |
| 1 / 5. `models/` never imports `views/` | ✅ zero occurrences |
| (implied) no matplotlib under `models/` | ✅ zero occurrences |
| 10. Every step names what it deletes | ✅ all thirteen steps do |

The one guard that stays deliberately non-empty is
`test_views_do_not_construct_traces_except_image_grid`, whose `allowed` set is
`image_grid_canvas.py` — deferred to that widget's rewrite, recorded rather
than closed.

### The size story is not a deletion story, and should not be told as one

| | Branch point `6dcb5ef` | Now `f7780fb` | Δ |
|---|---:|---:|---:|
| Production code lines | 19 261 | 18 925 | **−336 (−1.7%)** |
| `models/plot` | 5 479 | 4 889 | −590 (−11%) |
| `views/plot` | 5 564 | 5 415 | −149 |
| `models/data` | 1 212 | 1 524 | **+312** |
| Test code lines | 4 347 | 6 698 | **+2 351 (+54%)** |
| Test functions | 248 | **420** | +172 (+69%) |
| Tests collected | 248 | **431** | |

Production shrank by under two percent. That is the honest headline, and it is
not the point. `models/data` grew on purpose — step E moved combining and
freezing down to the data layer, where a combined run is a run rather than a
special case in the session. `models/plot` is where the deletion happened, and
the thing that actually changed is that each pipeline stage now has one
implementation instead of two that disagreed.

The refactor's real output is the **thirteen numbered defects it found**, eight
of which it closed, plus ten more fixed without ever being numbered. Most were
silent wrong answers — a plot that showed a number rather than an error: the
ROI mask applied upside down, the fetch narrowing to the wrong block, combining
runs plotting only the first one, "span full profile axis" widening the
reduction axis, one ROI on a cube transformed along two of three axes. That is
what a codebase with two implementations of everything costs, and it is what
the 54% growth in test code is buying down.

### Against the ownership plan's own size targets

Measured in code lines, the correction step H made to the table.

| Object | Code | Target | Public | Signals | |
|---|---:|---:|---:|---:|---|
| `PlotSession` | 370 | 450 | 17 | 4 | ✅ |
| `RegionController` | 455 | 450 | 28 | 6 | ✅ |
| `RunCollection` | 284 | 320 | 21 | 5 | ✅ |
| `Selection` | 125 | 220 | 9 | 1 | ✅ |
| `ViewIntent` | 189 | 250 | 11 | 3 | ✅ |
| `TraceSet` | 49 | 150 | 7 | 2 | ✅ |
| `RunListItemModel` | 92 | 150 | 6 | 0 | ✅ |
| `Trace` | 203 | 150 | 21 | 3 | ❌ |
| `RunSource` | 586 | 250 | 24 | 4 | ❌ |

Seven of nine met. The two misses are discussed under **What is still wrong**.

---

## What is still wrong, ranked

Ranked by *expected harm*, not by effort. A silent wrong answer on real data
outranks a large file.

### 1. Bug 6 — the Bluesky backend names one more axis than the array has

**Worse than the bug table describes, and now more consequential than when it
was recorded.** Reproduced directly:

```
det1d     shape=(100,)         dims=('time',)                          rank 1  ok
detector  shape=(100, 32)      dims=('time', 'dim_0', 'dim_1')         rank 2  MISMATCH
camera    shape=(100, 32, 64)  dims=('time','dim_0','dim_1','dim_2')   rank 3  MISMATCH
```

`BlueskyRun._infer_dims_from_shape` builds `("time",) + dim_0 … dim_{ndim-1}`
— `range(0, ndim)` where `MemoryRun` and `KafkaRun` both use `range(1, ndim)`.
`_resolve_dims` returns it unmodified. Every consumer that pairs names with
axes uses `zip`, which truncates silently, so a rank-2 detector's two axes come
out named `("time", "dim_0")` — and `dim_0` is what an unrelated 1-D key gets.

This is exactly the collision that was removed from the *test fixtures* in
`1eebfe1`, and view-pipeline step 7 made normalization align norm arrays to the
y key **by axis name**. So the failure mode is: on real Bluesky data with no
Tiled `dims` metadata, normalizing a detector by a scalar channel can match the
wrong axis and divide silently.

Mitigating: the inference is a fallback. `_resolve_dims` prefers Tiled's own
`dims` when present, so this only bites where that metadata is missing. That
should be measured against a real catalog before deciding urgency — but the
arithmetic is not in doubt, and the fix is one character.

**The test fixtures cannot catch it**, because `MemoryRun` has the correct
version. Any fix needs a test against `BlueskyRun._infer_dims_from_shape`
itself; the reproduction above is already in that shape.

### 2. Bug 7 — the two backends disagree about key grouping

`BlueskyRun.getRunKeys` ends with `ykeys[1] = all_keys` (line 515), so rank-3
camera keys are reported as rank 1. Same class as bug 6: a backend-specific
answer that the model layer then trusts. The refactor made every rank decision
downstream honest, which means a wrong rank here now propagates further than it
used to. Flagged in the plan as "own commit"; it still is.

### 3. Bug 10 — the Kafka tab cannot open

`widgets/kafkaViewerTab.py:73` calls `PlotWidget(self.run_list_model, self.plot_model)`
against `PlotWidget.__init__(self, presenter, parent=None)` — a `TypeError` on
construction. `widgets/` is out of scope by invariant 6, which is why the
refactor left it, but "out of scope" and "known broken" are different states
and this has been the latter for the whole refactor. It is a two-line fix plus
a construction smoke test.

It is one of three bugs of the same class — a widget whose constructor call
does not match its signature, or whose state the canvas alone can observe
(bugs 9, 10 and 11). All three were invisible to `tests/` when they were
found. See **Widget testing** below.

### 4. Bugs 4 and 5 — two features that do not work

- **Bug 4: "Show All Keys" is a no-op.** `run_display.py:386` assigns
  `self._show_all` and nothing ever reads it. Its intended backing,
  `CatalogRun.get_hinted_keys` (`models/data/base.py:318`), has zero callers.
  Open question 4 — whether `get_hinted_keys` produces the set the checkbox
  meant — is still unanswered, and answering it is most of the work.
- **Bug 5: unlinked mode double-lists synthetic keys.** `available_keys` is
  `catalog + frozen`, so a frozen spectrum gets a catalog row with an X
  checkbox it should not have. Confirmed unchanged at `run_source.py:120`.

Both are visible-to-the-user wrongness rather than silent, which is why they
rank below the first three.

### 5. `RunSource` is the one object the refactor did not shrink

586 code lines against a 250 target, 1193 raw, 24 public members. It grew
during the refactor (472 → 586 in step 7 alone). The reason is structural, not
sloppiness: the row's target was set for "uniform key access", and
`get_plot_bundle` — plan, load, orient, normalize, reduce, transform, mask,
pack, plus a block cache — was appended to its job description without the
number moving.

Two things are actually tangled here:

- **Key access** (`key_table`, `identity`, `read`, `describe_axes`,
  `load_axes`, frozen-spectrum registration) — the surface the plan named.
- **Fetch orchestration** (`get_plot_bundle`, `_load_block`,
  `_normalized_block`, `_plane_frame`, `_block_for_plan`, `_contained_window`,
  `_plane_render_mode`, `_storage_to_tensor`, `_loaded_plane_shape`).

The second group is ~330 of the 586 lines and touches the first only through
`read` and `load_axes`. It is the natural extraction, and it would put the
block cache next to the thing it caches. **But** invariant 10 applies: an
extraction that adds a module and deletes nothing is not obviously worth
doing, and the maintainer's standing rule is that a model which mostly
re-exposes its children is not a worthwhile extraction. The honest position is
that this is a *candidate*, not a defect — and the case for it should be made
on whether the two halves have different reasons to change, not on the line
count.

**Update 2026-09-15.** Recorded in full in
[`load_pipeline_problem_statement.md`](load_pipeline_problem_statement.md).
The extraction happened, in the data contract refactor:
`RunFetch` exists, owned by `RunSource` and handed out as `.fetch` with no
forwarding method. It was half right, and the module reorganisation measured
the other half:

- `RunFetch` is **281 of 461 method lines block cache**, the rest
  orchestration. Two jobs with different reasons to change, which is the test
  this item asked for, so the seam is real rather than a line count.
- `get_plot_bundle` is called from **two** production lines, both in
  `trace.py`, both reaching through a held `RunSource` to its `.fetch`. The
  other 75 callers are tests.
- The stage functions' **only** production consumer is `RunFetch`, yet they
  live in `models/plot/fetch/`, whose three files perform no fetching — the
  only code that reads storage is `RunFetch._read_block`.
- `RunSource` uses its `RunFetch` for three things: construct, hand out,
  `clear()`. Neither delegates to the other.

`RunSource` is now 701 lines, so the extraction did not shrink it either. The
candidate shape is to split `RunFetch` on its own seam — a block cache the
run owns, and `get_plot_bundle` as a function beside the stages it sequences,
which deletes the reach-through as a consequence rather than as a patch. Two
decisions must be settled first: whether the cache is handed out or private,
and whether the request and plan descriptions keep a package.

### 6. `MplCanvas` is now the largest object in the tree

1136 code lines, **94 methods** (35 public, 59 private). `views/plot` (5415
code lines) has overtaken `models/plot` (4889) as the biggest package, and two
files are 39% of it: `single_canvas.py` and `roi/window.py` (964 lines, 63
methods).

The refactor pushed policy out of views and did not follow it into the views
themselves — deliberately, since steps B and C were about taking domain work
*off* the canvas. What is left in `MplCanvas` is mostly genuine view work
(axes, artists, selectors, toolbars, colorbars, events), but 94 methods on one
class is where a widget stops being reviewable. Four view modules still import
numpy (`renderers.py`, `image_grid_canvas.py`, `dimension.py`,
`single_canvas.py`), which is the signal worth chasing first: numpy in a view
is either presentation arithmetic (fine) or domain computation (not).

### 7. Four definitions of one concept — **closed**

Closed by module-organization step 5. `SliceItem`, `SpatialReduce` and
`PlotAxisName` have one definition each in `view_spec.py`; `MaskMode` has one
in `region.py`, beside the `compile_with_mask_mode` it configures.

```
MaskMode       region.py (Literal)  plot_bundle.py (Literal)  roi_set.py (= str)
SpatialReduce  view_spec.py (Literal)                         roi_set.py (= str)
SliceItem      view_spec.py  plot_bundle.py  plot_request.py
PlotAxisName   view_spec.py  region.py
```

`roi_set.py` widens two of them to bare `str`, so the type that says
`"inside" | "outside"` and the type that says "any string" are both called
`MaskMode` depending on the import. Nothing is wrong at runtime —
`PlotRequest.__post_init__` validates — but this is the kind of thing that
makes a type annotation stop meaning anything. Cheap to consolidate into one
module; no behaviour risk.

### 8. Lint baseline outside the refactored packages

`models/plot`, `views/plot` and `tests/` are clean of `F` findings (one
deliberate `F841` recorded in step F). The remaining 45 unused imports
concentrate exactly where the refactor never went:

```
13  models/data      9  views/display     9  models/sources
 6  models/catalog   6  models/cache      4  views/catalog
```

Plus 45 `E402`, 30 `E501`, 5 f-strings without placeholders, and 42 bare
`print()` calls outside `utils`. Seven camelCase modules remain under
`models/cache/` and `models/sources/`.

This matters for one specific reason, learned the hard way in the step 6
follow-up: a *non-empty* lint baseline is where a real finding hides. That
follow-up shipped a runtime `NameError` because an `F821` count rise was read
as pre-existing noise. `F811` and `F821` are now zero tree-wide, which is the
state worth defending; the rest is hygiene. `structural_remediation_plan.md`
steps 9–12 already own it.

### 9. 96 broad `except Exception` handlers

Concentrated in `views/plot/mplCanvas` (27) and `views/plot` (16), with 12 in
`models/data`. `MplCanvas._do_update_plot` swallows every exception into a
`print_debug` call — which means a bug in the render path shows up as a plot
that does not update, with no traceback. Given that six of this refactor's
thirteen bugs were silent wrong answers, a render loop that also silences
*loud* failures is worth revisiting.

---

### 10. `TraceKey` lives beside the one constructor that is not the main one

`Trace` and `TraceSet` sit far from `TraceKey`, which is in
`models/plot/fetch/request.py` because `PlotRequest.trace_key()` derives one.
There are three ways to get a trace key, and the dominant one involves no
request at all: constructed directly from `(uid, xkey, ykey)` in `session.py`
(three sites) and `image_grid_canvas.py`; derived from a request, which is
`Trace.__init__`'s default; or read off a trace as `trace.trace_key`, which
`single_canvas.py` uses at eight sites.

Small, and the same confusion as item 5 one layer up, so it belongs with that
work: settle where a trace key is created and where it belongs follows. Open
as decision 4 of
[`load_pipeline_problem_statement.md`](load_pipeline_problem_statement.md).

## Deferred by decision, and still deferred

These are not oversights. Each was argued and recorded; listing them together
is the point.

| Item | Why it waits | Where |
|---|---|---|
| **`ImageGridCanvas` bypass** | Due for a rewrite once the canvas stabilises; it still constructs its own `Trace` (`image_grid_canvas.py:444`) and is the ownership guard's only exemption. Retrofitting it would be designing against code about to be replaced. | refactor plan step C |
| **`ViewIntent.fan_out`** | The image grid's API; same reason. | open question 5 |
| **Cache status aggregation** | `PlotSession` still reaches `getattr(run, "_chunk_cache", None).progress` — three private hops across two layers. Neither `ChunkCacheProgress` (owned by the run) nor `TiledFetchStatus` (a dataclass) is a session child; what should move is the aggregation, and it is blocked on a general progress/error/status interface that does not exist. | open question 2 |
| **Teardown** | `PlotSession`, `RegionController` and `RunCollection` have no `cleanup`/`dispose` at all; only `Trace.dispose` and `RunSource.cleanup` exist. The ownership tree now makes disciplined teardown *possible*, which it was not before. Nothing has done it. | open question 3 |
| **`PlotPresenter`** | Left alone by instruction in step F. It is now an id, a `PlotSession`, and one signal forward; its other two signals (`roi_region_changed`, `crop_region_changed`) are never emitted and never connected, and every view that takes it writes `self.plot_model = presenter.session` on the next line. | step F |
| **`RunDisplayWidget` key ordering** | Ordering keys for display is not domain policy, and that area is due to grow a sort-by-dimensionality rule. | step C |

---

## Widget testing is the gap the numbers point at

431 tests, 420 of them model-side. **Three** are widget tests.

Of the thirteen numbered bugs, three (9, 10, and the class 11 belongs to) were
live crashes or visible misbehaviour that `tests/` could not reach, and every
one was found by hand or by a throwaway script under a real `QApplication`.
Bug 9 meant the main run list could not be constructed at all. Bug 10 still
means the Kafka tab cannot open. Three of thirteen is a pattern.

**The structural obstacle is gone** (`9a567db`): `conftest.py` now creates a
real `QApplication` on the offscreen platform, so widget tests and model tests
coexist in one process. Twelve view modules under `views/plot/` have no test
that so much as names them:

```
image_grid_plot_widget  metadataView  plotWidget  control_panel
plot_settings  run_display  image_grid_panel  mpl_panel
plot_worker  renderers  overlays  preview_canvas
```

The cheapest thing that would have caught bugs 9 and 10 is a **construction
smoke test that builds every top-level widget once**. `test_widgets.py` already
does it for `RoiWindow` and `MplCanvas`; extending it to the other twelve is a
short afternoon and needs no design decisions.

That is deliberately *not* the same as a broad widget suite, which still wants
a plan of its own — `headless_testing_plan.md` phases 3–4 is its home.

---

## What to do next, in order

1. **Fix bug 6** (`range(0, ndim)` → `range(1, ndim)`), with a test against
   `BlueskyRun._infer_dims_from_shape` directly, since no `MemoryRun` fixture
   can reproduce it. One character; the highest expected harm on the list.
   Check first how often real catalogs supply Tiled `dims`, because that
   decides whether this is latent or live.
2. **Construction smoke tests for the twelve untested view modules.** No
   design decisions, and it closes the class that produced three of thirteen
   bugs. Bug 10 falls out of it.
3. **Fix bug 7** (`ykeys[1] = all_keys`) — the other backend-honesty defect,
   and the one that now propagates furthest.
4. **Consolidate the duplicated type aliases** into one module, especially the
   two that `roi_set.py` widens to `str`. Mechanical, no behaviour risk.
5. **Answer open question 4**, then fix bug 4 — "Show All Keys" is a dead
   checkbox in the UI, and the answer decides whether it is a fix or a
   deletion. Bug 5 rides along, since both are about what belongs in a key
   list.
6. **Decide about `RunSource`.** Make the case on reasons-to-change, not line
   count, and only then split. **Now measured**, in
   [`module_organization_plan.md`](archive/module_organization_plan.md): the class
   splits 512 / 569 raw lines with a six-member interface between the halves,
   and the fetch half holds all fifteen of its free-function imports. The case
   is made on coupling rather than size, and it is that plan's step 1.
7. **`ImageGridCanvas` rewrite**, which unblocks `ViewIntent.fan_out`, the
   ownership guard's last exemption, and the last live half of problem
   statement item 7 — three deferrals for one piece of work.
8. **Lint and hygiene sweep** outside the refactored packages, defending
   `F811`/`F821` at zero. Already owned by
   `structural_remediation_plan.md` steps 9–12.
9. **Teardown**, once something needs it. Nothing does today, which is why it
   sits here rather than higher.

---

## What worked about how this was run, and is worth keeping

Recorded because the process produced most of the value, and the next piece of
work should inherit it.

**Re-deriving a step against the tree before starting it.** Steps C, D, E, F
and 7 were all re-derived, and every one of them changed: bullets already
closed by an earlier step, payoffs already banked, and in three cases a
decision the plan had never asked. Step F's open question turned out to rest on
a false premise — `AppModel` and `DisplayManager` were never near-duplicates;
`AppModel`'s whole public surface was simply dead. Executing that step as
written would have merged two objects for no reason.

**Requiring every step to name what it deletes.** Invariant 10 is what stopped
this becoming a layer-adding exercise. It also forced the honest entries: step
7 grew `models/plot` by 79 lines and says so.

**Recording deviations instead of absorbing them.** Six steps deviated from
their own text; all six say why in the sub-plan. Step 7's `Trace.needs_fetch`
deviation is the clearest — the Do-list and the Findings section of the same
step contradicted each other, and the Findings were right.

**Confirming every new test fails against the previous commit.** Seven tests
in step 7, each checked against `1eebfe1`. Two process failures in the step 6
follow-up — a dismissed lint-count rise and a smoke check with a vacuous
`else: True` that reported PASS for not running — are why.

**Driving widget-adjacent changes from a scratch script under a real
`QApplication`.** It caught what the suite could not, three times.

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-10 | Written after step F closed `refactor_plan.md`. All numbers measured at `f7780fb` against branch point `6dcb5ef`; bug 6 reproduced directly rather than read from the bug table, and found to be a rank mismatch rather than the hint-shifting the table describes. |
