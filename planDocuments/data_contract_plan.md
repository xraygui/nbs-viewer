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

**Status:** drafted 2026-09-10 and revised the same day — to adopt `xarray`
rather than a bespoke type, and to settle coordinates onto the array. **Steps
1–4 landed 2026-09-10**; steps 5–7 not started. Numbers measured at
`74a7d6d`.

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

### Step 1 — make the backends agree ✅ 2026-09-10

The contract cannot be enforced while a backend returns more axis names than
the array has dimensions: `xr.DataArray` would raise on real data.

- [x] Fix **bug 6**: `BlueskyRun._infer_dims_from_shape` uses `range(0, ndim)`,
  producing `ndim + 1` names for every key of rank ≥ 2. The fix is
  `range(1, ndim)` — see *What inference should produce*, below, which
  justifies it against real data rather than against the other backends.
- [x] Fix **bug 7**: `BlueskyRun.getRunKeys` ends `ykeys[1] = all_keys`, so
  rank-3 camera keys are reported as rank 1.
- [x] Fix **bug 15**: with no X key selected, `analyze_dimensions` overrides a
  key's own declared dimension names with a positional guess from the run's
  motors, and can produce duplicate axis names.
- [x] Both need a test against the backend method directly — no `MemoryRun`
  fixture can reproduce either, because `MemoryRun` is the correct one.
- [x] Facts: backends producing `len(names) != ndim`, **1 → 0**. Confirmed
  against all three: `MemoryRun` and `KafkaRun` already used `range(1, ndim)`.

#### Outcome

Four edits across two files, 12 tests in `tests/test_backend_dimension_names.py`.
Each fix was reverted individually with the tests in place to confirm the test
fails without it; all four do.

- **Bug 6** is the one-character fix, with the docstring rewritten to state the
  rule and name UCAL as its justification.
- **Bug 7** groups the remaining keys by `len(getShape(key))`, as `MemoryRun`
  does. This costs nothing in practice: `getShape` is cached and
  `RunSource._build_key_table` already asks for every one of these shapes
  moments later, so the work moves earlier rather than being added. A key whose
  shape cannot be read keeps the old rank-1 answer and stays in the table.
- **Bug 15** needed *two* edits, not one, because it has two triggers. The plan
  predicted the motors fallback; the second was found while reproducing it.

#### Deviation: bug 15 has a second trigger, reachable by selecting a motor

The plan described bug 15 as the no-X-key case. It is also reachable *with* a
selection:

```
describe_axes("detector_cube", [])         -> ('pixel', 'pixel', 'dim_2')
describe_axes("detector_cube", ["pixel"])  -> ('pixel', 'pixel', 'dim_2')
```

`pixel` is both a selectable motor and a real dimension of the cube, so the
final "replace a dimension with its single associated axis" step renames the
event axis onto a name already in use. Removing the motors fallback fixes the
first line only.

The second edit is a de-duplication guard: a dimension is not replaced by a
name another dimension of the same key already holds. That is deliberately the
conservative half. The full fix — dimensions are static and the X selection
picks a *coordinate* — is step 2's coordinate work, and doing it here would
change every axis label in the application. So `["row"]` still renames the
event axis to `row`, and a test pins that, because the guard must not disable
the behaviour it guards.

#### Deviation: `KafkaRun` has bug 7 too, and is deliberately left alone

`KafkaRun.getRunKeys` also files every key under `ykeys[1]`. It is not fixed
here because `KafkaRun.getShape` calls `getData` — listing keys would
materialize every buffered array on a live stream, where a key may have no
events yet. Same defect, different cost; it needs a cheap shape source first,
and the Kafka tab cannot currently open at all (bug 10).

This is also the review's number-one finding, and this plan gives it a reason
beyond *it is wrong*: the contract cannot be enforced until it holds.

#### What inference should produce

`_resolve_dims` prefers tiled's own `dims` and only infers when they are
absent, so the question is what the inferred names should be *for a run that
would have had them*. Two real runs the maintainer supplied answer it.

**UCAL labels its dims**, so inference never runs there — which makes it the
ground truth:

```
tes_mca_spectrum  shape=(72, 800)          dims=('time', 'tes_mca_energies')
nexafs_sc         shape=(72,)              dims=('time',)
en_energy         shape=(72,)              dims=('time',)
```

**VPPEM has no dims at all**, so inference must serve it:

```
PCOEdge_image          shape=(201, 2160, 2560)   no dims
sampleVoltage_VSource  shape=(201,)              no dims
```

So the rule is: **the leading axis of anything in a stream's `data` is the
event axis, named `time`; remaining axes are detector-internal and get
placeholders.** That is `range(1, ndim)`:

| key | shape | current | proposed | UCAL's real dims |
|---|---|---|---|---|
| `PCOEdge_image` | (201, 2160, 2560) | `('time','dim_0','dim_1','dim_2')` | `('time','dim_1','dim_2')` | — |
| `tes_mca_spectrum` | (72, 800) | `('time','dim_0','dim_1')` | `('time','dim_1')` | `('time','tes_mca_energies')` |
| `nexafs_sc` | (72,) | `('time',)` | `('time',)` | `('time',)` |

The proposal reproduces the labelled case exactly where it can and degrades to
a placeholder only where the name is genuinely unknown. That, rather than
consistency with `MemoryRun`, is the argument.

#### UCAL confirms bug 15's model in production data

`en_energy` is the scanned motor. Its dims are `('time',)` — it is a **key on
the event axis**, not a name *of* it — and `start['hints']['dimensions']` is
`[[['en_energy'], 'primary']]`, naming which coordinate to plot against.

That is exactly the separation this plan proposes: dimensions are static, and
the X selection picks a coordinate. `analyze_dimensions` renaming the event
axis to `en_energy` or `sampleVoltage_VSource` contradicts UCAL's own
metadata. Bug 15 is not a modelling preference; it disagrees with the data.

#### Two things this step must *not* change

Both are real decisions that would be hidden inside a one-character fix.

- **The genericity of `dim_N`.** `PCOEdge_image` becomes
  `('time','dim_1','dim_2')`, and so does any other camera — with `dim_1`
  meaning 2160 on one and 512 on another. Under xarray that is a loud size
  conflict when the sizes differ and a *silent false alignment* when they
  coincide. Per-key names (`PCOEdge_image_dim_1`) would remove the hazard —
  but they would also break **flat-field normalization**, dividing a detector
  image by a reference image of the same shape, which is a real operation that
  depends on the two sharing axis names. Genuine trade-off, no obvious winner,
  its own decision.
- **The `has_time_key` guard.** By Bluesky's data model everything in a
  stream's `data` is stacked over events, so axis 0 is the event axis whether
  or not `time` happens to be present as a key. The guard may be unnecessary,
  but removing it changes behaviour for streams without `time`.

#### The test

Against the real shapes — `(201, 2160, 2560)`, `(201,)`, `(72, 800)`, `(72,)`
— asserting `len(dims) == len(shape)` and that the leading name is `time`.
Plus one that pins inference against ground truth: for a UCAL-shaped key, the
inferred dims must agree with the tiled dims on every axis whose name is
knowable. No `MemoryRun` fixture can carry either, because `MemoryRun` is
already correct.

### Step 2 — declare xarray; the sources return `DataArray` ✅ 2026-09-10

- [x] Add `xarray` to `pyproject.toml`. It is already installed transitively;
  depending on it implicitly is the hazard.
- [x] `CatalogRun.describe()` / `.load()`; the same on `FrozenSpectrum`.
- [x] Pin `skipna` and `arithmetic_join` at the pipeline boundary, with a test
  for each that fails if the setting is removed. **`arithmetic_join` only** —
  see the deviation below.
- [x] ~~`FrozenSpectrum` moves to `models/data/`~~ — the *convention* moved,
  not the class. See the deviation below; the upward import is closed either
  way, and pinned by a test.
- [x] Deletes `RunSource._truncate_dim_names` — the padding-and-truncating
  workaround has nothing left to hide — and `AxisLayout` entirely, whose
  `analysis` field has no readers and whose `placeholders` are derivable.
- [x] Facts: `AxisLayout` 5 fields → a `{name: length}` mapping; name/rank
  agreement enforced at 1 boundary instead of patched at 1 consumer.

#### Outcome

| | before | after |
|---|---:|---:|
| `RunSource` code lines | 586 | 533 |
| `RunSource` public members | 24 | 25 |
| frozen/catalog dispatch on the public surface | 5 | 4 |
| places name/rank agreement is patched | 1 | 0 |
| places it is enforced | 0 | 1 |
| `models/data` → `models/plot` imports | 1 | 0 |

Deleted: `AxisLayout`, `RunSource._truncate_dim_names`,
`RunSource._frozen_axis_names`, `RunSource.get_plot_hints` (zero callers once
the render hint came from the description), and `plot_geometry`'s
`get_render_mode_hint`, which moved down as `render_mode_hint_for`: it reads
run metadata and nothing else, and was in the plot layer only because its one
caller was.

New in `models/data`: `key_info.py` (`KeyInfo`, moved down and rebuilt around
`axes`), `array_contract.py` (the xarray settings and the construction that
enforces the contract), `synthetic_keys.py` (the naming convention).
`models/plot/key_info.py` became `run_identity.py`, holding the one value that
is genuinely a plot-layer concern.

The public-member count went *up* by one, and that is the honest result: two
methods went away and three arrived, because `describe_axes` was answering two
questions and is now two calls.

#### The split that made the rest work: `describe` against `plot_axis_names`

`describe(key)` is static, as the plan said it should be. But the X-selection
rename could not simply be dropped, and finding out why is the useful part:
**the default axis-order rule locates the X key's storage axis by name.** With
static names the X key never appears among a key's dimensions, `_project`
cannot place it, and default axis order stops working — reproduced against the
shipped fixtures before deciding.

So the rename stayed, under its own name, as `RunSource.plot_axis_names`. That
is better than where it was: the conflation is now visible in the signature
rather than hidden inside a call named `describe_axes`, and step 4 has a
single method to delete when a coordinate choice replaces it.

`PlotSession.driving_axes` returns both halves together —
`(run_model, ykey, KeyInfo, names)` — so neither of its two callers re-derives
the other's half.

#### Deviation: `skipna` has nothing to pin yet

`arithmetic_join` is a global xarray option, is now set to `"exact"` at import
of the data layer, and has two tests: one that fails if the setting is removed,
and one on the fly-scan case it exists for — two 64-point timestreams of equal
length and different phase, which divide silently under names alone.

`skipna` has **no global option**; it is a per-call argument. The reductions
are still `np.sum` / `np.nansum` today, so there is no call site to pin and a
wrapper written now would have no caller. It moves to step 4, where the
reductions convert. `REDUCE_SKIPNA = False` is recorded in `array_contract.py`
so the decision is not re-taken.

#### Deviation: the convention moved down, not the class

Moving `FrozenSpectrum` into `models/data/` would have relocated the upward
import rather than closing it: the class holds a `PlotBundle` and a
`PlotRequest`, so `models/data/frozen_spectrum.py` would import from
`models/plot` — worse than what it replaced.

What `bluesky.py` actually reached up for was the *key-prefix convention*, so
that is what moved, into `models/data/synthetic_keys.py`. `FrozenSpectrum`
stays where its payload does and answers `describe` / `load` from there. The
class can follow if `PlotBundle` ever stops being its payload, which is open
question 5.

A test now walks `models/data` for any import of `models.plot` and asserts
there are none, so this cannot quietly reopen.

#### Deviation: `load(..., coords=False)`, and why

`RunSource.read` routes through `load` so that every existing read exercises
the contract — which is what makes the enforcement real rather than a
promise — but asks for no coordinates. Attaching one costs a read of its own
key, and `read` returns bare values, so building them to discard them is pure
waste. It showed up immediately as a test asserting the frozen path touches
the catalog exactly once.

#### Risk recorded: the option is process-global

`xr.set_options(arithmetic_join="exact")` at import affects every xarray
operation in the process, including any inside tiled or databroker. That is
the plan's own choice, and it is the right default for a codebase whose bugs
are silent wrong answers — the hazard is arithmetic written *without* thinking
about joins, which a context manager around our own calls would not cover. It
is noted here because it is a side effect of an import, which is the kind of
thing that is hard to find later.

#### What `load` attaches, and what it does not

A dimension gets a coordinate when the run holds a 1-D key of that exact name
whose own dims are `(name,)` and whose length matches — which is how a
labelled Bluesky run spells `time` and a detector-internal axis like
`tes_mca_energies`. An axis with no such key keeps its bare name, where
`exact` degrades to the shape check it was before.

**Non-dimension coordinates are not attached yet.** Putting every per-event
motor onto the event axis is what makes `swap_dims` possible, and it is step
4's business: it needs the X selection, which `load` deliberately does not
take. A source that clips an axis relative to its coordinate key — as
`CombinedRun` does, to the shortest of its sources — keeps the bare name
rather than raising.

### Step 3 — `RunSource` performs the union once ✅ 2026-09-10

- [x] `read`, `load_axes`, `describe_axes`, `get_shape` and `get_plot_hints`
  collapse onto one dispatch over `load` / `describe`.
- [x] Facts: dispatch sites **5 → 1**. Counting every branch rather than only
  the five the diagnosis listed: **7 → 1**.

After this step the two classes are describable in one line each, which is the
test of whether the split was ever real:

- **`CatalogRun`** — one source of labelled arrays for a run's keys.
- **`RunSource`** — the union of a catalog run and its frozen synthetic keys
  under one key space, plus the key table, identity and signals the plot layer
  needs.

Both descriptions are now the classes' own docstrings.

#### Outcome

| | before | after |
|---|---:|---:|
| `RunSource` code lines | 533 | 517 |
| branches asking "is this key frozen?" | 7 | 1 |

The seven were `load`, `describe`, `plot_axis_names`, `load_axes`,
`_render_hint`, `_normalized_block`'s norm-key flag, and `get_plot_bundle`'s
label choice. Three of them dispatched to a *method*; four only wanted a
*fact*, and those four now read it off `KeyInfo` — `.synthetic` and
`.render_hint` — which is the plan's invariant working: a fact established
once at the boundary and carried, rather than re-established by looking the
source up again.

#### What makes one dispatch possible

The two sources differ in *shape*, not capability. A `FrozenSpectrum` **is**
one key, so its methods take no key name; a `CatalogRun` holds many, so its
methods take one. `CatalogKey` (`models/data/key_source.py`, 23 code lines)
binds a run and a key name so both answer the same key-free protocol —
`describe()`, `load()`, `plot_axis_names()`, `get_dimension_axes()`, and a
`kind`.

`RunSource._source(key)` returns whichever one holds the key, and it is the
only place on the class that knows there are two.

This is more code than the branches it replaces, and it is an adapter whose
body is delegation — normally not worth extracting. It earns its place by
being the boundary rather than a layer in front of one: a reader of
`RunSource.load` now sees one line with no branch in it, and there is exactly
one place to look for how the union is decided.

`plot_axis_names` moved onto `CatalogRun` as part of that protocol, taking the
`analyze_dimensions` call and its `KeyInfo.from_dims` validation with it.

#### The one branch that stayed, and why it is not a dispatch

`load_axes` still tests `source.kind == "stack_spectrum"`. That is the single
case that genuinely needs both sources at once — a frozen Y plotted against
the *catalog's* X keys — so it is `RunSource`'s own business rather than
either source's. The branch is on a kind each source declares itself to be,
not on which class it is.

#### Verification: three branches were reachable but untested

Each rewritten branch was reverted individually with the suite in place.
Three survived, meaning nothing checked the rewrite had preserved behaviour:

- a declared `render_mode` reaching the bundle,
- a 1-D frozen result being labelled with its ROI label,
- a frozen norm taking Y's event-axis index.

All three were already untested before this step, so this is a gap found
rather than one introduced — but a green suite after a signature change is not
evidence, which is the lesson from the `driving_axes` tie-break that shipped
broken in step 2.

The third is the interesting one. A catalog norm is matched to Y's axes *by
name*; a frozen one shares no name with anything, so it takes Y's own slice
instead. With a rank-3 cube plotted as a line, both leading axes are indexed
to a single event and the two rules diverge: the frozen rule divides by that
event's value, and matching by name raises because a 6-long norm cannot
broadcast onto a 3-long plot axis. So the branch is load-bearing and correct
— it simply had nothing pinning it. It does now, and all four mutations fail.

### Step 4 — the pipeline stages take and return a labelled array ✅ 2026-09-10

Designed in full before editing, at the maintainer's direction, because this
is the step the plan was written for.

#### The complaint, in the maintainer's words

> `get_plot_bundle` → `_load_block` → `_normalized_block` is too deep, and
> mixes high and low-level code. A method should generally either orchestrate
> high-level functions, or do low-level data manipulation.

Three levels, and *every one* of them does raw numpy work **and** calls into
other modules. The cause is not where the functions live. It is that the value
being passed down has no name, so each level unpacks it, re-derives the axis
context, and packs it again.

#### From the top: what `get_plot_bundle` should be

```python
def get_plot_bundle(self, request, *, cached_plane=None, label=""):
    if <in-plane ROI>:
        return reduce_cached_plane(plane, request, label=label)

    view = self._view_by_name(request)
    plan = plan_fetch(request, plane_frame=self._plane_frame(request))
    data, orientation = self._block_for_plan(request, plan) or self._load_block(
        request, plan, view
    )

    if request.region is None:
        data = reduce_to_plane(data, view)
        data = apply_transform(data, view, request.transform)
    else:
        profile = view.to_profile(request.profile_axis, request.spatial_reduce)
        data = reduce_before_mask(data, profile)
        data = apply_transform(data, profile, request.transform)
        data = mask_to_profile(data, profile, request, plan.region_frame)

    return build_plot_bundle(data, view, orientation, request, label=label)
```

Orchestration only, one altitude, no array indices. Every stage is
`DataArray -> DataArray` under a description.

#### From the bottom: what the middle value has to carry

Almost every low-level helper in the fetch path answers **one** question:
*given an array that has been sliced and reduced, which storage axis is each
of its current axes?* That is what `_storage_to_tensor`, `_loaded_axis_names`,
`_loaded_plane_shape`, `_reduce_axis_index`, `remaining`, `slice_info_for_key`
and `_aligned_norm` all exist for.

`xr.DataArray` answers it directly, provided the dimension names are unique
and survive the pipeline — which is what step 1 guaranteed and step 2
enforces. `da.dims` *is* `remaining`; `da.get_axis_num(name)` *is*
`_reduce_axis_index`; alignment by name *is* `_aligned_norm`.

What xarray does **not** carry is four display facts it drops silently
through `.sum()`, arithmetic and `where()`. The first draft of this design put
all four on a wrapper type, `PlotArray`, that every stage took and returned.
The maintainer asked which stages actually *read* each one, and whether any of
them only matter at the pack. Audited:

| fact | load | normalize | reduce | transform | mask | **pack** | cache |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `render_mode` | ✓ decides the flips | – | – | – | – | ✓ | ✓ |
| reversal | ✓ performs them | ✓ flips norms to match | – | – | – | ✓ | ✓ mirrors the window |
| plane dims | – | – | – | ✓ | ✓ | ✓ | – |
| storage names | ✓ | ✓ | ✓ | – | ✓ | ✓ | – |

**No stage between normalize and pack reads `render_mode` or the reversal.**
They would have been on the transformed value for one reason only: to get from
the load to the pack. That is a wrapper earning its place by being convenient,
which is the thing to avoid.

And the other two go the other way. Plane dims and storage names are pure
functions of the *request* — `request.view.plot_axis_order()` and
`plot_axis_names(ykey, xkeys)` — known before any load happens. Putting them
on a value the load produces says they were discovered by reading data, which
is false.

So `PlotArray` does not exist. Three things travel, and they are three
different kinds of thing:

1. **`xr.DataArray` — the data.** This is the pipeline's middle value, and
   adopting xarray *is* naming it. The stages take and return it bare.
2. **A named view — the description.** `Projection` re-expressed over
   dimension names: role per dim, the full plot order, the plane's two dims,
   and the profile dim. Derived **once**, from the request, before any load.
   This is what reduce, transform and mask take alongside the array.
3. **A plane orientation — the provenance.** `render_mode`, `row_reversed`,
   `col_reversed`. Produced by the load, held in a local by `get_plot_bundle`
   and in the block cache, and handed to exactly one consumer: the pack.

Reversal needs only two booleans, not a set of dim names:
`FetchPlan.reversed_axes_for` returns a subset of `plane_axes` and nothing
else, so a flip only ever applies to the plot plane's two axes. That is a
simplification the first draft missed.

**This answers the plan's own test** — it asked whether any bespoke type
survives step 4, and said that if none did, `AxisArray` was re-derivation with
nothing to show for it. The verdict: **no wrapper around the data survives**.
`AxisArray` was to hold the array, its names, its coordinates, its shape and
its rank validation, and xarray took every one of those. What is left are two
small *description* types that were never what `AxisArray` was for — one
derived from the request, one recorded by the load.

#### Measured, not assumed

Every claim below was run before designing around it.

| | result |
|---|---|
| `skipna=False` ≡ `np.sum`; `skipna=True` ≡ `np.nansum` | confirmed exactly, so the step-3 sum/nansum distinction survives as a flag |
| a mask `DataArray` with the plane's dim names broadcasts by name | confirmed — **and a transposed mask aligns identically** |
| `.copy(data=...)` keeps dims and coords | confirmed |
| a norm whose coordinate is **reversed** | **raises** under `exact` — so a norm sharing a reversed axis must still be reversed |
| a norm whose dim name is foreign | **outer-products silently**: `(5,3) / (5,) → (5,3,5)` |
| `load_axes` returns one 1-D array per surviving storage axis, lengths matching the sliced data | confirmed on both fixtures, including integer-indexed axes |

The last two matter most.

The transposed-mask result deletes the hardest twelve lines in `plot_bundle`:
`mask_to_profile` currently transposes the compiled mask by hand when storage
order disagrees with display order, and reshapes it into the right broadcast
shape. `data.where(mask)` does both, by name.

The foreign-name result is a **hazard the conversion creates**. `_aligned_norm`
falls back to matching by *shape* when names do not match, and a frozen stack
spectrum relies on it: its only dim is named after the ROI label, which is not
a dim of anything. Under xarray that silently becomes an outer product instead
of an elementwise divide. So a synthetic norm must be explicitly renamed onto
the dim it actually lives on — which is Y's event axis, stated positively
rather than inferred from a shape collision.

#### Stage by stage

| stage | today | after |
|---|---|---|
| orient | `orient_for_display(y, arrays, reversed_axes, storage_to_tensor)` | `data.isel({dim: slice(None, None, -1)})` — the coordinate follows |
| normalize | `apply_normalization` + `_aligned_norm`, 35 lines | `data / norm`, once per norm |
| reduce | `_materialize_without_region`, ~45 lines of index juggling | `.sum(dim=…, skipna=False)`, `.mean(dim=…)`, `.transpose(*order)` |
| transform | `apply_transform(xlist, y, text) -> (coords, y)` | `apply_transform(data, view, text)` |
| mask | 9 parameters, manual mask transpose and reshape | `data.where(mask)`, dims named |
| pack | `build_plot_bundle(y, coords, names, request, …)` | `build_plot_bundle(data, view, orientation, request, label=…)` |

Only the pack takes the orientation, which is the audit above made structural.

`Projection` gains two pure derivations — a description deriving another
description, which is what view-pipeline step 7's criterion was narrowed to
allow:

- `roles_by_name(storage_names) -> Mapping[str, DimRole]`
- `plot_order(storage_names) -> Tuple[str, ...]` — every dim, non-plot first,
  then plot Y, then plot X

#### Scope

- [x] `PlotAxes` and `PlaneOrientation`; the stages take and return a bare
  `xr.DataArray`.
- [x] `profile_view_spec` → `PlotAxes.to_profile(axis, reduce)`. **Not**
  `plan_fetch` → `PlotRequest.plan_fetch`: see the deviation below.
- [x] Narrow view-pipeline step 7's exit criterion — "`Projection` gains no
  reduce method" — to what it meant: a *describing* type may derive another
  description but may not apply itself to data. `PlotAxes` derives `PlotAxes`
  and touches no array.
- [x] Deletes `_storage_to_tensor`, `_loaded_axis_names`,
  `_loaded_plane_shape`, `_reduce_axis_index`, `_aligned_norm`,
  `orient_for_display`, `_materialize_without_region`,
  `_spatial_reduce_storage_axes`, `_global_reduce_storage_axes`,
  `_normalized_block`, and the `remaining` parameter.
- [x] Facts: parameter slots **78 → 47**.

#### Outcome

| | before | after |
|---|---:|---:|
| parameter slots that are pieces of one concept | 78 | 47 |
| — storage→tensor map | 4 | **0** |
| — per-axis names | 12 | 5 |
| — per-axis coordinates | 18 | 11 |
| — the plot plane | 11 | 5 |
| — which axes reversed | 8 | 4 |
| `run_source.py` code lines | 586 | 468 |
| `plot_bundle.py` code lines | 452 | 320 |
| `plot_geometry.py` code lines | 277 | 263 |
| new: `plot_axes.py` | — | 62 |

(The earlier count of 74 was measured by hand; re-counting the same seven
concept groups by script gives 78 for the same commit. The script is in the
step's history and the two numbers are the same measurement, not a change.)

Net across the four files: **1315 → 1113 code lines**, with the deepest part
of the fetch path down by a third.

`get_plot_bundle` now reads as a pipeline and nothing else, which is what the
step existed to achieve:

```python
axes = self._view_by_name(request)
plan = plan_fetch(request, plane_frame=self._plane_frame(request))
block = self._block_for_plan(cache_key, plan, axes) or self._load_block(...)
data, orientation = block

if request.region is None:
    data = reduce_to_plane(data, axes)
    data = apply_transform(data, axes, request.transform)
else:
    profile = axes.to_profile(request.profile_axis, request.spatial_reduce)
    data = reduce_before_mask(data, profile)
    data = apply_transform(data, profile, request.transform)
    data = mask_to_profile(data, profile, request.region,
                           request.mask_mode, plan.region_frame)
return build_plot_bundle(data, orientation, request, label=label)
```

#### Deviation: `plan_fetch` stayed a function

The plan wanted it as `PlotRequest.plan_fetch(plane_frame=None)`. It was left
alone: it is the one derivation that *cannot* be a pure method of the request,
because it needs the parent plane's frame, which only the source can build —
it reads coordinates. A method that must be handed the thing it depends on is
a function with extra ceremony. `profile_view_spec` did move, onto `PlotAxes`
rather than `Projection`, because the profile view needs the parent plane by
name and only `PlotAxes` knows it.

#### Deviation, since closed: normalization and the coordinate guard

As shipped, step 4 left norm arrays labelled but **carrying no coordinates**,
so they aligned by dimension name and position, exactly as the hand-written
aligner had. Giving them coordinates is what activates the
`arithmetic_join="exact"` check that step 2's fly-scan argument was all about,
and it was held back because it can raise where the old code broadcast.

**Closed 2026-09-11, after step 4b.** The reason it could not be done here is
that it did not work yet: the block was flipped at load and a norm read
afterwards was not, so their coordinates disagreed and the guard fired on
correct data. Moving the flip to the pack is what made it possible, and the
two changes are one argument in two commits.

What step 4 *did* close is the hazard the conversion created: a synthetic
norm's only dimension is named after its ROI label, which is foreign to the
block, and xarray would have broadcast it into a new axis rather than dividing
element by element. `_norm_arrays` renames it onto the block's leading
dimensions, which is the same rule the old shape-matching fallback implemented
by accident.

#### Verification: seven mutations, three gaps found

Every rewritten stage was reverted individually with the suite in place.

| mutation | result before | after |
|---|---|---|
| load skips the display reversal | 10 fail | — |
| a norm is not reversed with the block | 1 fail | — |
| a frozen norm keeps its own dim name | 1 fail | — |
| normalization does nothing | 9 fail | — |
| `reduce_to_plane` uses `skipna=True` | **survives** | 1 fail |
| `reduce_to_plane` skips the transpose | **survives** | 1 fail |
| the ROI mask is built transposed | **survives** | survives *by design* |

The first two survivors were real gaps, both pre-existing: nothing held the
sum/nansum distinction step 3 established, and nothing held the plot-order
transpose. Both now have tests.

The third survives because it *should*: a mask labelled with the plane's
dimension names lands on those axes wherever they are, so building it the
other way round gives the same answer. That is the property that deleted the
hand transpose and reshape, and it now has a test of its own rather than being
an unexamined pass.

#### Two inconsistent test fixtures, found by construction

`xr.DataArray` rejects a coordinate whose length disagrees with its axis, and
two fixtures had been quietly wrong:

- `test_materialize_stack_profile_4d` built a block whose stack axis
  broadcast to length **1** while passing a length-3 coordinate for it. "Sum
  over the stack" was summing one slab. The array is now genuinely 4-D.
- A mesh test passed `mesh_y` / `mesh_x` row and column means as coordinates.
  Those are **edge** grids, `n + 1` long. Nothing read them, so nothing
  noticed.

Neither changes production behaviour. Both are the contract doing on test data
what it was adopted to do on real data.

**Explicitly not in this step**, both because they are separable and because
each is its own risk:

- **Replacing `analyze_dimensions` with `swap_dims`.** The end state is that
  `load` attaches every per-event motor as a non-dimension coordinate and the
  X selection picks one with `swap_dims`, which deletes
  `RunSource.plot_axis_names` and most of `analyze_dimensions`. Here
  `plot_axis_names` and `load_axes` stay, as the *boundary* that produces the
  first labelled array — they run once, at the load, instead of being threaded
  through every stage. Doing both at once would change axis naming and
  coordinate resolution application-wide inside an already large change.
- **Step 5's cache boundary.** Normalization stays inside `_load_block` here.
  Once it is a `PlotArray -> PlotArray` stage, step 5 is a move of the call
  site and the cache key, not a rewrite.

Blast radius re-measured against the functions that actually change: **~80
references across 8 test files and 6 source files**, not the 166 the earlier
estimate counted (that included `frame_from_bundle` and other untouched
names). `PlotBundle` is the view layer's contract and does not change, so
`views/` is untouched.

Honest accounting of what xarray buys: of the 392 raw lines of axis
bookkeeping measured across twelve functions, roughly **160 is genuinely
xarray's job** — broadcasting a norm by name, the storage→tensor map, the
surviving-name list, the plane-shape lookup, the transpose and reduce
mechanics. The other ~230 is domain policy that stays either way: which axes
the ROI reduces, the *decision* to flip, and the fetch cache's containment
check. This step should not claim the larger number.

#### Found while designing: one name means two things

`view_spec.plot_axis_names(spec, dim_names)` returns the names of the *plot
axes* of a projection. `RunSource.plot_axis_names(ykey, xkeys)`, added in step
2, returns a name for *every storage axis* under an X selection. Two different
things one import apart. Recorded for the module reorganization rather than
renamed here.

### Step 4b — orientation moves to the pack ✅ 2026-09-11

Raised by the maintainer after step 4 landed: *"why does `PlaneOrientation`
need to be pushed down to such a low level? Isn't it a pure display concern?
Orientation is just a statement about the display of 2-D detectors, and we can
only display one 2-D plane at a time, so there's really no situation where
different pieces of data can have different orientations, and we need to sort
it all out before normalization."*

Checked, and it is right. `display_flips` returns `(False, False)` for every
mesh plane and, for an image, decides one thing: whether
``imshow(origin="upper")`` would put the coordinates upside down. It is a
matplotlib convention and nothing else.

#### It is not only tidiness: the flip blocks the plan's central guard

Step 4 left normalization arrays **without coordinates**, so they align by
name and position. Attaching coordinates is what turns on the
`arithmetic_join="exact"` check that the fly-scan argument settled the whole
representation on — and the flip is what stops it. Measured:

```
flat-field divide, coordinates attached, block flipped  -> AlignmentError
flat-field divide, no coordinates                       -> divides upside down, silently
```

Y's rows are reversed at load; a flat field read afterwards is not. Their
coordinates disagree, so the guard fires on correct data. With nothing
reversed, both are in source order and the guard means what it says. **This
step has to come before coordinates go on norm arrays**, and that is the most
valuable thing left in the plan.

#### The move

The flip goes from *the load, on the whole block* to *the pack, on the
finished plane*.

- [x] `_read_block` returns a bare `xr.DataArray` in source order.
- [x] `_norm_arrays` stops reversing; `_block_for_plan` stops mirroring cache
  windows.
- [x] `build_plot_bundle` classifies the render mode from the finished plane
  and flips it. Classification is order-independent — uniformity is a property
  of the differences — so moving it later does not change the answer.
- [x] `mask_to_profile` flips the **mask** rather than the data, using the
  region frame's own flags. The ROI is compiled on the frame the user drew on,
  which stays display-ordered; the block no longer is, so one of the two has
  to turn round and the boolean plane is the cheaper one.
- [x] Deletes `PlaneOrientation`, `RunSource._plane_render_mode`,
  `FetchPlan.reversed_axes_for`, the reversal loop in `_norm_arrays`, and the
  mirroring in `_block_for_plan`. The `orient_block` test helper survives, for
  the fixtures that build a *displayed* plane by hand.
- [x] Facts: places that flip data, **3 → 1**.

#### Outcome

`run_source.py` 468 → 438 code lines. `_read_block` returns one value where it
returned two; `_load_block` returns `(data, plan)`.

The block's coordinates are now in source order, which is the change in one
line — measured on the VPPEM fixture, whose rows do reverse:

```
before:  block dim_1: 23 -> 0    (descending; flipped at load)
after:   block dim_1:  0 -> 23   (ascending; flipped at the pack)
         bundle.row_reversed = True
```

And the flat-field divide that raised under `exact` join now aligns:

```
plane / flat, coordinates attached  ->  (24, 32)   OK
```

#### Verification

The four-orientation ground-truth test in `test_fetch_slice_info` — written
because *"three of the four orientations were wrong before"* — passes
unchanged with the flip moved, which is the evidence that matters most: the
ROI answer is identical whether the data turns round or the mask does.

Four mutations, each reverted with the suite in place:

| mutation | result |
|---|---|
| the mask is not flipped on reversed rows | 4 fail |
| the mask is not flipped on reversed columns | 2 fail |
| the pack does not flip rows | 8 fail |
| the pack does not flip columns | **survived** → now 2 fail |

The survivor was a real gap: `build_plot_bundle` had **no test references at
all**, so nothing packed a plane whose column coordinate descends. It now has
a four-orientation test of its own, plus one for a mesh, which is never
reordered.

#### What deliberately does *not* move

`PlotViewFrame.row_reversed` / `col_reversed` / `storage_bbox` stay. They are
not a property of the data: they map a box the user drew on the screen back to
storage indices, which is a genuine two-coordinate-system problem and is
exactly where it belongs. `plan_fetch` keeps using them.

`views/` is untouched, because `PlotBundle` stays display-ordered.

#### The maintainer's further suggestion, and the wrinkle in it

> *...and even then -- we can let the actual plot do the reversal, rather than
> saving flipped array data.*

That would make `PlotBundle` itself source-ordered and leave the flip to the
renderer. It works for **rows**: `imshow(origin="lower")` puts storage row 0 at
the bottom, which is precisely the case that is flipped today. Verified
against matplotlib.

It does not work for **columns**. `imshow` has one `origin` for both axes, and
a descending column coordinate needs the array actually reversed; the only
alternative is an inverted x extent, which draws x decreasing to the right.
So the renderer would do two different things, and `frame_from_bundle` would
describe a source-ordered array while the selector works on a displayed one —
putting the two coordinate systems back, one layer further out.

Stopping at `build_plot_bundle` gets the whole payoff: nothing in the model
pipeline is ever flipped, and the flip happens once, on a 2-D plane, at the
boundary where display begins.

#### Then: the norms get their coordinates ✅ 2026-09-11

The thing step 4b was for. A catalog norm now arrives from
`RunSource.load_axes` with its own coordinates, on the same axes and from the
same source as the block's, so the divide either lines up on coordinate
*values* or raises.

The failure this catches has the right name and the right length, which is
why nothing short of comparing values can see it: a norm read from a
different stretch of the same axis broadcasts without complaint. The test
shifts the coordinate by half a step, asserts first that the shapes still
match, and then that the divide raises.

**One norm is still aligned by position**, on purpose: a frozen synthetic
spectrum. Its axes are whatever the ROI reduction produced and stored, not the
block's, so attaching them would compare two unrelated coordinate systems. Its
single axis is renamed onto the block's leading one, which is the old
shape-matching fallback stated deliberately rather than by accident. That is
the remaining hole in the guard, and it is named here rather than left to be
found.

Facts: norm arrays aligned by coordinate value, **0 → all but the synthetic
one**. Both mutations bite — a norm built without coordinates, and a frozen
norm given index coordinates it has no business carrying.

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
| 2026-09-10 | Step 1's bug 6 fix re-justified against two real runs the maintainer supplied, rather than against the other backends. UCAL labels its dims and is therefore ground truth: `nexafs_sc` is `('time',)` and `tes_mca_spectrum` is `('time','tes_mca_energies')`, so inference's job is to reproduce that where it can — which `range(1, ndim)` does and `range(0, ndim)` does not. The same run confirms bug 15 in production data: `en_energy` is the scanned motor and its dims are `('time',)`, a key on the event axis rather than a name of it, with `start['hints']['dimensions']` naming which coordinate to plot against. Two decisions explicitly excluded from the step: whether placeholder axis names should be per-key (it would fix a false-alignment hazard but break flat-field normalization) and whether the `has_time_key` guard is needed. |
| 2026-09-10 | Step 1 done. Bugs 6, 7 and 15 fixed, with a test per fix verified to fail without it. Two deviations recorded: bug 15 turned out to have a second trigger — selecting a motor whose name is also a real dimension of the key produces the same duplicate — so it took a de-duplication guard as well as removing the motors fallback, with the full separation of dimension from plot coordinate left to step 2; and `KafkaRun` shares bug 7 but is left alone because its `getShape` calls `getData`, which would materialize every buffered array on a live stream. |
| 2026-09-10 | Step 2 done. Both sources answer `describe` / `load`; `KeyInfo` moved down to `models/data` and was rebuilt around one `{axis name: length}` mapping, which makes bug 6's and bug 15's shapes unrepresentable rather than merely absent. `AxisLayout`, `_truncate_dim_names`, `_frozen_axis_names` and `RunSource.get_plot_hints` deleted. Four deviations recorded: `skipna` has no global option and no call site until step 4; the synthetic-key *convention* moved down rather than `FrozenSpectrum` itself, since the class holds a `PlotBundle` and moving it would have relocated the upward import rather than closed it; `read` asks `load` for no coordinates, since each costs a read of its own key that bare values gain nothing from; and `describe_axes` split into a static `describe` plus `plot_axis_names` rather than collapsing, because the default axis-order rule locates the X key's storage axis by name and stops working without the rename. |
| 2026-09-10 | Step 3 done. Branches asking "is this key frozen?" went 7 to 1: three dispatched to a method and now go through `RunSource._source`, while four only wanted a fact and read it off `KeyInfo` instead. `CatalogKey` binds a run and a key name so both sources answer the same key-free protocol — an adapter whose body is delegation, which earns its place by being the boundary rather than a layer in front of one. Three of the rewritten branches turned out to be reachable but untested, found by reverting each one with the suite in place rather than by trusting it green; the frozen-norm branch in particular is load-bearing, and dividing a cube's line plot by a frozen stack spectrum is the case that shows why. |
| 2026-09-10 | Step 4 done. The middle value is a bare `xr.DataArray`; `PlotAxes` names the projection over dimension names once, before any load, and `PlaneOrientation` carries the three display facts from the load to the pack without entering a stage. Parameter slots that are pieces of one concept went 78 to 47, with the storage-to-tensor group to zero; the four files went 1315 to 1113 code lines. Seven mutations run: four bit immediately, two found pre-existing gaps (nothing held the sum/nansum distinction, nothing held the plot-order transpose), and one survives by design because a named mask aligns regardless of how it was built. Building the arrays as `DataArray`s also caught two inconsistent test fixtures -- a stack axis that broadcast to length 1 under a length-3 coordinate, and mesh edge grids passed as cell coordinates. Normalization deliberately stops short of coordinates, so the exact-join guard is not yet active on it; that is the most valuable thing left in this plan. |
| 2026-09-11 | Step 4b done, from the maintainer's observation that orientation is a pure display concern and has no business reaching back past normalization. It is: `display_flips` decides one thing, whether `imshow(origin="upper")` would put an image upside down. The flip moved from the load to the pack, the ROI mask turns round instead of the block, and `PlaneOrientation` -- added one commit earlier -- is gone. The payoff is not tidiness: reversal was what made the exact-join guard fire on correct data, so this is what unblocks coordinates on normalization arrays. The maintainer's further suggestion of letting the renderer flip works for rows via `origin="lower"` but not for columns, since `imshow` has one origin for both axes; stopping at the pack keeps `views/` untouched. Found while verifying: `build_plot_bundle` had no test references at all. |
| 2026-09-11 | Norm arrays got their coordinates, closing step 4's one open deviation. This is what step 4b was for: the guard had been firing on correct data because the block was flipped at load and a norm read afterwards was not. A norm read from the wrong stretch of an axis has the right name and the right length, so only comparing coordinate values catches it. The frozen synthetic norm is left aligned by position, deliberately -- its axes belong to the reduction that made it, not to the block -- and that is the one remaining hole in the guard. |
