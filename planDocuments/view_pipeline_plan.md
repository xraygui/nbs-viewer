# View pipeline plan

How a plot request becomes storage indices, and how those indices become a
`PlotBundle`. Sub-plan of [`refactor_plan.md`](refactor_plan.md); the other
half is [`session_and_traces_plan.md`](session_and_traces_plan.md), which
owns who holds what.

**Status:** steps 1–6 landed on branch `mesh-transpose-removal`
(2026-09-08/09). Step 7 not started.

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

14 test modules import `CubeViewSpec` against 11 that import from
`view_spec.py`, and — after step 4 — 2 still import `MaterializeRequest`
(down from 8). That is the real cost of the dependency inversion, and it
cannot be sliced: `view_spec.py:17` imports from `cube_view.py` and converts
back before the old code runs, so the round trip keeps both alive.

**Step 5 outcome: 19 modules, not 14.** The count above missed modules that
name `CubeViewSpec` only in a type annotation or a helper's keyword argument.

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
2. **0-D collapse on 1-D guests.** **Closed before step 6, by steps 3–4** —
   each trace builds its own request and the rank guard in
   `projection_for_shape` stopped the truncation. Verified against the tree
   before step 6 started; the step could not be justified on it.
3. **No semantic model for mixed overlay.** **Also already closed** — a 1-D
   `y` and a 1-D projection of `image` plot together against `x`, verified by
   running them. What was *not* closed, and what step 6 actually fixed, is
   recorded under the step: the model and the widget were applying two
   different orientation policies.

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

### Step 3 — Orientation once after load, one planner, one mask ✅ 2026-09-08 (`dbe6083`)

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

### Step 4 — One request, no side channels ✅ 2026-09-08 (`b431c47`)

**Not behaviour-preserving where the two ROI paths disagreed.** An in-plane
ROI preview with no valid cached plane used to raise "No parent 2D bundle
available"; it now loads.

Landed:

- `PlotRequest` carries the parent projection (`plot_ndim == 2` when a region
  is present), the crop, the region, the mask mode, `profile_axis` and
  `spatial_reduce`. Decision 1's other half: the assertion that a region
  requires `plot_ndim == 1` is now `== 2`.
- `RunSource.get_plot_bundle(request, *, cached_plane=None, label="")`. The
  frame the region compiles against is derived inside `RunSource` from the
  plane's own coordinate arrays (`_plane_frame` → `frame_for_plane`), so no
  caller hands one in.
- `plan_fetch(request, *, plane_frame=None)` — `plane_axes` comes off the
  request. It also widens a profile axis the projection holds at a single
  index back to the full axis (Decision 3); that used to be a side effect of
  `profile_view_spec` rewriting roles, which is now built at the reduce
  instead (`plot_bundle._materialize_request`).
- `PlotModel.build_roi_profile_request` derives the profile request from the
  parent trace's own request, so run, keys, projection and crop are inherited
  rather than reassembled.
- `reduce_cached_plane` is the `cached_plane` path: the one genuine
  optimisation, reducing the plane already in memory. Whether it can serve a
  given profile is now the fetch's decision, not the caller's.

Deleted: `derived_fetch.py` (481 lines) and `view_crop.py` (155 lines) in
full — with them `fetch_materialized_bundle`, `fetch_roi_preview`,
`fetch_derivative_preview`, `region_frame_for_roi_preview`,
`_profile_uses_nd_load`, `_request_for_display_plane`,
`_spatial_reduce_from_profile_spec`, `plot_plane_storage_axes(_for_frame)`,
`materialize_request_for_profile`, `build_roi_profile_request_from_operation`,
`resolve_profile_region`, the fat `ViewCrop`, `view_crop_from_region`,
`crop_status_text` and `spatial_fingerprint_from_frame`. Also
`slim_crop_from_legacy`, `_fetch_plot_plane_storage_axes`,
`display_plane_profile_spec`, `RunSource._plan_fetch`,
`single_canvas._view_crop_for_model` (already dead), and the `region_frame` /
`parent_spec` / `view_crop` / `parent_bundle` arguments wherever they
appeared.

Measured across `models/plot/`: **5419 → 5206 code lines** (−213, excluding
docstrings and comments); 10915 → 10586 raw; 23 → 21 files. Suite 351 → 350.

#### Findings

**The fat crop's remaining fields were three different things.** `full_frame`
was the region-compilation frame, which is derivable; `display_bbox` was a
status string; `source_key` was session state saying which trace the crop
belongs to; `spatial_fingerprint` was never read. Only the last-but-one
survives, as `PlotModel._view_crop_key` — one field, and step 6's `ViewIntent`
absorbs it.

**Bug 8 is not closed, and `cached_plane` was never going to close it.**
Step 3 moved it here on the premise that not refetching after a transform
change needs "the loaded plane held across requests, which is step 4's
`cached_plane`". Wrong plane: `cached_plane` is a packed, *post-transform*
bundle, and `reduce_cached_plane` only knows how to mask one down to an ROI
profile. Re-applying a transform needs the array as it stood before
`apply_transform`, which nothing keeps, and a `needs_fetch` that compares
`FetchPlan`s rather than whole requests — `FetchPlan` is already frozen and
hashable with the frames excluded from comparison, so the comparison half is
ready. Both halves belong to step 7, which is the step that moves the
transform stage.

**Transform and ROI still disagree across the two paths.** `reduce_cached_plane`
reduces a plane the transform has already been applied to; the load path
carries `transform=""` on profile requests, as the old ND path did. Making
them agree means applying the transform to the 2-D plane before the reduce
rather than to the finished output, which reorders `get_plot_bundle`. Not done
here. In practice the paths do not cross today — a live 2-D display always has
a valid cached plane — but the asymmetry is real and belongs to step 7.

**Fixed en route: "span full profile axis" spanned the reduction axis.**
`storage_axis_to_plot_axis` preferred the *frame* over the spec for a rank-2
parent, a leftover from when `frame_from_bundle` read the plot dims off the
storage layout. Since step 3 every frame it builds has `plot_y_dim == 0` and
`plot_x_dim == 1` -- display positions, not storage axes -- so comparing a
storage axis against them inverts the answer for any view whose plot-axis
order is not the identity. That is the *normal* case after step 2: selecting
X = `x` on a `(100, 32)` image gives `axis_order == (1, 0)`, so a profile
along `x` was reported as `plot_y`, the drawn band was widened on the wrong
axis, and the profile came back covering only the drawn slice of its own
axis. It also inverted which of "Set ROI: full height" / "full width" the ROI
window enabled. The spec now decides at every rank; the frame is the last
resort for a caller that has no spec, where "storage axis" can only mean
"display position".

The test that pinned the old behaviour, `test_storage_axis_to_plot_axis_
prefers_frame_on_2d_mesh_parent`, was asserting the mesh transpose step 1
deleted -- it hand-built a frame with `plot_x_dim=0` that `frame_from_bundle`
can no longer produce. Replaced by two tests that fail against the old
mapping.

**`_materialize_roi_profile` still assumes the plot plane is the trailing two
tensor axes.** With the profile axis widened rather than reordered, a parent
whose plane is axes (0, 1) with the profile on axis 2 would reduce the wrong
pair. Unreachable today (the scan axis leads), and it is `remaining` being
built in storage order rather than `axis_order` — a `cube_view.py` problem,
so step 5.

### Step 5 — Invert the dependency, delete `cube_view.py` ✅ 2026-09-08 (`e0d2ef1`)

**Behaviour-preserving.** One commit; the round trip was what kept both types
alive, so it could not be sliced.

Landed:

- `DimRole`, `ROLE_LABELS`, `SLICE_ROLES`, `SpatialReduce` and `PlotAxisName`
  now live in `view_spec.py`. Nothing imports upward any more.
- `CubeViewSpec` merged into `ViewSpec`, which was already a strict superset
  of it (same five fields plus `crop`). `ViewSpec` gained `swap_rows`;
  `to_load_slice_info` was already there as `base_slice`.
- `ViewSpec` renamed to **`Projection`**, the name the pipeline diagram uses.
- `materialize_view` takes `(spec, *, region, mask_mode)` rather than a
  request object.

Deleted: `cube_view.py` (1212 lines) in full, and with it `CubeViewSpec`,
`MaterializeRequest`, `apply_cube_view` (no production caller),
`_resolved_roles_tuple` (a byte-identical duplicate of `view_spec._resolved_roles`),
`resolve_roles` and its three call sites, `ViewSpec.to_cube_view_spec`,
`ViewSpec.from_cube_view_spec`, and `plot_bundle._materialize_request`.

Measured across `models/plot/`: **5093 → 4960 code lines** (−133, excluding
docstrings and comments); 10354 → 10043 raw; 20 → 19 files. Suite 350 → 344 —
the six removed tests each covered a symbol that no longer exists.

#### The decision the plan had not made: where the contents go

The step said "delete `cube_view.py`" and listed the *types* to remove, but
named no destination for the fifteen live functions that were not on that
list. They split cleanly in two, and the import graph decides which way:

- **Spec construction and queries** (754 lines) → `view_spec.py`. Consumed by
  `plot_session.py` and `views/plot/roi/window.py`, neither of which imports
  `plot_bundle`.
- **Materialize machinery** (382 lines) → `plot_bundle.py`, which was
  `materialize_view`'s only consumer and already owns `reduce_to_plot_plane`.

`view_spec.py` is now 1100 lines and `plot_bundle.py` 833. A third module for
the profile-axis cluster would have balanced them, but a step whose content
includes a new module is not a step in this plan (invariant 10). Step 6 takes
most of the spec constructors into `ViewIntent.project`, which is where the
relief comes from.

#### Deviations from the step as written

- **`materialize_view` takes a `Projection`, not a `PlotRequest`.** The
  cached-plane path builds a synthetic 2-D plane spec that is not any
  request's view, so a `PlotRequest` parameter would have forced it to
  fabricate a fake request — a bridge object, which is the thing invariant 10
  forbids. `(spec, region, mask_mode)` is the honest signature.
- **`build_plot_request` and `view_spec_from_legacy` were renamed, not
  deleted.** The plan listed both as deletions, but what dies with
  `CubeViewSpec` is the *conversion*; the *choice* — which projection fits an
  array of this rank, given session state — is still needed until step 6 moves
  it to `ViewIntent.project`. `view_spec_from_legacy` is now
  `projection_for_shape`, and its `cube_view_spec=` argument is `projection=`.
  Recorded as a rename so the deletion count stays honest.

#### Findings

**The two specs had already converged.** `ViewSpec` carried every field and
method of `CubeViewSpec` except `swap_rows`, and `_resolved_roles_tuple` was a
character-for-character copy of `view_spec._resolved_roles`. The inversion was
holding two copies of one type in place, not two designs.

**`resolve_roles` was already dead weight.** `ViewSpec.__post_init__` resolves
roles on construction, so `resolve_roles(spec)` could only ever return an
equal object. Its three call sites in `DimensionControl` and `swap_rows` were
no-ops. Deleting it is why `swap_rows` shrank.

**The `_materialize_roi_profile` trailing-axes assumption did not move on.**
Step 4 sent it here as "a `cube_view.py` problem". `cube_view.py` is gone and
the code is unchanged in `plot_bundle.py`: `remaining` is still built in
storage order rather than `axis_order`, so a parent whose plane is axes (0, 1)
with the profile on axis 2 would reduce the wrong pair. Still unreachable —
the scan axis leads in every layout the tree produces — and it is a question
about the order of the reduce, so it belongs with **step 7**, which moves the
reduce stage. Moved there rather than fixed blind.

#### Tests

19 test modules retargeted — the plan priced 14. `test_cube_view.py` was
merged into `test_view_spec.py` rather than retargeted: both then tested the
same type, so keeping two files would have split the projection tests by an
accident of history. Its three `apply_cube_view` tests went with the function;
its two `resolve_roles` tests became assertions that the constructor resolves.

`DimensionControl` is the widget most exposed by this step — it lost its
`resolve_roles` calls and had a `Projection` constructor rewritten by hand —
and the suite cannot build it. Driven from a scratch script under a real
`QApplication` instead: 1-D selection, the switch to 2-D through
`spec_for_plot_ndim`, `swap_rows` re-resolving roles with no helper, and an
image bundle out the far end.

### Step 6 — Adopt `ViewIntent` ✅ 2026-09-09 (`505240d`)

**Not behaviour-preserving.** Fixes the orientation split below.

Adopted, not deleted — but on a different justification than the step was
written with, and after reshaping the type.

#### The step's stated payoff was already banked

Step 6 claimed it "closes mixed-rank bugs 2 and 3". Both were already closed
by steps 3–4, verified by running them before starting: a 1-D `y` and a 1-D
projection of a 2-D `image` plot together against `x`, and nothing truncates a
rank-2 slice tuple onto a rank-1 key. Adopting `ViewIntent` had to be
justified on something else.

#### What was actually broken: two orientation policies

`default_spec_for_selection` — the rule that a key the user picked as X is
plotted horizontally — had exactly **one** caller,
`views/plot/controls/dimension.py:340`. The model's own `projection_for_shape`
fell back to `default_view_spec`, the plain trailing-axis rule, whenever the
widget's rank-bound spec did not fit a key. So the pipeline silently applied a
*different orientation policy* to exactly the mixed-rank keys:

```
plot_ndim=1, X = "x" selected, image of shape (100, 32)
before:  roles=['index', 'plot_x']  -> axis_names=['dim_1']   # the column index
after:   order=(1, 0)               -> axis_names=['x']
```

`default_view_spec` was also a byte-for-byte duplicate of `default_spec` bar
one guard — the tell that the model/widget split had been cloning the policy.

#### Decision: axis order is stored as dimension *names*

`ViewIntent.axis_order` was a rank-bound permutation with "when its length
does not match the projected `ndim`, natural order is used". Lifting the
image's intent (X = `x`, order `(1,0)`) and projecting onto a rank-3 detector
discarded the orientation — the same bug, relocated into the type meant to fix
it. That was the omitted decision the step never asked: **is axis order a
stored permutation, or a rule?**

It is neither on its own. `dim_order` is now a tuple of dimension *names*,
outermost first, plus `xkey`, the selection the default follows. Names survive
a key gaining or losing an axis, which a permutation cannot; and both the
default and a manual arrangement resolve through one function,
`resolve_axis_order`, which is the only place the order is decided.

A manual arrangement is honoured only while it still names exactly this key's
axes. Half-applying a stale order would silently reinterpret which axis the
user meant to be horizontal, so a partial match re-derives from `xkey`.
Decision 7's "last one wins" is now state rather than bookkeeping:
`follow_xkey` clears `dim_order` when the X selection actually changes.

The crop is **not** intent state. A crop is storage indices on one trace's
plot plane and means nothing on another, so `ViewIntent.crop` is gone and
`project(..., crop=)` takes it per trace. That is Decision 2 applied to
ownership rather than to the fetch.

#### The widget stopped owning the view

`DimensionControl` held the authoritative spec and pushed it *down* through
`canvas.update_view_state` → `session.set_view_state`; the session was
downstream of a widget. It now reads `session.driving_projection()` and sends
gestures back — `move_view_axis`, `set_axis_reduce`, `set_plot_ndim`,
`follow_x_selection`. It holds no view state of its own.

Two hacks disappeared with the ownership. `on_selection_changed` used to set
`self._cube_view_spec = None`, and `on_dimension_changed` hand-rolled a
rollback that re-applied `spec_for_plot_ndim` in reverse and rebuilt twice.
The canvas keeps only the rule it actually owns — "2-D shows one dataset" —
as `accepts_plot_ndim`, asked *before* the session is told.

`get_shape_info`'s policy half moved too, as `PlotSession.driving_axes`. Worth
being precise about what that buys: the request path does not need it at all,
because each trace projects onto its own key's rank and names. It now decides
only *which sliders are shown*.

#### Deleted

`projection_for_shape` and its three-way fallback; `default_view_spec`;
`default_spec`; `default_spec_for_selection`; `spec_for_shape_and_selection`;
`spec_for_plot_ndim`; **`ViewIntent.from_view_spec`** (a lift-from-legacy
converter, and the only thing that had connected `ViewIntent` to anything);
`ViewIntent.crop`; `ViewIntent.axis_order` as a permutation;
`PlotSession._dimension` / `_slice` / `_cube_view_spec` and the `slice` /
`cube_view_spec` properties; `set_view_state`; `Trace.update_data_info`
(replaced by `set_projection`); `MplCanvas.update_view_state` and its
`_slice` / `_cube_view_spec` forwarding properties;
`DimensionControl._cube_view_spec` (34 references), `_default_xkey`,
`_primary_xkey`, `_sync_spec_from_rows`, `_apply_view_state`, and its three
signals `indicesUpdated` / `cubeViewChanged` / `dimensionChanged`, all of
which had zero subscribers. `build_plot_request` lost `shape`, `plot_ndim`,
`slice_info` and `crop` — it takes a `Projection`.

`models/plot/` **4952 → 4897** code lines (−55); `views/plot/`
**5584 → 5484** (−100). `dimension.py` 556 → 475 (−81), `view_spec.py`
509 → 454 (−55), `plot_request.py` 276 → 245 (−31). `plot_session.py` grew
1031 → 1099 (+68): the policy the widget was holding had to land somewhere,
and the model is where it belongs. Net **−155**. Suite 350 → 350.

#### Findings

**`_slice` was never independent state.** `DimensionControl` passed
`indices=spec.base_slice()` alongside the spec it came from, so two of the
four session fields were the same information. That is also why
`projection_for_shape`'s middle branch was dead in the session path: if the
projection's rank did not match, neither did the slice tuple's. Its one live
caller was the `ImageGridCanvas` bypass, which now builds its own
`Projection` through `spec_from_slice_info` — the last caller of that
function, and it goes with the bypass in session-plan step C.

**A rank-2 `Projection` in the session was poison for a rank-1 key.** The
clearest statement of the disease was a test:
`test_set_view_state_clears_cube_view_spec` — *"DimensionControl passes
`cube_view_spec=None` when only 1D Y keys remain selected; leaving the old
spec caused 1D fetches to fail."* The widget had to detoxify the session. A
rank-agnostic intent has nothing to clear, so the test is now the opposite
assertion: a 2-D intent held while a 1-D key is selected simply projects to
1-D.

**The ROI window and the crop validator were reading the session spec as "the
parent projection".** Both now read `trace.request.view`, which is
rank-correct and is what the crop and the mask were expressed against anyway.

#### Tests

`test_default_axis_order.py` rewritten against `ViewIntent` — it is the
orientation policy's test suite and the policy moved. Four new cases cover
what names buy over a permutation: a manual order is honoured, the same
selection keeps it, a different selection supersedes it, a rank change
re-derives rather than half-applying, and the order transfers to another key
with the same axes in a different storage layout.

`ViewIntent.from_view_spec` was deleted from production but tests still want
to say "set the session up so this key projects to *this*". That lift lives in
`tests/fixtures/view.py` as `intent_from_projection`, documented as test-only,
so the bridge is not in the production surface.

`DimensionControl` is the widget most exposed by this step and the suite
cannot build it. Driven from a scratch script under a real `QApplication`:
rows build from the session projection, the widget holds no spec, the spinbox
reaches `set_plot_ndim`, a reorder lands on the intent **as names**, a new X
selection clears it, and a slider edit reaches `reduce_indices`. That script
caught two of the three breaks nothing else could:
`MplCanvas._handle_plot_data` and `roi/window.py` were still reading
`session.cube_view_spec`. It missed the third -- see below.

#### Follow-up (`a7a32f2`): the gestures had no tests at all

`set_axis_reduce` constructed a `Projection` by name in a module that imports
it only for annotations, so **moving any dimension slider raised
`NameError`**. Two process failures let it ship:

- The lint diff showed `plot_session.py` F821 going from 2 to 3, and that was
  read as pre-existing noise. A count *increase* on an existing code is a new
  instance. The two already there are parameter annotations, harmless under
  `from __future__ import annotations`; the new one was a runtime call.
- The scratch script's slider check was `if control._slice_rows: ... else:
  True`. At `plot_ndim=2` on a rank-2 key there are no slice rows, so it
  reported PASS for not running. A smoke check with a vacuous fallback is
  worse than no check: it reports success for skipping.

The deeper miss: these are *model* methods now. Moving them off the widget so
they can be tested without a `QWidget` is the whole argument for the step, and
none of them were tested. `tests/test_view_intent_session.py` (11) covers
`driving_axes`, `driving_projection`, `set_plot_ndim`, `set_axis_reduce`
(index, role, clamping), `move_view_axis` including its no-op ends, and
`follow_x_selection`. Four fail against `505240d` with the `NameError`,
confirmed by running them against that tree.

`set_axis_reduce` now edits through `Projection.with_slice_role` /
`with_index`, which already existed, so it constructs nothing; `Projection` is
imported for real, so the category cannot recur silently. Suite 350 → 361.

### Step 7 — `plot_bundle.py`

**Not started.** `reduce_to_plot_plane` becomes `request.view.apply(...)`;
`build_plot_bundle` moves to `plot_geometry.py`; norm / transform helpers move
to `runSource.py`.

Carries two things from step 4, both about where the transform runs:

- **Bug 8.** `needs_fetch` compares `FetchPlan`s instead of whole requests,
  and the pre-transform plane is held so a transform change re-runs
  `apply_transform` rather than reading the database. Extends to containment:
  shrinking a crop, or moving an ROI inside an already-loaded box, needs no
  round trip either.
- **The cached / loaded ROI asymmetry.** Applying the transform to the 2-D
  plane before the reduce, rather than to the finished output, makes the two
  paths agree.

And one from step 5:

- **The `_materialize_roi_profile` trailing-axes assumption.** `remaining` is
  built in storage order rather than `axis_order`, so a parent whose plane is
  axes (0, 1) with the profile on axis 2 reduces the wrong pair. Unreachable
  today because the scan axis leads. Step 4 sent it to step 5 as "a
  `cube_view.py` problem"; `cube_view.py` is gone and the code moved to
  `plot_bundle.py` unchanged, so it lands here — this is the step that
  reorders the reduce.

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
| 2026-09-08 | Step 3 landed (`dbe6083`). Findings recorded: normalization must follow the orientation; a rectangular ROI cannot detect either mapping bug; bug 8 moved to step 4. |
| 2026-09-08 | Step 4 landed (`b431c47`). `derived_fetch.py` and `view_crop.py` deleted. Findings recorded: the fat crop held three unrelated things; transform and ROI still disagree across the cached and loaded paths; the trailing-axes assumption in `_materialize_roi_profile` moves to step 5. |
| 2026-09-08 | Fixed `storage_axis_to_plot_axis` reading the plot-axis mapping off the frame instead of the spec, which made "span full profile axis" widen the reduction axis. Recorded under step 4. |
| 2026-09-09 | Step 6 follow-up (`a7a32f2`): moving a dimension slider raised `NameError` — `set_axis_reduce` named `Projection` in a module that imports it only for annotations. The lint diff had shown the F821 count rise and it was dismissed; the scratch script's slider check had a vacuous `else: True` that reported PASS for not running. The session gestures now have headless tests, which is what moving them off the widget was for. |
| 2026-09-09 | Step 6 landed. Adopted rather than deleted, but not on the plan's justification: mixed-rank bugs 2 and 3 were already closed by steps 3–4, and the live defect was that the orientation policy had two implementations, one of them in a widget. `ViewIntent.axis_order` reshaped from a rank-bound permutation to dimension names plus `xkey`, which was the decision the step had omitted; `ViewIntent.crop` dropped because a crop is trace state. `DimensionControl` no longer owns a spec. |
| 2026-09-08 | Step 5 landed (`e0d2ef1`). `cube_view.py` deleted; spec helpers to `view_spec.py`, materialize to `plot_bundle.py`; `ViewSpec` renamed `Projection`. The step had named no destination for the file's contents — the split and the reasoning are recorded under the step. Two deviations recorded honestly: `materialize_view` takes a `Projection` rather than a `PlotRequest`, and `build_plot_request` / `view_spec_from_legacy` were renamed rather than deleted. The `_materialize_roi_profile` trailing-axes assumption moves to step 7. |
