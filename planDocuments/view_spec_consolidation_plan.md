# ViewSpec consolidation plan

Collapse the parallel view / crop / materialize stacks so **`ViewSpec` is
the source of truth** for “how to turn storage data into a plot plane,” and
delete the leftover modules one file at a time.

**Status:** Step 1 complete (`region_reduce.py` deleted). Step 2 blocked on
slim-vs-fat `ViewCrop` decision (see below).

**Constraint:** each step’s definition of done is **delete one listed file**,
migrating its behavior into **existing** files. No new modules.

---

## Motivation

`RunSource.get_plot_bundle` is the single fetch entry we want, but it still
imports from `cube_view`, `view_crop`, `derived_fetch`, and `plot_bundle`
because several refactor waves left parallel type systems in place:

| Layer | Intended (new) | Still live (legacy / bridge) |
|-------|----------------|------------------------------|
| Spec | `ViewSpec` / `ViewIntent` in `view_spec.py` | `CubeViewSpec` in `cube_view.py` (UI + session) |
| Request | `PlotRequest` (`view` + `region` + `mask_mode`) | `MaterializeRequest` (`spec` + `region` + `mask_mode`) |
| Crop | slim `view_spec.ViewCrop` on `ViewSpec` | fat `view_crop.ViewCrop` on `PlotModel` |
| Apply | should be `ViewSpec.apply(...)` | `materialize_view` in `cube_view.py` |
| ROI fetch | same `get_plot_bundle` | `derived_fetch.py` dual path |

`PlotRequest.view` is already a `ViewSpec`, but reduce still converts to
`CubeViewSpec` and calls `materialize_view`. Ordinary 2D crop is already
folded into `ViewSpec.load_slice` via slim crop; fat crop remains for
session / ROI-under-crop.

### Target end state

```text
PlotModel / DimensionControl
  ViewIntent  →  project() → ViewSpec  →  PlotRequest

RunSource.get_plot_bundle(request, region_frame?=…)
  slice = request.view.load_slice()   # + ROI narrow if region
  load y, axes
  y, coords, names = request.view.apply(..., region=request.region, ...)
  norm / transform
  pack → PlotBundle
```

`PlotDataModel.preview_roi_profile` either applies on `last_bundle` or builds
a `PlotRequest` and calls the same method.

**Survive:** `view_spec.py`, `plot_request.py`, `runSource.py`,
`plot_geometry.py`, `plot_view_frame.py`, `region.py`, `region_mesh.py`,
plus session callers (`plotModel.py`, `plotDataModel.py`).

---

## Delete order

| Step | Delete | Main destination(s) | Status |
|------|--------|---------------------|--------|
| 1 | `region_reduce.py` | `region.py` + `cube_view.py` (temporary) | **Done** |
| 2 | `view_crop.py` | `view_spec.py` + `plotModel.py` + `plot_view_frame.py` | Pending decision |
| 3 | `derived_fetch.py` | `plotDataModel.py` + `plotModel.py` + `view_spec.py` | Pending |
| 4 | `cube_view.py` | `view_spec.py` | Pending |
| 5 | `plot_bundle.py` | `view_spec.py` + `runSource.py` + `plot_geometry.py` | Pending |

### Step 1 — Delete `region_reduce.py` (done)

- `reduce_masked_plane` → `region.py`
- `_profile_coords` / `_coord_for_profile_index` → `cube_view.py`
- Tests updated; related suite green

### Step 2 — Delete `view_crop.py` (see detailed notes below)

Unify on slim `view_spec.ViewCrop` for fetch identity. Session extras that
slim cannot carry must either live as private `PlotModel` fields or be
removed by redesigning the ND-ROI-under-crop path.

### Step 3 — Delete `derived_fetch.py`

One fetch entry (`RunSource.get_plot_bundle`); ROI preview becomes a caller.

- Profile request builders → `plotModel.py` and/or helpers beside
  `profile_view_spec` (then into `view_spec` in step 4)
- `fetch_roi_preview` / in-plane-from-bundle → `plotDataModel.py`
- Drop `plot_plane_storage_axes` import from `RunSource`

### Step 4 — Delete `cube_view.py`

`ViewSpec` is the only view type; apply lives on it;
`CubeViewSpec` / `MaterializeRequest` gone.

- Move `DimRole`, `materialize_view`, profile helpers into `view_spec.py`
- `ViewSpec.apply(y, axis_arrays, axis_names, *, region=None, region_frame=None, mask_mode=...)`
- DimensionControl / PlotModel hold `ViewIntent` or `ViewSpec`
- Drop `to_cube_view_spec` / `from_cube_view_spec` / `view_spec_from_legacy`
- `FrozenSpectrum` stores `PlotRequest` (or view+region+mask_mode), not
  `MaterializeRequest`

### Step 5 — Delete `plot_bundle.py`

- `reduce_to_plot_plane` → call `request.view.apply(...)` from `RunSource`
- `build_plot_bundle` → `plot_geometry.py`
- norm / transform / key-slice helpers → `runSource.py` or `plot_geometry.py`

---

## Step 2 deep dive: slim vs fat `ViewCrop`

### Two types today

**Slim** (`view_spec.ViewCrop`): `storage_bbox`, `plot_y_axis`, `plot_x_axis`.
Hashable; embedded in `ViewSpec` / `PlotRequest`. Already used for ordinary
2D load narrowing via `ViewSpec.load_slice`.

**Fat** (`view_crop.ViewCrop`): slim fields plus `display_bbox`, `source_key`,
`spatial_fingerprint`, `full_frame`, `row_axis`, `col_axis`. Stored on
`PlotModel._view_crop` and passed into ROI ND paths.

`build_plot_request` already strips fat → slim via `slim_crop_from_legacy`.

### Field-by-field: what fat crop is actually used for

| Fat field | Used for | Slim has it? | Replaceable today? |
|-----------|----------|--------------|--------------------|
| `storage_bbox` | Load narrowing; canvas “crop changed” | Yes | Yes — already on slim / `ViewSpec.load_slice` |
| `plot_y_axis` / `plot_x_axis` | Slice narrowing; invalidation | Yes | Yes |
| `source_key` | Which trace the crop applies to (`_crop_for_trace`, canvas, invalidate) | No | Session field on `PlotModel` (`TraceKey` / tuple) |
| `spatial_fingerprint` | **Never read** (only written) | No | Drop — dead |
| `display_bbox` | `crop_status_text`; ROI display→storage in `fetch_context_with_view_crop` | No | Status: need frame/extent; ND path: see below |
| `full_frame` | Status text; ND ROI compile frame; invalidate axis lookup; re-crop resolution | No | Hard — see call sites |
| `row_axis` / `col_axis` | `storage_bbox_from_display_bbox` when ROI is compiled on the **full** plane under crop | No | Same as ND path |

### Call sites that matter

**Already fine with slim + `ViewSpec`**

- `PlotModel._build_plot_request` → `slim_crop_from_legacy` → `ViewSpec.crop`
  → `load_slice()`
- Ordinary `get_plot_bundle` with no region: crop is only on the request view

**Need more than slim (current code)**

1. **`fetch_context_with_view_crop` / `RunSource._load_slice_for_request`**  
   ROI profile is `plot_ndim=1`, so it cannot carry the parent 2D crop on
   `request.view`. Under an active crop, ND reload still:
   - compiles the ROI on `crop.full_frame`
   - maps display ROI → storage with `crop.row_axis` / `crop.col_axis`
   - intersects with `crop.storage_bbox`

2. **`region_frame_for_roi_preview`**  
   For stack/ND profiles with crop: returns `view_crop.full_frame`, not
   `frame_from_bundle(cropped last_bundle)`. Encoded by
   `test_region_frame_for_roi_preview_uses_full_frame_on_nd_load`.

3. **`crop_status_text` / region control**  
   Needs `full_frame` + `display_bbox` for data-coordinate readout.

4. **`source_key` matching**  
   PlotModel / canvas gate crop per dataset. Slim crop has no identity.

**In-plane ROI on a cropped display** does *not* need the fat fields: preview
uses the cropped `last_bundle` frame. The gap is specifically **ND/stack
profile while cropped**.

### Do we already have machinery to replace fat crop?

| Concern | Existing machinery? |
|---------|---------------------|
| Main 2D load crop | Yes — `ViewSpec.crop` / `load_slice` |
| Bind crop to a dataset | No on slim — need `PlotModel` to remember the trace |
| Status text | No — need frame/extent (or store a status string/extent at commit) |
| ND ROI under crop | **Not with current algorithm** — that path assumes uncropped `full_frame` + full plane axes |

A redesign that would make slim + existing objects enough for ND:

- Always compile ROI on the **displayed** (cropped) frame from `last_bundle`
- Map ROI bbox → storage with **cropped** axes from that bundle
- Offset by `slim.storage_bbox` into full storage
- Drop `full_frame` / `row_axis` / `col_axis` from crop state

That is real behavior change in `fetch_context_with_view_crop` /
`region_frame_for_roi_preview`, not a straight move. Current tests encode
the full-frame behavior.

### Verdict

Slim `ViewCrop` is already enough for the **main 2D fetch**. It is **not**
enough, with today’s ROI-under-crop code, to delete the fat object without
either (a) keeping some session side-channel on `PlotModel`, or
(b) redesigning the ND ROI path.

### Step 2 options

**A — Slim for fetch; session side-channel (smaller risk)**

- Fetch identity: only `view_spec.ViewCrop` on `ViewSpec` / `PlotRequest`
- `PlotModel` keeps private: source key, `full_frame`, and axes (or display
  bbox) for status + ND-under-crop
- Delete `view_crop.py`; no second public `ViewCrop` type
- RunSource still needs *something* for ND-under-crop (parent slim crop +
  frame/axes), not a fat crop class

**B — Redesign ND-under-crop first, then slim-only**

- Compile on cropped bundle; offset into `storage_bbox`
- Then slim + `last_bundle` + PlotModel `source_key` really is enough
- More work and test rewrites in the same step

**Recommendation:** treat **A** as the honest step 2 (delete the module,
unify the value type, keep session extras on `PlotModel`). **B** is a
follow-on that can then delete the side-channel.

---

## What not to do

- Do not add `materialize.py`, `cube/`, or a third crop module — grow
  `view_spec.py` / `plotModel.py` instead.
- Do not keep `CubeViewSpec = ViewSpec` aliases past the end of step 4.
- Do not leave `MaterializeRequest` as a parallel request type once
  `PlotRequest` already has `view` + `region` + `mask_mode`.
- Do not pretend slim alone replaces fat `ViewCrop` without choosing A or B.

---

## Related plans

- `codebase_problem_statement.md` Beginning of reorganization
- `structural_remediation_plan.md` Plan for reorganization, partially complete