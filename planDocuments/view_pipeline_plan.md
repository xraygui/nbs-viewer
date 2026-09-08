# View pipeline plan

How a plot request becomes storage indices, and how those indices become a
`PlotBundle`. Sub-plan of [`refactor_plan.md`](refactor_plan.md); the other
half is [`session_and_traces_plan.md`](session_and_traces_plan.md), which
owns who holds what.

**Status:** steps 1–3 landed on branch `mesh-transpose-removal`
(2026-09-08). Steps 4–7 not started.

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

### Step 3 — Orientation once after load, one planner, one mask ✅ 2026-09-08

**Not behaviour-preserving.** Fixes bugs 2 and 3, which cancelled.

Landed:

- `orient_for_display` runs immediately after the load, on the N-D array,
  along the plot-plane storage axes. Everything downstream is display-ordered.
- `prepare_2d_bundle` no longer reorders anything — it packs an already
  display-ordered plane. `_orient_image_for_imshow_upper` is gone.
- `PlotBundle` and `PlotViewFrame` carry `row_reversed` / `col_reversed`, set
  where the flip happens. `PlotViewFrame.storage_bbox` maps a bounding box
  between display and storage and is its own inverse, so the same method reads
  the loaded storage bounds back as display.
- `plan_fetch` and the frozen `FetchPlan` in `plot_request.py`. Crop and ROI
  narrow through one `narrow` helper and one display-to-storage mapping.
  `FetchPlan.reversed_axes_for` owns the choice between the parent frame's
  recorded flip and one derived from the loaded coordinates.
- `ViewSpec.load_slice` → `base_slice`, which no longer applies the crop:
  `plan_fetch` is the only place a load is narrowed.

Deleted: `MaterializeRequest.fetch_context`, `MaterializeRequest.to_fetch_slice_info`,
`_narrow_fetch_slice`, `fetch_context_with_view_crop`, `apply_view_crop_to_slice_info`,
`apply_crop_to_slice_info`, `_narrow_slice`, `_orient_image_for_imshow_upper`,
`storage_bbox_from_display_bbox`, and `ViewCrop.row_axis` / `.col_axis` —
the two coordinate arrays the fat crop carried only to recover the reversal.

Measured across the ten touched files in `models/plot/`: **3605 → 3597 code
lines** (−8, excluding docstrings and comments); 6952 → 7047 raw. Suite 337 →
351.

Also fixed, en route:

- Committing a crop no longer reads from the database. With the reversal on
  the frame, `apply_view_crop_from_region` drops its `load_axes` call.
- The region frame for an ROI under a crop is derived from the narrowed
  slices, so an ROI reaching past the crop is the intersection rather than a
  shape-mismatch raise.
- The `ViewSpec` `crop requires plot_ndim == 2` assertion is relaxed to a
  bounds check when the view is a profile. That was half of Decision 1's
  contradiction; the other half goes with step 4.

#### Findings

**Orienting after the load is not free: normalization has to follow.** A norm
key that shares the plot-plane axes is loaded in storage order and divided
into a now display-ordered `y`. Reversing `y` alone divides by the wrong rows,
silently. `_normalized_y` reverses each norm array by axis *name*, so it works
when the norm key's axis layout differs from the y key's. This was the hidden
decision point in this step; nothing in the plan predicted it, and no test in
the tree would have caught it.

**A rectangular ROI cannot detect either bug.** A rectangle fills its own
bounding box, so its mask is invariant under the row/column reversal, and a
display-order mask is indistinguishable from a storage-order one. Every ROI
test in the tree used `RectRegion`. The new tests use a triangular
`PolygonRegion`; with it, three of the four axis orientations fail before the
fix and pass after — the fourth, descending rows with ascending columns, is
already display order and is genuinely a no-op.

**Bug 8 does not belong here.** `needs_fetch` compares whole requests, so a
transform change refetches. Not refetching requires holding the loaded plane
across requests, which is step 4's `cached_plane`. Moved to step 4.

#### Tests

`tests/test_fetch_slice_info.py` is rewritten as ground-truth tests: the
expected profile is computed by masking the oriented stack directly, over all
four axis orientations, never from `compiled.bbox`. Three end-to-end tests go
through `RunSource.get_plot_bundle` and `PlotSession.preview_roi_profile`.
Each of the three was confirmed to fail against the pre-step-3 behaviour.

`tests/fixtures/display_plane.py` builds display-ordered planes the way the
fetch path does, for the test call sites that used to get orientation for free
from `prepare_2d_bundle`.

### Step 4 — One request, no side channels

**Not started.** Step 3 is done, so this is next.

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

## Interlock with the other sub-plan

Step 6 here (adopt `ViewIntent`) needs the session to hold the intent, which
is session-and-traces step C. Step 4 here removes the extra `get_plot_bundle`
kwargs, which session-and-traces step D depends on. The merged order is the
table in [`refactor_plan.md`](refactor_plan.md).

Shared invariants, the bug list and the open questions live in the master
plan, not here.

## Modification log

| Date | Change |
|------|--------|
| 2026-09-08 | Written; replaces `view_spec_consolidation_plan.md`, `materialize_view_refactor_plan.md`, `mixed_rank_plot_view_plan.md`. Steps 1 and 2 recorded as landed. |
| 2026-09-08 | Became a sub-plan of `refactor_plan.md`; shared backlog and cross-plan notes moved there. |
| 2026-09-08 | Step 3 landed. Findings recorded: normalization must follow the orientation; a rectangular ROI cannot detect either mapping bug; bug 8 moved to step 4. |
