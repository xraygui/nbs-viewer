# Data contract plan

What a data source returns, and why `RunSource` is a different object from
`CatalogRun`.

This is the `RunSource` refactor, but it is written from the data layer
because that is where its logic starts: `RunSource` is hard to read because
the thing it is handed has no name. Standalone — it proceeds by its own
argument and is not gated on
[`module_organization_plan.md`](module_organization_plan.md), though it
changes what that plan should do (see **Kept in mind**, below).

**Absorbs** `structural_remediation_plan.md` step 9, "Enforceable data-layer
contract", never started.

**Status:** drafted 2026-09-10 and revised twice the same day — to adopt
`xarray` rather than a bespoke type, and to settle coordinates onto the array.
Not started. Numbers measured at `74a7d6d`.

---

## The diagnosis

### The protocol already exists, spelled in three pieces

`CatalogRun` exposes `getData` / `getShape` / `get_dimension_axes`.
`FrozenSpectrum` exposes `get_data` / `get_shape` / `get_dimension_axes` —
with a **byte-identical return annotation**,
`Tuple[List[np.ndarray], List[str], Dict[str, Dict[str, Any]]]`.

Two sources, one shape, written twice and returned in pieces. So every
consumer re-assembles them, and `RunSource` performs the same two-way branch
five separate times:

| `RunSource` method | body |
|---|---|
| `read` | frozen? `entry.get_data(…)` : `run.getData(…)` |
| `load_axes` | frozen? `entry.get_dimension_axes(…)` : `run.get_dimension_axes(…)` |
| `describe_axes` | frozen? … : `run.analyze_dimensions(…)` |
| `get_shape` | frozen? … : `run.getShape(…)` |
| `get_plot_hints` | frozen? … : `run.getPlotHints(…)` |

**Five methods, one dispatch, written five times.** That is what makes the
`RunSource` / `CatalogRun` split feel artificial: not the split, the
*interface*. A union performed once is an abstraction; a union performed five
times is a copy.

### The pipeline's middle value has no name

Counting every parameter of the pipeline functions in `plot_geometry`,
`plot_bundle`, `run_source` and `plot_view_frame`:

| One concept | …under how many names | slots |
|---|---|---:|
| the array | `y`, `plane`, `arr` | 20 |
| per-axis coordinates | `axis_arrays`, `x_axes`, `arrays`, `coords`, `xlist`, `row_axis`, `col_axis` | 18 |
| per-axis names | `axis_names`, `names`, `y_axis_names`, `y_storage_names`, `y_dim_names`, `key_dim_names`, `storage_names` | 12 |
| the plot plane | `plot_plane_storage_axes`, `plane_axes`, `plane_shape`, `y_shape` | 9 |
| which axes reversed | `reversed_storage_axes`, `reversed_names`, `row_reversed`, `col_reversed` | 8 |
| render mode | `render_mode_hint`, `render_mode` | 5 |
| storage→tensor map | `storage_to_tensor`, `tensor_axes` | 2 |

**74 parameter slots, 29 names, one unnamed thing.**

The pipeline has a noun at both ends — `PlotRequest` in, `PlotBundle` out —
and none in the middle, where the work happens. That is why every level of
`get_plot_bundle` → `_load_block` → `_normalized_block` does raw array work:
unpacking and re-deriving the axis context **is** the raw work.

### The workaround that proves it

`RunSource._truncate_dim_names` — 24 lines that **pad or truncate** dimension
names until they match the array's rank — is a consumer-side patch for
backends disagreeing about their own axis count. It is what silences
**bug 6**: `BlueskyRun` returns `('time','dim_0','dim_1')` for a rank-2 array
and this quietly clips it.

### `AxisLayout` is already mostly dead

Of its five fields: `shape` has 8 readers, `names` 6, `placeholders` 4 (and is
`np.arange(n)` per dimension — derivable), `associated` 3 (and is documented
as always empty on this path), **`analysis` has zero readers**.

The metadata-only call needs **names and lengths**. Nothing else.

### The layering is already violated, upward

`models/data/bluesky.py:7` imports `is_synthetic_key` from
`models/plot/frozen_spectrum`. `FrozenSpectrum` is a **data source for one
key** that lives in the plot layer, and the data layer has to reach up for its
key-prefix convention. Under this contract it becomes a data source proper and
moves down, closing a violation that exists today rather than creating one.

---

## The contract is `xarray.DataArray`

The first draft of this plan invented a frozen `AxisArray` dataclass. That was
re-deriving xarray, and the maintainer said so. Checked rather than assumed:

**xarray is already a guaranteed runtime dependency**, undeclared:

```
nbs-viewer → bluesky-widgets>=0.0.15 → bluesky-live>=0.0.7 → xarray
```

Non-extra at every hop; installed here at 2025.9.0 and used nowhere in the
codebase. Adopting it means *declaring* a dependency the project already
ships, not adding one.

**It enforces the contract the bespoke type was designed to enforce**, with
better messages:

```
xr.DataArray(rank2_array, dims=["time", "dim_0", "dim_1"])
  → ValueError: different number of dimensions on data and dims: 2 vs 3
xr.DataArray(a, dims=["time","pixel"], coords={"pixel": arange(31)})
  → CoordinateValidationError: conflicting sizes for dimension 'pixel'
```

The first of those *is* bug 6, caught at construction.

**It is what the ecosystem speaks.** Tiled, databroker and bluesky all use
xarray, so `CatalogRun.load() -> xr.DataArray` is legible to anyone working in
that ecosystem in a way a bespoke type never is.

So the contract is:

```python
def describe(key) -> KeyInfo                     # static facts; reads nothing
def load(key, slice_info=None) -> xr.DataArray   # dims named, coords attached
```

`KeyInfo` survives and gains the axes, which is what collapses the several
current ways of asking for key metadata into one:

```python
@dataclass(frozen=True)
class KeyInfo:
    name: str
    label: str
    axes: Mapping[str, int]      # axis name -> length; new
    synthetic: bool
    hinted: bool
    render_hint: Optional[str]

    @property
    def shape(self) -> Tuple[int, ...]:
        return tuple(self.axes.values())
```

`shape` stays available as a derived property, so its readers are untouched.
`key_table()` becomes `{key: describe(key)}` — one implementation rather than a
parallel one — and `describe_axes`, `get_shape` and `get_plot_hints` all fold
into it. **Four ways to ask for key metadata become one.**

### `describe` takes no `xkeys`, and the reason is a bug

`describe_axes(ykey, xkeys)` takes the X selection today because the selection
changes the answer. Measured on the VPPEM fixture:

```
describe_axes("PCOEdge_image", [])                        -> ('sampleVoltage_VSource', 'dim_1', 'dim_2')
describe_axes("PCOEdge_image", ["time"])                  -> ('time',                  'dim_1', 'dim_2')
describe_axes("PCOEdge_image", ["i0"])                    -> ('i0',                    'dim_1', 'dim_2')
```

Selecting `i0` as X renames the event axis to `i0`. That is not a dimension
name — the axis is still the event axis — it is *what we are plotting against*.
Two different facts are being carried in one field, which is why the call needs
the selection and why `KeyInfo` could not hold the answer.

**xarray separates them natively.** Dimensions are static; a dimension may
carry any number of *non-dimension coordinates*, and `swap_dims` chooses which
one is the plot axis. Verified:

```python
det.dims     -> ('time', 'dim_1', 'dim_2')
det.coords   -> ['time', 'voltage', 'i0']     # all three on the event axis
det.indexes  -> ['time']
det.swap_dims({"time": "i0"}).dims -> ('i0', 'dim_1', 'dim_2')
```

So the X selection stops being a describe-time parameter and becomes a
coordinate choice at plot time. `describe(key)` is static, selection-free, and
cacheable — which is what `KeyInfo` was documented to be all along.

### Bug 15, found while settling this

With **no** X key selected, `analyze_dimensions` falls back to the run's
declared motors and assigns them to axes positionally, overriding the key's own
correct dimension names:

```
run.get_dims("detector_cube", [])   -> ('time',  'pixel', 'dim_2')   the key's own dims
describe_axes("detector_cube", [])  -> ('pixel', 'pixel', 'dim_2')   wrong, and duplicated
describe_axes("detector_cube", ["en_energy"]) -> ('time', 'pixel', 'dim_2')   correct again
```

No X key selected is the *initial* state, so this is reachable by opening a
run. And duplicate dimension names are not caught by the contract: xarray
constructs the array and warns — *"most xarray functionality is likely to fail
silently if you do not [rename]"* — rather than raising. Taking dimension names
from the key's own metadata, which is already correct, removes the fallback
that causes it.

This joins step 1: it is a third case of a backend-or-analysis layer disagreeing
with a key's own declared dimensions, alongside bugs 6 and 7.

### `DataArray`, not `Dataset`

A `Dataset` would carry `y` and its normalization keys together and align them
automatically, which is superficially attractive since alignment is the point.
Rejected on the workflow: **norms are toggled on and off and swapped
constantly**, so bundling them means rebuilding the container on every change
of something that is not the data. One array per object; alignment happens at
the divide.

### The two defaults that must be pinned

xarray's convenience defaults are both silent-wrong-answer generators for this
pipeline. Measured, not assumed:

| Default | What it does here | Required setting |
|---|---|---|
| `skipna=True` for float reductions | `.sum(dim=…)` is NaN-aware. Step 3 deliberately separated `np.sum` (projection reduce) from `np.nansum` (masked ROI reduce); this erases the distinction — and costs 182 ms against 24 ms on a 52M-float camera array | `skipna=False` everywhere **except** the masked ROI reduce |
| `arithmetic_join="inner"` | `y / norm` on coordinates that do not match **silently drops rows** — verified: a 5-row `y` divided by a 4-row norm returns 4 rows | `arithmetic_join="exact"`, which raises `AlignmentError` instead |

Both belong in a module-level `xr.set_options(...)` at the pipeline boundary
plus explicit per-call flags, and both need a test that fails if the setting is
removed. A default that silently changes an answer is exactly what this
codebase's last thirteen bugs were made of.

### Coordinates, and why fly-scan data settles it

A `DataArray` can carry dimension *names* alone, or names plus coordinate
*values*. The pipeline works today on names alone — `_aligned_norm` matches a
norm array to `y` by axis name — so names looked sufficient.

They are not, and the case that proves it is one this codebase does not yet
handle. **Fly-scanned data**, raised by the maintainer as a coming
requirement: instead of a scan stepping and reading every detector at each
step, each detector produces a raw timestream sampled as fast as it can go.
Different keys then have different lengths *and different time values*, and
plotting them together needs interpolation onto a common base, binning, or
each array plotted against its own axis.

With that data, two keys whose axis is named `time` no longer share that axis.
Measured on staggered 1000-point timestreams of equal length:

```
dims only, no coordinates  ->  det / i0 returns (1000,)   divided at mismatched times, silently
coordinates + exact join   ->  AlignmentError              caught
```

Equal length is what makes it dangerous: a length mismatch already raises, so
the failure only appears when two detectors run at the same rate out of phase
— which is the normal case, not the exotic one. This is bug 6's family again:
a name that does not mean what the consumer assumes.

The cost was measured, and it is not a reason to hesitate:

| 5M points | build |
|---|---:|
| bare dimension, no coordinate | 0.03 ms |
| non-indexed coordinate | 6.0 ms |
| **indexed dimension coordinate** | **6.4 ms** |
| divide of two indexed 5M arrays under `exact` | 32 ms |

(An earlier measurement of 2566 ms for the indexed case was `tracemalloc`'s
allocation-tracking overhead, not xarray. Re-measured without it.) The real
cost is memory — the index holds roughly one more copy of the coordinate
array, ~40 MB per 5M float64 axis — which should be checked against a real
camera run during step 2, not assumed either way.

`arithmetic_join="exact"` still catches a plain length mismatch on a bare
dimension, so leaving a placeholder axis uncoordinated loses nothing: the
guard is strongest where there is real information and degrades to a shape
check where there is not.

Two further things fall out, and they are the fly-scan feature rather than
this plan's business — recorded so the decision is not re-litigated later.
`i0.interp(time=t1)` and `det.groupby_bins("time", edges).mean()` are one call
each; both were run. Interpolation and binning across mismatched time bases is
most of what fly-scan plotting needs, and it arrives with the coordinates.

**Not to be implemented now.** The decision this settles is only that
coordinates go on the array.

### What xarray does not carry: provenance

`.attrs` is dropped **silently** by `.sum()`, by arithmetic, and by
`xr.where()` — three of the pipeline's own stages — while surviving
`.transpose()` and `.isel()`. Verified. So the two provenance facts the
pipeline uses today cannot ride in attrs:

- **`storage_axis`** — which raw dimension an axis was, before indexing.
  Needed because `Projection.roles` is a tuple indexed by storage axis.
- **`reversed`** — whether an axis was flipped to reach display order. Needed
  so a norm key sharing a plot-plane axis is flipped the same way.

**Both are already recorded on `FetchPlan`**, and settling whether that is
enough is step 4's real content:

- `slice_info` says which storage axes survive — an integer item indexes one
  away — so the surviving axes are a derived property of the plan.
- `plane_frame.row_reversed` / `col_reversed` record the flip. Step 3 put it
  there precisely because a narrowed block can no longer show the coordinate
  direction.

And `reversed` may not be needed at all once both arrays are `DataArray`s:
`_normalized_block` reverses the norm array by axis name today only so it
matches `y`. Under `arithmetic_join="exact"` with coordinates attached, `y /
norm` either aligns correctly by coordinate value or raises — which is
strictly better than a manual flip that can be forgotten.

**The test of this plan's central claim is whether any bespoke type survives
step 4.** If none does, `AxisArray` was re-derivation with nothing to show for
it, and this document should say so.

---

## The invariant for this plan

The refactor's invariant 10 counted deletions; the module plan counts a
reader's working set. This one counts something else again:

> **Every step names a fact that stops being re-derived.** A fact the pipeline
> needs — an axis's name, its length, which storage dimension it came from,
> whether it was reversed — is established once, at the boundary where it is
> known, and carried. A step that leaves a fact reconstructed downstream has
> not landed.

Two measurable forms, both recorded before and after every step:

- **parameter slots that are pieces of one concept** — 74 today
- **places that re-perform the same dispatch** — 5 today

---

## Steps

### Step 1 — make the backends agree

The contract cannot be enforced while a backend returns more axis names than
the array has dimensions: `xr.DataArray` would raise on real data.

- [ ] Fix **bug 6**: `BlueskyRun._infer_dims_from_shape` uses `range(0, ndim)`
  where `MemoryRun` and `KafkaRun` use `range(1, ndim)`, producing `ndim + 1`
  names for every key of rank ≥ 2.
- [ ] Fix **bug 7**: `BlueskyRun.getRunKeys` ends `ykeys[1] = all_keys`, so
  rank-3 camera keys are reported as rank 1.
- [ ] Fix **bug 15**: with no X key selected, `analyze_dimensions` overrides a
  key's own declared dimension names with a positional guess from the run's
  motors, and can produce duplicate axis names.
- [ ] Both need a test against the backend method directly — no `MemoryRun`
  fixture can reproduce either, because `MemoryRun` is the correct one.
- [ ] Facts: backends producing `len(names) != ndim`, **1 → 0**.

This is also the review's number-one finding, and this plan gives it a reason
beyond *it is wrong*: the contract cannot be enforced until it holds.

### Step 2 — declare xarray; the sources return `DataArray`

- [ ] Add `xarray` to `pyproject.toml`. It is already installed transitively;
  depending on it implicitly is the hazard.
- [ ] `CatalogRun.describe()` / `.load()`; the same on `FrozenSpectrum`.
- [ ] Pin `skipna` and `arithmetic_join` at the pipeline boundary, with a test
  for each that fails if the setting is removed.
- [ ] `FrozenSpectrum` moves to `models/data/`, closing the upward import at
  `bluesky.py:7`.
- [ ] Deletes `RunSource._truncate_dim_names` — the padding-and-truncating
  workaround has nothing left to hide — and `AxisLayout` entirely, whose
  `analysis` field has no readers and whose `placeholders` are derivable.
- [ ] Facts: `AxisLayout` 5 fields → a `{name: length}` mapping; name/rank
  agreement enforced at 1 boundary instead of patched at 1 consumer.

### Step 3 — `RunSource` performs the union once

- [ ] `read`, `load_axes`, `describe_axes`, `get_shape` and `get_plot_hints`
  collapse onto one dispatch over `load` / `describe`.
- [ ] Facts: dispatch sites **5 → 1**.

After this step the two classes are describable in one line each, which is the
test of whether the split was ever real:

- **`CatalogRun`** — one source of labelled arrays for a run's keys.
- **`RunSource`** — the union of a catalog run and its frozen synthetic keys
  under one key space, plus the key table, identity and signals the plot layer
  needs.

### Step 4 — the pipeline stages take and return a `DataArray`

- [ ] `orient_for_display`, `apply_normalization`, `apply_transform`,
  `reduce_before_mask`, `mask_to_profile`, `materialize_view`,
  `build_plot_bundle`.
- [ ] **Settle the provenance question first**, because it decides whether any
  bespoke type is needed: can `storage_axis` and `reversed` be served from
  `FetchPlan`, which already records both? Try it on the load / orient /
  normalize path before converting the rest.
- [ ] Fold in the type-level moves while the signatures are open:
  `plan_fetch` → `PlotRequest.plan_fetch(plane_frame=None)`,
  `profile_view_spec` → `Projection.to_profile(axis, reduce)`. Both are
  derivations returning their own type and add no imports.
- [ ] Narrow view-pipeline step 7's exit criterion — "`Projection` gains no
  reduce method" — to what it meant: a *describing* type may derive another
  description but may not apply itself to data. `view/` describes, `fetch/`
  applies.
- [ ] Deletes `_storage_to_tensor`, `_loaded_axis_names`,
  `_loaded_plane_shape`, `_reduce_axis_index`, `_aligned_norm`, and the
  `remaining` parameter — all of which reconstruct what the dims already know.
- [ ] Facts: parameter slots **74 → target**, recorded honestly whatever it
  lands at.

Blast radius measured: **166 call sites across 27 files, two of them in
`views/`** (both `frame_from_bundle`). `PlotBundle` is the view layer's
contract and does not change.

Honest accounting of what xarray buys: of the 392 raw lines of axis
bookkeeping measured across twelve functions, roughly **160 is genuinely
xarray's job** — broadcasting a norm by name, the storage→tensor map, the
surviving-name list, the plane-shape lookup, the transpose and reduce
mechanics. The other ~230 is domain policy that stays either way: which axes
the ROI reduces, the *decision* to flip, and the fetch cache's containment
check. This step should not claim the larger number.

### Step 5 — the block cache stops holding normalized data

Found while drafting, and reproduced:

```
turning a norm ON  -> RunSource.read: ['PCOEdge_image', 'i0']
turning it OFF     -> RunSource.read: ['PCOEdge_image']
changing transform -> RunSource.read: []
```

View-pipeline step 7 moved normalization ahead of the reduce and then cached
the *normalized* block, which forced `norm_keys` into `_block_cache_key`. So
toggling a normalization re-reads **the whole detector array** — and toggling
norms on and off is a routine interaction, not an edge case. It is bug 8's
sibling, made by bug 8's fix.

- [ ] Cache the oriented-but-not-normalized block, keyed without `norm_keys`,
  and hold the loaded norm arrays in the same entry keyed by norm key.
- [ ] The stage *order* does not change — `load → orient → normalize → reduce
  → transform → mask` is still correct and is what step 7 established. Only
  the cache boundary moves back one stage.
- [ ] Preserve view-pipeline step 7's exit criterion: a transform change must
  still cause **zero** reads. Caching the norm arrays alongside is what keeps
  that true.
- [ ] Facts: reads caused by toggling a norm, **1 N-D read → 0** (a norm
  arriving costs one small 1-D read; a norm leaving costs none).

### Step 6 — the fetch orchestration leaves `RunSource`

Mechanical once step 4 lands, because the signatures are already right. The
seam was measured before this plan existed: 512 raw lines of key access
against 569 of fetch, with a six-member interface.

- [ ] `get_plot_bundle` should read as a pipeline and nothing else:

```python
def get_plot_bundle(self, request, *, cached_plane=None, label=""):
    plan  = request.plan_fetch(plane_frame=self._plane_frame(request))
    block = self.load_block(plan)
    block = normalize(block, self._norms(request, plan))
    plane = reduce_to_plane(block, request.view)
    plane = transform(plane, request.transform)
    if request.region is not None:
        plane = mask_to_profile(plane, request, plan.region_frame)
    return build_plot_bundle(plane, label=label)
```

- [ ] Facts: `run_source.py` 586 → ~250 code lines; its working set 5 → 0.

### Step 7 — `CatalogRun`'s public surface

- [ ] Delete `getDimensions` and `analyze_slice_request` — **zero callers
  anywhere**, including inside the data layer.
- [ ] `getData`, `get_dimension_axes` and `analyze_dimensions` become
  internals of `load` / `describe`.
- [ ] **Hold `get_hinted_keys`.** It also has zero callers, but it is bug 4's
  intended backing and master-plan open question 4 asks whether it produces
  the set "Show All Keys" meant. Deleting it forecloses that answer.
- [ ] Facts: public surface 23 → ~19; **the contract `RunSource` depends on,
  8 → 5**.

---

## Kept in mind: what this does to the module reorganization

Not gating, but [`module_organization_plan.md`](module_organization_plan.md)
should be re-derived after this lands rather than executed as written.

- **The pipeline's value type is `xr.DataArray`, from `models/data`.** That
  plan's draft filed a bespoke `AxisArray` beside `PlotBundle` in `geometry/`.
  There is no such type to file.
- **Its step 1 is superseded.** Splitting `run_source` becomes this plan's
  step 6, and doing it here is better: the signatures are right by then, so
  the split is a move rather than a judgment.
- **`fetch/` probably wants one `stages.py`, not three files.** Once every
  stage is `DataArray -> DataArray` they all have the same shape, and the
  proposed `reduce.py` / `normalize.py` split stops being a boundary.
- **`run/` may not need to exist.** With `FrozenSpectrum` moved to
  `models/data/` and `KeyInfo` largely absorbed by `describe`, what remains is
  `RunSource` alone — a file, not a package.
- **`geometry/` keeps `PlotBundle`, `PlotViewFrame`, orientation and masks**,
  and no longer has an identity problem, so the rename question raised there
  probably answers itself.

---

## Open questions

1. ~~**Does `describe` need `xkeys`?**~~ **Settled: no.** The X selection
   chooses a coordinate, not a dimension name; see *`describe` takes no
   `xkeys`* above.

2. ~~**Does `KeyInfo` survive?**~~ **Settled: yes, and `describe` returns it.**
   It gains `axes` and keeps `shape` as a derived property. What remains open
   inside it is `hinted`, which is bug 4's unresolved flag, and `render_hint`,
   which is a plot concept on a run-level record — neither blocks the contract.

3. **Where does `render_mode` finally live?** It is classified once, on the
   loaded plane, before the reduce — so it has to travel, and it cannot ride
   in `.attrs`. The honest options are a field on `FetchPlan` set after the
   load, or re-derivation at pack time.

4. ~~**Do coordinates go on the `DataArray`, or only dimension names?**~~
   **Settled: coordinates go on, indexed, wherever real ones exist.** See
   *Coordinates, and why fly-scan data settles it* below.

5. **Does `PlotBundle` eventually become a `DataArray` plus render payload?**
   It already carries `y`, `axis_names`, `render_mode`, `row_reversed`,
   `col_reversed`. Out of scope here — it is the view layer's contract and
   only two view call sites touch anything else — but worth revisiting once
   the middle of the pipeline is named.

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-10 | Drafted as a standalone plan at the maintainer's direction, after the module reorganization discussion established that moving functions could not fix `run_source` on its own. Written from the data layer because that is where the logic starts: the protocol already exists on both sources, spelled in three pieces, so `RunSource` performs one dispatch five times. Absorbs `structural_remediation_plan.md` step 9. |
| 2026-09-10 | Revised to adopt `xarray.DataArray` instead of the bespoke `AxisArray` the first draft invented. The maintainer asked whether that type was re-deriving xarray; checked, and it largely was. xarray is already a guaranteed transitive dependency through `bluesky-widgets → bluesky-live`, and `xr.DataArray` raises on exactly the dims/rank and coordinate-length mismatches the bespoke constructor was designed to catch — including bug 6. `DataArray` rather than `Dataset` on the maintainer's reason: norms are toggled and swapped constantly, so they must not travel with the data. Two library defaults recorded as required settings, both measured: `skipna=True` erases step 3's deliberate `sum` / `nansum` distinction, and `arithmetic_join="inner"` silently drops rows. Step 5 added from a defect found while drafting: step 7 cached the *normalized* block, so toggling a norm re-reads the whole detector array. |
| 2026-09-10 | Open question 4 settled: coordinates go on the `DataArray`, indexed, wherever real ones exist. The maintainer raised fly-scanned data — each detector a raw timestream on its own time base — as a coming requirement, and it is decisive rather than merely suggestive: two equal-length keys both naming a `time` axis divide silently at mismatched timestamps under names alone, and raise under coordinates plus `arithmetic_join="exact"`. Cost measured at 6.4 ms against 6.0 ms per 5M points, so time is not the consideration; index memory is, and is left to be checked against a real camera run in step 2. Fly-scan support itself remains out of scope. |
| 2026-09-10 | Open questions 1 and 2 settled together on the maintainer's suggestion that `describe` return `KeyInfo`, so there is one way to ask for key metadata rather than four. Checking it showed why the call currently needs `xkeys`: `describe_axes` renames a key's event axis to whichever X key is selected, conflating the axis's identity with the coordinate being plotted against it. xarray separates those natively — several non-dimension coordinates on one dimension, with `swap_dims` choosing the plot axis — so `describe(key)` becomes static and selection-free, which is what `KeyInfo` was documented to be. Bug 15 found while confirming it: with no X key selected the motor fallback overrides a key's correct declared dims and can produce duplicate axis names, which xarray warns about rather than rejecting. |
