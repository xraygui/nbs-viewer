# View pipeline plan

How a plot request becomes storage indices, and how those indices become a
`PlotBundle`. This is the single plan for the view / crop / ROI / fetch
stack.

**Status:** steps 1 and 2 landed on branch `mesh-transpose-removal`
(2026-09-08). Steps 3–6 not started.

**Replaces** — deleted in the same commit that added this file:

| Document | Why |
|----------|-----|
| `view_spec_consolidation_plan.md` | Its step 2 was blocked on a slim-vs-fat `ViewCrop` field inventory. That was the wrong question; see **Decision 2**. Its delete-order is carried forward here. |
| `materialize_view_refactor_plan.md` | Complete. It introduced `MaterializeRequest` / `materialize_view`, both of which this plan removes. |
| `mixed_rank_plot_view_plan.md` | Proposed `DrivingViewContext`, `view_compatible`, `view_blocked`, `adapt_fetch_context`. `ViewIntent.project` plus the selection-driven default do the same job with types that already exist. Its three observed bugs are carried forward below. |

**Numbering warning.** "Step 1" and "step 2" here are *not* the step 1 and
step 2 of the deleted `view_spec_consolidation_plan.md`. That document's
step 1 was deleting `region_reduce.py`; its step 2 was deleting
`view_crop.py`. Commits referring to "step 1" and "step 2" from 2026-09-08
onward mean the steps in this document.

---

## The two layers that are fixed

Everything else in the middle is negotiable, but these two are the contract:

**Top — `PlotRequest`.** A complete description of what ends up on the plot.
Frozen and hashable.

**Bottom — a fetch plan.** What array indices are read from the database.
Frozen and hashable, so "can this be served from data already loaded?" is an
equality test rather than a guess.

One pure function maps the first to the second. One pure function maps
(loaded arrays, request) to a `PlotBundle`.

```
session:   ViewIntent            rank-agnostic; one per plot session
              | project(ndim, shape)
per key:   Projection            axis order, roles, indices  (today: ViewSpec)
              | + identity + spatial window + presentation
per trace: PlotRequest           what ends up on the plot
              | plan_fetch()
low level: FetchPlan             slice_info + the plane the load lands in
              | load, reduce, normalise, transform
           PlotBundle
```

`ViewIntent` is the mechanism for plotting keys of different rank together —
a 1-D spectrum beside a 1-D projection of a 2-D spectrum. `project` binds it
to each key's rank; `plot_axis_names` decides whether two projected keys may
share a plot.

---

## Decisions

### 1. `projection.plot_ndim` is the rank of the plane loaded, not of what is drawn

Output rank is 1 when a masking region is present, `plot_ndim` otherwise.

Today two `__post_init__` assertions contradict each other —
`view_spec.py:203` says a crop requires `plot_ndim == 2`, `plot_request.py:254`
says a region requires `plot_ndim == 1` — so an ROI on a cropped plane is
unrepresentable. That is why `RunSource.get_plot_bundle` takes `region_frame`,
`parent_spec` and `view_crop` as extra keyword arguments: those three *are*
the parent view, smuggled past the request object that was created to hold it.

### 2. Crop and region are siblings, both above the projection

They are the same kind of thing at the fetch layer: a spatial restriction on
the plot plane that narrows the load. `fetch_context` already narrows to the
compiled ROI's bounding box, which is exactly the "fetch a small subset"
optimisation that motivated putting crop on the spec. They differ only after
the load: a crop keeps the plane 2-D, a region masks it down to a 1-D profile.

`ViewSpec` currently tries to be two things — the axis mapping *and* the fetch
descriptor — and only the second one needs the crop. Naming the fetch plan
separately lets the projection be just axis order and roles, and lets crop and
region sit together one level up.

The asymmetry in how they arrive is real and should be kept: a crop is
committed once and stored as storage indices; a region is a live geometric
object in data coordinates that must be compiled against a frame every time.

### 3. A reduction changes the load, not only the reduce

An ROI profile needs four things: the parent projection, the region and mask
mode, **which axis the profile runs along**, and **how the masked cells are
reduced**. `profile_view_spec` packs the last two into a rewritten 1-D
`CubeViewSpec`, which destroys the identity of the parent plane — that is why
`parent_spec` has to be passed separately and why
`_spatial_reduce_storage_axes` needs a hint to recover it.

When the profile axis is *not* on the display plane, that axis must be read in
full even though the parent projection holds it at a single index. A planner
that forgets this returns one point.

### 4. Orientation happens once, immediately after load

Storage-to-display reorientation is currently applied inside
`prepare_2d_bundle`, at the very end, so anything touching raw loaded arrays
before that is in storage order and has to remember to convert. It mostly
does not. Moving the reorientation to just after the load makes everything
downstream display-ordered.

### 5. Orientation is policy, expressed in the view spec

No implicit per-render-mode transforms. Which dimension is horizontal is a
default the user can see and change. **Landed in step 1.**

### 6. The selected X key is plotted horizontally

With one guard: when the X key names a slice axis rather than one of the axes
the plot plane already shows, the plane keeps its own orientation and the
selection drives nothing. Forcing a camera stack's voltage axis onto the image
plane replaces the frame with a voltage-versus-column view.

Detector-declared hints — a camera saying its data is energy vs dim_x vs
dim_y, which may differ per camera — are deferred. Same lookup, more sources.
**Landed in step 2.**

### 7. Reordering rows and picking an X key: last one wins

Both are explicit statements about which dimension is horizontal. A manual
order survives every rebuild until the X selection actually changes. The state
this needs is "which X key was this order derived from", not a
"has the user meddled" flag; it becomes `ViewIntent` state when the session
owns the spec. **Landed in step 2.**

---

## Findings, with evidence

Recorded because each one was found by writing code rather than by reading it,
and each changes the order of the remaining work.

### The ROI mask is applied in display order to a storage-order array

`_materialize_roi_profile` compiles the region on the display frame and applies
that mask directly to `y`, which is in storage order. On a 5×6 plane with an
ascending row axis (so the image is flipped for `origin="upper"`):

```
storage rows (first column): [0, 100, 200, 300, 400]
display rows (first column): [400, 300, 200, 100, 0]
ROI covers data rows 1-2, columns 2-3

materialize_view profile : [1010, 2020, 3030]
ground truth             : [ 610, 1220, 1830]
```

The in-plane preview path, which reduces `last_bundle` (already
display-ordered), returns 610 — correct. So the same drawn ROI gives two
different answers depending on whether the profile axis is on the display
plane.

**This cancels out the fetch bug below**, which is why
`test_bbox_fetch_matches_full_materialize_stack_profile` passes today: it makes
both errors together and `region_frame_for_bbox` keeps them consistent.
**Fixing the fetch alone breaks the ND ROI differently.** The two must land in
one change.

### Two fetch-narrowing paths that are the same function

`MaterializeRequest.fetch_context` (`cube_view.py:93`) and
`fetch_context_with_view_crop` (`view_crop.py:122`) differ in that the crop one
maps display to storage through `storage_bbox_from_display_bbox` and the other
applies a display bbox straight onto storage slices. `fetch_context` already
accepts `base_slice_info=`, so the crop variant never needed to be separate.

A prototype planner reproduced the plain path, the plain-plus-crop path and the
crop-plus-ROI path byte for byte across all four axis orientations, and
disagreed with the no-crop ROI path in three of four — including the default
`np.arange` case, where it fetches a block containing 36 of 72 ROI cells.

### `view_crop.py` is currently the only path that gets the mapping right

It has been on the delete list in two plans as a duplicate. Deleting it before
hoisting the display-to-storage mapping would remove the working implementation
and keep the broken one.

### `PlotViewFrame` is derivable; `region_frame` is a cache, not an input

The frame is a pure function of shape, the plot-plane coordinate arrays, the
axis names and the render hint. `prepare_2d_bundle` touches `y` only for
`y.shape` and the orientation flip. Coordinate arrays are 1-D and cheap, so
`RunSource` can build the parent frame itself before reading the big array.
`region_frame` is a required argument only because the canvas happened to have
a bundle to hand.

The flip cannot be recovered from a finished frame: `_extent_from_uniform_1d`
normalises with min/max so `bottom < top` always. Two booleans
(`row_reversed`, `col_reversed`) carry everything the fat `ViewCrop`'s two
coordinate arrays were carrying.

### Deleting `CubeViewSpec` costs 14 test modules

14 test modules import `CubeViewSpec` against 2 that import `ViewSpec`, and 8
import `MaterializeRequest`. That is the real cost of the dependency
inversion, and it cannot be sliced: `view_spec.py:17` imports from
`cube_view.py` and converts back before the old code runs, so the round trip
keeps both alive.

### `PlotDataModel` refetches on a transform change

`needs_fetch` compares whole `PlotRequest`s, so changing a transform triggers a
database read even though `apply_transform` runs on the loaded array at the end
of `get_plot_bundle`. A hashable fetch plan answers this properly, and extends
to containment — shrinking a crop, or moving an ROI inside an already-loaded
box, needs no round trip.

### Carried over from `mixed_rank_plot_view_plan.md`

Test catalog keys `x`, `y`, `image` of shape `(100, 32)`:

1. **Wrong default orientation.** With X = `x`, adding `image` as a 1-D slice
   defaulted to *slice `x` at index 0, plot `dim_1`*. **Closed by step 2** —
   it now plots `x` and slices `dim_1`.
2. **0-D collapse on 1-D guests.** The canvas passes the driving key's
   `to_load_slice_info()` to every trace, so a 1-D `y` truncates
   `(0, slice(None))` to `(0,)` and raises "Unsupported plot dimensionality:
   0". **Open** — step 6.
3. **No semantic model for mixed overlay.** Flipping the plot axis is valid for
   `image` but makes `y` unplottable on the same horizontal axis. **Open** —
   `ViewIntent.project` plus `plot_axis_names` is the intended answer, step 6.

---

## Steps

Each step must name what it deletes. A step that adds a module, a bridge type,
or a `*_from_legacy` converter as its main content is not a step in this plan.

### Step 1 — Delete the mesh transpose ✅ 2026-09-08 (`321bf53`)

Deleted `y_mesh = y.T` and the coordinate swap, `_infer_mesh_plot_dims`, the
mesh branches in `frame_from_bundle`, `_plot_axis_length` and
`_storage_axis_arrays_for_bundle`, `_tensor_axis_for_plane_storage`, and
`_storage_indices_for_plot_axis`. Fixed the mesh ND-ROI raise and image cell
bounds ignoring the index. Follow-up `b2a817d` fixed plot-axis row labels
reading `plot_x_dim` (a plane position) as a storage axis.

### Step 2 — Selection-driven default axis order ✅ 2026-09-08 (`11c7a0d`)

Added `default_spec_for_selection` and `spec_for_shape_and_selection`; removed
the last branching from `DimensionControl.create_sliders`.

### Step 3 — Orientation once after load, one planner, one mask

**Not started.** The largest step and the only one that cannot be sliced,
because the fetch narrowing and the mask application currently cancel.

Do:

- move storage-to-display reorientation to immediately after the load
- add `row_reversed` / `col_reversed` to `PlotViewFrame`, set where the flip
  happens, so the frame is self-sufficient for the mapping
- add `plan_fetch` and a frozen `FetchPlan`
- apply the ROI mask to display-ordered data

Deletes: `fetch_context_with_view_crop`, `MaterializeRequest.fetch_context`,
`MaterializeRequest.to_fetch_slice_info`, `apply_view_crop_to_slice_info`,
`apply_crop_to_slice_info`, `_narrow_slice`, `_narrow_fetch_slice`.

Tests: rewrite the fetch tests to assert against known data rather than against
`compiled.bbox`. `test_fetch_slice_info.py:44` currently asserts
`slice_info[2] == slice(r0, r1)` with `r0, r1` straight from the compiled
display bbox — it pins the bug. Add the descending-axis case, which has no
coverage.

**Not behaviour-preserving.** Say so in the commit.

### Step 4 — One request, no side channels

**Not started.** Depends on step 3.

- `PlotRequest` carries the projection (2-D when a region is present), crop,
  region, mask mode, profile axis and spatial reduce
- `get_plot_bundle(request, *, cached_plane=None, label="")`

Deletes: the `region_frame`, `parent_spec` and `view_crop` arguments; the fat
`view_crop.ViewCrop` and so `view_crop.py`; `_profile_uses_nd_load`;
`region_frame_for_roi_preview`'s branch; `fetch_materialized_bundle`'s
eleven-parameter signature and the two-branch `fetch_roi_preview`, and so
`derived_fetch.py`.

`cached_plane` is the honest name for the one thing that really is an
optimisation — reduce the plane already in memory rather than reload.

### Step 5 — Invert the dependency, delete `cube_view.py`

**Not started.** Depends on step 4. One commit; the round trip is what keeps
both types alive.

- move `DimRole` / `SLICE_ROLES` so `cube_view.py` imports from `view_spec.py`,
  never the reverse
- `ViewSpec` becomes the only spec; rename to `Projection`
- `materialize_view` takes a `PlotRequest`

Deletes: `CubeViewSpec`, `MaterializeRequest`, `to_cube_view_spec`,
`from_cube_view_spec`, `view_spec_from_legacy`, `slim_crop_from_legacy`,
`build_plot_request`, and `cube_view.py` itself (1401 lines).

Cost: 14 test modules to retarget. Price it in the PR description.

### Step 6 — Adopt `ViewIntent`, or delete it

**Not started.** Depends on step 5.

`ViewIntent` has zero production callers today. Either the session holds one
instead of `PlotModel._dimension` / `_slice` / `_cube_view_spec` /
`_view_crop`, or it goes — an unused abstraction is worse than none, because
the next plan gets written against it.

- `PlotModel` holds one `ViewIntent`; `_build_plot_request` becomes
  `intent.project(ndim, shape)`
- `DimensionControl` edits the intent instead of owning a spec
- `ViewIntent.axis_order == ()` means "derive from the selection", replacing
  `DimensionControl._default_xkey`
- closes mixed-rank bugs 2 and 3 above

Deletes: four hand-synced fields on `PlotModel`; `DimensionControl`'s ownership
of domain policy (problem statement item 7).

### Step 7 — `plot_bundle.py`

**Not started.** `reduce_to_plot_plane` becomes `request.view.apply(...)`;
`build_plot_bundle` moves to `plot_geometry.py`; norm / transform helpers move
to `runSource.py`.

---

## Relationship to the remaining plans

- **`structural_remediation_plan.md`** — steps 3–8 assume a `models/plot/cube/`
  and `models/plot/roi/` package split. That is superseded: this plan deletes
  those files rather than moving them. **Steps 2 and 9–12 are unaffected and
  still live** (CI, data-layer contract, `ChunkCache`, logging sweep, repo
  hygiene) and are the reason that document survives.
- **`plot_package_reorganization.md`** — superseded on file splits for the same
  reason. Its inventory of private model APIs used by views is still the best
  record of that surface.
- **`codebase_problem_statement.md`** — still the backlog. Item 2
  (display-vs-storage) is what steps 3 and 4 close.
- **`model_core_refactor_plan.md`** and **`plot_session_list_adapter_plan.md`**
  — active and adjacent, not superseded. They cover ownership and naming
  (`Trace`, `PlotSession`, `RunListItemModel`); this plan covers the view and
  fetch pipeline. Step 6 here needs their `ViewIntent` slot on the session.
- **`headless_testing_plan.md`** — the suite runs on `QCoreApplication` only.
  Constructing a `QWidget` in `tests/` aborts the interpreter, so widget
  behaviour has to be either driven from a scratch script under a real
  `QApplication` or moved model-side to be testable. Prefer the second.

## Modification log

| Date | Change |
|------|--------|
| 2026-09-08 | Written; replaces `view_spec_consolidation_plan.md`, `materialize_view_refactor_plan.md`, `mixed_rank_plot_view_plan.md`. Steps 1 and 2 recorded as landed. |
