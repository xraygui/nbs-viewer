# Materialize-view refactor plan

Unify main plots, ROI profiles (in-plane and stack), and masked 2D crops under a single view pipeline: **`MaterializeRequest` + `materialize_view`**.

**Status:** Phase 4 complete

## Motivation

Today the stack is split:

```
load → apply_cube_view → PlotBundle          # main plot
load → apply_cube_view → apply_region_profile  # derivative profile (2D only)
```

Derivative options live in **`DerivativeSpec`** (`profile_axis`, `reduce`, …) which duplicate information that belongs in **`CubeViewSpec`**. Stack profiling (e.g. sum in ROI vs `en_energy`) has no clean path.

**Target:** one frozen request object and one materialization function. Profile axis and reduction op are encoded only in `CubeViewSpec` roles; ROI and mask mode are the only extra inputs.

## Architecture (locked)

```
storage cube (y + axis arrays + names)
        │
        ▼
MaterializeRequest(spec, region?, mask_mode)
        │
        ▼
materialize_view(...)  ──►  PlotBundle
        │
        ▼
prepare_1d_bundle / prepare_2d_bundle  (unchanged)
```

| Layer | Responsibility |
|-------|----------------|
| **`CubeViewSpec`** | Per storage axis: `INDEX`, `SUM`, `MEAN`, `PLOT_X`, `PLOT_Y`; load slices; output rank (`plot_ndim`) |
| **`MaterializeRequest`** | Frozen `spec` + optional `region` + `mask_mode` |
| **`materialize_view`** | Load spec → global reductions → mask (if region) → spatial reductions → orient → arrays |
| **`PlotViewFrame`** | Compile ROI mask on parent 2D plane; stable across profile axes |
| **`DerivedProduct`** | Persist `MaterializeRequest`, cached `PlotBundle`, `label`, provenance |

### Reduction semantics (locked)

- **No ROI-specific roles** (`ROI_SUM`, `ROI_REDUCE`, etc.).
- When `region` is provided, mask the tensor on the plot plane (`PLOT_X` × `PLOT_Y` storage axes) before any `SUM`/`MEAN` on those axes: `y_masked = np.where(mask, y, np.nan)`.
- **`SUM` / `MEAN`** always mean “collapse this axis”; sum vs mean is the role on the axis being collapsed.
- **Global** `SUM`/`MEAN` on slice-section axes run **before** ROI masking (full-axis reduction, unchanged).
- **`mask_mode`**: `inside` uses compiled mask; `outside` inverts before masking.
- **Stable geometry**: one `CompiledRegion` from parent `PlotViewFrame`, broadcast over any leading profile dimension.

### Profile axis eligibility (locked)

Eligible profile axes for the derivative dialog:

- Parent `PLOT_X` / `PLOT_Y` storage axes (in-plane profiles)
- Storage axes with role **`INDEX`** in the parent spec (stack profiles, e.g. `en_energy`)

**Excluded:** axes with role **`SUM`** or **`MEAN`** (already aggregated; nothing left to profile).

## Core types

### `MaterializeRequest` (new)

Location: `nbs_viewer/models/plot/cube_view.py` (or `materialize_view.py` if file grows large).

```python
@dataclass(frozen=True)
class MaterializeRequest:
    spec: CubeViewSpec
    region: RectRegion | None = None
    mask_mode: Literal["inside", "outside"] = "inside"
```

| Use case | `spec.plot_ndim` | `region` |
|----------|------------------|----------|
| Main plot | 1 or 2 | `None` |
| ROI 1D profile | 1 | ROI (optionally span-expanded) |
| ROI 2D masked crop | 2 | ROI |

### Types to remove

| Type | Fate |
|------|------|
| **`DerivativeSpec`** | Delete after migration |
| **`AnalysisRegion`** | Delete (only used in tests + legacy fetch API) |

### Types to update

| Type | Change |
|------|--------|
| **`DerivedProduct`** | `spec: DerivativeSpec` → `request: MaterializeRequest`; keep `label`, `bundle`, `source_key`, `cube_fingerprint` |
| **`CubeViewSpec`** | Extend load + validation for profile-output specs (see below) |

## `CubeViewSpec` extensions

### Output specs for profiles

Built from parent spec via **`profile_view_spec()`** (pure helper, not stored separately):

```python
def profile_view_spec(
    parent: CubeViewSpec,
    profile_storage_axis: int,
    spatial_reduce: Literal["sum", "mean"],
) -> CubeViewSpec:
    ...
```

**In-plane profile** (profile axis = parent plot X storage axis):

- Profile axis: remains output axis (`PLOT_X`, `plot_ndim=1`)
- Orthogonal plot axis: `SUM` or `MEAN` (from dialog “Reduce”)
- Other roles: unchanged from parent

**Stack profile** (profile axis = INDEX storage axis, e.g. `en_energy`):

- Profile axis: no longer fixed index; load full axis; assign `PLOT_X`, `plot_ndim=1`
- Both parent plot axes: `SUM` or `MEAN`
- Other `INDEX` axes: unchanged (fixed at current slider index)
- Parent `SUM`/`MEAN` axes: unchanged

### `to_load_slice_info()` change

Today: `INDEX` → integer index; everything else → `slice(None)`.

For **profile-output specs** (`plot_ndim=1` and the sole `PLOT_X` axis was `INDEX` in parent): that axis must load **`slice(None)`** even though it is not “indexed” in the output spec.

Implementation: the output spec’s `PLOT_X` axis always loads full extent. Only axes with role **`INDEX`** use `indices[i]`.

### Validation helpers (new)

```python
def eligible_profile_axes(spec: CubeViewSpec) -> list[int]:
    """Storage axis indices valid as profile axis choices."""

def profile_axis_name(spec: CubeViewSpec, storage_axis: int, axis_names: Sequence[str]) -> str:
    """Display name for dialog dropdown."""

def default_profile_label(request: MaterializeRequest, axis_names: Sequence[str]) -> str:
    """Legend label from spec roles + mask_mode (replaces DerivativeSpec.default_label)."""
```

### Plane (2D crop) spec

Masked 2D crop is also a `MaterializeRequest`:

- `plot_ndim=2`, parent plot roles unchanged
- `region` set; `materialize_view` crops to bbox and applies mask (logic migrated from `fetch_derived_plane_bundle`)
- No spatial `SUM`/`MEAN`; mask only affects displayed values

Distinguish plane vs profile in UI via `plot_ndim` and whether spatial axes are collapsed, not a separate `output_kind` enum on a second spec type.

## `materialize_view` pipeline

Location: `nbs_viewer/models/plot/cube_view.py` initially; extract if needed.

```python
def materialize_view(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    axis_names: Sequence[str],
    request: MaterializeRequest,
    *,
    region_frame: PlotViewFrame | None = None,
) -> tuple[np.ndarray, list[np.ndarray], list[str]]:
```

**Stages** (single function; order matters):

1. **Assert** `y.ndim == request.spec.ndim` after load (same as today).
2. **Global reductions**: `SUM`/`MEAN` on non-plot, non-index-collapsed axes (reverse axis order, same as `apply_cube_view`).
3. **INDEX selections**: axes still marked `INDEX` → take `indices[i]`, drop axis (coordinate array likewise).
4. **ROI mask** (if `request.region` and `region_frame`):
   - Compile region on `region_frame`; invert if `mask_mode == "outside"`.
   - Identify plot-plane axis indices in current tensor (parent `PLOT_Y` / `PLOT_X` storage axes).
   - Apply mask; broadcast over any leading dimensions (profile axis).
5. **Spatial reductions**: `SUM`/`MEAN` on axes so marked (`np.nansum` / `np.nanmean`).
6. **Transpose/orient** for `plot_ndim` (reuse existing perm logic from `apply_cube_view`).
7. **Return** `(y, axis_arrays, axis_names)` for `prepare_*_bundle`.

**`apply_cube_view`** becomes a thin wrapper:

```python
def apply_cube_view(y, axis_arrays, axis_names, spec):
    return materialize_view(y, axis_arrays, axis_names, MaterializeRequest(spec))
```

### Plane branch

After stage 4 (mask), if `plot_ndim==2` and no spatial SUM/MEAN:

- Crop to mask bbox (existing `_plane_bundle_from_mesh_crop` logic)
- Return 2D arrays + mesh/image coords

Consider a post-step in `derived_fetch` / `runSource` wrapper rather than bloating core loop — but still driven by `MaterializeRequest`.

## Fetch / run integration

### New entry point

```python
def fetch_materialized_bundle(
    run_model,
    xkeys,
    ykey,
    norm_keys,
    request: MaterializeRequest,
    *,
    region_frame: PlotViewFrame | None = None,
    transform=True,
) -> PlotBundle:
```

Flow:

1. `slice_info = request.spec.to_load_slice_info()`
2. `_fetch_plot_arrays(..., cube_view_spec=None)` with that slice **or** pass arrays + call `materialize_view` only on y (norm must follow same path as today).
3. Prefer: load raw with slice_info derived from spec, then `materialize_view` on y and norm consistently.

**Refactor `RunModel.get_plot_bundle`:**

```python
if cube_view_spec is not None:
    request = MaterializeRequest(cube_view_spec)
    # ... load + materialize_view ...
```

Keep public `cube_view_spec=` parameter for callers; construct `MaterializeRequest` internally.

### Replace `derived_fetch.py`

| Old | New |
|-----|-----|
| `fetch_derived_profile_bundle` | `fetch_materialized_bundle(..., request)` |
| `fetch_derived_plane_bundle` | same |
| `fetch_derivative_preview_bundle` | build `MaterializeRequest` in controller, call fetch |
| `region_for_derivative_fetch` | `resolve_profile_region(parent_frame, roi, profile_storage_axis, span_full)` — pure geometry, used when **building** request |

Delete **`apply_region_profile`** from `region_reduce.py` once tests pass through `materialize_view`. Keep **`reduce_masked_plane`** if still useful for tests or inline clarity.

## UI layer

### `DerivativePlotDialog`

| Control | Maps to |
|---------|---------|
| Profile axis dropdown | `profile_storage_axis` → `profile_view_spec(parent, …)` |
| Reduce Sum/Mean | `spatial_reduce` in `profile_view_spec` |
| Inside/Outside ROI | `request.mask_mode` |
| Span full profile axis | expand ROI before `request.region` (in-plane only) |
| 1D profile / 2D plane | `plot_ndim` 1 vs 2 in output spec |
| Label | `DerivedProduct.label` only |

Dialog emits **`MaterializeRequest`** (or emits fields; controller builds request). Remove `get_spec() -> DerivativeSpec`.

### `DerivativeController`

- Hold parent `CubeViewSpec` from `dimension_control`.
- On context update: `eligible_profile_axes(parent_spec)` → populate dropdown.
- Preview worker takes `MaterializeRequest` + `region_frame` from parent bundle.
- On commit: `DerivedProduct(request=..., label=..., bundle=..., ...)`.
- Remove references to `spec.profile_axis`, `spec.reduce`, etc.

### Signals

- `DerivativePlotDialog.spec_changed` → rename to `request_changed` emitting `MaterializeRequest`.

## Files touched

### New / heavily modified

| File | Work |
|------|------|
| `models/plot/cube_view.py` | `MaterializeRequest`, `materialize_view`, `profile_view_spec`, helpers; refactor `apply_cube_view` |
| `models/plot/derived_fetch.py` | Slim to `fetch_materialized_bundle`, region resolve helper |
| `models/plot/derived_product.py` | `request: MaterializeRequest` |
| `models/plot/runSource.py` | Route through `materialize_view` |
| `views/plot/derivative_plot_dialog.py` | Build `MaterializeRequest` |
| `views/plot/derivative_controller.py` | Wire request + eligible axes |
| `views/plot/derivative_preview_canvas.py` | Worker accepts `MaterializeRequest` |

### Delete

| File | When |
|------|------|
| `models/plot/derivative_spec.py` | Phase 3 |
| `models/plot/analysis_region.py` | Phase 3 |

### Deprecate / shrink

| File | Work |
|------|------|
| `models/plot/region_reduce.py` | Remove `apply_region_profile`; keep `reduce_masked_plane` if needed |
| `planDocuments/roi_analysis_plan.md` | Cross-link this plan; mark Phase 4 absorbed |

## Tests

### Phase 1 — `materialize_view` core (`tests/test_materialize_view.py`)

- [ ] `apply_cube_view` parity: all existing `tests/test_cube_view.py` cases pass via wrapper
- [ ] In-plane profile (image): sum/mean along plot Y, profile along plot X
- [ ] In-plane profile (mesh): non-uniform axes (TES-like fixture)
- [ ] Stack profile: 4D synthetic — INDEX + SUM + 2D plot; profile INDEX axis; ROI on plot plane
- [ ] Outside ROI mask_mode
- [ ] Empty ROI column → NaN profile point
- [ ] `eligible_profile_axes` excludes SUM/MEAN axes
- [ ] `profile_view_spec` role assignment for in-plane and stack cases
- [ ] `to_load_slice_info` loads full profile axis

### Phase 2 — fetch integration (`tests/test_derived_fetch.py` rewrite)

- [ ] Port mesh profile/plane tests to `MaterializeRequest`
- [ ] Stack profile end-to-end through `fetch_materialized_bundle`
- [ ] Span-full region expansion before request freeze

### Phase 3 — regression

- [ ] `tests/test_region_mesh.py` — update or remove direct `apply_region_profile` usage
- [ ] Existing `test_region.py` unchanged

## Implementation phases

### Phase 0 — Foundation (no UI changes)

**Goal:** `materialize_view` exists; main plot behavior unchanged.

1. Add `MaterializeRequest` dataclass.
2. Implement `materialize_view` with `region=None` path by extracting logic from `apply_cube_view`.
3. Make `apply_cube_view` delegate to `materialize_view`.
4. Run `tests/test_cube_view.py` — must pass unchanged.
5. Add `tests/test_materialize_view.py` for ROI-free cases.

**Acceptance:** zero behavior change for main plot; all cube_view tests green.

### Phase 1 — ROI profile via view spec (backend only)

**Goal:** in-plane ROI profiles work through `MaterializeRequest`; no stack axis yet.

1. Add `profile_view_spec()` for in-plane case only.
2. Implement ROI mask + spatial SUM/MEAN in `materialize_view`.
3. Add `fetch_materialized_bundle()`.
4. Port in-plane cases in `test_materialize_view.py` and `test_derived_fetch.py`.
5. Keep old `fetch_derived_profile_bundle` as thin wrapper delegating to new path (temporary).

**Acceptance:** in-plane profile numerically matches current `apply_region_profile` on test fixtures.

### Phase 2 — Stack profile + spec helpers

**Goal:** profile along INDEX axes (e.g. `en_energy`).

1. Extend `profile_view_spec()` for stack axes.
2. Extend `to_load_slice_info()` for profile-output specs.
3. Add `eligible_profile_axes()` and tests for 4D stack profile.
4. Add `resolve_profile_region()` (migrate `region_for_derivative_fetch` + span full).

**Acceptance:** stack profile tests pass; eligible axis rules enforced.

### Phase 3 — UI migration

**Goal:** dialog and controller use `MaterializeRequest`; stack axis in dropdown.

1. Update `DerivativePlotDialog` to build and emit `MaterializeRequest`.
2. Update `DerivativeController` and preview worker.
3. Update `DerivedProduct` storage.
4. Delete `DerivativeSpec`, `AnalysisRegion`.
5. Remove temporary wrappers and `apply_region_profile`.

**Acceptance:** manual GUI — in-plane and stack profiles preview, create, pin; labels correct.

### Phase 4 — Plane output + cleanup

**Goal:** 2D masked crop through same pipeline; dead code removed.

1. Plane `MaterializeRequest` specs through `materialize_view` / fetch.
2. Remove `fetch_derived_plane_bundle` duplication.
3. Update `roi_analysis_plan.md` Phase 4 status.
4. Optional: `RunModel.get_plot_bundle` accepts `MaterializeRequest` directly.

**Acceptance:** plane preview/commit works; `derived_fetch.py` minimal.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Axis order bugs in N-D mask + reduce | Explicit storage-axis tracking through stages; 4D test with permuted `axis_order` |
| Performance on long energy axis | Correctness first; later bbox-limited reads (Phase 5 in roi plan) |
| `region_frame` missing at fetch time | Require parent bundle / frame for any request with `region`; clear error in preview |
| Normalization path divergence | Run norm arrays through same `materialize_view` stages as y |
| Breaking pinned products | `DerivedProduct` schema change — no migration needed if feature is pre-release |

## Out of scope (this refactor)

- L2 Zarr cache (`zarr_l2_cache_plan.md`) — orthogonal; benefits automatically once load uses spec.
- Multi-ROI, lasso (Phase 3 roi plan).
- Threshold / segmentation regions.
- Session persistence format for pinned curves.

## Open questions (resolve in Phase 0)

1. **File split:** keep `MaterializeRequest` in `cube_view.py` vs new `materialize_view.py` — decide when file exceeds ~500 lines.
2. **Plane in core loop vs post-process:** start with post-process in fetch layer; fold in if duplication is painful.
3. **`plot_ndim=1` validation:** relax `resolve_roles` so output spec does not require trailing plot rows from parent when building profile spec programmatically.

## Checklist summary

- [x] Phase 0: `MaterializeRequest` + `materialize_view` (no ROI)
- [x] Phase 1: in-plane ROI profiles
- [x] Phase 2: stack profiles + helpers
- [x] Phase 3: UI + delete `DerivativeSpec`
- [x] Phase 4: plane output + cleanup
- [x] Update `roi_analysis_plan.md` cross-references
