# Session and traces plan

Who owns what. Sub-plan of [`refactor_plan.md`](refactor_plan.md); the other
half is [`view_pipeline_plan.md`](view_pipeline_plan.md), which owns how a
request becomes a bundle.

**Status:** steps A–F not started. Everything this plan's predecessors marked
done is verified against the tree below.

**Replaces** `model_core_refactor_plan.md` (steps 4–8) and
`plot_session_list_adapter_plan.md` (P2–P3), both deleted 2026-09-08 and
recoverable from `57f6d7b`.

## Already landed

Verified in the tree, not taken on trust from the deleted documents:

- `PlotSession = PlotModel` alias exists (`plotModel.py:1947`).
- `PlotModel` owns `RunCollection`, visibility, `Selection`, transform, the
  plot-data map and the ROI set.
- `RunListModel` is a thin Qt facade — 187 lines, no forwarding, no cache
  aggregation (that moved to the session).
- `RunSource` no longer holds selection, visibility or transform.
- `KeyInfo` / `RunIdentity` / `AxisLayout` exist; `key_table`, `identity`,
  `read`, `describe_axes`, `load_axes` are the surface.
- `PlotRequest` / `TraceKey` exist; `PlotDataModel` holds a request and
  `set_request` reuses the artist.

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
| `RunSource` | 792 | ~250 | uniform key access over real and frozen keys, plus `get_plot_bundle` |
| `PlotSession` | 1947 | ~500 | selection, visibility, view, transform, traces |
| `RoiController` | — | ~400 | ROI request building, preview, commit |
| `Trace` | 496 | ~150 | request identity plus cached bundle |
| `RunListItemModel` | 187 | ~150 | sidebar rows, moved to `views/` |
| `RunCollection` | 261 | ~150 | ordered membership, combine / freeze factories |

---

## Step A — `PlotSession` / `RunListItemModel` rename and move

**Independent.** Can land any time. Pure rename plus one file move.

### Do

- [ ] Rename the class `PlotModel` → `PlotSession`; keep
  `PlotModel = PlotSession` for one commit, then delete the alias.
- [ ] Rename the file `plotModel.py` → `plot_session.py`.
- [ ] Rename `RunListModel` → `RunListItemModel`; move to
  `nbs_viewer/views/dataSource/run_list_item_model.py`, next to
  `runListView.py`.
- [ ] `PlotPresenter` constructs the session first, then the item model.
  Drop `PlotSession.bind_run_list` and the `run_list_model` reverse pointer.
- [ ] `DisplayManager.get_plot_model` → `get_session`; keep `get_plot_model`
  as an alias for one commit.
- [ ] Drop `presenter.plot`; `presenter.session` is the only name.

### Deletes

`bind_run_list`, `run_list_model`, `presenter.plot`, `PlotModel` and
`RunListModel` as names, `plotModel.py` and `runListModel.py` as paths.

### Exit criteria

- [ ] `rg "PlotModel|RunListModel" nbs_viewer/ tests/` returns nothing
- [ ] The item model lives under `views/`, so `models/` no longer holds a
  `QStandardItemModel`
- [ ] `pytest tests/` green

### Non-goals

Not `Trace`. Not `ViewIntent`. Not the ROI extraction.

---

## Step B — `Trace`

**Depends on** view-pipeline step 4, so the request shape is settled first.

`PlotDataModel` becomes `Trace`: request identity plus a cached bundle. The
matplotlib artist moves to a view-side map keyed by `TraceKey`, which clears
the last ownership-guard violation and unblocks a headless plot frontend.

### Do

- [ ] Introduce `TraceSet` on the session, holding `Trace` keyed by `TraceKey`.
- [ ] `Trace` holds `request`, `last_bundle`, `trace_key`, visibility intent.
  No matplotlib import.
- [ ] Move `set_artist`, `remove_artist_from_axes`, `add_artist_to_axes`,
  `move_artist_to_axes` and the artist half of `clear()` to a canvas-side
  artist map.
- [ ] `Trace.set_visible(bool)` records session intent and emits; the canvas
  reacts by setting artist visibility.
- [ ] Delete the six underscore-named compatibility properties on
  `PlotDataModel` (`_key`, `_xkey`, `_ykey`, `_norm_keys`, `_indices`,
  `_cube_view_spec`) and fix the six view call sites that read them.

### Rebuild by diff

The trace set is a pure function of session state. Retention and drawing are
different questions:

```
retained = { build_request(uid, x, y, view)
             for uid in member_uids            # membership, not visibility
             for (x, y) in selection_for(uid)
             for view in intent.fan_out() }

drawn    = { t for t in retained if t.uid in visible_uids }
```

`rebuild()` diffs `retained` against the live set. Hide/show changes only
`drawn`, so `last_bundle` and the artist survive as the first cache layer.
Dispose happens when a run leaves membership or a key leaves selection.

### Deletes

`PlotDataModel` as a name; the artist API on it; the compatibility properties;
`from matplotlib.image import AxesImage` from `models/`.

### Exit criteria

- [ ] `rg "matplotlib" nbs_viewer/models/` returns only `region_mesh.py`
- [ ] `EXPECTED_VIOLATIONS` in the ownership guard is empty
- [ ] A full `ensure_trace` → `get_plot_bundle` → `set_visible` cycle runs in
  a test with no canvas and no matplotlib import
- [ ] Hide, then show, does not refetch

### Open before coding

Live data: a bundle cache must invalidate on `data_changed`. Specify the rule.

---

## Step C — Consumer sweep

**Depends on** step B and view-pipeline step 6.

### Do

- [ ] `MplCanvas` renders a `TraceSet` — iterate traces, map trace → artist.
  It stops computing the x × y × run cartesian product
  (`single_canvas.py:584-607`).
- [ ] `DimensionControl` builds and pushes a `ViewIntent` instead of owning
  and mutating a spec. `_default_xkey` becomes `intent.axis_order == ()`.
- [ ] Delete the `ImageGridCanvas` bypass: it constructs `PlotDataModel`
  directly (`image_grid_canvas.py:393-401`) and keeps a private
  `(uid, image_idx)` map. Both collapse into `intent.fan_out()`, which makes
  each grid cell an ordinary trace.
- [ ] Delete the duplicated shape discovery in `ImageGridCanvas._get_shape_info`.
- [ ] Move the remaining domain policy out of views: `run_display.py:191-193`
  sorting `"time"` to the front, the 2-D multi-dataset `QMessageBox` rule
  (`single_canvas.py:422-437`), `_make_slice_info`.

### Closes

Mixed-rank bugs 2 and 3 from the view pipeline plan: the canvas stops passing
the driving key's slice tuple to every trace, so a 1-D guest no longer
collapses to 0-D, and `plot_axis_names` decides overlay compatibility.

### Exit criteria

- [ ] No `plot_data._`-prefixed access under `views/`
- [ ] `ImageGridCanvas` constructs no models
- [ ] A 1-D key and a 1-D projection of a 3-D key plot together
- [ ] `codebase_problem_statement.md` item 7 can be struck

---

## Step D — Extract the ROI pipeline off the session

**Depends on** view-pipeline step 4, which removes the extra `get_plot_bundle`
kwargs.

`PlotSession` is 1947 lines with roughly 54 public members and 12 signals. The
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
- [ ] Delete remaining aliases: `PlotModel`, `RunModel`, `get_plot_model`
- [ ] Delete `RunSource.get_plot_data` (broken, no live callers) and
  `PlotDataModel.get_plot_data`
- [ ] Delete `cached_parent_bundle_for_preview` (an equality check)
- [ ] Collapse near-duplicate APIs: `add_run` / `add_runs`, `remove_run` /
  `remove_uids`, `set_run_visible` / `set_uids_visible`
- [ ] Resolve `DisplayManager` versus `AppModel` (open question 6)

### Exit criteria

- [ ] No camelCase filenames under `models/plot/`
- [ ] No compatibility aliases anywhere
- [ ] Record final file and line counts against the targets above

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-08 | Written from the live parts of `model_core_refactor_plan.md` and `plot_session_list_adapter_plan.md`. Claimed-done items re-verified against the tree; sizes re-measured. |
