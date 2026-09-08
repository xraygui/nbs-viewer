# ROI workbench plan

Extend ROI support from a single rectangle in a collapsible panel to a multi-ROI,
multi-shape workflow driven from a dedicated pop-out window. Supersedes Phase 3 of
[`roi_analysis_plan.md`](roi_analysis_plan.md).

## Goals

| # | Goal |
|---|------|
| 1 | Add ROI shapes beyond the axis-aligned rectangle, starting with ellipse and polygon |
| 2 | Move the full option set into a dedicated ROI window with its own draw/clear controls |
| 3 | Allow the preview plot to pop out into its own resizable window |
| 4 | Support several simultaneous ROIs producing a set of 1-D spectra |
| 5 | Make adding an ROI type a small, local change |
| 6 | Separate 1-D reduction (ROI) from 2-D extraction (crop) into distinct operations |

## Locked decisions

| Topic | Decision |
|-------|----------|
| Window structure | Dedicated non-modal **ROI window**; inline `Region` panel becomes a launcher plus the crop controls |
| ROI output | **1-D reduction only.** An ROI always produces a profile |
| 2-D output | Handled entirely by **crop**, which stays **rectangle-only** and independent of the ROI set |
| Operation scope | **Per-ROI**: each ROI carries its own mask mode, profile axis, reduce, span-full, and label |
| Cell selection | **Cell-center-inside** for every shape, including rectangles |
| First shapes | Ellipse (with circle as a constrained case) and polygon |
| Class structure | Pure geometry dataclasses in `models/plot`; a view-side type registry supplies selector, overlay, and options widget |
| ROI state owner | New `RoiSetModel`, not `MplCanvas` |
| View invalidation | ROIs are marked **stale** rather than deleted |

## Current state

The model layer is close to ready. `RegionDefinition.compile(frame) -> CompiledRegion`
already abstracts shape from reduction, and everything downstream consumes the boolean
mask. Three places pin the abstraction to rectangles:

- `MaterializeRequest.region` is typed `Optional[RectRegion]`.
- `MaterializeRequest.fetch_context`, `cube_view._materialize_roi_profile`, and
  `derived_fetch.assemble_plane_bundle` call `compile_rect_with_mask_mode(...)` and
  `region.normalized()`.
- `expand_rect_for_profile` (span-full) takes a `RectRegion`.

`view_crop_from_region` also takes a `RectRegion`, but that one is correct and stays.

`region_mesh.py` builds masks with cell-intersects-rectangle semantics and has no
cell-center helper.

The 2-D plane output is reachable only from the dialog's `2D plane` radio button. It
flows `build_plane_request` → `materialize_request_for_plane` → `_materialize_roi_plane`
→ `assemble_plane_bundle`, and `DerivativeController._start_commit` already refuses to
save it. Crop is a completely separate mechanism: `view_crop_from_region` builds a
`ViewCrop` of storage indices that `runSource` applies through
`apply_view_crop_to_slice_info` and `fetch_context_with_view_crop`, never touching
`MaterializeRequest.region`. The two paths are therefore already independent in the
model; only the dialog's output radio pair conflates them.

The view layer holds all ROI state in `MplCanvas` (`_roi_region`, `_roi_selector`,
`_roi_overlay`, `_roi_view_fingerprint`) wired to a single matplotlib
`RectangleSelector`. `DerivativePlotDialog` owns the operation controls and the
embedded preview; `DerivativeController` runs a debounced preview worker and commits a
`FrozenSpectrum` on save.

Committed output already supports many spectra: each save registers a synthetic
`__roi__/<uuid>` key on the run and appears in Run Display. What is single-valued today
is the live ROI and the live preview.

## Architecture

```
models/plot/
  region.py          RegionDefinition (+ RectRegion, EllipseRegion, PolygonRegion, AxisSliceRegion)
                        .compile(frame) -> CompiledRegion
                        .data_bounds() / .describe() / .to_dict() / .from_dict()
  region_mesh.py     cell_centers(frame), mask_from_vertices(), existing rect fast path
  roi_set.py         RoiOperation, RoiEntry, RoiSetModel (QObject + signals)

views/plot/
  roi_types.py       RoiTypeRegistry: id -> display name, selector adapter,
                     overlay factory, options-widget factory
  roi_window.py      RoiWindow: list, Add ROI dropdown, shape options,
                     reduction options, preview host
  roi_overlays.py    per-shape overlay artists
  preview_window.py  detached preview host
```

### Region geometry

`RegionDefinition` stays frozen, serializable, and free of Qt and matplotlib-widget
imports so the existing headless tests keep working. It gains:

| Member | Purpose |
|--------|---------|
| `region_type` | Stable string id for serialization and registry lookup |
| `compile(frame)` | Existing mask contract |
| `data_bounds()` | `(x0, x1, y0, y1)` for span-full, list readouts, and stale checks |
| `describe()` | Short human-readable summary for the ROI list |
| `to_dict()` / `from_dict()` | Provenance on `FrozenSpectrum` and session persistence |

`EllipseRegion(cx, cy, rx, ry, angle)` and `PolygonRegion(vertices)` are the first
additions. Both compile through one new primitive: `cell_centers(frame)` returns center
coordinates for every cell (from `extent` for image frames, from corner averages for
mesh frames), and `matplotlib.path.Path.contains_points` tests them. Ellipse can use the
analytic normalized-radius test on the same centers.

### Cell-center semantics

Switching rectangles from intersects to centers is a small behavior change. For ROIs
drawn on cell boundaries the selection is identical, so most existing assertions in
`test_region_mesh.py` hold. The real change is a sub-cell ROI, which currently selects
one cell and would select none. Mitigation: when a shape has nonzero area but compiles
to an empty mask, select the single cell containing the shape centroid, so a tiny ROI
still yields data rather than an error.

### Multi-ROI state

```
RoiOperation      mask_mode, profile_storage_axis, spatial_reduce,
                  span_full_profile_axis, label
RoiEntry          id, display_label, color, region, operation, visible,
                  view_fingerprint, stale
RoiSetModel       entries, selected_id, add/remove/update/clear,
                  signals: entries_changed, entry_changed, selection_changed
```

Every ROI reduces to a profile, so `MaterializeRequest.spec.plot_ndim` is always 1 on
the ROI path. That invariant is what makes the rest of the multi-ROI work tractable: all
outputs are lines, all previews overlay, and all saves are `FrozenSpectrum` entries.

`MplCanvas` stops owning ROI state and becomes a renderer plus interaction source: it
draws one colored overlay per visible entry and hosts at most one active selector for
the ROI being drawn or edited, emitting the finished geometry upward. `get_roi_region()`
survives as "geometry of the selected entry" so the crop path keeps working through the
transition.

Invalidation moves per entry. On a view-frame change each entry's stored fingerprint is
compared and mismatches are marked stale: greyed in the list, excluded from preview and
save, with a "Remove stale" action. Clearing every ROI on a slider move is acceptable for
one rectangle and hostile once a user has built up five.

### Per-ROI operations

Each ROI carries its own mask mode, profile axis, reduce, and label, so a set can mix a
summed band along one axis with a mean over a polygon along another. Since every output
is a line, they all overlay on one preview axes without special handling. A **Selected
only** toggle stays available as a decluttering convenience, not a correctness
requirement.

Two ROIs reducing along different profile axes produce curves on different x-scales.
The preview labels each curve with its axis name and warns in the status line when the
visible set spans more than one profile axis, rather than blocking it.

Save offers **Save selected** and **Save all**, registering one `FrozenSpectrum` per
ROI, labeled from the ROI label so Run Display entries stay traceable to the overlays.

### In-plane profiles with non-rectangular ROIs

There are two families of ROI reduction, matching the existing `classify_profile_kind`
split:

| Family | Profile axis | Per-bin reduction |
|--------|-------------|-------------------|
| Through-stack | Perpendicular to the display plane | The whole 2-D mask collapses to one value per stack index |
| In-plane | One of the two displayed axes | The orthogonal in-plane axis collapses within the mask, one value per bin |

Through-stack is shape-agnostic by construction. In-plane is where a non-rectangular
shape becomes interesting, and it is well defined: the mask simply contributes a different
set of cells to each profile bin. Two motivating cases:

- **Inside a trapezoid or polygon** tracking a feature whose position drifts across the
  profile axis, for example an emission line that moves with incident energy. A rectangle
  would have to be widened to contain the drift, admitting background at both ends.
- **Outside an arbitrary shape** to blank an over-exposed or noisy blob before reducing
  along a display axis, where a rectangle would discard far more good data than necessary.

No reduction code changes are needed. `_masked_reduce_along_axes` already applies
`np.where(mask, y, np.nan)` and reduces with `nansum` / `nanmean` per bin, returning NaN
for bins the mask misses entirely, which plots as a gap at the shape's edges.

#### Varying cell counts change what Sum means

For a rectangle every profile bin draws on the same number of cells, so `Sum` and `Mean`
differ by a constant. For any other shape the count varies per bin, and the two diverge in
ways that can be mistaken for signal:

| Case | `Sum` | `Mean` |
|------|-------|--------|
| Inside a trapezoid | Profile is modulated by the shape's width, so the geometry imprints on the spectrum | Normalized per bin; shape does not imprint |
| Outside a blob | Bins crossing the blob lose cells and dip, replacing a bright artifact with a dark one | Normalized per bin; the blanked region is genuinely removed |

So `Mean` should be the default whenever the selected shape is not separable along the
profile axis, and the window should say why. This matters most in the blanking case, where
`Sum` actively defeats the purpose of the operation.

Because counts matter for Poisson error estimates, a third reduce option is worth
considering: **Sum scaled to bin count**, computed as the per-bin mean times a reference
cell count. That keeps count-like magnitudes while removing the geometric modulation.
Proposed for Phase 5, and only if the mean-based default proves insufficient.

To make this visible rather than a trap, the ROI window reports the per-bin cell count
range from the compiled mask, for example `cells per bin: 3–47`. A wide spread is the
signal that `Sum` will encode geometry.

#### Span-full

Span-full exists to stop a profile being clipped along its own axis. It applies only to
inside-mode reductions on shapes that are separable along the profile axis, meaning
rectangles and axis bands. It is disabled, with an explanatory tooltip, in two cases:

- **Non-separable shapes**, where expanding the region along the profile axis would
  discard the shape the user drew. The shape's own extent is the intended limit.
- **Outside mode**, where the inverted mask already covers the full profile axis. Today
  span-full plus outside mode silently produces a mask of everything except a full-width
  band, which is a different operation from everything except the drawn shape and is
  almost certainly not what the user meant.

### Preview fetch cost

One worker per ROI, reusing `DerivativePreviewWorker`, is cheap when the parent 2-D
bundle is cached, which covers profiles along plot-plane axes. A profile along a
non-plot-plane axis triggers a real N-D load, and N ROIs would trigger N loads. The fetch
API should therefore be shaped to accept a list of regions from the start, even if the
first implementation loops; a later batched `materialize_view` variant can then produce N
profiles from one pass without changing callers.

### Crop stays separate

Crop is 2-D-to-2-D extraction whose output must go straight into `imshow`, so it stays
rectangle-only and keeps its existing `RectRegion` signature. Nothing in Phase 1
generalizes it.

Today crop is driven by the drawn ROI rectangle, and `RoiController` makes the two
mutually exclusive: apply-crop is disabled while a crop is active, and the ROI is cleared
when a crop is committed. Once ROIs are a set of arbitrary shapes, borrowing their
geometry for crop no longer makes sense. Crop gets its own rectangle: a separate draw
toggle, a separate selector, and a separate overlay drawn in a distinct style.

That also removes the exclusivity. Crop narrows the loaded plane; ROIs are then drawn and
reduced within the cropped view, which the fetch path already supports through
`region_frame_for_derivative` and `fetch_context_with_view_crop`.

### Retiring the 2-D plane path

With plane output gone from the ROI UI, these become unreachable and should be deleted
rather than left as dead branches:

| Location | Symbol |
|----------|--------|
| `derivative_plot_dialog.py` | `output_profile` / `output_plane` radios, `build_plane_request`, `is_profile_output` |
| `derived_fetch.py` | `materialize_request_for_plane`, `assemble_plane_bundle`, `display_plane_spec`, `_plane_bundle_from_mesh_crop`, `_crop_mesh_grids`, `_axis_centers_for_crop` |
| `cube_view.py` | `_materialize_roi_plane` and its dispatch branch |
| `runSource.py` | the `plot_ndim == 2` branch of the materialize path |
| `tests/test_derived_fetch.py` | plane assertions |

If a masked 2-D view is ever wanted again (blank out a bright feature, keep the rest),
it belongs as a crop option rather than as an ROI output, since the result is still a
rectangular array for `imshow`.

## ROI window layout

```
┌─ Regions of Interest ────────────────────────────────────────┐
│ [Add ROI: Rectangle ▼] [Draw] [Clear] [Delete] [Remove stale]│
│ ┌────────────────────────┐ ┌───────────────────────────────┐ │
│ │ ● roi_1  Rect    ✓     │ │ Shape                         │ │
│ │ ● roi_2  Ellipse ✓     │ │  (type-specific fields)       │ │
│ │ ○ roi_3  Polygon stale │ │                               │ │
│ │                        │ │ Reduction                     │ │
│ │                        │ │  (•) Inside  ( ) Outside      │ │
│ │                        │ │  Profile axis: [Along … ▼]    │ │
│ │                        │ │  Reduce: [Sum ▼]              │ │
│ │                        │ │  ☑ Span full profile axis     │ │
│ │                        │ │  Label: [____________]        │ │
│ └────────────────────────┘ └───────────────────────────────┘ │
│ Preview:  ☐ Selected only                    [Pop out ⇱]     │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │                                                          │ │
│ └──────────────────────────────────────────────────────────┘ │
│ status line                       [Save selected] [Save all] │
└──────────────────────────────────────────────────────────────┘
```

The shape form is built by the registry entry for the selected ROI's type, so a new type
needs no changes in `roi_window.py`. The reduction form is common to every type.

The inline `Region` panel becomes a crop panel plus a launcher: **Draw crop region**,
corner readout, **Apply crop**, **Clear crop**, and an **ROI Window…** button in place of
**Create ROI Plot**. It no longer draws ROIs, which keeps the two operations visually as
well as logically distinct.

### Preview pop-out

Reparent the single `DerivativePreviewCanvas` into a top-level window and add a
navigation toolbar, leaving a placeholder in the docked slot. One renderer and one fetch
path means the docked and floating views cannot drift. Closing the window returns the
canvas to the docked slot.

## Adding a new ROI type

1. Add a frozen dataclass in `region.py` implementing `compile`, `data_bounds`,
   `describe`, and the dict round-trip.
2. Add a registry entry in `roi_types.py` with the display name, selector adapter,
   overlay factory, and options-widget factory.
3. Add compile tests on both image and mesh frames.

## Phases

Ordered so that every phase ends in something that can be exercised by hand on live data,
and no phase leaves the application in a broken state. The consequence is that the ROI
window skeleton lands **before** the new shapes: a shape you cannot select from a dropdown
is a shape you cannot hand-test, so the window is the enabling step rather than the
capstone. Each phase lists its manual check.

### Phase 1 — model foundation

No new UI. Two separable steps, kept as distinct commits so a regression is easy to
attribute.

**1a — widen the region abstraction, retire plane output.** The only user-visible change
is the loss of the `2D plane` radio button, whose output could never be saved anyway.

- `MaterializeRequest.region` typed `Optional[RegionDefinition]`; ROI requests are
  always `plot_ndim == 1`.
- `compile_with_mask_mode(frame, region, mask_mode)` replaces
  `compile_rect_with_mask_mode` at the remaining call sites.
- `data_bounds()` on regions; `resolve_profile_region` / span-full expressed through it.
- Delete the plane path listed above.
- `view_crop_from_region` unchanged: still `RectRegion`.

**1b — cell-center masks.**

- `cell_centers(frame)` and `mask_from_vertices(frame, vertices)` in `region_mesh.py`.
- Rectangle mask switched to centers; sub-cell centroid fallback.

Acceptance: `test_region*.py`, `test_materialize_view.py`, and `test_view_crop.py` pass
unchanged; `test_derived_fetch.py` loses only its plane cases.

**Hand-test:** draw a rectangle, preview, and save a profile exactly as today. Save the
same ROI before and after 1b and confirm the spectra match for an edge-aligned rectangle;
confirm a sub-cell rectangle still returns one cell rather than an error.

### Phase 2 — ROI state model and canvas ownership

Still one rectangle, still driven from the inline panel. This is a refactor that moves
state, so the visible behavior should not change except where noted.

- `roi_set.py` with `RoiOperation`, `RoiEntry`, `RoiSetModel`.
- `MplCanvas` renders overlays from the model and hosts one active selector; its own ROI
  state is removed.
- Crop gets its own rectangle, selector, and distinctly styled overlay; the ROI/crop
  exclusivity in `RoiController` goes away.
- Per-entry stale marking replaces the global clear.

**Hand-test:** the existing draw/preview/save flow behaves as before. Apply a crop and
confirm an ROI can be drawn and reduced inside the cropped view without either clearing
the other. Move a slice slider and confirm the ROI is marked stale rather than deleted,
and that preview and save refuse to run on a stale ROI.

### Phase 3 — ROI window skeleton, rectangle only

The enabling phase. No new geometry, but the full window frame exists and binds to
`RoiSetModel`, so nothing built here needs rewiring later.

- `roi_window.py`: entry list, `Add ROI` dropdown (Rectangle only), Draw, Clear, Delete,
  Remove stale.
- Reduction controls migrate out of `DerivativePlotDialog` into the per-ROI form;
  `DerivativePlotDialog` retires.
- Preview hosted in the window, showing the **selected** ROI only, reusing the existing
  single worker unchanged.
- Inline panel reduced to crop controls plus the window launcher.

**Hand-test:** add two rectangles, see both overlays on the canvas, select either one and
watch the preview follow the selection, save each to Run Display, delete one. Crop still
works from the inline panel with no ROI interaction.

### Phase 4 — shapes

Each step is independently drawable and previewable the moment it lands, because Phase 3
supplied the dropdown and the preview.

- **4a — registry.** `roi_types.py`, with the existing rectangle re-expressed through it.
  Deliberately a small refactor whose point is to prove the extension seam before there is
  a second type to add.
- **4b — ellipse.** `EllipseRegion`, analytic mask on cell centers, `EllipseSelector`
  adapter, overlay, options widget. Circle is the constrained case.
- **4c — polygon.** `PolygonRegion`, `PolygonSelector` adapter with vertex editing.

Acceptance: ellipse and polygon compile correctly on image and non-uniform mesh frames.

**Hand-test:** per step, pick the type from the dropdown, draw it, confirm the overlay
matches the selector, and confirm the previewed profile shows gaps where the shape misses
bins entirely. Draw an ellipse in outside mode over a bright feature and confirm the
feature is suppressed.

### Phase 5 — multi-ROI preview and save

- One debounced worker per non-stale ROI with per-entry generation guards.
- Colors and labels shared between overlays, preview lines, and saved spectra.
- Selected-only toggle; mixed-profile-axis warning.
- Per-bin cell count range readout; `Mean` defaulted for non-separable shapes.
- Save selected / save all.

**Hand-test:** three ROIs of different shapes and reduce ops produce three overlaid
preview curves and three Run Display entries with matching labels and colors. Switch a
trapezoid between Sum and Mean and confirm the count readout explains the difference.

### Phase 6 — pop-out preview and persistence

- Detached preview window with toolbar.
- ROI set serialization for session restore.

**Hand-test:** pop the preview out, resize it, confirm it keeps updating and that closing
it returns the canvas to the window.

## Open items

- A **banded polyline** ROI type, a path with a width, as the natural tool for a feature
  that drifts across the profile axis. A trapezoid approximates this by hand; a polyline
  with width would track the drift directly and keeps the integration width constant, so
  `Sum` stays meaningful. Candidate for the first shape added after ellipse and polygon.
- Whether `Sum scaled to bin count` is needed alongside `Sum` and `Mean`.
- Whether ROI sets should be shareable across canvases (`ImageGridWidget`).
- Whether a batched multi-region `materialize_view` is needed before Phase 5 ships, based
  on measured N-D load cost.
- Export of ROI geometry alongside spectra in `export_to_xdi`.
