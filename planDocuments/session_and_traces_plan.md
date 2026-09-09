# Session and traces plan

Who owns what. Sub-plan of [`refactor_plan.md`](refactor_plan.md); the other
half is [`view_pipeline_plan.md`](view_pipeline_plan.md), which owns how a
request becomes a bundle.

**Status:** steps A, B, C, G, D and H landed; **E, F** remain. The sequence is re-derived 2026-09-09 from the object-boundary question rather than taken
from the original step order; the target ownership tree below was rewritten in
the same pass. Everything marked done is verified against the tree.

**Replaces** `model_core_refactor_plan.md` (steps 4–8) and
`plot_session_list_adapter_plan.md` (P2–P3), both deleted 2026-09-08 and
recoverable from `57f6d7b`.

## Already landed

Verified in the tree, not taken on trust from the deleted documents:

- `PlotSession` (`plot_session.py`) owns `RunCollection`, `Selection`,
  `ViewIntent`, `RegionController` and the `TraceSet`, and connects them.
  Visibility went back down to the collection in step H. No aliases.
- `RunListItemModel` is a thin Qt facade under `views/dataSource/` — 186
  lines, no forwarding, no cache aggregation. Since step H it observes a
  `RunCollection` rather than a whole session.
- `RunSource` no longer holds selection, visibility or transform.
- `KeyInfo` / `RunIdentity` / `AxisLayout` exist; `key_table`, `identity`,
  `read`, `describe_axes`, `load_axes` are the surface.
- `PlotRequest` / `TraceKey` exist; `Trace` holds a request and
  `set_request` reuses the canvas artist filed under the same `TraceKey`.

## Target ownership tree

**Revised 2026-09-09** after working the object-boundary question through
rather than executing step D as written. Composition, not sibling
coordination. Every arrow is "owns".

```
PlotSession                  one per display; coordinator only
├── RunCollection    QObject membership + visibility + combine / freeze
├── Selection        QObject session default + per-run overrides
├── ViewIntent       QObject mutable view state; projects to frozen Projections
├── RegionController QObject crop + fingerprint + staleness + ROI pipeline
│   └── RoiSetModel  QObject entry store; views connect to it directly
└── TraceSet         QObject derived: collection × selection × view
    └── Trace                request + cached PlotBundle

RunListItemModel (views/)    QStandardItemModel over the session
MplCanvas (views/)           renders a TraceSet, owns axes
```

The session keeps only what no single child can answer: `rebuild`,
`driving_axes`, `resolve_single_visible_2d_trace`, `freeze_runs`, the
transform, the request assembly, and `request_plot_update`.

### The three rules this tree follows

1. **A method earns a place on the session only if it joins two children,
   announces on a child's behalf, or enforces an invariant neither child
   can.** Otherwise the child is handed out and the method deleted. This is
   the test that keeps the session from becoming a forwarding layer.
2. **Signal ownership follows state ownership.** A model holding state that
   others react to owns the signal announcing it. Stripping a model's signals
   does not simplify it; it relocates the coupling into whatever has to
   announce on its behalf — which is what happened when `RunCollection` was
   thinned to a plain container and its visibility moved to the session.
3. **Mutable models emit; their outputs are values.** `ViewIntent` becomes a
   `QObject`, but `intent.project(...)` still returns a frozen `Projection`,
   and `PlotRequest` stays frozen because a request is the fingerprint of a
   fetch. Immutability is for things that are *retained and compared*, not
   for things that are *observed*.

### What is deliberately not a child

- **Cache status aggregation.** `ChunkCacheProgress` is owned by the run, one
  per run, in the cache layer; `TiledFetchStatus` is a plain dataclass carried
  by a signal. The session holds neither — it aggregates, through a
  `getattr` chain across three privates. `_progress_sources`,
  `_cache_statuses` and `cache_status_changed` stay on the session until a
  general progress / error / status interface exists. Master-plan open
  question 2; deferred by decision, not oversight.
- **`ViewCrop`.** Already a value type in `view_spec.py`. What the session
  holds is the crop *plus* the trace key it was drawn on, because storage
  indices on one plot plane mean nothing on another. That pair is state
  inside `RegionController`, not a child of its own.

### Why crop and ROI are one child

They are not siblings; they are the same lifecycle under two names.
`sync_region_state_with_view` marks ROIs stale **and** clears invalid crops;
`invalidate_all_region_state` clears the crop **and** stales every ROI; both
are geometry on the sole visible 2-D plot plane, validated by the same
fingerprint; and `region_status_changed` / `region_invalidation_requested`
already cover both. Holding them apart is what produced the duplication.

`RoiSetModel` does **not** move inside the controller. Of its ~23 public
members, exactly one (`mark_stale_for_fingerprint`) is session-only; the rest
are consumed directly by `roi/window.py` and `single_canvas.py`. Subsuming it
would force the controller to re-export fifteen members — rule 1's
anti-pattern. The controller *uses* the store; it does not wrap it.

Sizes, current → target:

| Object | Start | Target | Now | Job |
|---|---:|---:|---:|---|
| `PlotSession` | 2051 | ~450 | 717 | coordination joins only |
| `RunSource` | 955 | ~250 | 955 | uniform key access, plus `get_plot_bundle` |
| `RegionController` | — | ~450 | 953 | crop, fingerprint, staleness, ROI pipeline |
| `RunCollection` | 261 | ~320 | 560 | ordered membership **+ visibility**, factories |
| `Selection` | 190 | ~220 | 314 | default + overrides, owns its signal |
| `ViewIntent` | (in `view_spec.py`) | ~250 | 445 | mutable view state, three signals |
| `Trace` | 483 | ~150 | 447 | request identity plus cached bundle |
| `TraceSet` | 136 | ~150 | 136 | derived membership |
| `RunListItemModel` | 186 | ~150 | 186 | sidebar rows, now in `views/` ✅ |

`PlotSession` started at 2051 file lines but **800 code lines** across 94
public members and 17 signals — the rest is docstrings. It is now 717 file
lines / **371 code lines** across 17 public members and 4 signals, so the
public surface hit its target while the file did not. Every other row is
over its file-line target for the same reason: these are numpydoc-documented
modules, and the targets were set against code volume. **Measure code lines
against these targets, not file lines** — that is the correction this pass
makes to the table, not a claim that the objects came in under budget.

---

## Step A — `PlotSession` / `RunListItemModel` rename and move ✅ (`5330b81`)

**Landed.** Independent of every other step. Rename, one file move, and one
ownership correction found while doing it.

### Did

- [x] Renamed the class `PlotModel` → `PlotSession` and the file
  `plotModel.py` → `plot_session.py`. **No alias kept.** The plan had said to
  hold `PlotModel = PlotSession` for one commit, but every call site is
  in-tree — `widgets/kafkaViewerTab.py` included, which needed its import
  line rewritten either way — so an alias would only have deferred the same
  edit. Same reasoning for `get_plot_model`, which step F had queued for
  deletion.
- [x] Renamed `RunListModel` → `RunListItemModel`; moved to
  `nbs_viewer/views/dataSource/run_list_item_model.py`, next to
  `runListView.py`. Its `plot_model` property became `session`.
- [x] **`RunListView` constructs the item model**, not `PlotPresenter`.
  See the decision below. Dropped `PlotSession.bind_run_list` and the
  `run_list_model` reverse pointer.
- [x] `DisplayManager.get_plot_model` → `get_session`.
- [x] Dropped `presenter.plot`; `presenter.session` is the only name. The
  same duplicate pair on the test fixture `HeadlessSession` went with it.

### The decision the plan got wrong

The plan said "`PlotPresenter` constructs the session first, then the item
model". Because `PlotPresenter` lives under `models/plot/`, that made
`models/` import `views/dataSource/` — an inversion invariant 11 warns about,
and one this plan's own invariant 1 already ruled out ("views may create Qt
proxies used purely as view adapters").

Counting the consumers settled it. Only `RunListView` ever used the item
model. `base.py`, `run_display.py`, `dimension.py`, `image_grid_canvas.py`
and `single_canvas.py` each assigned `presenter.run_list` to an attribute
**never read**; `mainDisplay.py` assigned it twice and never read it;
`plotDisplay.py` held it only to pass along; `get_run_list_model` had no
production caller; and `display_added = Signal(str, object)` emitted a
payload both handlers silently dropped.

So `RunListView` now takes the presenter and builds
`RunListItemModel(self.session)` itself, exactly as a view builds a filter
proxy. `rg "nbs_viewer.views" nbs_viewer/models/` is empty.

### Deleted

`bind_run_list`, the `run_list_model` reverse pointer, `presenter.plot`,
`PlotPresenter.run_list`, `DisplayManager.get_run_list_model`, the
`display_added` object payload, seven dead `run_list_model` attributes across
`views/`, `HeadlessSession.run_list`, the `PlotSession = PlotModel` alias,
`PlotModel` and `RunListModel` as names, `plotModel.py` and `runListModel.py`
as paths.

146 insertions, 223 deletions — net −77 lines.

### Exit criteria

- [x] `rg "PlotModel|RunListModel" nbs_viewer/ tests/` returns nothing
- [x] The item model lives under `views/`, so `models/` no longer holds a
  `QStandardItemModel`
- [x] `rg "nbs_viewer.views" nbs_viewer/models/` returns nothing
- [x] `pytest tests/` green at 350

### Findings

**Bug 9 (closed here).** `RunListView` passed its item model into
`DisplayControlWidget(display_manager, presenter, parent)`, whose first act is
`self.session = presenter.session`. `RunListModel` had no `session`
attribute, so constructing any `RunListView` raised `AttributeError`.
Verified against a worktree at `bfb8a73` before the fix. Passing the real
presenter closes it. Nothing in `tests/` caught this because the suite runs on
`QCoreApplication` and cannot construct a `QWidget`; it took a scratch script
under a real `QApplication`, per the headless testing plan's note.

**Bug 10 (open).** `widgets/kafkaViewerTab.py:68` makes the same class of
mistake: `PlotWidget(self.run_list_model, self.plot_model)` against a
`(presenter, panel, ...)` signature. Verified to raise `TypeError` on
construction. Left alone — `widgets/` is out of scope (invariant 6) — but it
means the Kafka tab cannot currently be opened.

Both bugs are positional-argument mismatches on widget constructors that no
test can reach, and bug 11 (a stale plot legend, fixed separately) is a third
of the same kind. Closing that gap is deferred to after this refactor by
decision, not oversight — see "After this refactor" in
[`refactor_plan.md`](refactor_plan.md).

### Non-goals

Not `Trace`. Not `ViewIntent`. Not the ROI extraction. The ~12 views that name
their session attribute `self.plot_model` keep that name; it is not the
`PlotModel` symbol and renaming it is a much wider diff than this step.

---

## Step B — `Trace` ✅ (`0aaa133`)

**Landed.** Depended on view-pipeline step 4, which had settled the request
shape.

`PlotDataModel` is `Trace`: request identity plus a cached bundle, with no
matplotlib import. The artist moved to a canvas-side map keyed by `TraceKey`,
which closes problem-statement item 6 and unblocks a headless plot frontend.

### Did

- [x] `TraceSet` (`trace_set.py`) holds `Trace` keyed by `TraceKey` and is
  owned by the session as `session.traces`. It emits `trace_added` and
  `trace_removed`, and `ensure()` returns `(trace, created)` so both
  `ensure_trace` and `rebuild` share one creation path.
- [x] `Trace` (`trace.py`) holds `request`, `last_bundle`, `trace_key` and
  visibility intent. `rg "^\s*(import|from)\s+matplotlib" nbs_viewer/models/`
  now matches only `region_mesh.py`.
- [x] `set_artist`, `remove_artist_from_axes`, `add_artist_to_axes`,
  `move_artist_to_axes` and the artist half of `clear()` are gone. `MplCanvas`
  owns `self._artists: Dict[TraceKey, Artist]` with `artist_for`,
  `_set_artist` and `_destroy_artist`; `ImageGridCanvas` owns the same map
  keyed by its `(uid, image index)` cell key.
- [x] `Trace.set_visible(bool)` records intent and emits `visibility_changed`;
  `MplCanvas._on_trace_visibility_changed` applies it to the artist and takes
  over the legend, autoscale and paint that the deleted `draw_requested` and
  `autoscale_requested` signals used to trigger.
- [x] The six compatibility properties are gone, along with `_dimension`,
  which was the same family. Call sites read `trace_key`, `xkey`, `ykey`,
  `request.norm_keys`, `request.view` and `request.view.plot_ndim`.
- [x] Session API renamed off the old class: `ensure_trace`, `traces`,
  `iter_visible_traces`, `drop_traces_for_uid`,
  `resolve_single_visible_2d_trace`, `parent_trace=`, `trace=`.

### The two decisions the plan left open

**Bundle invalidation on live data.** `needs_fetch` used to answer "is there
an artist?", which made it the canvas's question asked of the model. It now
answers "is there a bundle for this request?" — but a live scan changes the
arrays without changing the request, so that alone would serve stale data.
`Trace.invalidate_bundle` drops `last_bundle` and the fetched-request
fingerprint on the run's `data_changed`, unconditionally, and emits only when
visible. The canvas keeps its own half of the old test: it refetches when
`needs_fetch()` **or** it has no artist.

**Removal has to be announced, not performed.** `_dispose_plot_data` called
`plot_data.clear()`, which removed the artist. A session that cannot touch
artists cannot do that, so `TraceSet.discard` emits `trace_removed(key)` — the
key, not the trace, because the canvas files artists under the same key and
the trace is already gone by the time it needs one. `discard` also calls
`Trace.dispose`, which disconnects from the run; nothing did that before, so
dropped traces used to keep waking on every fetch their old run made.

### Hide and show stopped refetching

The old `_do_update_plot` hid a trace with `set_visible(False)` followed by
`clear()`, destroying the artist, so showing it again fell into the
`needs_artist` branch and started a worker. Hiding is now an artist flag and
nothing else; the bundle and the artist both survive. Verified under a real
`QApplication`, not only in the suite: after hide/show the artist is the same
object, `last_fetched_request` is unchanged, and no worker starts.

### Deleted

`PlotDataModel` as a name and `plotDataModel.py` as a path; `Trace.artist`,
`set_artist`, `clear`, `remove_artist_from_axes`, `add_artist_to_axes`,
`move_artist_to_axes`; the `artist_needed`, `draw_requested` and
`autoscale_requested` signals (`artist_needed` had no subscriber at all); the
session's `plot_data_added` signal, which also had none; `_key`, `_xkey`,
`_ykey`, `_norm_keys`, `_indices`, `_cube_view_spec`, `_dimension`;
`from matplotlib.image import AxesImage` under `models/`;
`ImageGridCanvas._handle_image_draw` and `_move_plot_data_to_axes`;
`MplCanvas.plotArtists`.

`models/plot/`: **4966 → 4952 code lines** (−14, excluding docstrings and
comments); 19 → 20 files. `views/plot/` 5544 → 5584 (+40) — the artist
lifecycle is now written where the artists live. Suite 344 → 351.

### Exit criteria

- [x] `rg "matplotlib" nbs_viewer/models/` returns only `region_mesh.py` —
  **for imports**. Nine files under `models/plot/` still say "matplotlib data
  coordinates" in prose, which is what those coordinates are called; the
  criterion was about the dependency, and `region_mesh.py:339` is the only
  `import` left. `tests/test_trace.py` enforces it in a fresh interpreter,
  since by the time the suite runs matplotlib is already imported.
- [ ] `EXPECTED_VIOLATIONS` in the ownership guard is empty — **not
  closable here.** The guard's `allowed` set is the single entry
  `image_grid_canvas.py`, which constructs a `Trace` directly. Renaming the
  class does not remove the construction; deleting that bypass is step C's
  first bullet. This criterion belongs to step C and is moved there.
- [x] A full `ensure_trace` → `get_plot_bundle` → `set_visible` cycle runs in
  a test with no canvas and no matplotlib import
- [x] Hide, then show, does not refetch

### Tests

`tests/test_trace.py` (7): the artist API and the compatibility properties are
absent rather than renamed; the full headless cycle; hide/show does not
refetch; new run data invalidates the bundle; dropping a trace announces its
key; and a subprocess that imports `trace` and `trace_set` into a fresh
interpreter and asserts matplotlib did not come with them.

Three scratch scripts ran under a real `QApplication` — `MplCanvas` line plot
with hide/show/drop, `MplCanvas` 2-D image with a committed crop, and
`ImageGridCanvas` paging — because the suite runs on `QCoreApplication` and
cannot build a `QWidget`. All three pass; none is committed, for the same
reason step A's was not.

### Non-goals

Not the `ImageGridCanvas` bypass, the x × y × run product in the canvas, or
`ViewIntent` — all step C. `MplCanvas.plot_data` keeps its name: it is a
canvas method meaning "fetch and draw this", not the deleted class.

---

## Step C — Consumer sweep (narrowed to `single_canvas`) ✅ (`940d45c`)

**Depends on** step B and view-pipeline step 6.

**Re-scoped twice, 2026-09-09.** First against the tree: two of the six
bullets were already closed or reversed by step 6, and the step's stated
payoff was banked by step 3. Then against the maintainer's call: the image
grid and `RunDisplayWidget` are deferred, so what shipped is the
`single_canvas` half alone.

### Did

- [x] `MplCanvas` renders the `TraceSet`. `_do_update_plot` iterated
  `visible_models × selection.x × selection.y` and called `ensure_trace` for
  each — **a second implementation of `PlotSession._retained_trace_keys`**,
  which `rebuild()` already runs from seven call sites. The canvas now reads
  `self.traces` and decides only visibility, from `plot_model.visible_uids`.
- [x] Deleted `updatePlotData`, which existed only to serve that product.
  Its signal wiring moved to `_on_trace_added`, connected to the set's
  existing `trace_added` — the canvas now *learns* of a trace instead of
  asking for one. `__init__` adopts any traces that already exist, so a
  canvas built after runs are loaded is not blind to them.
- [x] Deleted `remove_run_data` (44 lines). The session emits `run_removed`,
  then `rebuild()` disposes the run's traces, and `_on_trace_removed` —
  which step B added and which already handled *every* other removal path —
  destroys each artist. All `remove_run_data` still owned was the axes reset.
- [x] Dropped the `TraceKey` import from the canvas. Nothing under
  `views/plot/mplCanvas/single_canvas.py` constructs a trace identity now.

### Deferred by decision, not left open

- **`ImageGridCanvas`** — the `Trace` bypass, the private `(uid, image_idx)`
  map, `_get_shape_info` and `_make_slice_info`. It is due for a rewrite once
  `single_canvas` stabilizes, so tidying it now is wasted, and
  `intent.fan_out()` (master-plan open question 5) should be designed against
  that rewrite rather than retrofitted. **This keeps the ownership guard's
  `allowed` set non-empty**; see exit criteria.
- **`run_display.py`'s `"time"`-first sort** — a display concern, correctly
  in the widget. Key ordering is due to grow a sort-by-dimensionality rule,
  so `RunDisplayWidget` is deferred on the same grounds.
- **The 2-D `QMessageBox`** — reversed by step 6, not deferred. It is
  `accepts_plot_ndim`, and it tests how many artists are visible, which only
  the canvas knows. Moving it would re-add the artist state step B deleted.

### The ordering the deletion exposed

`run_removed` is emitted *before* `rebuild()` disposes the traces, so an
`_on_run_removed` that reset the axes immediately would have run while the
artists were still on them. The reset is deferred to a `_needs_axes_reset`
flag consumed at the top of the next scheduled `_do_update_plot`, which the
session already triggers via `request_plot_update`. The old code got away
with the ordering only because it did the destruction itself.

### `Trace.dispose` had to grow

`remove_run_data` was the only place a dropped trace's *outgoing* signals were
disconnected. Removal is announced by key, so `_on_trace_removed` never gets
the trace and cannot unsubscribe on its behalf — and a `Trace` is a child of
the `TraceSet`, so Qt keeps it alive past its own removal. `dispose` now drops
`data_changed`, `visibility_changed` and `render_mode_changed` along with the
run connection it already dropped.

A first attempt gated this on `self.receivers(signal)` to avoid PySide6's
warning when nothing is connected. `receivers()` takes a *signature string*
there, so it raised `TypeError`, the surrounding `except` swallowed it, and
the disconnect silently never ran — the suite passed anyway. The new test
caught it. The gate is now `warnings.catch_warnings`.

### Deleted

`MplCanvas.updatePlotData`, `MplCanvas.remove_run_data`, the x × y × run
product in `_do_update_plot`, the `TraceKey` import under
`views/plot/mplCanvas/`. `single_canvas.py` 1695 → 1667 lines; the canvas
gained `_connect_trace` / `_on_trace_added` (25 lines) and lost 82.

### Exit criteria

- [ ] The views-construct-no-traces guard has an empty `allowed` set —
  **deliberately still open.** The guard is
  `test_views_do_not_construct_traces_except_image_grid`
  (`tests/test_plot_model_step3.py:194`), not a constant named
  `EXPECTED_VIOLATIONS` as step B's criterion claimed. Its one entry is the
  image grid, which is deferred to its rewrite. Carry this to that work
- [x] No `plot_data._`-prefixed access under `views/` — done in step B
- [x] `MplCanvas` constructs no models and no trace keys
- [ ] `ImageGridCanvas` constructs no models — deferred with the rewrite
- [x] A 1-D key and a 1-D projection of a 3-D key plot together — already
  true model-side after step 6; the canvas no longer flattens the set
- [ ] `codebase_problem_statement.md` item 7 can be struck — its
  `MplCanvas._do_update_plot` bullet can be struck now. The `ImageGridCanvas`
  bullet is deferred; the `run_display.py` bullet should be **deleted** from
  item 7, since sorting keys for display is not domain policy; and the
  `views/catalog/base.py` bullet is invariant 1's explicit carve-out and
  should be deleted too

### Tests

`tests/test_trace.py::test_dropping_a_trace_drops_its_outgoing_connections`
— the one piece of this step that is reachable headlessly. Suite 361 → 362.

Two scratch scripts under a real `QApplication`, since the suite runs on
`QCoreApplication`: a line-plot session (two runs × two Y keys through add,
hide, show, deselect and remove — 25 assertions) and a 2-D image session
(image render, committed crop, hide/show, removal tearing down the colorbar
and render mode — 18 assertions). Both pass; neither is committed, for the
same reason steps A and B did not commit theirs.

---

## Step G — `ViewIntent` becomes a model ✅ (`63a73f0`)

**Landed.** Smallest of the remaining steps, fixes a confirmed defect, and
establishes the pattern the other two promotions follow. Depends on step 6,
which made `ViewIntent` the single axis-order policy.

`ViewIntent` is a frozen dataclass that `PlotSession` replaces wholesale. It
becomes a `QObject` that mutates and emits. `Projection` and `PlotRequest`
stay frozen — a request is the fingerprint of a fetch and is compared to
decide whether to refetch. Immutability is for things retained and compared,
not for things observed.

### The evidence that settled it

The whole tree retains exactly two `ViewIntent` values: `PlotSession._intent`
(the live one) and `MplCanvas._last_2d_intent`. Nothing hashes one, keys a
dict with one, or stores one for later. The worker thread takes a
`PlotRequest`, so there is no cross-thread reader. Every other use is a field
read or a test calling `.project()`.

`_last_2d_intent` is not a reason to keep the type frozen — it is a view
doing its own change detection because the signal is too coarse to say what
changed, the same shape as the duplications steps C and 6 deleted. Read as a
requirement it argues for freezing; read correctly it is **bug 12**.

### Bug 12, confirmed before writing this step

`_prepare_2d_axes` computes `spec_changed = intent != self._last_2d_intent`
and calls `_reset_plot_axes()` on any difference. A slider step changes
`reduce_indices`, so **every slider tick on a 3-D dataset destroys the image
artist, the colorbar, and any live ROI or crop selector, then rebuilds them.**

Reproduced under a real `QApplication` with a 4x5x6 cube at `plot_ndim=2`: one
`set_axis_reduce({0: (INDEX, 2)})` and the image artist is a different object
and the colorbar has been rebuilt. The suite cannot reach this — `MplCanvas`
is a `QWidget`.

The fix is the signal split, not a smarter diff: an index change does not move
the plot plane's coordinate frame, so it must not reset the axes.

### The signals

Derived from consumers, not from fields. Today's `cube_view_changed` has four
consumers wanting three different things:

| Consumer | Reacts to |
|---|---|
| `MplCanvas._on_view_intent_changed` | `plot_ndim` only |
| `MplCanvas._prepare_2d_axes` (value diff) | orientation only — over-fires today |
| `PlotSession._on_cube_view_changed_for_region` | orientation only |
| `roi/window._on_view_context_changed` | anything |
| `set_view_intent` body (`_refresh_held_requests`, refetch) | anything |

So three signals:

```python
class ViewIntent(QObject):
    plot_ndim_changed = Signal(int)   # rank changed
    orientation_changed = Signal()    # dim_order / xkey — the plane's frame
    changed = Signal()                # any mutation; always emitted last
```

`reduce_roles` and `reduce_indices` get **no signal of their own**, because no
consumer distinguishes them from any other change — they fall under `changed`
and cause a refetch. One signal per distinct reaction, not one per field.

**No mutable payload.** `plot_ndim_changed` carries an `int`, which is a
value; the other two carry nothing and receivers read the object. This is the
one rule that survives from the frozen argument: a mutable object as a signal
payload cannot answer "what changed?" for a receiver that runs after
coalescing.

Emission matrix — each mutator guards on real change, which is the per-field
version of the `set_view_intent` equality guard and is why that guard goes:

| Mutator | `plot_ndim_changed` | `orientation_changed` | `changed` |
|---|:--:|:--:|:--:|
| `set_plot_ndim(n)` | ✔ | — | ✔ |
| `follow_xkey(k)` | — | ✔ | ✔ |
| `set_axis_order(order, names)` | — | ✔ | ✔ |
| `set_reduce(roles, indices)` | — | — | ✔ |

`changed` fires **last and always**, so a consumer connected only to it never
misses anything, and one connected to a specific signal sees that first.
Connect to exactly one: connecting to both double-handles.

### Do

- [x] `ViewIntent` becomes a `QObject` in its own module (`view_intent.py`),
  out of `view_spec.py`. Constructor keeps today's keyword parameters so the
  ~40 test construction sites are unchanged.
- [x] `follow_xkey`, `with_axis_order`, `with_reduce_from` stop returning new
  instances and become `follow_xkey`, `set_axis_order`, `set_reduce`, each
  guarding on real change and emitting per the matrix above.
- [x] `project()` is unchanged apart from a `plot_ndim` override — see below; and still returns a frozen `Projection`.
- [x] `PlotSession` holds the intent, wires `intent.changed` →
  `_refresh_held_requests` **then** → `request_plot_update` (in that order;
  requests must be rewritten before the refetch is scheduled), and exposes it
  as `session.view_intent`.
- [x] `PlotSession.set_view_intent`, `set_plot_ndim`, `follow_x_selection`,
  `move_view_axis` and `set_axis_reduce` become gestures on the intent. Keep
  `move_view_axis` and `set_axis_reduce` on the session **only** if they still
  need `driving_projection()` — they do, so they are joins and stay.
- [x] `MplCanvas` connects `plot_ndim_changed` → the existing clear-and-set,
  and `orientation_changed` → `self._needs_axes_reset = True`, consumed at the
  top of `_do_update_plot` exactly as step C's run-removal reset is.
- [x] `roi/window.py` connects `intent.changed`.

### Deleted

`PlotSession.cube_view_changed`, `PlotSession.set_view_intent`,
`PlotSession._on_cube_view_changed_for_region` (one of the five self-signal
connections), `MplCanvas._last_2d_intent` and the `spec_changed` diff, the
`replace(self._intent, ...)` calls, and `ViewIntent`'s frozen `with_*`
constructors.

### The decision the plan had not predicted

`project()` needed a `plot_ndim` override. The mixed-rank path built a
throwaway intent with `dataclasses.replace(intent, plot_ndim=len(shape))` — a
key that cannot fill the session plot still plots on its own terms — and a
mutable model cannot supply a throwaway. Mutating the live intent instead
would have been a silent global side effect. The override says what the call
actually means, "project at this rank", and `test_plot_request_wiring` reads
better for it: the test had the same `replace` and now expresses the same
thing in one call.

`tests/fixtures/view.py` gained `apply_projection(intent, projection)` for the
same reason: 9 test sites said `session.set_view_intent(intent_from_projection(p))`,
which no longer exists. The helper drives the production mutators, so setting
a test view now exercises the emission matrix on the way in.

### The honest trade

A flag set by a signal over-approximates where a value diff was exact: if the
orientation changes and changes back between two paints, the flag is set and
an unnecessary reset happens. That is strictly better than today, where a
reset happens on *every slider tick*, but it is a trade and not a pure win.

### Exit criteria

- [x] `rg "cube_view_changed" nbs_viewer/ tests/` returns nothing
- [x] `rg "_last_2d_intent" nbs_viewer/` returns nothing
- [x] Bug 12 closed: a slider step keeps the same image artist and colorbar,
  asserted under a real `QApplication`
- [x] An orientation change still resets the 2-D axes
- [x] `PlotRequest` and `Projection` are still frozen; `rg "@dataclass\(frozen=True\)" nbs_viewer/models/plot/` still matches both

### Tests

Suite 362 → 374. `tests/test_view_intent_signals.py` (10) covers the emission
matrix, that no-op mutations are silent, that `changed` fires last, that a
projection already handed out survives a later mutation, and that an invalid
mutation leaves the intent untouched and silent.

`test_move_view_axis_off_the_ends_is_a_no_op` asserted
`session.view_intent is intent`, which **inverted** as predicted — with one
live object that identity is trivially true, so the test passed while
asserting nothing. It now asserts no signal fired and no field moved. Two
session-level tests were added: that the intent's `changed` rewrites held
requests *before* scheduling the refetch, and that leaving 2-D invalidates
region state while entering it does not.

The predicted test cost was three edits. Actual: those three plus 9
`set_view_intent` call sites, absorbed by the `apply_projection` fixture. The
~40 `ViewIntent(...)` construction sites were unaffected, as predicted.

Three scratch scripts under a real `QApplication`: bug 12's reproduction now
shows the same artist and colorbar across a slider step, an orientation change
still resets, and step C's line and image regressions still pass.

---

## Step D — `RegionController` (crop and ROI are one child) ✅ (`aba26a3`)

**Depends on** step G, which gives it `orientation_changed` to consume instead
of the session's self-signal, and on view-pipeline step 4.

**Rewritten 2026-09-09.** The original step said "extract the four-method ROI
pipeline" and "keep thin delegating methods on the session so view call sites
are unchanged." Both are now wrong. The pipeline is not the whole cluster —
crop belongs with it — and the delegating methods are exactly the forwarding
layer rule 1 forbids. They are affordable to delete because **every
heavyweight ROI member has exactly one caller**, and it is not `MplCanvas`.

### Who actually consumes this

`roi/window.py` uses 16 session members and is the only caller of
`prepare_roi_commit`, `finalize_roi_commit`, `build_roi_profile_request`,
`resolve_roi_entry` and `cached_parent_bundle_for_preview`.
`roi/preview_canvas.py` is the only caller of `preview_roi_profile`.
`MplCanvas` touches only the draw-enable half — `roi_set`,
`set_roi_draw_enabled`, `is_roi_draw_enabled`, `sync_region_state_with_view`
and three signals. So handing out a controller costs the canvas almost
nothing.

### How cleanly it detaches

Tracing every `self.` reference in the four pipeline methods, their entire
coupling to the rest of the session is `resolve_single_visible_2d_trace()`
plus one `_selection.default.x` read in `finalize_roi_commit`. That trace
resolution is a join over `TraceSet` and visibility, so it **stays on the
session** and the controller is constructed with a reference to it.

### Do

- [x] `RegionController(QObject)` in `models/plot/region_controller.py`, owned
  by the session as `session.region`, holding `RoiSetModel` and the crop pair
  (`ViewCrop` + the trace key it was drawn on).
- [x] Move the ROI pipeline: `build_roi_profile_request`,
  `preview_roi_profile`, `prepare_roi_commit`, `commit_roi_profile`,
  `finalize_roi_commit`, `resolve_roi_entry`,
  `cached_parent_bundle_for_preview`, `resolve_parent_frame`,
  `apply_roi_region_to_selected`, `apply_expanded_roi_profile_span`,
  `_commit_span_full`.
- [x] Move the crop half with it: `view_crop`, `set_view_crop`,
  `clear_view_crop`, `crop_applies_to`, `crop_status_text`,
  `apply_view_crop_from_region`, `invalidate_view_crop_if_invalid`.
- [x] Move the shared machinery: `resolve_current_view_fingerprint`,
  `sync_region_state_with_view`, `invalidate_all_region_state`, and the
  `region_status_changed` / `region_invalidation_requested` /
  `view_crop_changed` signals.
- [x] **Delete `MplCanvas.current_view_fingerprint`**, which is
  `resolve_current_view_fingerprint` written a second time against the
  canvas's own active bundle. One fingerprint policy, in the controller.
- [x] `RegionController` connects `intent.orientation_changed` →
  `sync_region_state_with_view` and `intent.plot_ndim_changed` → the
  leaving-2-D invalidation. Two more self-signals become real connections.
- [x] **No delegating methods on the session.** `roi/window.py`,
  `roi/preview_canvas.py` and `MplCanvas` retarget to `session.region` and
  `session.region.roi_set`.
- [x] `MplCanvas` connects `region.view_crop_changed` → `_needs_axes_reset`,
  deleting `_last_2d_view_crop` and its diff — the crop twin of bug 12,
  though this one over-fires correctly since a crop really does move the
  extent.
- [x] Collapse `set_view_crop` / `clear_view_crop` /
  `apply_view_crop_from_region` into one entry point now that they are in one
  object.
- [x] Break the last region self-signal: the session connects
  `selected_keys_changed` → `_on_selected_keys_changed_for_region`, which
  invalidates all crop and ROI state on every key change. Make it an explicit
  call, or a connection from `Selection` once step H lands.

### The decisions the plan had not predicted

**`cached_parent_bundle_for_preview` deleted rather than moved.** It rebuilt
the session request and compared its projection against the trace's, returning
None when they differed. That comparison can no longer fail:
`_refresh_held_requests` is wired to every signal that moves the session view
— the intent's `changed`, the transform, and this controller's
`view_crop_changed` — so a held request is rewritten before anything can
observe it as stale. Verified empirically across axis-order, slider, crop,
plot-rank, selection and transform changes before the comparison was dropped.
Step F had queued this as "an equality check"; it is now literally that, so
step F's entry is closed here.

**The crop collapse went one method, not three.** The plan said to collapse
`set_view_crop` / `clear_view_crop` / `apply_view_crop_from_region` into one
entry point. Examined, they are a primitive plus two guarded uses, and two of
the three have distinct production callers — merging them would need a
polymorphic setter, which is worse. What was actually available: `set_view_crop`
now guards on real change (the rule step G established for the intent's
mutators), which leaves `clear_view_crop` as a null check wrapped around
`set_view_crop(None)`. That one is deleted; the other two stay.

**The controller borrows two things, and returns one.** Tracing every `self.`
reference in the moved code, its coupling to the session is
`resolve_single_visible_2d_trace` (×10) and the session-default X keys (×1).
Both are joins the session owns. The reverse direction is a single signal:
`view_crop_changed`, which the session connects to `_refresh_held_requests`
then `request_plot_update`, because the crop rides on every request and the
controller does not own the traces. `_build_plot_request` and
`_refresh_held_requests` were on the borrowed list until the two decisions
above removed them.

### Exit criteria

- [ ] `plot_session.py` under ~900 file lines — **2045 → 1263, not met.** The
  remainder is runs/visibility (27 methods) and selection, which is step H's
  content; region work alone could not reach 900
- [x] `rg "roi|crop|region|fingerprint" nbs_viewer/models/plot/plot_session.py`
  returns nothing outside the controller's construction. Enforced by
  `test_the_session_defines_no_region_methods`, which allows exactly `region`
  and `_on_view_crop_changed`
- [x] `rg "current_view_fingerprint" nbs_viewer/views/` returns nothing —
  enforced by `test_the_canvas_holds_no_second_fingerprint_policy`
- [x] No delegating ROI or crop method remains on the session
- [ ] Three of the five session self-signal connections are gone — **two, not
  three.** Step G took `cube_view_changed`; this step took
  `selected_keys_changed`. The third the criterion counted on is
  `available_keys_changed` → selection revalidation, which is step H's, and
  the remaining pair is the deferred cache aggregation
- [x] `test_roi_preview_commit` and `test_roi_wiring` green. **They needed
  edits** — the original step used "unchanged" as the thinness check, which no
  longer applies now that the delegation is deliberately deleted. Retarget
  them at the controller; the assertions themselves should not change.

### Tests

Suite 380 → 389. `tests/test_region_controller.py` (9): the session owns one
region child and re-exports none of it; sessions get distinct controllers; the
crop mutator guards on real change; a crop change rewrites held requests
*before* the repaint is scheduled; leaving 2-D and changing the selection each
invalidate; and two AST guards — the session defines no method named for ROI,
crop or fingerprints beyond `region` and `_on_view_crop_changed`, and the
canvas defines no `current_view_fingerprint`. Those two are what stop the
forwarding layer growing back.

110 references across three views and eight test modules were retargeted onto
`session.region`. All four `QApplication` scripts still pass, plus an 18-case
ROI-window sweep over x key × axis order × profile axis on the 3-D cube.

### Sizes

`plot_session.py` 2045 → 1263; `region_controller.py` 953 new lines;
`single_canvas.py` 1676 → 1674. Session self-signal connections 4 → 3.

---

## Step H — `RunCollection` and `Selection` become models ✅ (`85e653b`)

**Depended on** step D only for sequencing, not mechanism. Reverses a thinning
that went too far.

`RunCollection` was converted from a `QObject` to a plain container earlier in
this refactor, and its visibility state and signals moved up to
`PlotSession`. That did not remove the work; it relocated it into a larger
object and forced the session to announce on the container's behalf. Rule 2.

### The measurement that justified it

`_visible_uids` lived on the session, so `visible_models` was a **join** of
membership × visibility rather than a forward, and `remove_uids` touched the
collection, the selection, visibility and four signals. That is why the
runs/visibility cluster was 27 methods and 171 code lines rather than the thin
pass-through it looked like. Moving visibility down made the join disappear.

### Did

- [x] `RunCollection` is a `QObject` owning `run_added`, `run_removed`,
  `available_runs_changed`, `visible_runs_changed` and `available_keys_changed`,
  and holds `_visible_uids` with `visible_uids`, `visible_models`,
  `set_uids_visible`, `auto_add`, `dynamic_update`, `single_selection_mode`
  and the available-key universe.
- [x] `Selection` is a `QObject` owning `selected_keys_changed`, with
  `set_selected_keys`, `set_selection_for`, `clear_overrides`,
  `selection_for`, `get_selected_keys` and `retain_selection`.
- [x] `runListView.py` takes `session.collection`; `run_display.py` takes both
  `collection` and `selection`; `dimension.py`, `metadataView.py`,
  `plot_settings.py`, `displayControl.py`, `single_canvas.py` and
  `image_grid_canvas.py` each take the child they actually use.
  **`RunListItemModel` now observes a `RunCollection`, not a session** — it
  used six collection members and nothing else.
- [x] The session keeps `rebuild`, `driving_axes`,
  `resolve_single_visible_2d_trace` and `freeze_runs` — the joins — plus
  the request assembly, the transform, and `request_plot_update`.
- [x] The remaining self-signal connections became connections between two
  objects. **All of them**, including the cache-progress pair the criterion
  had expected to defer — see below.
- [x] Collapsed the singular/plural pairs. `set_run_visible` turned out to be
  dead; `add_run` and `remove_run` were deleted on the session *and* on
  `PlotPresenter`, where they were a second layer of the same forward.

### The decisions the plan had not predicted

**`Selection` is constructed with the collection.** The plan listed them as
siblings, but `selection_for(uid)` filters against the keys that run actually
has, which is the collection's answer — on the session that was a join, and
as siblings it would have had to stay one. Giving `Selection` the collection
turns three couplings into internal wiring: it drops an override when
`run_removed` fires, revalidates the default when `available_keys_changed`
fires, and adopts a lone run's own default selection on membership or
visibility changes. This is step D's borrow pattern, one level down.

**The deferred cache pair went too, for free.** The criterion expected
`rg "self\.[a-z_]*\.connect\(self\._"` to still match the cache-progress
connections. It matches nothing: those were `self.run_added` and
`self.run_removed`, and once those signals moved to the collection the
session was subscribing to *another object*, not to itself. The aggregation
itself is unchanged and still deferred (open question 2).

**Both mutators guard on real change**, which step G established for the
intent and step D for the crop. This was not in the step, and it is load-
bearing here rather than cosmetic: several signals now land on the selection
that previously could not, and without the guard each would restart the fetch
of every trace. `set_selected_keys`'s dead `force_update` parameter went with
it — the one caller that passed `True` meant "repaint even if nothing
changed", which is `request_plot_update.emit()` and now says so.

**Visibility no longer rebuilds the trace set.** Retention is membership ×
selection, so a visibility change has nothing to rebuild; it only repaints.
The one test that asserted otherwise reached that state through
`drop_traces_for_uid`, which had no production caller. Both are deleted, and
the replacement test states the positive version: hide-then-show hands the
canvas the same `Trace` object.

### Deleted

`PlotSession.available_runs`, `available_uids`, `set_run_visible`,
`is_key_selected`, `set_runs`, `cleanup_state`, `visible_runs`,
`set_plot_ndim`, `dimension`, `drop_traces_for_uid`, `validate_combine`,
`combine_runs`, `update_available_keys`, `_maybe_apply_default_selection`,
`_on_available_keys_changed`, `_connect_run_keys`, `_disconnect_run_keys`;
the `available_runs_changed` list payload (a signal with no subscribers at
all); `set_selected_keys`'s `force_update`; `PlotPresenter.add_run`,
`add_runs` and `remove_run`; `RunCollection.add`, `remove` and `clear` as
raw dict operations.

### Exit criteria

- [x] `rg "self\.[a-z_]*\.connect\(self\._" nbs_viewer/models/plot/plot_session.py`
  returns nothing — better than the criterion, which allowed the cache pair
- [ ] `plot_session.py` under ~450 file lines — **2045 → 717, not met at the
  file level.** 800 → **371 code lines**, and 94 public members + 17 signals →
  17 + 4. The residue is numpydoc, plus the ~60-line deferred cache cluster.
  The sizes table is corrected above to measure code lines
- [x] No view names both a child and the session for the same concern
  (invariant 8). `runListView` names `session` only for `freeze_runs`, which
  is a join and not a collection concern
- [x] `_visible_uids` does not appear in `plot_session.py` except as the
  parameter name of the visibility handler

### Tests

Suite 389 → 403. `tests/test_collection_and_selection.py` (11) plus a rewritten
visibility test in `test_plot_model_step3.py` and two cache-status tests that
now go through the real add path instead of injecting fakes past the API.

Three of the eleven are structural guards on the session source: it declares
exactly four signals and none of them is about runs or keys; it subscribes to
none of its own signals; and it holds none of the children's state. Those are
what stop rule 2 being undone a second time.

Every new test was checked by breaking what it guards, one mutation at a time:
dropping the `available_keys_changed` → revalidate connection, the
`run_removed` → override-cleanup connection, either change-guard, the
selection → rebuild connection, and regrowing a runs signal on the session
each fail exactly the intended test. Dropping the visibility → repaint
connection is caught **only** by `test_widgets.py`, which is the first return
on the previous commit's headless-widget work.

110 call sites were retargeted across 16 production files and 19 test modules.
A real-`QApplication` script builds `PlotDisplay`, `MetadataViewer` and
`ImageGridDisplay` and drives add, select, 2-D, hide/show, unlink/relink and
remove; all four earlier scripts still pass.

### Sizes

`plot_session.py` 1263 → 717 (371 code lines); `run_collection.py` 261 → 560;
`selection.py` 190 → 314. Session self-signal connections 3 → 0.

---

## Step E — Re-home `CombinedRunSource` and `FrozenRunSource`

**Next.** Step H stabilised the collection's factory API (`make_combined`,
`make_frozen`, and the new `combine`). Otherwise unchanged from the original.

Both are `RunSource` subclasses that should be `CatalogRun` implementations —
they synthesise data, which is a data-layer job.

### Do

- [ ] Move `combinedRunSource.py` and `frozenRunSource.py` into `models/data/`
  as `CatalogRun` subclasses.
- [ ] **Fixes bug 1**: `CombinedRunSource` does not override
  `get_plot_bundle`, and the inherited path reads `self._run`, which
  `super().__init__(first_run.run)` set to the first run. Combining currently
  plots the first run and says nothing. Making combine a `CatalogRun` removes
  the inherited path entirely.
- [ ] Remove the duplicate `data_changed` connect in `CombinedRunSource`
  (`:69-70` plus `RunSource._connect_run` connects the same signal twice, so
  every combined run fires its handler twice).

### Exit criteria

- [ ] A combined run plots the combination, asserted against known arrays
- [ ] A source `data_changed` fires its handler exactly once
- [ ] `models/plot/` holds no `CatalogRun` subclasses

---

## Step F — Final deletions and renames

**Last.** Shrunk: steps G, D and H absorb most of what it used to hold.

### Do

- [ ] `runSource.py` → `run_source.py`
- [x] ~~Delete remaining aliases~~ — done in step A
- [x] ~~Collapse near-duplicate APIs: `add_run`/`add_runs`,
  `remove_run`/`remove_uids`, `set_run_visible`/`set_uids_visible`~~ — moved
  to step H, which is where those methods stop existing
- [x] ~~Delete `cached_parent_bundle_for_preview`~~ — moved to step D
- [ ] Delete `RunSource.get_plot_data` (broken, no live callers)
- [ ] Resolve `DisplayManager` versus `AppModel` (open question 6)
- [ ] Re-check the ownership guard's `allowed` set. It stays non-empty by
  decision — the entry is `ImageGridCanvas`, deferred to its rewrite — so
  record that rather than closing it

### Exit criteria

- [ ] No camelCase filenames under `models/plot/`
- [ ] No compatibility aliases anywhere
- [ ] Record final file and line counts against the targets above

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-08 | Written from the live parts of `model_core_refactor_plan.md` and `plot_session_list_adapter_plan.md`. Claimed-done items re-verified against the tree; sizes re-measured. |
| 2026-09-08 | Step A landed (`5330b81`). Aliases dropped rather than held for a commit. `RunListView` builds the item model instead of `PlotPresenter`, which removes the `models/` → `views/` import the step as written would have created; the dead-consumer count that justified it is recorded in the step. Bugs 9 and 10 found en route, 9 closed. |
| 2026-09-08 | Step B landed. `TraceSet` and `Trace` split into two files; the artist map is canvas-side. Two things the plan left open are resolved in the step: the live-data cache rule (invalidate on the run's `data_changed`) and the fact that removal must be *announced* by key rather than performed. The `EXPECTED_VIOLATIONS` exit criterion moved to step C — it names the `ImageGridCanvas` bypass, which step B does not touch. |
| 2026-09-08 | Sizes re-measured; `RunSource` (792 → 955) and `Trace` (496 → 483) had drifted. Step D's `PlotSession` figure corrected to 1938. Step A's findings now point at the master plan's "After this refactor" section for the widget-testing gap. |
| 2026-09-09 | Step C re-scoped before starting, against the tree rather than the plan. Its `DimensionControl` bullet was closed by view-pipeline step 6, which had to do it to move the axis-order policy out of a widget. Its `QMessageBox` bullet was *reversed* by the same step: `accepts_plot_ndim` tests visible-artist count, which only the canvas knows, so moving it would re-add the artist state step B deleted. Its "Closes" payoff was banked by step 3. The four live bullets remain, and one of them (`fan_out`) needs master-plan open question 5 answered first. |
| 2026-09-09 | Step C landed (`940d45c`), narrowed to `single_canvas` by the maintainer: the image grid is due for a rewrite once the canvas stabilizes, and `run_display.py`'s key sort is a display concern that belongs in the widget and will grow a dimensionality rule. The canvas stopped recomputing `_retained_trace_keys` and now reads the session's `TraceSet`; `updatePlotData` and `remove_run_data` are gone. `Trace.dispose` grew the outgoing-signal disconnect that `remove_run_data` had owned. The ownership guard stays non-empty by decision and carries to the grid rewrite. |
| 2026-09-09 | Remaining sequence re-derived and the ownership tree rewritten. Step D's original mandate to keep thin delegating methods was dropped — it is the forwarding layer rule 1 forbids, and it is affordable to drop because every heavyweight ROI member has exactly one caller, none of them `MplCanvas`. Crop merged into the ROI child (one lifecycle, one fingerprint, two shared invalidation methods); `RoiSetModel` kept as a sibling (22 of 23 members have external consumers, so subsuming it would force a 15-member re-export). New steps G (`ViewIntent` becomes an emitting model, three signals derived from consumers) and H (`RunCollection` / `Selection` promoted, reversing an over-thinning). Bug 12 confirmed while designing G's signals. Cache aggregation ruled out as a child and deferred. |
| 2026-09-09 | Step H landed (`85e653b`). `RunCollection` and `Selection` are `QObject`s again, owning the signals for the state they hold. Two things the plan had not predicted are recorded in the step: `Selection` is constructed *with* the collection, because resolving a selection needs the run's own keys — which turns three cross-object couplings into internal wiring and kills the last self-signals; and both mutators guard on real change, which is load-bearing now that several signals land on the selection that previously could not. Visibility stopped rebuilding the trace set, and `drop_traces_for_uid` — the only way to observe the old coupling — was found to have no production caller and deleted. The self-signal criterion came in better than written: the cache-progress pair it expected to defer was `run_added`/`run_removed`, which now belong to the collection. The file-line target is still unmet and the sizes table is corrected to measure code lines. |
| 2026-09-09 | Step D landed (`aba26a3`), rewritten from its original text: no delegating methods, and crop merged into the ROI child. Two unpredicted decisions are recorded in the step — `cached_parent_bundle_for_preview` deleted rather than moved (its equality check is now structurally unreachable, which also closes step F's entry for it), and the crop collapse reduced to deleting `clear_view_crop` once `set_view_crop` guards on real change. Two exit criteria are honestly unmet: `plot_session.py` is 1263 rather than under 900, and two rather than three self-signals are gone; both remainders are step H's content. |
