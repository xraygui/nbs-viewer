# Mixed-rank plot view plan

Unify how 1D and N-D Y keys share a single `CubeViewSpec` on a plot:
correct defaults, safe slice projection for lower-rank fields, and graceful
suppression of incompatible traces without unchecking Run Display.

**Status:** Not started

Related:

- `[materialize_view_refactor_plan.md](materialize_view_refactor_plan.md)` —
  `MaterializeRequest` + `materialize_view` (done); this plan extends that
  pipeline for mixed-rank overlays.
- `[plot_package_reorganization.md](plot_package_reorganization.md)` — model/view
  leaks (`DimensionControl._cube_view_spec`, `PlotDataModel.set_visible`).
- `[headless_testing_plan.md](headless_testing_plan.md)` — H0/H1 test tiers;
  use `create_test_catalog()` from `testSource.py` for wiring tests.

---

## Motivation

### Observed bugs (test catalog: `x`, `y`, `image` shape `(100, 32)`)

1. **Wrong default orientation.** With Run Display X = `x`, adding `image` as a
   1D slice defaults to *slice `x` at index 0, plot `dim_1`* because
   `default_spec` always uses the trailing-axis convention. Users expect *plot
   `x`, slice `dim_1`*.

2. **0-D collapse on 1D guests.** The canvas passes the driver's
   `cube_view_spec.to_load_slice_info()` to every trace. For 1D `y`, storage
   truncates `(0, slice(None))` → `(0,)` → scalar →
   `Unsupported plot dimensionality: 0`.

3. **No semantic model for mixed overlay.** Flipping plot axis from `x` to
   `dim_1` is valid for `image` but makes `y` physically unplottable on the
   same horizontal axis. Today this either errors or fails silently.

### Design goal

| Layer | Responsibility |
|-------|----------------|
| **Run Display** | User *selection* (what keys are checked) |
| **`CubeViewSpec` on `PlotModel`** | User *view intent* for the driving (highest-rank) field |
| **`view_blocked` on `PlotDataModel`** | Per-trace *render eligibility* given current view |
| **`MplCanvas`** | Iterate plot-data models; ask `should_fetch()`; never interpret dimension names |

Selection and render eligibility must diverge without ad-hoc canvas rules.

---

## Architecture (locked)

### Driver + guests

```
visible selected Y keys
        │
        ▼
DrivingViewContext  ← highest-rank Y among selection (same rule as DimensionControl)
        │
        ├── CubeViewSpec (canonical view on PlotModel)
        │
        ▼
for each PlotDataModel (guest):
        │
        ├── view_compatible(guest, context) → reason | None
        ├── set_view_blocked(reason)
        └── if not blocked: adapt_fetch_context → load → materialize_view
```

**Driving field:** highest-rank selected Y key across visible runs (tie-break:
larger extent per axis, same as `DimensionControl.get_shape_info` today).

**Guest:** any other selected Y (or norm) trace on the same plot.

**Compatibility (v1, simple):** a guest is compatible when it can share the
driver's plot-axis coordinate:

- Resolve guest dimension names via `analyze_dimensions(ykey, xkeys)`.
- Resolve driver plot-axis name from `CubeViewSpec` + driver `dim_names`.
- **1D guest:** its sole dimension name must equal the driver's PLOT_X name.
- **Same-rank guest:** guest PLOT_X dimension name must match driver's PLOT_X
  (PLOT_Y must also match when `plot_ndim == 2`; defer if no test case yet).

When incompatible: `view_blocked = "requires 'x' as plot axis (view plots 'dim_1')"`
— checkbox stays checked; artist cleared/hidden; no worker started.

### Visibility gate (extend existing pattern)

`PlotDataModel.set_visible` already composes run visibility:

```python
visible = requested and self._run._is_visible
```

Add:

```python
visible = requested and self._run._is_visible and self._view_blocked is None
```

`MplCanvas._do_update_plot` may keep calling `set_visible(True)` for all
selected keys; blocked traces stay hidden. Add one guard before starting
`PlotWorker`:

```python
if plotDataModel.should_fetch() and needs_artist:
    self.plot_data(plotDataModel)
```

`should_fetch()` is `not view_blocked and run visible` (key selection is
already enforced by the visible_keys loop).

---

## Core APIs (`cube_view.py`)

New pure helpers (H0-testable, no Qt):

### `DrivingViewContext` (dataclass)

```python
@dataclass(frozen=True)
class DrivingViewContext:
    ykey: str
    run_uid: str
    shape: Tuple[int, ...]
    dim_names: Tuple[str, ...]
    spec: CubeViewSpec
```

Built by `PlotModel.resolve_driving_view_context()` — single implementation
of the max-rank selection loop (replaces duplicate logic in
`DimensionControl.get_shape_info`).

### `default_spec_for_selection`

```python
def default_spec_for_selection(
    ndim: int,
    plot_ndim: int,
    dim_names: Sequence[str],
    x_keys: Sequence[str],
) -> CubeViewSpec:
```

- Match `x_keys` to `dim_names` (first match wins; same semantics as
  `analyze_dimensions` motor replacement).
- **1D plot:** put matched X dimension in the plot slot (last row of
  `axis_order`); other non-trivial axes in slice slots.
- **2D plot:** put matched X dimension on PLOT_X (last row); next non-trivial
  axis on PLOT_Y.
- **Fallback:** `default_spec(ndim, plot_ndim)` when no match.

### `plot_axis_dim_name`

```python
def plot_axis_dim_name(spec: CubeViewSpec, dim_names: Sequence[str]) -> str:
```

Return the dimension name for the storage axis assigned PLOT_X (using
`spec.plot_axis_order()` and `dim_names`).

### `view_compatible`

```python
def view_compatible(
    guest_dim_names: Sequence[str],
    driver_plot_dim: str,
    *,
    plot_ndim: int = 1,
) -> Optional[str]:
```

Return `None` if compatible, else a short human-readable reason string.

### `adapt_fetch_context` (consolidation hub)

```python
def adapt_fetch_context(
    spec: CubeViewSpec,
    driver_dim_names: Sequence[str],
    guest_dim_names: Sequence[str],
    guest_shape: Sequence[int],
) -> Tuple[Optional[MaterializeRequest], Tuple, Optional[str]]:
```

Single entry for fetch-time adaptation:

| Case | Behavior |
|------|----------|
| Guest blocked | `(None, (), reason)` — caller skips load |
| Guest rank == spec rank | `(MaterializeRequest(spec), spec.to_load_slice_info(), None)` |
| Guest rank < spec rank | Project spec + slice by **name** onto guest axes; build reduced `MaterializeRequest` or slice-only path |
| Guest rank > spec rank | Block with reason (guest drives a higher-rank view; shouldn't happen if driver resolution is correct) |

**Projection rule (rank < spec):**

- For each guest dimension name, find the corresponding storage axis in the
  driver spec.
- Build guest-rank `slice_info`: INDEX roles on axes *not present* in the guest
  are dropped; for axes present in the guest, use `slice(None)` when the driver
  role is PLOT_X/PLOT_Y, else use the driver's index.
- Never apply an integer INDEX on the guest's only/plot dimension.

This replaces the scattered logic today:

```python
# runSource._fetch_plot_arrays — remove/adapt
if cube_view_spec.ndim <= y_rank:
    view_spec = cube_view_spec
    slice_info = cube_view_spec.to_load_slice_info()
# ...
elif y.size > 1 and not preserve_storage_axes:
    filtered = [(x, n) for x, n in zip(xlist, axis_names) if x.size > 1]
```

After adaptation, **always prefer `materialize_view`** when a request is
returned; the `filtered xlist` fallback becomes dead for mixed-rank cases and
can remain only for legacy `slice_info`-only callers with no spec.

### `normalize_slice_info` (relocate)

Move `frozen_spectrum._normalize_slice_info` here as a public helper.
`MemoryRun.getData` / `BlueskyRun.getData` already truncate by rank; document
that **callers with a `CubeViewSpec` must use `adapt_fetch_context` first**,
not raw truncation.

---

## Model changes

### `PlotModel`

| Method | Purpose |
|--------|---------|
| `resolve_driving_view_context()` | Max-rank Y + current `cube_view_spec` + dim names |
| `_refresh_view_compatibility()` | Fan out to all `_plot_data` entries |
| `view_block_reason(run_uid, ykey)` | Query for Run Display UI |
| `iter_plottable_plot_data()` | `iter_visible_plot_data()` with `not view_blocked` |

Call `_refresh_view_compatibility()` from:

- `set_view_state` (slice / dimension / spec change)
- `set_selected_keys` (driver may change when Y selection changes)
- `_on_visible_runs_changed` / `_ensure_plot_data_for_visible` (new plot-data)

Emit `view_compatibility_changed` after refresh (Run Display listens).

**`resolve_single_visible_2d_plot_data`:** use `iter_plottable_plot_data()` so
a blocked 2D trace is not treated as the ROI parent. Prevents ROI/crop acting
on a hidden driver.

### `PlotDataModel`

| Member | Purpose |
|--------|---------|
| `_view_blocked: Optional[str]` | Reason trace cannot render |
| `view_blocked` | Read-only property |
| `set_view_blocked(reason)` | Clear artist, gate visibility, emit `view_blocked_changed` |
| `should_fetch()` | `not view_blocked` (+ existing run visibility) |
| `sync_view_blocked(reason)` | Called from `PlotModel._refresh_view_compatibility` |

Gate `set_visible` on `_view_blocked` as described above.

When unblocked, emit `data_changed` so the canvas refetches.

### `RunModel._fetch_plot_arrays`

Refactor to:

1. Accept optional `DrivingViewContext` or `(driver_dim_names, spec)` from
   `PlotDataModel.get_plot_bundle` (plot-data knows its ykey; plot model
   supplies context).
2. Call `adapt_fetch_context` before `get_data` / `materialize_view`.
3. If blocked at fetch time (defense in depth), raise `ViewBlockedError` —
   should not happen if `should_fetch()` is respected.

**Norm keys:** apply the same adaptation per norm key rank (1D norms are guests).

---

## View changes (minimal)

### `MplCanvas`

- Guard worker start with `plotDataModel.should_fetch()`.
- No dimension-name or compatibility logic.

### `DimensionControl`

- On `create_sliders`, use `default_spec_for_selection` instead of
  `default_spec` when creating a fresh spec.
- Read driving shape/names from `plot_model.resolve_driving_view_context()`
  instead of duplicating `get_shape_info` max-rank loop (**consolidation**).
- Keep widget-local spec as edit buffer until
  `[plot_package_reorganization.md](plot_package_reorganization.md)` Step 8
  moves to model-owned spec exclusively.

### `RunDisplayWidget`

- Connect to `plot_model.view_compatibility_changed`.
- For each Y row: if `view_block_reason(uid, key)` is set, show muted style +
  tooltip; checkbox stays checked.

---

## What should use `view_blocked` / `adapt_fetch_context`

| Code path | Use view_blocked? | Notes |
|-----------|-------------------|-------|
| Main `MplCanvas` line/image plots | **Yes** | Primary target |
| Norm keys on same plot | **Yes** | Same guest rules as Y |
| `PlotModel.resolve_single_visible_2d` | **Indirect** | Skip blocked traces |
| ROI preview / commit | **No** | Always targets explicit parent 2D plot-data; parent must be plottable |
| Frozen / synthetic spectra | **No** | Own bundle + `committed_xkey`; exempt from cube spec |
| `ImageGridCanvas` | **No** | Per-cell slice; no mixed-rank overlay on one axis |
| `CombinedRunModel` / stack overlays | **Defer** | Revisit when wiring tests cover multi-run mixed rank |

---

## Consolidation and simplification opportunities

### 1. Single driving-context resolver (high value)

**Today:** `DimensionControl.get_shape_info` and (new)
`PlotModel.resolve_driving_view_context` would duplicate the same max-rank loop
over `visible_models × y_keys`.

**After:** one function on `PlotModel`; `DimensionControl` and headless tests
call it. `ImageGridCanvas._get_shape_info` stays separate (first Y only) unless
image grid later shares the plot model.

### 2. `adapt_fetch_context` replaces `y_rank` gate + raw truncation (high value)

The `cube_view_spec.ndim <= y_rank` branch in `_fetch_plot_arrays` is an
incomplete version of projection. Replacing it removes the accidental "works when
flipped, breaks when default" behavior and eliminates reliance on
`getData` truncating `slice_info[:ndim]` without semantic knowledge.

### 3. Retire the `filtered xlist` fallback for spec-backed fetches (medium value)

Once guests always go through `materialize_view` with a projected request, the
branch:

```python
elif y.size > 1 and not preserve_storage_axes:
    filtered = [(x, n) for x, n in zip(xlist, axis_names) if x.size > 1]
```

should only run when **no** `cube_view_spec` is in play (pure 1D plots).
Document and test that path explicitly; consider asserting `view_spec is None`
in that branch.

### 4. `normalize_slice_info` in `cube_view.py` (low value, easy)

`frozen_spectrum._normalize_slice_info` and the truncation in `memory.getData`
/ `bluesky.getData` share the same idea. Public `normalize_slice_info` in
`cube_view` gives one name; frozen_spectrum imports it. Do **not** change
`getData` truncation behavior in this PR — only stop relying on it for
mixed-rank plots.

### 5. `PlotDataModel.set_visible` meaning (document, defer rename)

`plot_package_reorganization.md` already notes `set_visible` mixes session
visibility with `artist.set_visible`. This plan extends session visibility with
`view_blocked` without solving the artist-on-model split. Optional follow-up:
`session_visible` vs `artist_visible`.

### 6. `DimensionControl._cube_view_spec` duplicate (defer)

Reducing to `PlotModel` as sole spec owner is orthogonal but easier once view
state changes always go through `_refresh_view_compatibility`. Not required for
the mixed-rank fix.

### 7. No new compatibility logic in `derived_fetch` / ROI

ROI paths already build explicit `MaterializeRequest` objects from a known 2D
parent. They should **not** call `view_compatible` — instead, they depend on
`resolve_single_visible_2d_plot_data` returning a **plottable** parent.

---

## Phases

### Phase 1 — Pure functions + H0 tests

- [ ] `default_spec_for_selection`
- [ ] `plot_axis_dim_name`, `view_compatible`
- [ ] `adapt_fetch_context` + `normalize_slice_info` relocate
- [ ] `tests/test_mixed_rank_view.py` using `create_test_catalog` data shapes
  (no Qt)

**Test cases:**

| Case | Expect |
|------|--------|
| Default spec with X=`x`, dims `['x','dim_1']` | plot `x`, slice `dim_1` |
| `adapt_fetch_context` for `y` + driver spec | full 1D, not scalar |
| `view_compatible(['x'], 'dim_1')` | reason string |
| `view_compatible(['x'], 'x')` | `None` |
| Flip spec: `image` still fetches; `y` blocked | via `adapt_fetch_context` |

### Phase 2 — Model wiring

- [ ] `DrivingViewContext` + `PlotModel.resolve_driving_view_context`
- [ ] `PlotModel._refresh_view_compatibility` + signal
- [ ] `PlotDataModel.set_view_blocked` / `should_fetch` / gated `set_visible`
- [ ] `RunModel._fetch_plot_arrays` uses `adapt_fetch_context`
- [ ] `PlotModel.iter_plottable_plot_data`; update `resolve_single_visible_2d`
- [ ] H1 tests: `PlotModel` + `RunModel.get_plot_bundle` without canvas

### Phase 3 — View integration

- [ ] `DimensionControl`: `default_spec_for_selection` + driving context from
  `PlotModel`
- [ ] `MplCanvas`: `should_fetch()` guard only
- [ ] `RunDisplayWidget`: blocked-row styling + tooltip
- [ ] Manual: test catalog workflow from bug report

### Phase 4 — Cleanup (optional, same or follow-up PR)

- [ ] Narrow `filtered xlist` branch to spec-free path only
- [ ] Remove dead `y_rank` branch comments
- [ ] `frozen_spectrum` imports `normalize_slice_info` from `cube_view`

---

## Connection coverage (headless)

Add to headless testing connection matrix when Phase 3 lands:

| Signal | Test |
|--------|------|
| `PlotModel.set_view_state` → `_refresh_view_compatibility` | flip spec blocks guest |
| `view_blocked_changed` → Run Display refresh | optional widget test |
| `set_selected_keys` adds lower-rank Y | guest compatible when driver plot axis matches |

---

## Open questions

1. **2D guests with mismatched PLOT_Y** — defer until a real dataset needs
   overlaying two 2D fields with different plane assignments.

2. **Status bar vs Run Display for block message** — prefer per-row tooltip in
   Run Display; optional single-line `PlotModel` status for "2 traces hidden".

3. **Combined / multi-run plots** — driver resolution across runs with
   different dimension names may need per-run contexts; v1 assumes shared dim
   names for visible runs (true for test catalog and typical scans).

4. **Auto-restore on flip back** — `set_view_blocked(None)` emits `data_changed`;
   confirm canvas refetches without requiring manual "Update Selection".

---

## Success criteria

1. Test catalog: `x` + `image` default to plot along `x`, slice `dim_1`.
2. `y` + `image` together: both plot along `x` without manual flip.
3. Flip to plot `dim_1`: `image` updates; `y` stays checked but hidden with
   explanation; no terminal error spam.
4. Flip back: `y` reappears without re-checking.
5. No compatibility rules added to `MplCanvas` beyond `should_fetch()`.
6. `adapt_fetch_context` is the only place that maps a global spec onto a
   guest's rank.
