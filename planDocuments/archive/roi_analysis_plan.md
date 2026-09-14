# ROI analysis implementation plan

Track implementation of region-of-interest (ROI) extraction and derived spectra in nbs-viewer.

## Goals

| Workflow | Description |
|----------|-------------|
| **A** | 2D plot → ROI → partial reduction → 1D spectrum along remaining plot axis |
| **B** | Fixed 2D mask from reference slice → integral vs stack (Z) axis |
| **Shared** | `RegionDefinition` → `CompiledRegion` (mask + bbox) on `PlotViewFrame` |

## Architecture (locked)

```
PlotViewFrame          # shape, axis names, image or mesh coordinates
RegionDefinition       # Rect, AxisSlice, Polygon (P3), Mask import (P5)
    └─ compile() → CompiledRegion(mask, bbox)
MaterializeRequest     # spec + region + mask_mode (see materialize_view_refactor_plan.md)
materialize_view()     # Workflow A — profiles and masked 2D planes
extract_stack_spectrum() # Workflow B (Phase 4 below)
```

**Reduction order:** load → `materialize_view` → `prepare_*_bundle` (norm + transform applied in `RunModel._fetch_plot_arrays` before materialization).

**Workflow A (profiles + planes)** is implemented via the unified materialize pipeline documented in [`materialize_view_refactor_plan.md`](materialize_view_refactor_plan.md).

**Z / mask:** Fixed mask from drawn ROI on reference slice. **Thresholding deferred** to a separate project.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Mesh / `pcolormesh` | Phase 0+1 (main use case: `tes_mca_energies`) |
| Threshold | Separate project, not in phases below |
| Z-stack mask | Fixed from drawn ROI on reference slice |
| Mask representation | `CompiledRegion` bool array matching `PlotBundle.y` shape + bbox |
| Coord space | Matplotlib data coords → cell centers |
| Phase 1 UI | Collapsible **Region** panel under **Dimension Control** on `PlotWidget` (not sidebar) |
| Phase 1 ROI count | Single ROI; multi-ROI in Phase 3 |
| Phase 1 draw UX | Explicit **Draw region** toggle; clear button |
| Phase 1 status display | Corner values in data coords (no pixel count) |
| Phase 1 enablement | Region panel active only in **2D** mode (`image` / `mesh`) |
| Phase 1 derived plot | **None** — draw/control only |
| Phase 2 derivative UI | **Create Derivative Plot** button → modal dialog; optional live preview in dialog |
| Phase 2 committed plot | **TBD** per output type (1D comparison overlay vs 2D splitter/tab) |
| View invalidation | Clear ROI + status line (not dialog per slider move) |
| Multi-dataset | Region disabled unless exactly one visible 2D trace |
| ROI edit | Re-enable **Draw region** to adjust existing rectangle |
| Empty ROI | Allowed in Phase 1; status notes zero cells; Phase 2 errors on fetch |

## Phase 0 — Foundation

**Status:** complete

### Deliverables

- `models/plot/plot_view_frame.py` — `PlotViewFrame`, `frame_from_bundle()`
- `models/plot/region_mesh.py` — data coord → cell mask (image + mesh)
- `models/plot/region.py` — `RectRegion`, `AxisSliceRegion`, `CompiledRegion`
- `models/plot/region_reduce.py` — `reduce_masked_plane` (scalar test helper)
- `models/plot/cube_view.py` — `MaterializeRequest`, `materialize_view` (see materialize refactor plan)
- `tests/test_region.py`, `tests/test_region_mesh.py`

### Acceptance

- [ ] Rect and axis-slice on non-uniform col axis (TES-like)
- [ ] Profile along plot X / plot Y (unit tests on reduction path)
- [ ] Existing tests unchanged

## Phase 1 — Rect ROI draw and control

**Status:** complete

Focus: define and edit a single rectangle ROI on the current 2D view. No derived 1D plot.

### Deliverables

- `views/plot/roi_panel.py` — Draw toggle, Clear, corner readout (data coords)
- `views/plot/roi_controller.py` — panel ↔ canvas, holds `RectRegion`, invalidation
- `views/plot/mpl_canvas.py` — `RectangleSelector`, overlay, ROI mode vs pan/zoom
- `views/plot/plotWidget.py` — `CollapsiblePanel("Region", …)` below dimension control

Depends on Phase 0 (`RectRegion.compile`, `frame_from_bundle` for overlay/mask alignment).

### Integration

- `PlotWidget`: `CollapsiblePanel("Region")` below Dimension Control; `RoiController` wires panel, `DimensionControl`, `RunListModel`, `MplCanvas`.
- `MplCanvas`: `RectangleSelector` when draw is on; cyan overlay patch when off; `roi_region_changed` / `plot_view_updated` signals; overlay re-applied after async plot worker redraw.
- Invalidation: slice indices, cube axis order, 1D↔2D, run display X/Y/norm key changes.

### UI behavior

- **Draw region** toggles ROI mode on the canvas; turning off exits draw mode but keeps the region until cleared or invalidated.
- **Clear** removes selector, overlay, and corner readout.
- Corner labels update when the rectangle changes (matplotlib data coordinates).
- Panel and draw controls **disabled** when not in 2D (`currentDim == 2` and render mode `image` or `mesh`; same single-dataset constraints as 2D dimension control where applicable).
- Slice index, plot axis assignment, field, or 2D→1D transition **clears** ROI and shows a short warning (status or one-shot message).

### Acceptance

- [ ] Rectangle ROI on mesh (`tes_mca_spectrum`) — draw, overlay, corners shown
- [ ] Rectangle ROI on uniform `image` — draw, overlay, corners shown
- [ ] Draw toggle does not fight navigation toolbar when off
- [ ] Slice/field/axis change clears ROI
- [ ] Region panel disabled outside 2D mode
- [ ] Manual GUI verification on live Tiled data

## Phase 2 — Derivative plots (dialog + preview)

**Status:** in progress (modeless dialog + live preview; Create/Pin pending)

Configure and create derived 1D profiles or 2D planes from the current ROI. The Region panel stays minimal; derivative options live in a dialog.

### Entry point

- **Region panel:** `Create Derivative Plot` button (enabled when a valid ROI exists on a single 2D trace).
- Opens a **modal or modeless dialog** (`DerivativePlotDialog`) with room for labels, axis names, and a preview pane.

### Dialog layout (concept)

```
┌─ Create Derivative Plot ─────────────────────────────┐
│ Source: <scan> · <ykey> · slice summary            │
│ ROI: (x0,y0) — (x1,y1)                             │
│                                                     │
│ Operation                                           │
│   Region:  (•) Inside ROI  ( ) Outside ROI         │
│   Output:  ( ) 1D profile  ( ) 2D plane             │
│   [Profile axis: plot X ▼]  [Reduce: Sum ▼]        │
│        ↑ enabled only for 1D profile               │
│   Label: [________________]                         │
│                                                     │
│ ☑ Preview plot in dialog                           │
│   ┌─────────────────────────────────────────┐      │
│   │  (MplCanvas or embedded figure)         │      │
│   └─────────────────────────────────────────┘      │
│                                                     │
│ Destination (committed plot, not preview)           │
│   1D: ( ) Overlay on line plot  ( ) New pane ▼     │
│   2D: ( ) Splitter below parent ( ) Tab ▼          │
│                                                     │
│        [Create]  [Pin for comparison]  [Cancel]     │
└────────────────────────────────────────────────────┘
```

### Preview checkbox

| Setting | Behavior |
|---------|----------|
| **Checked** (default on open) | Dialog runs debounced fetch (worker thread); embedded preview updates when ROI (if dialog open), slice, or operation fields change. |
| **Unchecked** | No preview compute/draw; **Create** still runs full fetch on click. |

Preview is **ephemeral** (discarded on dialog close). **Create** / **Pin** produce durable products.

### Operations (maps to `MaterializeRequest`)

| Region | Output | Extra | Use case |
|--------|--------|-------|----------|
| Inside | 1D profile | axis + sum/mean | Sum along axis within ROI bounds |
| Inside | 2D plane | crop (+ optional mask) | Zoomed view / dedicated color scale |
| Outside | 1D profile | axis + sum/mean | Integrate excluding ROI |
| Outside | 2D plane | crop outside / inverted mask | Suppress bright feature |

Model: `MaterializeRequest` (`spec`, `region`, `mask_mode`); profile vs plane distinguished by `spec.plot_ndim`. See [`materialize_view_refactor_plan.md`](materialize_view_refactor_plan.md).

### Data management

- **`MaterializeRequest`** — frozen view + ROI parameters from the dialog.
- **`DerivedProduct`** — `request`, source plot key, cube-view fingerprint, resulting `PlotBundle`, timestamp.
- **Preview** — held only by the dialog controller; debounced recompute (~150 ms).
- **Create** — commits 1D profiles (2D plane commit deferred).
- **Pin for comparison** — appends to display-scoped **comparison bank** (1D spectra list).

### Deliverables

- `models/plot/cube_view.py` — `MaterializeRequest`, `materialize_view`
- `models/plot/derived_fetch.py` — `fetch_materialized_bundle`, request builders
- `models/plot/derived_product.py` — pinned profile storage
- `models/plot/derived_series_registry.py` — pinned / comparison list per display
- `models/plot/derived_plot_data_model.py` — frozen bundle as plottable series
- `views/plot/derivative_plot_dialog.py` — dialog UI + preview canvas
- `views/plot/roi_panel.py` — **Create Derivative Plot** button only (no dense controls)
- `views/plot/derivative_controller.py` — dialog ↔ fetch ↔ destinations
- `tests/test_derived_fetch.py`

### Acceptance

- [x] Dialog opens with ROI context; preview checkbox toggles live preview (modeless)
- [x] Preview updates when ROI or operation fields change (debounced worker)
- [x] Preview: 1D profile along plot X / plot Y / stack INDEX axis (mesh + image)
- [x] Preview: 2D masked plane crop (mesh + image)
- [x] Create / Pin for 1D profiles
- [ ] Create / Pin for 2D planes (deferred)
- [ ] Inside ROI → 2D plane with independent color scale in chosen pane (committed)
- [x] Empty ROI → clear error on fetch (not on every preview frame)
- [x] Dialog close does not leave orphan preview artists on parent canvas

## Phase 3 — Multi-ROI, lasso

**Status:** superseded by [`roi_workbench_plan.md`](roi_workbench_plan.md)

That plan also retires the 2D-plane ROI output described in Phase 2 above: ROIs reduce to
1D only, and 2D extraction is handled by crop.

- `PolygonRegion` + lasso selector
- Dialog + comparison bank support multiple pinned entries per ROI

## Phase 4 — Z-through-stack

**Status:** pending (stack profiles along INDEX axes are covered by the materialize refactor; this phase is fixed-mask integral vs Z only)

- `extract_stack_spectrum()` with fixed compiled mask
- Stack axis selector, “Plot vs Z”

## Phase 5 — Performance & integration

**Status:** pending

- Bbox-limited chunk reads, progress UI
- `ImageGridWidget` shared ROI
- Export ROI metadata (`export_to_xdi` alignment)
- Optional `MaskRegion` import

## Phase 6 — Polish

**Status:** pending

- Session persistence, display registry, multi-canvas alignment

## Separate project: threshold / segmentation

Not scheduled here. Will add `ThresholdRegion` compiling to `CompiledRegion` when started.

## Implementation checklist

- [x] Plan document (phased; Phase 1 = draw/control only)
- [x] Phase 0 modules + tests
- [x] Phase 1 ROI panel + controller + canvas hooks
- [ ] Manual test on mesh 2D map (GUI)
- [x] Phase 2 derived fetch + 1D presentation
- [x] Phase 2 `test_derived_fetch.py`

## File tree

```
nbs_viewer/models/plot/
  plot_view_frame.py      # P0
  region_mesh.py          # P0
  region.py               # P0
  region_reduce.py        # P0
  cube_view.py            # MaterializeRequest, materialize_view
  derived_fetch.py        # P2 (unified fetch_materialized_bundle)
  derived_product.py      # P2
  derived_plot_data_model.py  # P2

nbs_viewer/views/plot/
  derived_series_registry.py  # P2
  roi_panel.py            # P1 (+ Create Derivative button P2)
  roi_controller.py       # P1
  derivative_plot_dialog.py   # P2
  derivative_controller.py    # P2
  mpl_canvas.py           # P1+
  plotWidget.py           # P1 (Region collapsible panel)

tests/
  test_region.py          # P0
  test_region_mesh.py     # P0
  test_derived_fetch.py   # P2
  test_materialize_view.py
```
