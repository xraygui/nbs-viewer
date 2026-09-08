# PlotSession and RunListItemModel plan

Finish the step‑3 ownership merge: make `PlotModel` into a real
`PlotSession`, and shrink today's `RunListModel` into a thin Qt list
adapter that a view can attach to.

Extracted from
[`model_core_refactor_plan.md`](model_core_refactor_plan.md) step 5
(`RunListItemModel` / session‑only consumers). Complements that plan;
does **not** replace Trace (step 4), `ViewIntent` / image‑grid fan‑out,
`RoiController`, or Combined/Frozen re‑home.

## Status

- Drafted 2026-09-04.
- Parent progress: steps 0–3c done. `PlotModel` already owns
  `RunCollection`, visibility, `Selection`, transform, and the plot‑data
  map. `RunListModel` is a `QStandardItemModel` facade that **requires** a
  `PlotModel` and forwards most of the old list API. Alias
  `PlotSession = PlotModel` already exists.
- Locked: item model lives in `views/dataSource/`; does not re‑emit
  session signals.
- **P0 done 2026-09-04:** `tests/fixtures/plot_session.make_plot_session`;
  failing tests retargeted to session‑first construction; `tests/` green
  (317 passed).
- **P1 done 2026-09-04:** widgets/canvases connect to the session; list no
  longer re‑emits session signals or forwards membership/keys/combine/
  freeze/settings; `getHeaderLabel` lives on `RunDisplayWidget`;
  `presenter.session` alias added; `RunListModel` ~250 lines (cache
  aggregation retained). Next: P2 rename / move to `views/dataSource/`.

## Why this document exists

Step 3 landed ownership but left a **fat facade**. `RunListModel` still
exposes membership, visibility, keys, combine/freeze, auto‑add, and
dynamic update by forwarding to the session. Widgets and tests therefore
still treat the list as the session. That is why renaming feels scary and
why the suite broke: the public construction story changed, the mental
model did not.

Parent step 5 bundles this cleanup with Trace rendering, `ViewIntent`,
image‑grid fan‑out, and a private‑attribute sweep. Those are separate
problems. This plan is only:

1. One session object that owns session state.
2. One thin Qt item model for sidebar rows / checkboxes.
3. Consumers and tests that talk to the right object.

## Diagnosis (current tree)

```
PlotPresenter
├── PlotModel (= PlotSession alias)     owns collection, visible uids,
│                                       Selection, keys, combine/freeze,
│                                       transform, plot-data, ROI set
└── RunListModel(plot)                  QStandardItemModel rows + check
                                        sync, PLUS forwarding of nearly
                                        the entire session API, PLUS
                                        cache-status aggregation
```

Call sites still mixed:

| Need | Today often read from | Should own |
|---|---|---|
| Add / remove / combine / freeze | `run_list` | session |
| Visibility set / single‑select mode | list or session (split) | session |
| Available / synthetic keys | `run_list.available_keys` | session (`key_universe` / entries) |
| Key selection / link runs | mostly `plot_model` already | session |
| Header label text | `run_list.getHeaderLabel` | widget |
| Row index ↔ run / uid | `run_list` | item model |
| `QListView.setModel` | `run_list` | item model |
| Cache status string | `run_list.cache_status_changed` | item model or presenter (open) |

## Target architecture

```
PlotPresenter
├── PlotSession                         QObject, session root
│   └── RunCollection                   plain container
│       └── RunSource × N
└── RunListItemModel(session)           views/… QStandardItemModel
                                        rows, checks, index helpers,
                                        optional cache-status observe
```

Views attach as adapters:

| Widget | Reads |
|---|---|
| `RunListView` | item model for the view; **session** for add/remove/combine/freeze/visibility commands |
| `RunDisplayWidget` | **session only** (keys, selection, visible identities, freeze delete) |
| `DimensionControl` / canvases | **session** for `visible_models` / selection; not the item model |
| `PlotSettings` | **session** for auto‑add / dynamic update |
| `DisplayControl` | item model identity for "is this the main list"; session for visibility commands |

`RunCollection` stays internal. Widgets never get a second model object
for key/checkbox state (that is how today's split bugs start).

## Locked decisions

Confirm before coding; defaults are recommended.

1. **Class rename in place, then file move.**
   `PlotModel` → rename class to `PlotSession` with
   `PlotModel = PlotSession` until callers are updated; file rename to
   `plot_session.py` in the last phase. Same pattern as step 2/3.
   `RunListModel` → `RunListItemModel` with a temporary alias; file moves
   to `nbs_viewer/views/dataSource/run_list_item_model.py` once forwarding
   is gone.
2. **Presenter construction:** create `PlotSession` first, then
   `RunListItemModel(session)`. Session does **not** construct the item
   model (keeps models package free of depending on a views‑layer type).
   Drop `PlotModel.bind_run_list` / `run_list_model` reverse pointer once
   nothing needs it; until then keep it as a soft back‑ref for
   compatibility.
3. **Item model surface is Qt + navigation only:**
   - `QStandardItemModel` rows (display name, uid, `RunSource` payload)
   - check state ↔ `session.set_uids_visible`
   - `get_run_at_index` / `get_uid_at_index` / `find_index_by_uid` /
     `get_first_run` / `get_siblings_of_run`
   - Observe session `run_added` / `run_removed` / `visible_runs_changed`
   - **Not** forwarded: `add_run(s)`, `remove_*`, `combine_runs`,
     `freeze_runs`, `validate_combine`, `available_keys`,
     `synthetic_display_entries`, `set_auto_add`, `set_dynamic_update`,
     `getHeaderLabel`, `update_available_keys`
4. **Session is the only place for** membership, visibility,
   `is_main_display` / `single_selection_mode`, `Selection`,
   `available_keys` / future `key_universe()`, combine/freeze factories,
   transform, plot‑data map, ROI set.
5. **`presenter.session`** is the primary property. Keep
   `presenter.plot` as an alias through this plan. Keep
   `presenter.run_list` as the item model (type changes to
   `RunListItemModel`).
6. **Cache status aggregation** stays on the item model for this plan
   (it already discovers progress from member runs). Declaring a clean
   `CatalogRun` progress interface remains parent open item 5; do not
   block this plan on it.
7. **Out of scope:** `PlotDataModel` → `Trace`, `ViewIntent` push from
   dimension UI, image‑grid fan‑out / shape‑discovery merge, collapsing
   `available_keys_changed` + `frozen_spectra_changed` into one
   `keys_changed` (may stay dual signals), `RoiController`, Combined /
   Frozen catalog re‑home.
8. **Item model package path (confirmed 2026-09-04):**
   `nbs_viewer/views/dataSource/run_list_item_model.py` (next to
   `runListView.py`).
9. **Item model does not re‑emit session signals (confirmed 2026-09-04).**
   After P1, views connect to the session for keys / visibility /
   membership. The item model only drives `QAbstractItemView` rows and
   check state.

## Two ways to cut the work

### Option A — unbreak tests, then thin, then rename (preferred)

1. **P0. Test / fixture construction.** One helper builds the real pair
   in the modern order. Fix every failing test against *current* types
   (`PlotModel` + `RunListModel(plot)`). Assert session flags on
   `presenter.plot`, not the list. Green suite before further API loss.
2. **P1. Stop forwarding.** Retarget widgets and remaining tests to call
   session methods. Delete forwarded methods from the list class. Move
   `getHeaderLabel` formatting into `RunDisplayWidget` (or a tiny view
   helper).
3. **P2. Rename.** `PlotSession` / `RunListItemModel`; update imports;
   file moves; leave aliases one commit if needed, delete aliases at end.
4. **P3. Session‑only run display polish.** `key_rows` /
   `visible_identities` / drop `_synthetic_entries` if still present;
   Link Runs = `clear_overrides()` only (already largely true).

Why prefer A: the suite is already red for construction reasons. P0 is
a small, reviewable diff that restores the safety net before deleting
API.

### Option B — thin API and rename in one pass

Retarget consumers, delete forwards, rename classes/files, and fix tests
together. Fewer intermediate states; larger review; longer time with a
red suite. Reject unless P0 is somehow harder than expected (it is not).

## Consumer retarget map

| Caller | Change |
|---|---|
| `PlotPresenter` | Own `PlotSession`; expose `session` (+ `plot` alias); build item model from session |
| `DisplayManager` | `get_plot_model` → prefer `get_session`; list accessor returns item model |
| `RunListView` | `setModel(item_model)`; commands → `presenter.session` / `session.*` |
| `RunDisplayWidget` | Keys, selection, header, synthetics → session; stop using list for those |
| `DimensionControl`, `ImageGridCanvas`, plot controls `base` | `visible_models` / run signals from session (or keep listening to item model **only** for row churn if desired — prefer session signals) |
| `PlotSettings` | auto‑add / dynamic → session |
| `DisplayControl` | Compare item model identity if needed; visibility commands → session |
| `tests/fixtures/session.py` | `plot` / `session` / `run_list` properties match presenter; document modern construction |
| Unit tests that did `RunListModel(); PlotModel(run_list)` | Use helper (below) |

## Test helper (P0)

Add something like `tests/fixtures/plot_session.py` (or extend
`tests/fixtures/session.py`):

```python
def make_plot_session(
    *,
    is_main_display: bool = False,
    single_selection_mode: bool = False,
) -> tuple[PlotSession, RunListItemModel]:
    session = PlotSession(
        is_main_display=is_main_display,
        single_selection_mode=single_selection_mode,
    )
    item_model = RunListItemModel(session)
    return session, item_model
```

During P0 the names stay `PlotModel` / `RunListModel`. Tests that only
need session behavior should prefer `session = PlotModel(...)` and skip
the item model entirely when no Qt rows are required (ROI, plot‑data,
selection). Tests that need rows / checks construct both.

Failing files to retarget in P0 (inventory from 2026-09-04 suite):

- `test_plot_model.py`, `test_plot_model_step3.py`
- `test_plot_presenter.py` (assert `_single_selection_mode` on **plot**)
- `test_plot_request_wiring.py`, `test_roi_preview_commit.py`
- `test_run_list_cache_status.py`, `test_run_list_combine_freeze.py`
- `test_run_list_wiring.py` (selection via session, not `RunSource`)

After P1, combine/freeze tests should call `session.combine_runs` /
`session.freeze_runs` and only use the item model if they assert row
presence.

## `RunListItemModel` shape (end state)

```python
class RunListItemModel(QStandardItemModel):
    """Sidebar rows for one PlotSession. No session policy."""

    # Optional: re-emit or let views connect to session directly
    # Prefer views → session for data; item model for QAbstractItemView.

    def __init__(self, session: PlotSession): ...
    def get_run_at_index(self, index) -> RunSource | None: ...
    def get_uid_at_index(self, index) -> str | None: ...
    def find_index_by_uid(self, uid: str): ...
    def get_first_run(self) -> RunSource | None: ...
    def get_siblings_of_run(self, run) -> list: ...
    # check changes → session.set_uids_visible
    # session run_added/removed/visible → insert/remove/sync checks
    # cache_status_changed aggregation (temporary home)
```

Target size ~120–180 lines (today's file is ~470 with forwards).

## `PlotSession` shape (end state of this plan)

Not a full shrink to the parent "~500 lines" target — ROI and plot‑data
stay until later parent steps. For **this** plan, success is:

- Canonical name `PlotSession` (file `plot_session.py` by the end).
- No dependency on a required bound item model for session logic.
- Public API used by widgets/tests is session‑first.
- `key_universe()` may still be named `available_keys` until run_display
  P3; either is fine if there is a single owner.

## Migration order (Option A)

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **P0** | `make_plot_session` helper; fix ~34 failing tests; presenter tests assert flags on session | `pytest tests/` green |
| **P1a** | Widgets call session for membership / visibility / keys / settings; list forwards become thin wrappers or deleted | No production caller needs list forwards except `setModel` / index helpers |
| **P1b** | Delete forwards + `getHeaderLabel` from list class; header formatting in widget | List file ≤ ~200 lines; combine/freeze tests use session |
| **P2** | Rename to `PlotSession` / `RunListItemModel`; move item model under `views/`; update imports; drop aliases | Names match architecture diagram |
| **P3** | `RunDisplayWidget` session‑only polish (`key_rows` / identities; delete dead sync helpers if any remain) | Widget does not import item model for key state |

Update parent plan status when P2 completes: step 5's list‑adapter bullet
is done; remaining step 5 items stay on the parent doc.

## Explicitly not in this plan

- `Trace` / `TraceSet` / canvas render rewrite
- `DimensionControl` → `ViewIntent`
- Image grid bypass deletion / shared shape discovery
- `RoiController` extraction
- `CatalogRun` progress interface (open item 5)
- Collapsing key signals to a single `keys_changed` (optional follow‑up
  once only the session emits them)

## Risks

- **`bind_run_list` reverse pointer.** Something may still dig
  `plot.run_list_model`. Inventory before deleting; presenter already
  holds both.
- **Signal fan‑out.** Today many widgets connect to
  `run_list.available_keys_changed` etc. Either keep re‑emitting from
  the item model during P1, or retarget connections to the session in
  the same PR as the delete. Prefer retarget; re‑emit is another mirror.
- **`visible_runs` vs `visible_models`.** Session already has both; keep
  one uid accessor name (`visible_uids`) and a models list; delete the
  confusing alias pair when touching that surface.
- **Kafka / display tabs** that construct presenters or grab
  `get_run_list_model` — grep and update in P1/P2.

## Test plan

- P0 restores full `tests/` green without behavior changes.
- New or updated unit tests:
  - Construct session without item model; add run; selection / rebuild
    still work.
  - Item model row count tracks session membership; uncheck updates
    `session.visible_uids` only (plot‑data retained — existing step 3
    invariant).
  - Combine/freeze via session; item model grows a row when the session
    emits `run_added`.
  - Presenter: `session is plot` (while alias lives); 
    `single_selection_mode` on session.
- Keep green: `test_run_source.py`, `test_plot_bundle.py`,
  `test_frozen_spectrum.py`, `test_plot_session.py` (extend rather than
  fork).

## Open decisions to confirm before P1

1. ~~**Item model package path**~~ — locked: `views/dataSource/`.
2. ~~**Does the item model re‑emit session signals?**~~ — locked: no.
3. **How far into `run_display` in this plan?** Minimum for P1: stop
   reading keys from the list. Full `key_rows` /
   `_synthetic_entries` deletion can be P3 in this same document.
4. **`DisplayManager.get_run_list_model` name.** Keep the method name
   through P2 (return type changes) or rename to `get_run_list_item_model`?
   Recommendation: keep name until a dedicated display‑manager cleanup;
   document the type change.
