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
contract", never started. `AxisArray` is what makes that contract enforceable
rather than a paragraph of prose.

**Status:** drafted 2026-09-10, not started. Numbers measured at `38f5584`.

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

A validating `AxisArray` moves that from *the consumer papers over it* to
*the backend cannot construct its return value*.

### `AxisLayout` is already mostly dead

Of its five fields: `shape` has 8 readers, `names` 6, `placeholders` 4 (and is
`np.arange(n)` per dimension — derivable), `associated` 3 (and is documented
as always empty on this path), **`analysis` has zero readers**.

The metadata-only call needs **shape and names**. Nothing else.

### The layering is already violated, upward

`models/data/bluesky.py:7` imports `is_synthetic_key` from
`models/plot/frozen_spectrum`. `FrozenSpectrum` is a **data source for one
key** that lives in the plot layer, and the data layer has to reach up for its
key-prefix convention. Under this contract it becomes a data source proper and
moves down, closing a violation that exists today rather than creating one.

---

## The contract

Two types, in `models/data/`, because `CatalogRun` returns them and the data
layer must not import the plot layer.

```python
@dataclass(frozen=True)
class AxisSpec:
    """One axis, described without reading anything."""
    name: str
    size: int

@dataclass(frozen=True)
class Axis:
    """One axis of a loaded array."""
    name: str
    coords: np.ndarray      # len(coords) == the array's extent on this axis
    storage_axis: int       # which raw dimension this was, before indexing
    reversed: bool = False  # flipped to reach display order

@dataclass(frozen=True)
class AxisArray:
    """An array that knows what its axes are."""
    data: np.ndarray
    axes: Tuple[Axis, ...]  # one per *surviving* dimension
```

`AxisArray.__post_init__` asserts `len(axes) == data.ndim` and
`len(axis.coords) == data.shape[i]`. That assertion is the contract.

The source protocol, satisfied by `CatalogRun` and `FrozenSpectrum` alike:

```python
def describe(key, xkeys=()) -> Tuple[AxisSpec, ...]   # cheap, reads nothing
def load(key, slice_info=None) -> AxisArray           # reads
```

`shape` and `names` become derived from `describe`; `placeholders` becomes
`np.arange(spec.size)` at the one call site that still wants it.

**`AxisArray` is display-agnostic and must stay so.** It is a data-layer type,
so it may not carry `render_mode` — that is a plot concept and stays on
`FetchPlan` or is derived at the plane. `Axis.reversed` survives as
*provenance*: the data layer always returns storage order and never sets it;
`orient_for_display` in the plot layer does. If the type ever needs
`Projection`, `PlotViewFrame` or a render mode, it has become a context bag
and the design is wrong.

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

The type cannot be introduced while a backend returns more axis names than the
array has dimensions, because the constructor would raise on real data.

- [ ] Fix **bug 6**: `BlueskyRun._infer_dims_from_shape` uses
  `range(0, ndim)` where `MemoryRun` and `KafkaRun` use `range(1, ndim)`,
  producing `ndim + 1` names for every key of rank ≥ 2.
- [ ] Fix **bug 7**: `BlueskyRun.getRunKeys` ends `ykeys[1] = all_keys`, so
  rank-3 camera keys are reported as rank 1.
- [ ] Both need a test against the backend method directly — no `MemoryRun`
  fixture can reproduce either, because `MemoryRun` is the correct one.
- [ ] Facts: backends producing `len(names) != ndim`, **1 → 0**.

This is also the review's number-one finding, and this plan gives it a reason
beyond *it is wrong*: the contract cannot be enforced until it holds.

### Step 2 — the types, and the sources that produce them

- [ ] `AxisSpec`, `Axis`, `AxisArray` in `models/data/`, with the validating
  constructor.
- [ ] `CatalogRun.describe()` / `.load()`; the same on `FrozenSpectrum`.
- [ ] `FrozenSpectrum` moves to `models/data/`, closing the upward import at
  `bluesky.py:7`.
- [ ] Deletes `RunSource._truncate_dim_names` — the padding-and-truncating
  workaround has nothing left to hide — and `AxisLayout.analysis`, which has
  no readers.
- [ ] Facts: `AxisLayout` 5 fields → `AxisSpec` 2; name/rank agreement
  enforced at 1 boundary instead of patched at 1 consumer.

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

### Step 4 — the pipeline stages take and return an `AxisArray`

- [ ] `orient_for_display`, `apply_normalization`, `apply_transform`,
  `reduce_before_mask`, `mask_to_profile`, `materialize_view`,
  `build_plot_bundle`.
- [ ] Fold in the type-level moves while the signatures are open:
  `plan_fetch` → `PlotRequest.plan_fetch(plane_frame=None)`,
  `profile_view_spec` → `Projection.to_profile(axis, reduce)`. Both are
  derivations returning their own type and add no imports.
- [ ] Narrow view-pipeline step 7's exit criterion — "`Projection` gains no
  reduce method" — to what it meant: a *describing* type may derive another
  description but may not apply itself to data. `view/` describes, `fetch/`
  applies.
- [ ] Deletes `_storage_to_tensor`, `_loaded_axis_names`,
  `_loaded_plane_shape`, `_reduce_axis_index`, and the `remaining` parameter
  — all of which reconstruct what the axes already know.
- [ ] Facts: parameter slots **74 → target**, recorded honestly whatever it
  lands at.

Blast radius measured: **166 call sites across 27 files, two of them in
`views/`** (both `frame_from_bundle`). `PlotBundle` is the view layer's
contract and does not change.

### Step 5 — the fetch orchestration leaves `RunSource`

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
    return plane.as_plot_bundle(label=label)
```

- [ ] Facts: `run_source.py` 586 → ~250 code lines; its working set 5 → 0.

### Step 6 — `CatalogRun`'s public surface

- [ ] Delete `getDimensions` and `analyze_slice_request` — **zero callers
  anywhere**, including inside the data layer.
- [ ] `getData`, `get_dimension_axes` and `analyze_dimensions` become
  internals of `load` / `describe`.
- [ ] **Hold `get_hinted_keys`.** It also has zero callers, but it is bug 4's
  intended backing and master-plan open question 4 asks whether it produces
  the set "Show All Keys" meant. Deleting it forecloses that answer. Delete it
  only once the question is settled.
- [ ] Facts: public surface 23 → ~19; **the contract `RunSource` depends on,
  8 → 5**.

---

## Kept in mind: what this does to the module reorganization

Not gating, but [`module_organization_plan.md`](module_organization_plan.md)
should be re-derived after this lands rather than executed as written.

- **`AxisArray` is not a `geometry/` type.** That plan's draft filed it beside
  `PlotBundle`; it belongs in `models/data/`, below the plot layer entirely.
  The correction is what forces the type to stay display-agnostic, so it is a
  gain, not a compromise.
- **Its step 1 is superseded.** Splitting `run_source` becomes this plan's
  step 5, and doing it here is better: the signatures are right by then, so
  the split is a move rather than a judgment.
- **`fetch/` probably wants one `stages.py`, not three files.** Once every
  stage is `AxisArray -> AxisArray` they all have the same shape, and the
  proposed `reduce.py` / `normalize.py` split stops being a boundary.
- **`run/` may not need to exist.** With `FrozenSpectrum` moved to
  `models/data/` and `KeyInfo` largely absorbed by `AxisSpec`, what remains is
  `RunSource` alone — a file, not a package.
- **`geometry/` keeps `PlotBundle`, `PlotViewFrame`, orientation and masks**,
  and no longer has an identity problem, so the rename question raised there
  probably answers itself.

---

## Open questions

1. **Does `describe` need `xkeys`?** Today `describe_axes(ykey, xkeys)` takes
   them because catalog X keys can name a dimension. If the metadata call is
   to be "simple, for the key table and the sliders", it may want a
   key-only form with an X-aware variant beside it — or `xkeys` may be
   cheap enough to keep. Worth checking what the sliders actually vary.

2. **Does `KeyInfo` survive?** Its fields are `name`, `label`, `shape`,
   `synthetic`, `hinted`, `render_hint`. `shape` becomes derived from
   `describe`; `hinted` is bug 4's unresolved flag; `render_hint` is a plot
   concept on a run-level record. It may reduce to two or three fields, or
   fold into whatever `describe` returns.

3. **Where does `render_mode` finally live?** Stated above as "`FetchPlan` or
   derived at the plane", which is not yet a decision. It is classified once,
   on the loaded plane, before the reduce — so it has to travel, and the
   honest options are a field on `FetchPlan` set after the load, or
   re-derivation at pack time.

4. **Is `AxisArray` the name?** It matches this codebase's vocabulary
   (`axis_names`, `axis_arrays`, "storage axes"). `LabelledArray` is the
   standard term and would read better to someone new.

5. **Does `PlotBundle` eventually become an `AxisArray` plus render payload?**
   It already carries `y`, `axis_names`, `render_mode`, `row_reversed`,
   `col_reversed` — the finished, rank-2 case of the same idea. Out of scope
   here; it is the view layer's contract and only two view call sites touch
   anything else. Worth revisiting once the middle of the pipeline is named.

---

## Modification log

| Date | Change |
|------|--------|
| 2026-09-10 | Drafted as a standalone plan at the maintainer's direction, after the module reorganization discussion established that moving functions could not fix `run_source` on its own. Written from the data layer because that is where the logic starts: the protocol already exists on both sources, spelled in three pieces, so `RunSource` performs one dispatch five times. Absorbs `structural_remediation_plan.md` step 9. |
