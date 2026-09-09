# Session and traces plan

Who owns what. Sub-plan of [`refactor_plan.md`](refactor_plan.md); the other
half is [`view_pipeline_plan.md`](view_pipeline_plan.md), which owns how a
request becomes a bundle.

**Status:** steps A and B landed; C–F not started. Everything this plan's
predecessors marked done is verified against the tree below. Step C was
re-scoped 2026-09-09 after view-pipeline step 6 closed two of its bullets.

**Replaces** `model_core_refactor_plan.md` (steps 4–8) and
`plot_session_list_adapter_plan.md` (P2–P3), both deleted 2026-09-08 and
recoverable from `57f6d7b`.

## Already landed

Verified in the tree, not taken on trust from the deleted documents:

- `PlotSession` (`plot_session.py`) owns `RunCollection`, visibility,
  `Selection`, transform, the plot-data map and the ROI set. No aliases.
- `RunListItemModel` is a thin Qt facade under `views/dataSource/` — 186
  lines, no forwarding, no cache aggregation (that moved to the session).
- `RunSource` no longer holds selection, visibility or transform.
- `KeyInfo` / `RunIdentity` / `AxisLayout` exist; `key_table`, `identity`,
  `read`, `describe_axes`, `load_axes` are the surface.
- `PlotRequest` / `TraceKey` exist; `Trace` holds a request and
  `set_request` reuses the canvas artist filed under the same `TraceKey`.

## Target ownership tree

Composition, not sibling coordination. Every arrow is "owns", so the
four-signal coordination protocol has nowhere to live.

```
PlotSession                  one per display
├── RunCollection            membership + order, plain container
│   └── RunSource × N        CatalogRun + frozen synthetic keys
│       └── CatalogRun       untouched
├── Selection                session default + per-run overrides
├── ViewIntent               roles, axis order, crop, fan-out; rank-agnostic
├── TraceSet                 Trace × N
│   └── Trace                request + cached PlotBundle
├── RoiSetModel              untouched
└── RoiController            ROI preview / commit pipeline

RunListItemModel (views/)    QStandardItemModel over the session
MplCanvas (views/)           renders a TraceSet, owns axes
```

Sizes, current → target:

| Object | Now | Target | Job |
|---|---:|---:|---|
| `RunSource` | 955 | ~250 | uniform key access over real and frozen keys, plus `get_plot_bundle` |
| `PlotSession` | 1938 | ~500 | selection, visibility, view, transform, traces |
| `RoiController` | — | ~400 | ROI request building, preview, commit |
| `Trace` | 471 | ~150 | request identity plus cached bundle |
| `RunListItemModel` | 186 | ~150 | sidebar rows, now in `views/` ✅ |
| `RunCollection` | 261 | ~150 | ordered membership, combine / freeze factories |

Re-measured 2026-09-08 against the tree. `RunSource` and `Trace` had drifted
from the figures this plan was written with (792 and 496); the others were
accurate.

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

## Step D — Extract the ROI pipeline off the session

**Depends on** view-pipeline step 4, which removes the extra `get_plot_bundle`
kwargs.

`PlotSession` is 1938 lines with roughly 54 public members and 12 signals. The
four-method ROI preview/commit pipeline is the largest coherent piece.

### Do

- [ ] Extract `preview_roi_profile` (66 lines), `prepare_roi_commit` (69),
  `commit_roi_profile` (85) and `finalize_roi_commit` (66) into `RoiController`,
  owned by the session, living in `models/plot/`.
- [ ] Move region fingerprinting and `invalidate_all_region_state` with it.
- [ ] Keep thin delegating methods on the session so view call sites and the
  `test_roi_wiring` matrix rows are unchanged. If those tests need edits, the
  delegation is not thin enough.
- [ ] Break the self-signal cascade: the session connects its own
  `selected_keys_changed` to `_on_selected_keys_changed_for_region`, which
  invalidates all crop and ROI state on every key change. Make invalidation an
  explicit call from the setter.
- [ ] Collapse `set_view_crop` / `clear_view_crop` /
  `apply_view_crop_from_region`.

### Exit criteria

- [ ] `plot_session.py` under ~700 lines
- [ ] No self-signal subscriptions on the session
- [ ] `test_roi_preview_commit` and `test_roi_wiring` green **unchanged**

---

## Step E — Re-home `CombinedRunSource` and `FrozenRunSource`

**Independent.**

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

**Last.**

### Do

- [ ] `runSource.py` → `run_source.py`
- [x] ~~Delete remaining aliases: `PlotModel`, `RunModel`, `get_plot_model`~~
  — done in step A, which kept no aliases. `rg "RunModel" nbs_viewer/` was
  already empty. Nothing left here.
- [ ] Delete `RunSource.get_plot_data` (broken, no live callers). The
  `PlotDataModel.get_plot_data` half of this item did not exist by the time
  step B renamed the class
- [ ] Delete `cached_parent_bundle_for_preview` (an equality check)
- [ ] Collapse near-duplicate APIs: `add_run` / `add_runs`, `remove_run` /
  `remove_uids`, `set_run_visible` / `set_uids_visible`
- [ ] Resolve `DisplayManager` versus `AppModel` (open question 6)

### Exit criteria

- [ ] No camelCase filenames under `models/plot/`
- [x] No compatibility aliases anywhere (holds as of step A; re-check)
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
