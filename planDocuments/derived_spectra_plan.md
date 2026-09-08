# Derived spectra — frozen synthetic keys on RunModel

Plan for saving, displaying, and plotting ROI-derived 1D spectra as first-class run keys.

**Supersedes** the data-management and commit sections of [`roi_analysis_plan.md`](roi_analysis_plan.md) Phase 2. ROI drawing, the derivative dialog, preview, and the materialize pipeline are **done** — see that document and [`materialize_view_refactor_plan.md`](materialize_view_refactor_plan.md) for completed foundation work.

## Motivation

The derivative plot dialog can preview 1D profiles and 2D planes from a drawn ROI, but **Create** and **Pin for comparison** do not integrate with Run Display or the normal plot pipeline. Users need to:

1. **Reduce away** internal image axes and save a 1D spectrum along an external (INDEX) axis — e.g. mean intensity in an ROI vs `en_energy` — for comparison with other 1D detectors **or use as a norm** (dark-field on a CCD).
2. **Save in-plane profiles** (along `plot_x` / `plot_y`) for comparison across ROIs or runs on the same detector — these are **not** comparable to catalog scan variables.

Saving must not disturb the current view: the main plot stays the original 2D image, checkboxes are unchanged, and the user can define and save multiple ROIs in one session.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Storage | Register frozen spectra as **synthetic keys on `RunModel`** (not a parallel overlay registry) |
| Immutability | Once saved, spectra are **totally frozen** — no Tiled re-fetch, no re-materialization on slice/view change |
| Save side effects | **No checkbox changes** on save; 2D parent plot and Run Display selection stay as-is |
| Run Display layout | Catalog keys above a **separator line**; synthetic spectra below |
| Synthetic key columns | Full **X / Y / Norm** checkboxes (norm is a primary use case) |
| Stack profiles (scan storage axis) | Appear in Run Display; scan axis may be INDEX **or** plot X/Y (mesh) |
| Local profiles (non-scan axes) | **Not** in Run Display; separate **ROI Profiles** panel (later phase) |
| Stack span | **Full scan axis** on save; ROI limits only orthogonal dimensions |
| Dialog commit | Single **Save** button; remove **Create** / **Pin** |
| X on synthetic rows | v1: synthetic keys are **Y and Norm only**; X stays catalog |
| Overlay path | Retire `DerivedPlotDataModel`, `canvas.derived_models`, `DerivedSeriesRegistry` on controller |
| Classification | Leading non-reduced **storage index** (see below); not UI `axis_order` |
| Dimension Control labels | Must match `PlotViewFrame` / rendered plot (known bug; Phase 1 fix) |

## Background (already implemented)

| Component | Status |
|-----------|--------|
| `RectRegion`, ROI draw/control, invalidation | Done |
| `MaterializeRequest`, `materialize_view`, `derived_fetch` | Done |
| `DerivativePlotDialog` + live debounced preview | Done |
| `DerivedProduct`, `DerivedPlotDataModel`, `DerivedSeriesRegistry` | Stub — to be replaced / removed |

## Architecture

```
DerivativePlotDialog
        │  Save (one-shot fetch)
        ▼
FrozenSpectrum  ──register──►  RunModel._frozen_spectra[key]
        │                              │
        │                              ├── available_keys (catalog + synthetic)
        │                              ├── get_plot_bundle (intercept synthetic Y)
        │                              └── _fetch_plot_arrays (intercept synthetic norm)
        ▼
RunDisplayWidget  ──separator──►  synthetic rows (toggle / delete)
        ▼
PlotDataModel  ──►  MplCanvas  (normal 1D line path)
```

### Why `RunModel` (not a side registry)

Synthetic keys participate in the same pipeline as catalog keys:

- Y / Norm checkboxes and selection state
- Norm division via `np.prod` of norm arrays (including mixed catalog + synthetic norms)
- User transform expression on Y
- Per-run visibility
- No duplicate overlay logic on `MplCanvas`

### Profile kinds and classification

Not every INDEX axis is a scan axis. Classification uses **underlying storage axis index** (`0 … ndim-1`), not UI row order in `CubeViewSpec.axis_order`.

#### Example A — 4D CCD `(en_energy, dim_0, dim_1, dim_2)`

| Storage axis | Role in 2D view | Meaning |
|--------------|-----------------|---------|
| 0 — `en_energy` | INDEX (slider) | Scan / external axis |
| 1 — `dim_0` | INDEX (slider) | Exposure counter (internal) |
| 2, 3 — `dim_1`, `dim_2` | PLOT_Y, PLOT_X | Image plane |

#### Example B — 2D mesh `(en_energy, tes_mca_energies)`

| Storage axis | `CubeViewSpec` role | On-screen |
|--------------|---------------------|-----------|
| 0 — `en_energy` | PLOT_Y or PLOT_X | Horizontal axis (Plot X) on mesh |
| 1 — `tes_mca_energies` | other plot axis | Vertical axis (Plot Y) |

Here the scan axis is still **storage axis 0** even though it is a **plot axis**, not an INDEX slider. Profiling along `en_energy` is a `stack_spectrum`; profiling along `tes_mca_energies` is `local_profile`.

#### `scan_profile_storage_axis(parent_spec)`

Return the **minimum storage index** among axes that are not globally reduced (`SUM` / `MEAN`). This is the leading scan axis in tensor order.

```python
def scan_profile_storage_axis(parent_spec: CubeViewSpec) -> int | None:
    candidates = [
        sa for sa in range(parent_spec.ndim)
        if parent_spec.roles[sa] not in (DimRole.SUM, DimRole.MEAN)
    ]
    return min(candidates) if candidates else None


def classify_profile_kind(
    parent_spec: CubeViewSpec, profile_storage_axis: int
) -> Literal["stack_spectrum", "local_profile"]:
    if profile_storage_axis == scan_profile_storage_axis(parent_spec):
        return "stack_spectrum"
    return "local_profile"
```

Do **not** use `is_plot_plane_storage_axis` for Run Display routing. The scan axis may lie on the plot plane (mesh case).

Location: `nbs_viewer/models/plot/cube_view.py` (alongside `is_plot_plane_storage_axis`).

#### Kind summary

| Kind | Profile axis | Example | Run Display | Typical use |
|------|--------------|---------|-------------|-------------|
| `stack_spectrum` | Scan storage axis only (index 0 in typical layouts) | mean in ROI vs `en_energy` on mesh or stack | Yes (below line) | Compare to detectors; **norm** (dark field) |
| `local_profile` | Any other axis | vs `tes_mca_energies`; vs `dim_0`; vs `dim_2` | No (ROI Profiles panel) | Line cuts; exposure-axis profiles |

**Dialog preview** may still offer all `eligible_profile_axes`. **Save routing** uses `classify_profile_kind`. Phase 1 implements `stack_spectrum` only; `local_profile` save is Phase 2.

### Full span along the scan (profile) axis

A stack spectrum must include **every bin along the scan axis**, not only the ROI extent on that axis. The orthogonal plot dimension(s) stay constrained by the drawn ROI (e.g. a horizontal band selecting a `tes_mca_energies` range).

`expand_rect_for_profile` already implements this for in-plane profile axes: profiling along plot X expands the ROI to the full plot X data limits while keeping plot Y limits from the drawn band (and vice versa). See `region.py` docstring (en_energy on horizontal axis case).

| Scan axis role | Span behaviour on save |
|----------------|------------------------|
| INDEX (off plot plane, e.g. 4D `en_energy`) | Full axis loaded from storage; ROI does not narrow that dimension in `slice_info` |
| PLOT_X / PLOT_Y (on plot plane, e.g. 2D mesh `en_energy`) | **Mandatory** `span_full=True` in `resolve_profile_region` when profiling along the scan axis |

For `stack_spectrum` commit, **always** apply span expansion when the scan axis is on the plot plane. Do not rely on the dialog checkbox alone — force `span_full_profile_axis=True` for stack saves. Use `PlotViewFrame` (`storage_axis_to_plot_axis`) for expansion geometry, not `CubeViewSpec` row labels.

The dialog “Span full profile axis” checkbox remains useful for **local** in-plane preview; stack-spectrum Save overrides to full span regardless of checkbox state.

### Dimension Control plot-axis labels (bug fix)

ROI and derivative code use `PlotViewFrame` from the rendered bundle (mesh transpose, `plot_x_dim` inference). Dimension Control currently assigns **Plot Y** then **Plot X** by row offset in `axis_order`, which can disagree with the actual plot — e.g. `tes_mca_spectrum` mesh shows `en_energy` on the horizontal axis but Dimension Control labels `en_energy` as Plot Y.

**Phase 1 prerequisite:** label plot-axis rows from the live `PlotViewFrame` (or bundle), mapping each `storage_axis` to Plot X / Plot Y via `frame.plot_x_dim` / `frame.plot_y_dim`, not blind row order.

This fix is required for trustworthy profile-axis dropdown labels and ROI span buttons (`Set ROI: full width/height`).

## Core types

### `FrozenSpectrum`

Location: `nbs_viewer/models/plot/frozen_spectrum.py` (new).

```python
@dataclass(frozen=True)
class FrozenSpectrum:
    key: str                    # internal: "__roi__/<uuid>"
    label: str                  # display: "mean(in ROI) · en_energy"
    bundle: PlotBundle          # 1D line; arrays deep-copied at registration
    kind: Literal["stack_spectrum", "local_profile"]
    source_ykey: str            # parent detector catalog key
    committed_xkey: str         # X key selected at save time
    request: MaterializeRequest # provenance; not used for re-fetch
    source_key: tuple           # (xkey, ykey, run_uid) of parent 2D trace
    cube_fingerprint: tuple | None
```

Internal key prefix `__roi__/` distinguishes synthetic keys from catalog streams and prevents accidental `getData` calls.

### `RunModel` extensions

```python
def register_frozen_spectrum(self, entry: FrozenSpectrum) -> str: ...
def remove_frozen_spectrum(self, key: str) -> bool: ...
def frozen_spectra(self) -> list[FrozenSpectrum]: ...
def is_synthetic_key(self, key: str) -> bool: ...
```

**`available_keys`:** `catalog_keys + [s.key for s in frozen_spectra]` (order: catalog unchanged, synthetic appended). Catalog refresh via `_update_available_keys` must **preserve** synthetic entries.

**`set_selected_keys`:** Synthetic keys pass the existing `key in available_keys` filter like catalog keys.

## Fetch interception

All Tiled access for synthetic keys is forbidden after registration.

### Synthetic as Y (`get_plot_bundle` / `_fetch_plot_arrays`)

When `ykey` is synthetic:

1. Load `FrozenSpectrum` by key.
2. Extract frozen `xlist` and `y` from `bundle` (ignore `slice_info`, `cube_view_spec`, `materialize_request`).
3. Apply **norm keys** (catalog or synthetic) via existing norm division path.
4. Apply **user transform** via `transform_data`.
5. Return `prepare_1d_bundle(...)`.

`PlotDataModel` may still receive slice/cube-view updates; synthetic Y must return identical data every time.

### Synthetic as Norm

When any `norm_key` is synthetic:

1. Use frozen `bundle.y` from that entry.
2. Do **not** call `getData` or `materialize_view` for that key.
3. Combine with other norms via `np.prod` as today.

Catalog Y traces continue to refetch on slice change; frozen norm stays fixed. Shape mismatch after a slice change is acceptable for v1 (frozen semantics); optional later: warn when `norm.shape` incompatible with `y.shape`.

### Synthetic as X

**Not supported in v1.** Run Display X column disabled or hidden on synthetic rows.

## Save flow

### Dialog

Replace **Create** / **Pin** with a single **Save** button.

1. Run the same fetch as preview (worker thread).
2. Classify profile kind via `classify_profile_kind` (storage-axis scan rule).
3. If `local_profile` and Phase 2 not implemented: show status (e.g. "Save to ROI Profiles not available yet") and return without registering.
4. Build `FrozenSpectrum` with deep-copied bundle arrays.
5. `run_model.register_frozen_spectrum(entry)` on the parent 2D trace's run.
6. Emit `available_keys_changed`.
7. Show status: `Saved: <label>`.
8. **Do not** change Run Display checkboxes, plot dimension, or canvas mode.

User remains on the 2D parent plot and can adjust the ROI and save again.

### Delete

Synthetic rows in Run Display include a delete control:

1. `run_model.remove_frozen_spectrum(key)`
2. Remove key from current selection if checked
3. Drop any `PlotDataModel` / artist for that key
4. Refresh Run Display grid

## Run Display UI

### Layout

`RunDisplayWidget._update_display` builds two sections:

```
[Catalog keys — existing grid, unchanged]
─────────────────────────────────────────
[Synthetic keys — same X / Y / Norm columns + delete]
```

Synthetic row label column shows `FrozenSpectrum.label` (not the internal key).

### Key list sources

| Mode | Catalog keys | Synthetic keys |
|------|--------------|----------------|
| Linked | Intersection across visible runs (unchanged) | Per-run entries; prefix with `scan_id ·` when multiple runs visible |
| Unlinked | Current run catalog keys | Current run synthetic keys only |

Synthetic keys are **excluded** from the catalog intersection logic in `RunListModel.update_available_keys`. A dedicated query aggregates synthetic keys from visible runs for display.

### Linked runs (v1)

- Synthetic keys are run-specific (unique `__roi__/<uuid>` per save).
- Checking a synthetic norm on run 110520 does not imply the same ROI on run 110521.
- v1: no label-based matching across runs. Document as limitation; revisit if linked multi-run norm comparison is needed.

## Retire overlay path

Remove or stop using after Phase 1:

| File / symbol | Action |
|---------------|--------|
| `DerivedPlotDataModel` | Remove |
| `MplCanvas.add_derived_plot`, `derived_models`, `sync_derived_line_display` | Remove |
| `DerivedSeriesRegistry` on `DerivativeController` | Remove |
| `DerivedProduct` | Fold into `FrozenSpectrum` or thin wrapper |

Keep `derived_fetch.py`, dialog, preview worker — only the **commit destination** changes.

## Phases

### Phase 1 — Stack spectra on RunModel + Run Display

**Goal:** Save scan-axis profiles (including mesh cases where scan axis is Plot X/Y); toggle as Y or Norm in Run Display; plot via normal 1D pipeline.

**Deliverables**

- `views/plot/plotDimensionWidget.py` — plot-axis labels from `PlotViewFrame`
- `models/plot/cube_view.py` — `scan_profile_storage_axis`, `classify_profile_kind`
- `derivative_controller` / `derived_fetch` — mandatory `span_full` on stack-spectrum save when scan axis is on plot plane
- `models/plot/frozen_spectrum.py`
- `RunModel` registry + fetch interception (Y and norm)
- `RunListModel` / `RunDisplayWidget` — separator, synthetic section, delete
- `DerivativeController` — Save → register; no selection side effects
- `DerivativePlotDialog` — Save button only
- Remove overlay commit path
- `tests/test_frozen_spectrum.py`

**Acceptance**

- [ ] Dimension Control plot-axis labels match rendered plot (mesh `tes_mca_spectrum` case)
- [ ] Save stack profile (ROI vs `en_energy`) — appears below separator; no checkboxes change; 2D plot unchanged
- [ ] 2D mesh `(en_energy, tes_mca_energies)`: save profile along `en_energy` spans full horizontal axis; ROI band limits orthogonal axis only
- [ ] Check synthetic Y — 1D line appears when plot is in 1D mode with matching X
- [ ] Check synthetic Norm — divides catalog Y without Tiled fetch for norm
- [ ] Mixed norm: catalog + synthetic `np.prod` works
- [ ] User transform applies to synthetic Y
- [ ] Slice slider move does not alter synthetic Y or synthetic norm values
- [ ] Delete removes row and artist
- [ ] Save second ROI — both appear in synthetic section
- [ ] No `getData` / Tiled call when plotting synthetic key (unit test with mock)
- [ ] 4D layout `(en_energy, dim_0, dim_1, dim_2)`: save along `en_energy` → Run Display; save along `dim_0` → rejected or deferred to Phase 2 (not Run Display), including after UI axis reorder

### Phase 2 — Local profiles (ROI Profiles panel)

**Goal:** Persist `local_profile` entries (in-plane and secondary INDEX); compare without polluting Run Display.

**Deliverables**

- `views/plot/roi_profiles_panel.py` — list, visibility toggle, delete
- Register `local_profile` on `RunModel` (same fetch interception)
- Save routing in `DerivativeController` by `classify_profile_kind`
- Overlay or dedicated 1D comparison when toggled (TBD: overlay on main canvas vs embedded mini-plot)

**Acceptance**

- [ ] Save profile along `dim_2` — appears in ROI Profiles, not Run Display
- [ ] Save profile along `dim_0` (exposure INDEX) — ROI Profiles, not Run Display
- [ ] Toggle visibility — compare two saved local profiles
- [ ] Frozen semantics same as stack spectra

### Phase 3 — 2D plane commit

**Goal:** Committed masked 2D crop (preview exists; commit deferred in old plan).

Out of scope for synthetic RunModel keys (2D planes are not 1D spectra). Separate design when needed.

### Phase 4 — Polish

- Session persistence of `FrozenSpectrum` list
- X compatibility hint (grey synthetic rows when current X ≠ `committed_xkey`)
- Linked-run label matching for norms across scans
- Export provenance (`request`, ROI corners) with `export_to_xdi`

## File tree (target)

```
nbs_viewer/models/plot/
  frozen_spectrum.py          # Phase 1 (new)
  runSource.py                 # Phase 1 (registry + intercept)
  derived_fetch.py            # unchanged
  cube_view.py                # Phase 1 (scan axis classification)

nbs_viewer/models/plot/runListModel.py   # Phase 1 (synthetic key aggregation)

nbs_viewer/views/plot/
  derivative_controller.py    # Phase 1 (Save → RunModel)
  derivative_plot_dialog.py # Phase 1 (Save only)
  controls/run_display.py   # Phase 1 (separator + synthetic rows)
  roi_profiles_panel.py     # Phase 2 (new)

tests/
  test_frozen_spectrum.py     # Phase 1 (new)
  test_derived_fetch.py       # unchanged
```

## References

- [`roi_analysis_plan.md`](roi_analysis_plan.md) — Phases 0–1 complete; Phase 2 preview complete; commit superseded here
- [`materialize_view_refactor_plan.md`](materialize_view_refactor_plan.md) — `MaterializeRequest`, profile axis eligibility, `is_plot_plane_storage_axis`

## Tests for scan-axis classification and span

Add to `tests/test_materialize_view.py`, `tests/test_derived_fetch.py`, or `tests/test_frozen_spectrum.py`:

- 4D parent `(en_energy, dim_0, dim_1, dim_2)` default spec: `scan_profile_storage_axis` → `0`
- Same parent after `swap_rows` in UI: still → `0`
- 2D mesh parent `(en_energy, tes_mca_energies)` both plot axes: `scan_profile_storage_axis` → `0`
- `classify_profile_kind(..., 0)` → `stack_spectrum` (including mesh case)
- `classify_profile_kind(..., 1)` → `local_profile` (exposure counter or `tes_mca_energies`)
- Stack save along scan axis on plot plane: `resolve_profile_region(..., span_full=True)` expands along `frame.plot_x_dim` / `plot_y_dim` for scan axis

## Implementation checklist

- [ ] Plan document (this file)
- [ ] Phase 1: Dimension Control plot-axis label fix
- [ ] Phase 1: `FrozenSpectrum` + `RunModel` registry
- [ ] Phase 1: Fetch interception (synthetic Y and norm)
- [ ] Phase 1: Run Display synthetic section + delete
- [ ] Phase 1: Dialog Save + retire overlay path
- [ ] Phase 1: `test_frozen_spectrum.py`
- [ ] Phase 2: ROI Profiles panel + in-plane routing
