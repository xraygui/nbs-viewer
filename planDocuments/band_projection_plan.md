# Band projection plan

A sibling tool to ROI and crop that collapses **one** in-plane axis inside a
drawn band and yields a **2-D** image of the kept spatial coordinate versus the
stack / scan axis (e.g. `dim_1` × `sampleVoltage_VSource`).

ROI stays **1-D only** ([`roi_workbench_plan.md`](archive/roi_workbench_plan.md)). Crop
stays **same-plane 2-D** extraction. Band projection is the third product.

## Motivation

Dimension Control can already Sum one storage axis and plot the other against
Z, but the sum always spans the full axis (or a clumsy view crop), and the
geometry is locked to storage axes. Users want to draw a band on the current
X–Y image, average across the band width, and see how that projection evolves
along Z.

V1 is an axis-aligned rectangle. The model must not bake in “grid indices along
X or Y”; that is only the first sampler. A later line-with-width must reuse the
same extract → interpolate → reduce pipeline, with interpolation becoming
real instead of a no-op.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Relation to ROI | **Separate tool** (approach C). Not an ROI output mode |
| Relation to crop | Independent; crop may still narrow the parent view underneath |
| V1 geometry | Axis-aligned **rectangle** on the parent plot plane |
| V1 collapse | Exactly one parent plot-plane axis (`plot_x` or `plot_y`) |
| V1 reduce | `mean` default; `sum` available |
| Kept spatial bins | Only bins that **intersect** the band (not span-full on the kept axis) |
| Stack axis | Full span of the leading scan / INDEX axis (same rule as stack spectra) |
| Interpolation (V1) | **Identity** — samples coincide with cell centers / integer indices |
| Preview | Band window preview only; **no save / freeze** in V1 |
| Commit / Run Display | Deferred; 2-D frozen products are a later phase |
| Outside / mask mode | Not in V1 |
| Multi-band | Not in V1 (single band, like early ROI) |

## Product comparison

| Tool | Output | Geometry role |
|------|--------|---------------|
| Crop | 2-D, same axes as parent view | Narrow load / display window |
| ROI | 1-D profile | Mask → collapse **all** reduced in-plane axes |
| Band projection | 2-D: kept spatial × stack | Band → collapse **width** → image vs length × Z |

Do **not** revive the retired ROI “2D plane” path (masked XY of the parent
view). That product is not band projection.

## Architecture

```
models/plot/
  band.py              BandDefinition, RectBand, (later LineBand)
  band_sample.py       BandSampling, GridAlignedSampling, (later PathSampling)
  band_interpolate.py  BandInterpolator protocol, IdentityInterpolator,
                       (later NearestInterpolator, BilinearInterpolator)
  band_reduce.py       reduce_across_width(...)
  band_fetch.py        band_view_spec, materialize_request_for_band,
                       materialize_band_view
  band_model.py        BandProjectionModel (QObject + signals)

views/plot/
  band_window.py       draw/clear, collapse axis, reduce, 2-D preview host
  band_controller.py   canvas overlay + selector + stale handling
```

ROI code (`roi_set`, `roi_window`, `profile_view_spec`, `_materialize_roi_profile`)
is not extended to emit 2-D. Band may **reuse** `PlotViewFrame`,
`RectRegion` / region compile helpers, and fetch-slice patterns, but the
reduction contract is different.

### Pipeline (the compatibility seam)

Every band materialization runs the same stages:

```
BandDefinition
    │  sample(frame) → BandSampling
    ▼
sample coordinates in plane
    │  (i, j) indices  — or —  (x, y) float positions
    ▼
extract slab along stack  →  values[..., n_along, n_across]
    │  interpolate(grid, samples)     # Identity in V1
    ▼
values_on_band[..., n_along, n_across]
    │  reduce across n_across (mean / sum)
    ▼
image[..., n_along]  +  along-axis coordinates
    │  attach full stack axis as the other plot axis
    ▼
PlotBundle (ndim=2, image or mesh)
```

**V1 (`RectBand` + `GridAlignedSampling` + `IdentityInterpolator`):**

- `along` = kept plot axis cell centers whose cells intersect the rect.
- `across` = collapsed plot axis indices inside the rect.
- Extraction is integer gathers / a masked reduce on the native tensor axes.
- `IdentityInterpolator` returns the gathered values unchanged.
- Numerically identical to “mask rect → `nanmean`/`nansum` along collapse axis.”

**Later (`LineBand` + `PathSampling` + real interpolator):**

- `along` = arc-length (or parameterized) samples along the center line.
- `across` = samples along the local normal, spanning ±width/2.
- Extraction asks the interpolator for values at float `(x, y)` for every
  stack plane (or once per plane in a loop / vectorized map).
- Reduce across `n_across` unchanged.
- Subdivision density, interpolator choice, and width semantics land in
  `BandSampling` / `BandInterpolator` options — not in a forked materialize
  path.

### Core types

```python
@dataclass(frozen=True)
class BandSampling:
    """
    Discrete samples for one band on the parent plot plane.

    along_coords : (n_along,) float
        Coordinate values for the kept / path axis (data units or arc length).
    across_coords : (n_across,) float
        Coordinate values across the width (data units; may be signed offset).
    sample_rows : (n_along, n_across) float
        Plot-Y data coordinates of each sample (or NaN if unused).
    sample_cols : (n_along, n_across) float
        Plot-X data coordinates of each sample (or NaN if unused).
    grid_rows : (n_along, n_across) int or None
        Optional integer row indices when samples are grid-aligned.
    grid_cols : (n_along, n_across) int or None
        Optional integer column indices when samples are grid-aligned.
    along_name : str
        Label for the kept axis.
    """

class BandDefinition(ABC):
    band_type: ClassVar[str]

    @abstractmethod
    def sample(self, frame: PlotViewFrame) -> BandSampling:
        """Build along/across sample lattice on the parent frame."""

    @abstractmethod
    def describe(self) -> str: ...
    @abstractmethod
    def to_dict(self) -> dict: ...


@dataclass(frozen=True)
class RectBand(BandDefinition):
    """
    Axis-aligned rectangle treated as a band.

    collapse : 'plot_x' | 'plot_y'
        Axis reduced across the band width.
    x0, x1, y0, y1 : float
        Rectangle in parent data coordinates.
    """
    # sample() fills grid_rows/grid_cols; sample_rows/cols are cell centers


class BandInterpolator(Protocol):
    def interpolate(
        self,
        plane: np.ndarray,          # 2-D plot plane (row, col)
        sampling: BandSampling,
        frame: PlotViewFrame,
    ) -> np.ndarray:                # (n_along, n_across)
        """Map plane values onto the band sample lattice."""


class IdentityInterpolator:
    """Require grid_rows/grid_cols; gather by integer index."""
```

`RectBand.sample` always populates `grid_*`. `IdentityInterpolator` refuses
samplings that lack integer indices, so a future `LineBand` cannot silently
take the wrong path — it must pick a non-identity interpolator.

### Output view spec

`band_view_spec(parent, collapse_storage_axis, spatial_reduce) -> CubeViewSpec`
with `plot_ndim=2`:

| Storage axis | Role |
|--------------|------|
| Collapse (one parent plot-plane axis) | `SUM` or `MEAN` (encoding only; actual reduce is across-width) |
| Kept parent plot-plane axis | `PLOT_X` or `PLOT_Y` |
| Scan / stack axis | the other of `PLOT_X` / `PLOT_Y` |
| Remaining INDEX axes | unchanged (fixed slice) |

Scan axis selection follows the same leading-scan rule as
`scan_profile_storage_axis` / stack spectra: full axis, not ROI-limited.

Implementation note: the role encoding documents intent for fetch/slice
helpers; the actual across-width reduce goes through `band_reduce` after
interpolate, not through `_materialize_roi_profile`. Do not force band
through the 1-D ROI materialize branch.

### State and UI

```
BandProjectionModel
    region / band definition
    collapse_axis   # plot_x | plot_y
    spatial_reduce  # mean | sum
    view_fingerprint, stale
    signals: band_changed, stale_changed
```

**Band window** (non-modal, parallel to ROI window):

- Draw / Clear rectangle
- Collapse: Plot X | Plot Y
- Reduce: Mean | Sum
- Status + 2-D preview (image/mesh + colorbar)
- Launcher on the inline Region/Crop panel: **Band Window…**

Canvas overlay style distinct from ROI and crop. Stale on view-frame change,
same fingerprint idea as ROI.

### Fetch cost

Stack axis is typically INDEX; materializing a band needs the plot plane for
every stack index (or an N-D slab with both plot axes + stack). V1 may load
via existing cube-view slice patterns with the collapse axis narrowed to the
rect bbox when `GridAlignedSampling` applies (cheap path). Off-grid bands
later may still load the bbox or full plane, then interpolate — load policy
is a `BandSampling` concern, not a separate API.

## Phases

### Phase 0 — sampling and reduce (headless)

No UI.

- `BandSampling`, `RectBand.sample`, `IdentityInterpolator`, `reduce_across_width`
- Unit tests: rect on image frame and non-uniform mesh frame; collapse X vs Y;
  mean vs sum; empty intersection errors
- Prove V1 numerically matches mask + `nanmean`/`nansum` along the collapse axis

**Hand-test:** none (unit only).

### Phase 1 — materialize + band window, rectangle only

- `band_view_spec`, `materialize_request_for_band`, `materialize_band_view`
- `BandProjectionModel`, canvas draw/overlay, `band_window` with 2-D preview
- Inline **Band Window…** launcher
- Stale marking

**Hand-test:** on a 3-D cube viewed as `dim_0`×`dim_1` with Z = `sampleVoltage`,
draw a vertical band, collapse Plot X, confirm preview is intensity vs
`dim_0`×Z localized to the band; compare to Dimension Control Sum-over-X after
a matching crop (should agree within float noise for Mean/Sum as chosen).

### Phase 2 — commit / apply (optional follow-on)

Choose one after living with preview:

- **Apply to main plot** — push a temporary cube-view + crop equivalent, or
- **Frozen 2-D product** — parallel to `FrozenSpectrum` but for images

Deferred until preview proves the product.

### Phase 3 — leave the grid

- `LineBand` (center line + width) or rotated rect
- `PathSampling` producing float `sample_rows`/`sample_cols` without `grid_*`
- `NearestInterpolator` / `BilinearInterpolator` (and UI for choice)
- Subdivision / `n_along` / `n_across` controls
- Same window and materialize entry points; new band type + interpolator only

## Open items

- Whether Apply-to-main or Frozen-2-D is the right Phase 2 commit story
- Whether mesh frames need a distinct gather path for Identity beyond cell
  centers already provided by `PlotViewFrame`
- Color scale policy in the band preview (independent vs match parent)
- Whether band should refuse to open unless parent `ndim >= 3` with a scan axis
- Shared canvas interaction manager so ROI / crop / band selectors do not fight

## Implementation checklist

- [ ] Plan document (this file)
- [ ] Phase 0: `band_sample` / `IdentityInterpolator` / reduce + tests
- [ ] Phase 1: materialize + model + window + preview
- [ ] Phase 1 hand-test on live 3-D cube
- [ ] Phase 2: commit strategy (decide after Phase 1)
- [ ] Phase 3: path sampling + real interpolation
