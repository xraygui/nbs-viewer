# Model core refactor plan

Reorganization of the five classes that move data from a catalog to a plot:
`CatalogRun`, `RunModel`, `RunListModel`, `PlotModel`, `PlotDataModel`.

## Status

- Drafted 2026-09-02. In progress.
- Steps 0–2 done 2026-09-03. Step 3a–3c done 2026-09-03:
  ``PlotModel`` owns ``RunCollection``, visibility, and ``Selection``;
  ``RunListModel`` is a Qt facade; ``RunSource`` no longer holds selection /
  visibility / transform. Alias ``PlotSession = PlotModel`` exists.
- **Session / list adapter finish** is extracted to
  [`plot_session_list_adapter_plan.md`](plot_session_list_adapter_plan.md)
  (was part of step 5). That plan covers ``PlotModel`` → ``PlotSession``,
  ``RunListModel`` → thin ``RunListItemModel`` in ``views/``, consumer
  retarget, and the tests broken by the step‑3 constructor change. Do that
  before or instead of the rest of step 5.
- Remaining on this doc after the adapter plan: step 4 ``Trace``, then the
  rest of step 5 (canvas ``TraceSet``, ``ViewIntent``, image‑grid fan‑out,
  private‑attribute sweep), then 6–8.
- Supersedes the `PlotModel` / `RunListModel` ownership split in
  `model_ownership_headless_plan.md` (Step 6 "Presenter vs multi-view" and
  "Run list vs plot session"). See [Locked decisions](#locked-decisions).
- Complements, does not replace: `plot_package_reorganization.md` (file
  layout), `zarr_l2_cache_plan.md` (cache internals),
  `roi_workbench_plan.md` and `band_projection_plan.md` (ROI features),
  `plot_session_list_adapter_plan.md` (session rename + list adapter).
- Depends on nothing. Blocks the "mixed-rank plot view" and "band
  projection" plans, both of which add more parameters to the fetch path this
  plan collapses.

## Why this document exists

The existing plans treat the problem as **file layout** (reorg 7a–7e),
**ownership** (who holds which attribute), or **feature work** (ROI, bands).
Each is locally correct and none of them change the shape of the problem,
because the shape of the problem is not where code lives or who owns an
attribute. It is that **no object can be handed a description of a plot.**

Everything else follows from that absence:

- Fetch takes ten parameters because the description has to be reassembled
  from overlapping fragments at every call.
- State is mirrored across four objects because a description cannot be
  passed, so each layer keeps its own copy of the parts it needs.
- Trace identity is `(xkey, ykey, uid)` — the description minus the view —
  so any feature that varies the view has to build a second pipeline.

This plan introduces that description as a value type and lets the class
structure fall out of it.

## Diagnosis

### The five classes are three concerns

| Concern | Currently spread across |
|---|---|
| Array access and derivation | `CatalogRun`, `RunModel._fetch_plot_arrays` |
| Session state (selection, visibility, view, transform) | `RunModel`, `RunListModel`, `PlotModel`, `PlotDataModel` |
| Render bookkeeping | `PlotDataModel` (artist), `MplCanvas` |

No class owns exactly one concern. `RunModel` is in all three.

### Evidence 1 — fetch reassembles its own argument

`RunModel._fetch_plot_arrays` takes ten parameters, eight of which are
alternative or overlapping ways to state the same thing: `slice_info`,
`cube_view_spec`, `materialize_request`, `view_crop`,
`preserve_storage_axes`, `region_frame`, `parent_spec`, `transform`.

`runSource.py:493-528` does nothing but resolve precedence among them
(`materialize_request` > `cube_view_spec` > `slice_info`, with a frozen-key
short-circuit and crop composition). That same precedence tree is then walked
a second time in the materialize branch (`:540-565`) and a third time in the
normalization branch (`:568-596`).

Three copies of one decision. The method reads as neither low-level nor
high-level because its actual first job is to reconstruct an argument that
was never passed.

### Evidence 2 — the ten-parameter signature has already caused a live bug

`RunModel.get_plot_data` (`runSource.py:646-648`) forwards positionally:

```python
xlist, _axis_names, y = self._fetch_plot_arrays(
    xkeys, ykey, norm_keys, slice_info, transform
)
```

The fifth positional parameter of `_fetch_plot_arrays` is `cube_view_spec`,
not `transform`. So `transform` lands in the cube-spec slot, `cube_view_spec
is not None` is satisfied by a bool, and `cube_view_spec.ndim` raises
`AttributeError`.

Consequences:

- `CombinedRunModel.get_plot_data` (`combinedRunModel.py:170`) is the only
  live caller. It is therefore dead on arrival — **combining runs cannot
  work.**
- Worse, `CombinedRunModel` never overrides `get_plot_bundle`, which is what
  the canvas actually calls. `super().__init__(first_run.run)` sets `_run` to
  the first source run, so the inherited bundle path loads *only the first
  run*. **Combining runs silently plots run\[0\] instead of the
  combination.**

Both failures are invisible because the combine feature and the legacy API
are the only things on that path. This is what a ten-parameter positional
signature buys.

### Evidence 3 — trace identity omits the view, so a second pipeline exists

`PlotModel._plot_data` is keyed `(xkey, ykey, uid)`, which cannot express
"same keys, different slice." `ImageGridCanvas` therefore keeps its own trace
map keyed `(uid, image_idx)` (`image_grid_canvas.py:383`) and constructs
`PlotDataModel` directly (`:393`), bypassing `ensure_plot_data`.

The image grid did not need a second pipeline. It needed the slice in the
key. It has independently arrived at request-as-identity, which is the
central proposal of this plan.

Shape discovery is duplicated for the same reason: `dimension.py:639-704`
and `image_grid_canvas.py:124-179` both walk `visible_models[0]`, call
`get_selected_keys` and `get_dimension_ui_info`, and pick a max shape.

### Evidence 4 — the layering's justification is not exercised

The `RunListModel` / `PlotModel` split exists so several plots can share one
run list. `PlotPresenter` creates exactly one of each (`presenter.py:43-47`)
and its own docstring says N>1 is deferred. One `CatalogRun` maps to several
`RunModel`s only when a run is copied to a *different* display — different
run lists, so nothing is shared within a session.

The cost is paid in full and the benefit is not realized anywhere.

### Evidence 5 — what the cost is

Eight facts stored twice or more, enumerated in
`codebase_problem_statement.md` §3. The three that bite:

- **Selected keys.** `PlotModel` stores the user's selection unfiltered;
  `RunModel.set_selected_keys` filters to that run's `available_keys`
  (`runSource.py:878-882`). After a sync the two disagree for any run missing
  a key, and views are split on which one they read.
- **Visibility, four copies.** `RunListModel._visible_runs`, the
  `QStandardItem` check state, `RunModel._is_visible`,
  `PlotDataModel._visible`. Plus `visible_runs` and `visible_models` return
  different sets on the main display (`runListModel.py:589-606`).
- **View state.** `PlotModel._slice` / `_cube_view_spec` versus each
  `PlotDataModel._indices` / `_cube_view_spec`, compared field-by-field to
  decide cache validity (`plotModel.py:743-747`).

### Evidence 6 — the coordination protocol is integration tax

`PlotModel`'s module docstring documents a four-signal protocol it must
implement against `RunListModel` (`run_added`, `run_removed`,
`visible_runs_changed`, `available_keys_changed`), each with a handler that
patches the plot-data map. Add `ensure_plot_data` and
`drop_plot_data_for_uid` and there are six mutation paths into one dict.

The canvas carries `_ensure_sibling_lines_on_axes` (`single_canvas.py:730`)
as race recovery for when those paths disagree. A recovery hack for a
protocol between two objects that turn out to be one object.

## Locked decisions

Decided 2026-09-02.

1. **Multi-view means N panels of the same runs differing by slice or
   view** (image grid, slice montage). Not N independent plots with
   independent key selections. Therefore one session with many traces is
   sufficient, and **`RunListModel` and `PlotModel` merge.** This reverses
   the "N `PlotModel`s sharing one `RunListModel`" decision in
   `model_ownership_headless_plan.md`.
2. **Frozen ROI spectra are scoped per plot session.** The per-run wrapper is
   owned by the session and is not shared across displays.
3. **Key selection is session-global with an explicit per-run override
   map.** The `link runs` checkbox in `run_display.py:56` stays functional
   and becomes "clear the overrides". Selection is resolved and filtered at
   request-build time, not stored per run.
4. **`RunSource` exposes six members**, two values and four calls. Static
   per-key facts are projected into a `KeyInfo` table; selection-dependent
   axis analysis is `describe_axes` / `load_axes` on the source (revised
   2026-09-03, decision 13). See [Key universe and the no-re-export
   rule](#key-universe-and-the-no-re-export-rule).
5. **Crop folds into the view specification.** One slice-narrowing path.
6. **An ROI profile is a trace whose request carries a region.** One
   materialization path; parent-bundle reuse becomes a `TraceSet` lookup
   rather than a caller-side branch. Refined by decision 11.
7. **Headless rendering is not a driver.** `Trace` may keep the matplotlib
   artist for now. It must be the only non-pure thing on `Trace` so it can be
   lifted later without touching anything else.
8. **Execution is a long-lived branch** optimized for the end state, not for
   shippable intermediates. Public APIs may change freely.

Decided 2026-09-03, revising the fetch pipeline.

9. **Request to bundle is one named method, not a staged pipeline.**
   `RunSource.get_plot_bundle(request) -> PlotBundle`. There is no
   `fetch` free function and **no plan object**; the request *is* the plan.
   The draft name `prepare_plot_bundle` was dropped so existing callers
   keep working. See [Request to bundle](#request-to-bundle).
10. **The session holds a rank-agnostic `ViewIntent`; requests carry a
    concrete `ViewSpec`.** One run can expose y keys of different rank, so no
    single `ViewSpec` describes a session. The projection happens at
    request-build time. See [`ViewIntent` and
    `ViewSpec`](#viewintent-and-viewspec).
11. **`Trace` is the bundle cache.** Validity is `trace.request ==
    new_request`, and the ROI ancestor short-circuit is a lookup over the
    `TraceSet`. `RunSource.get_plot_bundle` is uncached and has no cache
    of its own.
12. **Step 2 adds the `RunSource` surface; it does not delete session
    state.** Selection, visibility, transform text, and the live interpreter
    stay on `RunModel` until `PlotSession` exists (step 3). Deleting them in
    step 2 would force the PlotModel / RunListModel merge into the same
    diff. The six-member surface is additive; the re-exports become shims
    or private helpers used only by leftover session methods.
13. **`describe_axes` and `load_axes` are methods**, for the same reason
    as `get_plot_bundle`. They are not `CatalogRun` re-exports: they apply
    the frozen-key overlay and are fully parameterized by their arguments.
    `PlotSession` already holds the source, so
    `source.describe_axes(ykey, xkeys)` is not a longer chain than a free
    function. The earlier `axis_analysis` member and the free-function pair
    are dropped. The "five members" cap was a guard against wrapper width,
    not a fixed count; the public surface is six. See [Key universe and the
    no-re-export rule](#key-universe-and-the-no-re-export-rule).

## Target architecture

### Ownership tree

Composition, not sibling coordination. Every arrow is "owns", so the
four-signal protocol has no place to exist.

```
PlotSession                    (one per display)
├── RunCollection             membership + order, plain container
│   └── RunSource × N         CatalogRun + frozen synthetic keys
│       └── CatalogRun        untouched
├── Selection                 session default + per-run overrides
├── ViewIntent                roles, axis order, crop, fan-out; rank-agnostic
├── TraceSet                  Trace × N, keyed by PlotRequest
│   └── Trace                 request + cached PlotBundle
├── RoiSetModel               untouched
└── RoiController             ROI preview / commit pipeline
```

Views attach as adapters and read only:

```
RunListItemModel (views/)      QStandardItemModel over (collection, session)
MplCanvas (views/)             renders TraceSet, owns axes
```

### Object roles and sizes

| Object | Replaces | Lines now → target | Job |
|---|---|---|---|
| `CatalogRun` | itself | 787, unchanged | arrays, keys, hints, dimension analysis |
| `RunSource` | `RunModel` | 909 → ~250 | uniform key access over real + frozen keys, plus `get_plot_bundle`; six members, see [no-re-export rule](#key-universe-and-the-no-re-export-rule) |
| `RunCollection` | membership half of `RunListModel` | — → ~150 | ordered membership, combine/freeze factories |
| `PlotSession` | `PlotModel` + session half of `RunListModel` | 1253 + 675 → ~500 | selection, visibility, view, transform, traces |
| `RoiController` | ROI half of `PlotModel` | ~500 → ~400 | ROI request building, preview, commit |
| `Trace` | `PlotDataModel` | 445 → ~150 | request identity + cached bundle |
| `RunListItemModel` | Qt half of `RunListModel` | — → ~120 | sidebar rows, in `views/` |

`RunSource` shrinks by an order of magnitude because everything that made
`RunModel` "a fancy `CatalogRun` accessor" leaves: selection, visibility,
transform text, the asteval interpreter, the `_catalog_keys` mirror, and
the ten pass-through properties. `_fetch_plot_arrays` is already gone
(step 1b). What remains is the frozen-key overlay plus `get_plot_bundle`.
That is real work and it is roughly 150 lines of overlay plus ~40 of
orchestration.

## The value types

### `PlotRequest`

The description that does not currently exist. Frozen, hashable, and the
identity of a trace.

```python
@dataclass(frozen=True)
class PlotRequest:
    uid: str
    xkeys: tuple[str, ...]
    ykey: str
    norm_keys: tuple[str, ...]
    view: ViewSpec
    region: RegionDefinition | None
    mask_mode: str
    transform: str
```

Subsumes, at the fetch boundary: `xkey`, `ykey`, `norm_keys`, `slice_info`,
`cube_view_spec`, `materialize_request`, `view_crop`,
`preserve_storage_axes`, `region_frame`, `parent_spec`, `transform`,
`dimension`, `label`.

### `ViewIntent` and `ViewSpec`

Two types, because view state is expressed at two different ranks.

`ViewSpec` is today's `CubeViewSpec` absorbing `ViewCrop`: per-storage-axis
role (index / sum / mean / plot-x / plot-y) for a **specific** `ndim`, axis
order, and optional plot-plane bounds. It is a field of `PlotRequest`.

`ViewIntent` is what the session holds and the dimension controls edit. It is
rank-agnostic: desired plot dimensionality, the roles and indices the user
has chosen, axis order, crop, and fan-out.

The split is forced by the data. The fixture run
(`models/sources/fixtures.py`) exposes `PCOEdge_stats` at rank 1 and
`PCOEdge_image` at rank 3 in the same run, and a session showing both needs
one view state that yields a different `ViewSpec` for each. Today this is
papered over by the `view_spec.ndim <= y_rank` guard (`runSource.py:523-524`)
and by `spec_for_plot_ndim` adapting a spec after the fact. Making the
projection explicit is what keeps that guard from growing back inside
`get_plot_bundle`:

```
ViewIntent.project(ndim, shape) -> ViewSpec
```

Projection requires ``ndim >= plot_ndim``. A 1-D key cannot fill a 2-D
plot; attempting to project raises. Whether two keys that *can* project
may share a plot is a separate check: ``plot_axis_names(spec, dim_names)``
must match across keys (a rank-1 ``sampleVoltage`` spectrum is compatible
with a cube reduced so Plot X is also ``sampleVoltage``, and incompatible
when Plot X is a detector axis).

A rank-1 key under a 1-D intent projects to a trivial spec
(``plot_ndim=1``, single ``PLOT_X``), which is also why the frozen-key
short-circuit at ``runSource.py:495-498`` deletes rather than moves: a
frozen 1-D spectrum is not a special case, it is a rank-1 projection.

Fan-out belongs to ``ViewIntent``, not ``ViewSpec``: it enumerates
*several* specs from one intent, which is the image grid (Open item 2).
Deferred past the value-types slice.

Crop folds in because a persistent crop *is* a view property — it narrows the
same plot-plane axes that the spec already describes. The single resolution
function is:

```
narrow_plot_plane(base_slice, crop_bounds, region_bounds) -> slice_info
```

replacing `apply_view_crop_to_slice_info`, `fetch_context_with_view_crop`,
and `MaterializeRequest.fetch_context` as three separate entry points.

**Implementation note.** `ViewCrop` currently carries `full_frame`,
`row_axis`, `col_axis`, `spatial_fingerprint`, and `source_key`
(`view_crop.py:53-61`) purely to convert display coordinates back to storage
indices later, and to decide when to self-invalidate. Under folding:

- Display-to-storage conversion becomes **construction-time** logic —
  `crop_bounds_from_region(frame, region) -> bounds` — so only integer bounds
  enter `ViewSpec`.
- Invalidation disappears as a mechanism. A stale crop is a request that no
  longer matches, which the trace diff already handles.
- The cost is that resolving a region against a cropped plane needs the full
  plane's coordinate arrays at resolve time. Get them from the source
  (`get_dimension_axes` on the uncropped plot-plane slice) and memoize per
  `(uid, ykey, plane axes)` on the session. Axis arrays are small relative to
  the data; measure before optimizing.

### Request to bundle

One method with an obvious name, orchestrating pure functions that mostly
already exist.

```python
class RunSource:
    def get_plot_bundle(self, request: PlotRequest) -> PlotBundle:
        plane = self._read_plane_coords(request)
        slice_info = request.view.load_slice(plane, request.region)

        y = self.read(request.ykey, slice_info)
        coords, names, _extra = self.load_axes(
            request.ykey, request.xkeys, slice_info
        )
        norms = [self.read(k, slice_info) for k in request.norm_keys]

        y, coords, names = reduce_to_plot_plane(y, coords, names, request)
        y = apply_normalization(y, coords, names, norms, request)
        coords, y = apply_transform(coords, y, request.transform)
        return build_plot_bundle(y, coords, names, request)
```

**Why a method and not a staged free function.** An earlier draft proposed
`fetch(source, request)` decomposed into `resolve` / `load` / `materialize` /
`normalize` / `transform` / `prepare_bundle`, threading a `plan` object.
That was wrong on both counts.

The plan object was dead weight. Everything `resolve` produced — the load
slice, the region frame, `plot_plane_storage_axes`, `preserve_storage_axes` —
is consumed inside a single method, so locals suffice. A plan object earns
its keep only when state must cross separately-callable top-level functions,
and the six-stage split was the sole reason it had to.

`get_plot_bundle` also does not re-open the `RunModel` failure mode, even
though it takes on normalization and transform. `RunModel` grew to 909 lines
by holding session *state*: `_transform_text`, a live `asteval.Interpreter`
as instance state, `_selected_norm`, the `_catalog_keys` mirror. Here all of
that is **in the request**. The transform is a pure function of
`(arrays, text)` with the interpreter created per call, and norm keys are a
request field. The method takes on policy that is fully parameterized by its
argument and adds no state, which is categorically different from eleven
stateful wrappers. Nor is it a re-export: `get_plot_bundle` is not in
`CatalogRun`'s API.

**The one seam that is real.** `ViewSpec.load_slice` maps `INDEX` roles to
integer indices and every other role to `slice(None)`. So `INDEX` is pushed
down into the storage read and `SUM` / `MEAN` cannot be — they require the
bytes in memory first. Against the fixture cube at `(11, 24, 32)`:

| Roles | Load slice | Read returns | Left to do in memory |
|---|---|---|---|
| `(INDEX@4, PLOT_Y, PLOT_X)` | `(4, :, :)` | `(24, 32)` | nothing |
| `(PLOT_X, MEAN, MEAN)` | `(:, :, :)` | `(11, 24, 32)` | mean over axes 1, 2 |

That is the load / reduce boundary, and it is a property of array storage
rather than of this codebase. It is worth a function boundary — which it
already has, as `materialize_view`. The rename to `reduce_to_plot_plane`
says what it does: reduce the non-plot axes, transpose to plot axis order,
trim the coordinate arrays to the surviving axes.

**Where the deleted lines actually come from.** Not from relocation.
`_fetch_plot_arrays` plus `get_plot_bundle` is ~290 lines and the
orchestration above is ~40, but the difference is not moved elsewhere: the
three-way precedence tree collapses to one `load_slice` call, the
compat branches die under the always-a-real-`ViewSpec` contract,
`preserve_storage_axes` becomes unreachable (it only gates the drop-length-1
fallback at `runSource.py:556-564`, taken when no spec was supplied), and the
frozen short-circuit becomes a rank-1 projection. The heavy lifting stays
where it already lives and is already tested: `cube_view.py`,
`plot_geometry.py`, `region.py`, exercised by `tests/test_materialize_view.py`,
`test_cube_view.py`, `test_plot_geometry.py`, `test_region*.py`. Nothing moves
out of a class merely to make the class smaller.

**Ordering constraint.** `_read_plane_coords` comes first because compiling a
region from data coordinates to integer storage bounds needs the plot plane's
coordinate arrays. That is one small read before the main read, and it is the
only place where "work out the slice, then load" is not a clean sequence.
Same issue as Open item 1.

**Normalization needs its own rule.** A norm array is reduced according to
the sub-spec covering *its own* dimensions, not the y key's spec. The fixture
makes the failure concrete: `i0` has dims `("time",)` while the cube has
`("time", "dim_1", "dim_2")`, so when `time` is `PLOT_X` the norm is already
aligned to the plot axis and divides elementwise with no reduction. Reusing
the y spec reduces storage axis 2 of a 1-D array and raises (bug 6). A rank-3
norm key does need the same reduction as y. The rule is derivable by
comparing the two keys' dims and belongs in `apply_normalization`.

This is also where the filtering bug dies. `session.selection_for(uid)`
resolves the session default against the per-run override, filters once
against that run's available keys, and the filtered result exists **only
inside the immutable request**. There is no second artifact to diverge from,
so the bug becomes structurally impossible rather than merely fixed.

## Key universe and the no-re-export rule

`RunModel` reached 909 lines by re-exporting `CatalogRun`'s API surface:
`getData`, `getShape`, `get_dimension_axes`, `get_dimension_ui_info`,
`getPlotHints`, `available_keys`, `uid`, `scan_id`, `plan_name`, `metadata`,
`display_name` — eleven members, each answering one question about one key,
each carrying its own synthetic-key branch. Every new question needs a new
forwarding method and repeats the branch.

`RunSource` must not reproduce that. The rule:

> A layer may **hold a value** obtained from below, and may **pass its child
> into a free function**, but may not **re-export its child's API.**

Depth in the ownership tree is fine and stays three levels
(`PlotSession` → `RunSource` → `CatalogRun`). Depth in the *call* chain and
width of the re-exported surface is what the rule forbids.

### Static facts become a projection

```python
@dataclass(frozen=True)
class KeyInfo:
    name: str
    label: str                  # synthetic keys carry a friendly label
    shape: tuple[int, ...]
    synthetic: bool
    hinted: bool
    render_hint: str | None
```

`RunSource` exposes six members total (locked 2026-09-02 as five,
revised 2026-09-03: `get_plot_bundle` added; `describe_axes` /
`load_axes` are methods, `axis_analysis` dropped):

| Member | Kind | Consumer |
|---|---|---|
| `key_table() -> Mapping[str, KeyInfo]` | value | `PlotSession`, views |
| `identity() -> RunIdentity` | value | views (uid, scan_id, plan_name, display_name, metadata) |
| `get_plot_bundle(request) -> PlotBundle` | call | `Trace` only |
| `read(key, slice_info) -> ndarray` | call | `get_plot_bundle`, `load_axes` |
| `describe_axes(ykey, xkeys) -> AxisLayout` | call | dimension UI, `PlotSession` |
| `load_axes(ykey, xkeys, slice_info) -> ...` | call | `get_plot_bundle`, dimension UI |

`get_plot_bundle`, `describe_axes`, and `load_axes` are the members that
do substantive work. Computing something from a frozen overlay is the
opposite of the failure mode the no-re-export rule targets, which is
width of forwarded surface.

The synthetic-key overlay is applied **once**, when merging catalog keys
with frozen entries into `key_table`, instead of eleven times in eleven
wrappers. `RunSource` calls into `CatalogRun` once per *invalidation event*,
not once per question.

### The universe is set arithmetic, not traversal

```python
def key_universe(self) -> list[KeyInfo]:
    tables = [s.key_table() for s in self.visible_sources()]
    shared = set.intersection(*(set(t) for t in tables))
    return order_keys(k for k in tables[0].values() if k.name in shared)
```

This one derived function absorbs `RunListModel.update_available_keys`,
`RunListModel.synthetic_display_entries`, and the `"time"`-first ordering
hack at `run_display.py:188`. It is shallow and cheap — one cached dict per
source.

### Selection-dependent facts stay on the source

`analyze_dimensions` resolves motors and axis hints *against the x
selection*, so dimension names and associated axes are a function of
`(ykey, xkeys)` and cannot be projected into `KeyInfo`. They are also not
`CatalogRun` re-exports. Two methods on `RunSource`, same rationale as
`get_plot_bundle` (decision 13):

```python
class RunSource:
    def describe_axes(self, ykey: str, xkeys: tuple) -> AxisLayout: ...
    def load_axes(self, ykey, xkeys, slice_info) -> tuple[list, list, dict]: ...
```

`PlotSession` calls `source.describe_axes(ykey, xkeys)` directly; there is
no `session → collection → source → run` chain because the session already
holds the source.

This collapses an existing duplicated pair. `CatalogRun.get_dimension_ui_info`
(`data/base.py:670-681`) and `get_dimension_axes` (`:713-787`) are both
`analyze_dimensions` plus a coordinate policy: the first returns `np.arange`
placeholders with empty associated data, the second loads real arrays. As
`describe_axes` (metadata, no load) plus `load_axes` (materialize) it becomes
one analysis with two consumers. The frozen-key overlay lives in these two
methods instead of in eleven wrappers. Until the consumer sweep,
`get_dimension_ui_info` / `get_dimension_axes` on `RunModel` are one-line
shims.

### Invalidation

| Cache | Invalidated by |
|---|---|
| `RunSource.key_table` | `CatalogRun.keys_ready`, `CatalogRun.data_changed`, frozen register/remove |
| `PlotSession.key_universe` | any source `keys_changed`, plus visibility change |

One `keys_changed` signal on the source and one on the session replace the
four signals currently carrying this single fact
(`available_keys_changed` and `frozen_spectra_changed`, on both `RunModel`
and `RunListModel`).

### `run_display.py` after the change

It becomes a view of `PlotSession` only. `RunCollection` is internal and
never reaches a widget — handing a view a second model object is exactly how
the current widget ends up reading the key list from `RunListModel` and the
checkbox state from `PlotModel`.

| Widget need | Session API |
|---|---|
| Key rows, both link modes, both sections | `key_rows()` — `KeyInfo.synthetic` selects the section |
| Checkbox state | `selection` / `selection_for(uid)` |
| Checkbox writes | `set_selection(...)` / `set_selection_for(uid, ...)` |
| Run selector dropdown, header text | `visible_identities()` |
| Delete a frozen spectrum | `remove_frozen_spectrum(uid, key)` — a command, legitimate delegation |
| "Show All Keys" filter | filter on `KeyInfo.hinted` |

Two methods delete rather than move:

- `_synthetic_entries` (`:325-342`) — `KeyInfo.synthetic` replaces it.
- `_synchronize_selections` (`:462-493`) — intersecting per-run selections to
  derive a linked selection is only needed because per-run selection is the
  storage. With a session default plus overrides, **"Link Runs" is "clear the
  overrides."**

`RunListModel.getHeaderLabel` (`:192-200`) moves into the widget.
`"Run: {plan_name} ({scan_id})"` is view formatting that currently lives in a
model.

## Single owner for every mirrored fact

| Fact | Owner | Everyone else |
|---|---|---|
| Selected x / y / norm keys | `PlotSession.selection` (+ per-run overrides) | resolved into `PlotRequest` |
| Run visibility | `PlotSession` | `RunListItemModel` renders it; `Trace` derives from it |
| View state (roles, axis order, crop, fan-out) | `PlotSession.intent` as `ViewIntent` | projected per key rank into a concrete `ViewSpec` inside `PlotRequest` |
| Transform text | `PlotSession` | a field in `PlotRequest`; applied by a pure function |
| Available key universe | `PlotSession.key_universe()`, derived from `RunSource.key_table()` values | cached, invalidated by `keys_changed`; never stored twice |
| Frozen spectra | `RunSource` | exposed as ordinary keys |
| Plot dimensionality | derived from `ViewSpec.plot_ndim` | not stored |
| Per-trace cached bundle | `Trace.bundle` | validity is `trace.request == new_request` |

The immutable snapshot in `PlotRequest` is the point of the design, not a
compromise. Today's `PlotDataModel._indices` is a *mutable stale copy* that
`PlotModel` must compare field-by-field. A snapshot inside a frozen
dataclass is a deliberate record of "what this bundle was fetched for", and
validity collapses to one equality check.

## Trace lifecycle: rebuild by diff

The trace set is a pure function of session state. Retention and drawing
are different:

```
retained = { build_request(uid, x, y, view)
             for uid in member_uids              # not visibility
             for (x, y) in selection_for(uid)
             for view in view.fan_out() }

drawn = { r for r in retained if r.uid in visible_uids }
```

``rebuild()`` diffs ``retained`` against the live map. Hide/show only
changes ``drawn`` (artist visibility / canvas iteration); it does not
dispose models, so ``last_bundle`` and the artist remain as the first
cache layer. Dispose happens when a run leaves membership or a key leaves
selection (or the request identity itself changes — then ``set_request``
reuses the model and invalidates the fetch).

`ViewSpec.fan_out()` is where the image grid lives. Enumerating slice indices
along one axis yields N requests, so the grid becomes N ordinary traces. The
canvas maps trace → subplot and does nothing else. `_create_image_plot_data`
and the private `(uid, image_idx)` map both delete, and the duplicated shape
discovery collapses into the one place that builds the fan-out.

## ROI and crop under one fetch path

`fetch_roi_preview` currently branches on `_profile_uses_nd_load`
(`derived_fetch.py:457`): if the profile axis lies in the displayed plot
plane, materialize from the cached parent 2D bundle; otherwise reload N-D
through `run_model.get_plot_bundle`.

That is a **cache-hit test**, written as a caller-side branch. Restated:
"can this request be satisfied from an already-materialized ancestor?"

Under unification it becomes a **`TraceSet` lookup**, not a branch and not a
new cache. `Trace` already holds a bundle keyed by its request, so "is there
an already-materialized ancestor?" is a query over the existing traces, and
`RunSource.get_plot_bundle` stays uncached (locked decision 11). The two
materialization paths (`derived_fetch._storage_axis_arrays_for_bundle` +
`materialize_view` on a rendered bundle, versus `RunModel`'s
load-then-materialize) become one path with an optional ancestor
short-circuit resolved *before* the source is asked.

What that deletes: `fetch_materialized_bundle`'s dual-mode signature,
`_request_for_display_plane`, `region_frame_for_roi_preview`,
`fetch_context_with_view_crop`, `invalidate_view_crop_if_invalid`,
`_resolve_full_view_frame_for_crop`, `spatial_fingerprint_from_frame`, and
the private cross-module imports (`view_crop.py:16-17` and `plotModel.py:32`
both reach into `cube_view` privates; `plotModel.py:38` reaches into
`derived_fetch._profile_uses_nd_load`).

What it must preserve: preview responsiveness. The ancestor short-circuit is
the whole reason in-plane previews feel instant, so it has to be a real cache
hit, not a re-derivation. Benchmark the in-plane preview before and after;
regression budget is zero.

`RoiController` keeps the request-building and commit policy that is
genuinely ROI-specific (span-full expansion, profile-kind classification,
local-profile rejection, labelling) and loses the fetch plumbing.

## Re-homing the two `RunModel` subclasses

`CombinedRunModel` and `FrozenRunModel` subclass `RunModel` only because
`RunModel` was where `get_plot_data` lived. Both override the legacy API and
neither overrides `get_plot_bundle`, which is why combine is broken
(Evidence 2).

Once `get_plot_bundle` is the single entry point on `RunSource`, "a run
that is the average of other runs" is a **data-access** concern, not a
session concern: it is a `getData` that stacks and reduces, below the level
the request operates at. Both become `CatalogRun` implementations in
`models/data/`:

- `CombinedRun(CatalogRun)` — `getData` stacks and reduces the sources;
  `available_keys` is the intersection. Fixes the silent run\[0\] bug by
  construction, because there is no inherited `_run` to fall back to.
- `FrozenRun(CatalogRun)` — snapshots one y key.

`RunCollection` keeps the factories (`validate_combine`, `combine_runs`,
`freeze_runs`) since the *policy* of what may be combined is a collection
concern.

## Untouched

Protect these; they are already pure, tested, and correctly scoped:

`CatalogRun` and the `models/data/` backends · `plot_geometry.py` ·
`plot_view_frame.py` · `region.py` · `region_mesh.py` · `region_reduce.py` ·
`roi_set.py` · `models/cache/` · `models/catalog/`

`cube_view.py` is modified (crop folds in, `MaterializeRequest` merges into
`PlotRequest`) but its reduction and axis-order semantics are kept as-is.

## Migration order

One branch. Ordered for reviewability, not for shippability.

0. **Fixtures.** Done 2026-09-03. `metadata["dims"]` on `MemoryRun` and
   `models/sources/fixtures.py` with the separable 3-D fixture run. See
   [Test strategy](#test-strategy).
1a. **Value types.** Done 2026-09-03. `PlotRequest`, `ViewIntent`, `ViewSpec`,
   slim `ViewCrop` in `models/plot/view_spec.py` and
   `models/plot/plot_request.py`. `ViewIntent.project` refuses
   `ndim < plot_ndim`. Plot-axis compatibility across keys is
   `plot_axis_names`. Fan-out deferred. Transform on the request is the
   effective string; session preserves enabled/text. `CubeViewSpec` untouched.
   Tests live with the types (`view_spec.py`, `plot_request.py`); add
   `tests/test_view_spec.py` if projection cases are not already covered
   by `test_plot_bundle.py` / `test_plot_key_selection.py`.
1a2. **Canvas → worker → RunModel via PlotRequest.** Done 2026-09-03.
   `build_plot_request` / `view_spec_from_legacy` adapt today's PlotModel
   slice/cube/crop into a request. `PlotWorker` takes only a
   `PlotRequest`. `RunModel.get_plot_bundle` accepts a request. (Step 1b
   later deleted the unpack into `_fetch_plot_arrays`.)
1a3. **TraceKey vs PlotRequest on PlotDataModel.** Done 2026-09-03.
   Object identity is ``TraceKey(uid, xkey, ykey, fan_out_index)``;
   ``PlotRequest`` is the fetch fingerprint held on the model.
   ``PlotModel.ensure_plot_data`` assembles the request from session
   slice/cube/crop and ``set_request`` on view/crop/transform so the
   artist is reused. Canvas reads ``plot_data.request``. Map keyed by
   ``TraceKey``, not the full request.
1b. **`get_plot_bundle` pipeline.** Done 2026-09-03. The method name is
   still ``get_plot_bundle`` (not ``prepare_plot_bundle``). Orchestration
   lives on ``RunModel``; pure helpers live in ``models/plot/plot_bundle.py``:
   ``reduce_to_plot_plane`` (wraps ``materialize_view``, which is not
   renamed), ``slice_info_for_key``, ``reduce_loaded_array``,
   ``apply_normalization``, ``apply_transform``, ``build_plot_bundle``.
   ``_fetch_plot_arrays`` is deleted. Transform comes from
   ``request.transform`` with a per-call interpreter. Each norm key is
   reduced by its own dims (bug 6). ROI still takes
   ``region_frame`` / ``parent_spec`` / ``view_crop`` / ``label`` kwargs.
   Tests in ``tests/test_plot_bundle.py`` against the vppem fixture (1-D,
   2-D image, mesh, crop, SUM/MEAN, rank-1 projection, transform, y/norm
   rank matrix). 4-D cubes and ROI-on-this-path were left to existing
   ``test_derived_fetch.py`` / ``test_region*.py``.
2. **`RunSource` surface.** Done 2026-09-03. See
   [Step 2](#step-2-runsource-surface). ``KeyInfo`` / ``RunIdentity`` /
   ``AxisLayout``; ``key_table`` / ``identity`` / ``read`` /
   ``describe_axes`` / ``load_axes``; ``get_plot_bundle`` routed through
   ``read`` / ``load_axes``. Session state left on ``RunModel``
   (decision 12). ``RunSource = RunModel`` alias in place.
3. **`PlotSession` / `RunCollection`.** See
   [Step 3](#step-3-plotsession--runcollection). Merge session ownership;
   introduce ``RunCollection``; replace the six mutation paths with
   ``rebuild()`` over the existing ``PlotDataModel`` map; move selection /
   visibility / transform off ``RunSource``.
4. **`Trace`.** Request identity, cached bundle, artist retained per locked
   decision 7. `Trace` is the only bundle cache (locked decision 11).
5. **Consumer sweep.** `RunListItemModel` + ``PlotSession`` rename and the
   session‑only widget retarget live in
   [`plot_session_list_adapter_plan.md`](plot_session_list_adapter_plan.md)
   (do that first). Remaining here: `MplCanvas` renders a `TraceSet`;
   `DimensionControl` builds and pushes a `ViewIntent` instead of mutating
   a spec; delete the `ImageGridCanvas` bypass and its shape-discovery
   copy; fix the ~20 private-attribute reads catalogued in the consumer
   survey.
6. **`RoiController`.** Extract from `PlotSession`; turn the ancestor
   short-circuit into a `TraceSet` lookup. Drop the extra kwargs on
   ``get_plot_bundle``.
7. **Re-home** `CombinedRun` / `FrozenRun` into `models/data/`.
8. **Delete.**

## Step 2: `RunSource` surface

The class can stay named ``RunModel`` in this step (file ``runSource.py``)
with ``RunSource`` as an alias, or the file can move to ``run_source.py``
with ``RunModel = RunSource`` for imports. Prefer the alias-in-place so
step 2 is not a rename diff. The rename is step 8.

Two ways to cut this step were considered:

- **Strip session state now.** Delete selection, visibility, transform, and
  the interpreter, and update ``PlotModel`` / ``RunListModel`` /
  ``run_display.py`` in the same change. That is the end state, but it is
  step 3's merge wearing a step 2 label.
- **Add the six-member surface and stop growing re-exports** (this step).
  Session methods stay as a compatibility layer until ``PlotSession``
  takes them. Frozen overlay is applied in ``key_table``, ``read``,
  ``describe_axes``, and ``load_axes``, not in eleven wrappers.

### Add

Value types (new file ``models/plot/key_info.py``, snake_case; do not
create ``run_source.py`` until the step 8 rename):

```python
@dataclass(frozen=True)
class KeyInfo:
    name: str
    label: str
    shape: tuple[int, ...]
    synthetic: bool
    hinted: bool
    render_hint: str | None

@dataclass(frozen=True)
class RunIdentity:
    uid: str
    scan_id: str
    plan_name: str
    display_name: str
    metadata: Mapping[str, Any]
```

``AxisLayout`` is the return of today's ``analyze_dimensions`` plus the
name-list truncation already done in ``get_dimension_ui_info``. Do not
invent a second analysis.

Methods on the run object:

| Member | Implementation |
|---|---|
| ``key_table()`` | Merge ``CatalogRun.available_keys`` + shapes/hints with frozen entries. Cache; invalidate on ``keys_ready``, ``data_changed``, frozen register/remove. |
| ``identity()`` | Snapshot of uid / scan_id / plan_name / display_name / metadata. |
| ``read(key, slice_info)`` | Today's ``get_data`` (frozen then catalog). |
| ``describe_axes(ykey, xkeys)`` | Frozen shape/names when synthetic; else ``CatalogRun.analyze_dimensions`` with the ui-info name truncation. Placeholders (``np.arange``). |
| ``load_axes(ykey, xkeys, slice_info)`` | Real coordinates, including the stack-spectrum catalog-X path currently in ``RunModel._stack_spectrum_dimension_axes``. |
| ``get_plot_bundle(request)`` | Already the pipeline. Call ``read`` and ``load_axes`` instead of ``get_data`` / ``get_dimension_axes``. |

After this step, ``get_dimension_ui_info`` / ``get_dimension_axes`` on the
run object are one-line shims over ``describe_axes`` / ``load_axes`` so
``PlotModel`` and dimension UI keep compiling. There are no free-function
axis helpers and no separate ``axis_analysis`` member.

### Do not do in this step

- Delete ``set_selected_keys``, ``set_visible``, ``set_transform``,
  ``_transform_text``, ``_catalog_keys``, or the selection/visibility
  signals.
- Collapse ``available_keys_changed`` + ``frozen_spectra_changed`` into
  one ``keys_changed`` (``RunListModel`` still listens to both).
- Fold ROI kwargs off ``get_plot_bundle``.
- Re-home ``CombinedRunModel`` / ``FrozenRunModel``.
- Resolve open items 7–8 fully. ``KeyInfo.hinted`` may be ``True`` for
  every catalog key until ``get_hinted_keys`` is confirmed; ``render_hint``
  may be filled from ``get_render_mode_hint(getPlotHints(), name)`` and
  left ``None`` when that returns nothing. Note the choice in the test
  docstring.

### Callers that keep working without edits

``PlotModel``, ``RunListModel``, ``PlotDataModel``, ``run_display.py``,
``DimensionControl``, ``derived_fetch.py``. They still call
``get_selected_keys``, ``available_keys``, ``get_dimension_ui_info``,
``get_plot_bundle``. New code in this step must not add further
CatalogRun pass-throughs.

### Tests

``tests/test_run_source.py`` (headless, vppem fixture + frozen spectrum):

- ``key_table`` contains catalog keys and frozen keys; frozen rows have
  ``synthetic=True`` and the friendly ``label``.
- ``identity()`` matches the fixture uid / scan_id / plan_name.
- ``read`` on a frozen key does not call ``CatalogRun.getData`` for that
  key (existing frozen test).
- ``describe_axes`` / ``load_axes`` on ``PCOEdge_image`` agree with
  today's ``get_dimension_ui_info`` / ``get_dimension_axes`` (names
  ``sampleVoltage_VSource, dim_1, dim_2``).
- ``get_plot_bundle`` still matches the closed-form cells in
  ``test_plot_bundle.py`` after the internal reroute through ``read`` /
  ``load_axes``.

Existing ``test_frozen_spectrum.py`` and ``test_plot_key_selection.py``
must stay green; they are the compatibility net for the shims.

## Step 3: `PlotSession` / `RunCollection`

This is the ownership merge. After it, one session object owns membership,
visibility, selection, view intent, transform, and the plot-data map. The
four-signal protocol between ``RunListModel`` and ``PlotModel`` has nowhere
to live. ``RunSource`` keeps only the six-member surface from step 2.

Step 3 does **not** rename ``PlotDataModel`` → ``Trace`` (step 4), does
**not** rewrite ``run_display.py`` / ``DimensionControl`` / canvases to the
final session API (step 5), and does **not** extract ``RoiController``
(step 6). Those stay behind compatibility shims.

### Why it is hard

Today the truth is split:

| Fact | Owner today | Mirror |
|---|---|---|
| Membership + order | ``RunListModel._run_models`` | Qt rows on the same object |
| Visibility | ``RunListModel._visible_runs`` + item check state | ``RunModel._is_visible`` |
| Key selection | ``PlotModel._current_*`` | every ``RunModel._selected_*`` via sync |
| Unlinked per-run selection | ``RunModel._selected_*`` (widget writes directly) | intersection on re-link |
| Transform | ``PlotModel._transform`` | ``RunModel._transform_text`` + interpreter |
| Available key universe | ``RunListModel.available_keys`` | recomputed from visible catalog keys |
| Plot-data map | ``PlotModel._plot_data`` | mutated by six paths |

``run_display.py`` reads keys from the list and checkboxes from the plot;
unlinked mode writes ``RunModel.set_selected_keys`` directly. ``freeze_runs``
reads per-run selection. ``PlotDataModel`` listens to run visibility /
selection / transform signals. Stripping session state from ``RunModel``
without a session API and without a consumer sweep means every one of those
paths needs a shim or a temporary bridge.

``rebuild()`` is also awkward before ``Trace``: the target identity is a
``PlotRequest``, but today's map is keyed by ``TraceKey`` and the artist
lives on ``PlotDataModel``. Step 3 therefore rebuilds a set of
``TraceKey``s (plus updates held requests), not a ``TraceSet`` yet.

### Two ways to cut the step

**Option A — staged ownership (preferred).** Three reviewable diffs that
land the end-state ownership without rewriting every consumer:

1. **3a. ``RunCollection`` + move membership/visibility into ``PlotModel``.**
   Extract a plain container from ``RunListModel`` (ordered uid →
   ``RunSource``, combine/freeze factories). ``PlotModel`` owns the
   collection and visibility set. ``RunListModel`` keeps the
   ``QStandardItemModel`` surface and becomes a thin facade that forwards
   add/remove/visibility to the session (or is constructed *by* the session
   and observes it). Presenter still exposes ``run_list`` + ``plot``. No
   strip of ``RunModel`` yet. Replace ``_on_run_added`` /
   ``_on_run_removed`` / ``_on_visible_runs_changed`` / ``ensure_plot_data`` /
   ``drop_plot_data_for_uid`` / ``_ensure_plot_data_for_visible`` with one
   ``rebuild()`` that diffs desired ``TraceKey``s against ``_plot_data``.
2. **3b. Selection + transform owned only by the session.** Introduce
   ``Selection`` (session default + per-uid override map). ``Link Runs``
   becomes ``clear_overrides()``. Filter against ``key_table`` /
   ``key_universe`` at ``selection_for(uid)`` / request-build time, not
   inside ``RunModel.set_selected_keys``. Stop syncing selection and
   transform onto every ``RunModel``. ``freeze_runs`` and unlinked
   ``run_display`` write session overrides instead of run state.
3. **3c. Strip session state from ``RunSource``.** Delete
   ``_selected_*``, ``_is_visible``, ``_transform_text``, the live
   interpreter, ``set_selected_keys`` / ``set_visible`` / ``set_transform``,
   and the selection/visibility/transform signals on ``RunModel``.
   ``PlotDataModel`` stops listening to those run signals and reads
   visibility / transform from the session (or from its held request).
   ``available_keys_changed`` / ``frozen_spectra_changed`` may stay until
   step 5 collapses them to ``keys_changed``.

**Option B — one diff.** Do 3a–3c together, and also push
``run_display`` / presenter onto session-only reads. Smaller total churn
across the branch, larger review, and it bleeds into step 5. Rejected for
the same reason step 2 rejected stripping session state early.

Prefer **Option A**. Alias ``PlotSession = PlotModel`` (or rename the class
in place with ``PlotModel = PlotSession``) so step 3 is not a rename-only
diff; file rename to ``plot_session.py`` is step 8.

### Locked for this step (propose; confirm before coding)

1. **``Selection`` holds full ``(x, y, norm)`` tuples per override**, not
   sparse per-axis diffs. ``selection_for(uid)`` is then
   ``overrides.get(uid, default)`` filtered by that source's available
   keys. Clearing overrides is one map clear ("Link Runs"). Settles open
   item 3 toward the obvious API.
2. **Visibility is a set of uids on the session**, not a flag on
   ``RunSource``. Qt check state is a view of that set (today's
   ``RunListModel`` item sync, later ``RunListItemModel``). Bug 3
   (``visible_runs`` vs ``visible_models``) dies by having one accessor.
3. **``rebuild()`` target in step 3** is
   ``{(uid, x, y) for uid in visible for (x,y) in selection_for(uid)}``
   as ``TraceKey``s. For each desired key: create or ``set_request``. For
   extras: dispose. Fan-out index stays unused (open item 2). Request
   assembly still uses session slice/cube/crop via
   ``build_plot_request`` / ``ViewIntent.project`` when ready; do not
   require every caller to pass a ``ViewIntent`` yet.
4. **``key_universe()``** lives on the session: intersection of
   ``key_table()`` keys among visible sources, ordered with the existing
   ``time``-first preference (absorb ``update_available_keys`` + the
   display hack later; for 3a keep order compatible with today's list).
5. **ROI, crop invalidation, and ``RoiSetModel`` stay on ``PlotModel``**
   as they are. No ``RoiController`` extraction.
6. **Cache-status aggregation** stays on whatever object still owns the
   Qt list / presenter wiring (open item 5 deferred).
7. **Dynamic updates** stay as ``session → each source → CatalogRun``;
   bundle invalidation rule still deferred to step 4 (open item 4).

### Object shapes after step 3

```
PlotSession (alias PlotModel)          QObject
├── RunCollection                      plain container, not QObject
│   └── RunSource × N                  six-member surface only (after 3c)
├── visible: set[uid]
├── Selection                          default + overrides
├── view state                         still slice/cube/crop (ViewIntent later)
├── transform                          {enabled, text}
├── _plot_data: Dict[TraceKey, PlotDataModel]
├── RoiSetModel
└── rebuild()                          sole mutator of _plot_data membership

RunListModel                           still QStandardItemModel for now
                                       facade/observer over session membership
                                       + visibility; sidebar rows only
```

``PlotPresenter`` still constructs one list + one plot. Internally the plot
owns the collection; the list is either handed the session or created as
its Qt adapter. Prefer: **presenter creates ``PlotSession``, session
creates/owns ``RunCollection``, and ``RunListModel`` is constructed with a
reference to the session** so ``displayManager`` / widgets that take
``run_list_model`` keep compiling.

### ``rebuild()`` contract (step 3)

Visibility and trace retention are **different axes**. Today's code already
treats them that way; ``rebuild`` must not collapse them.

#### Hidden traces vs rebuild

Current behavior (preserve):

- ``_on_visible_runs_changed`` only calls ``_ensure_plot_data_for_visible``
  and ``request_plot_update``. It does **not** drop plot-data on uncheck
  (module docstring: "keep plot-data on uncheck").
- ``drop_plot_data_for_uid`` runs only on run **remove**.
- ``PlotDataModel`` keeps ``artist`` and ``last_bundle``. Re-show with an
  unchanged request hits ``needs_fetch() == False`` and is artist
  ``set_visible(True)`` — no worker, no catalog read. For images that is
  the first cache layer.

A naive ``desired = visible × selection`` would dispose on hide and
force a full re-fetch on show. That is a regression, especially for
large images and for ROI preview that reads ``last_bundle``.

So step 3 uses two sets:

```python
# Retention: what models exist (cache / artist identity)
retained = {
    TraceKey(uid, x, y)
    for uid in self.collection.uids()          # membership, not visibility
    for x, y in product(self.selection_for(uid).x, self.selection_for(uid).y)
}

# Drawing: what the canvas iterates
visible_keys = {k for k in retained if k.uid in self.visible_uids}
```

``rebuild()`` diffs ``retained`` against ``_plot_data`` (create / dispose /
``set_request``). Visibility changes do **not** call dispose; they only
emit ``request_plot_update`` (and eventually toggle artist visibility).
Run remove removes that uid from the collection, so those keys leave
``retained`` and are disposed — same as today.

```python
def rebuild(self) -> None:
    desired = self._retained_trace_keys()
    for key in set(self._plot_data) - desired:
        self._dispose_plot_data(key)
    for key in desired:
        source = self.collection.get(key.uid)
        request = self._request_for(source, key)
        if key in self._plot_data:
            self._plot_data[key].set_request(request)
        else:
            self._plot_data[key] = PlotDataModel(source, request, ...)
            self.plot_data_added.emit(self._plot_data[key])
```

Triggers that call ``rebuild()``: add/remove run, selection change,
view/crop/transform change that alters requests. **Not** visibility
toggle alone (unless a newly visible run has selection but no models
yet — then rebuild or a narrow ensure is needed for first paint; today's
``_ensure_plot_data_for_visible`` covers that. Equivalent: rebuild is
cheap when ``desired`` already matches, so calling it on visibility is
fine *as long as desired ignores visibility*).

Property to test: any sequence of add / remove / select leaves
``set(_plot_data)`` equal to membership × selection; hide/show sequences
leave the map and ``last_bundle`` intact and only change what
``iter_visible_plot_data`` yields.

This also amends the high-level sketch under
[Trace lifecycle](#trace-lifecycle-rebuild-by-diff), which had
``for uid in visible_uids``. That formula is the *draw* set, not the
*retain* set. Fan-out still enumerates views into retain when step 4/5
adds it.

### Compatibility during 3a–3c

| Caller | During step 3 | Deleted in |
|---|---|---|
| ``presenter.run_list`` / ``presenter.plot`` | keep both properties | step 5/8 |
| ``run_display`` linked mode | still ``plot.set_selected_keys``; keys from ``run_list.available_keys`` or session ``key_universe`` | step 5 |
| ``run_display`` unlinked mode | write ``session.set_selection_for(uid, ...)`` once 3b exists; until then may keep writing run (only until 3c) | step 5 |
| ``PlotDataModel`` run signal hooks | bridge until 3c; then listen to session or rely on ``set_request`` + ``data_changed`` from catalog | step 3c |
| ``freeze_runs`` | read ``session.selection_for(uid).y`` | — |
| Canvas / ``ensure_plot_data`` | may remain as a thin wrapper that calls ``rebuild`` semantics for one key, or become unused if canvas only iterates ``iter_visible_plot_data`` | step 5 |
| ``RunModel.set_selected_keys`` etc. | present through 3b; gone after 3c | 3c |

### Do not do in this step

- Rename files to ``plot_session.py`` / ``run_collection.py`` as the only
  change; prefer alias-in-place (``PlotSession = PlotModel``,
  ``RunCollection`` can be a new file).
- Full ``ViewIntent`` push from ``DimensionControl`` (step 5); session may
  *store* an intent if projection is already useful for request build.
- ``RunListItemModel`` in ``views/`` (step 5); keep ``RunListModel`` as Qt
  half + facade.
- Collapse ``available_keys_changed`` + ``frozen_spectra_changed`` into
  ``keys_changed`` on the source (step 5 widget API).
- ``Trace`` / artist-only cache redesign (step 4).
- Fix combine bug by re-homing ``CombinedRun`` (step 7); factories stay.
- Consumer private-attribute sweep (step 5).

### Suggested implementation order inside Option A

1. Add ``models/plot/run_collection.py`` and ``models/plot/selection.py``
   (value types + collection; no behavior change yet).
2. Give ``PlotModel`` ownership of a ``RunCollection`` and a visibility
   set; implement ``rebuild()``; retarget the six mutation paths to call
   it; keep ``RunListModel`` API by forwarding.
3. Wire presenter so one session is the root; list observes session.
4. Add ``Selection`` default + overrides; change ``set_selected_keys`` /
   link-mode / freeze to use it; stop syncing onto ``RunModel``.
5. Point ``PlotDataModel`` off run selection/visibility/transform signals.
6. Delete session state and signals from ``RunModel``.
7. Tests green at each numbered item.

### Tests

New ``tests/test_plot_session.py`` (headless, vppem + line fixtures):

- **Membership.** Add/remove updates collection order and ``rebuild``
  plot-data keys.
- **Visibility.** One accessor; toggling visibility changes which keys
  appear in ``iter_visible_plot_data`` without disposing hidden
  plot-data. Disposal is only for run remove or keys leaving the
  selection-based desired set. See [Hidden traces](#hidden-traces-vs-rebuild).
  Prefer **desired = membership × selection** (not visible-only), so
  hide/show stays a visibility toggle over retained models/artists/
  ``last_bundle`` — today's first-layer image cache.
- **Selection resolution.** Default + override + per-run key filter;
  assert through ``selection_for`` and through the requests on created
  plot-data, not through ``RunModel.get_selected_keys``.
- **Link Runs.** Setting overrides then ``clear_overrides()`` restores
  default for all uids.
- **``rebuild`` invariant.** Randomised sequences of add/remove/select
  leave ``set(_plot_data.keys()) == membership × selection``. Hide/show
  sequences leave the map and ``last_bundle`` intact.
- **No run selection after 3c.** ``RunModel`` has no ``set_selected_keys``;
  freeze and display tests use session APIs.

Keep green: ``test_plot_key_selection.py``, ``test_run_list_combine_freeze.py``,
``test_frozen_spectrum.py``, ``test_run_source.py``. Update combine/freeze
tests when freeze reads session selection.

### Open decisions to confirm before coding

1. **Hidden traces:** settled — **keep** on uncheck. Retention =
   membership × selection; visibility filters draw only. See
   [Hidden traces vs rebuild](#hidden-traces-vs-rebuild).
2. **``Selection`` storage:** full tuple overrides (recommended) vs sparse
   diffs?
3. **Presenter construction:** session-owns-list vs list-owns-collection
   with session wrapping list? Recommendation: session owns collection;
   list is Qt adapter referencing session.
4. **How far into ``run_display`` in 3b?** Minimum: unlinked writes go to
   ``set_selection_for``; leave ``_synthetic_entries`` /
   ``_synchronize_selections`` deletion for step 5.

## Deletion list

Files removed: `runSource.py` · `runListModel.py` · `plotDataModel.py` ·
`view_crop.py` (folded) · `derived_fetch.py` (split between `RoiController`
and the `TraceSet` lookup) · `combinedRunModel.py` and `frozenRunModel.py`
(moved).

Methods removed rather than moved: `RunModel.get_plot_data` (broken, no live
callers) · `PlotDataModel.get_plot_data` · `RunListModel.visible_runs` vs
`visible_models` (one accessor) · `PlotModel.cached_parent_bundle_for_preview`
(equality check) · the crop invalidation trio ·
`RunListModel.update_available_keys` and `synthetic_display_entries` (absorbed
by `key_universe`) · `RunDisplayWidget._synthetic_entries` and
`_synchronize_selections` · the nine `RunModel` pass-through properties and
frozen-key wrappers replaced by `KeyInfo` / `RunIdentity`.

Methods merged: `CatalogRun.get_dimension_ui_info` +
`CatalogRun.get_dimension_axes` → `describe_axes` + `load_axes`.

Moved to views: `RunListModel.getHeaderLabel`.

New-file naming follows the snake_case convention already used by
`cube_view.py`, `plot_geometry.py`, and `roi_set.py`, consistent with
`plot_package_reorganization.md`.

## Test strategy

The pure core is testable without Qt, which is the main reason to do step 1
first.

- **Fixtures.** `models/sources/fixtures.py` holds deterministic
  `MemoryRun` builders: fixed uids and closed-form array contents, unlike the
  `uuid4`-based demo runs in `testSource.py`. `make_vppem_run` models vppem
  scan 102 at `(11, 24, 32)` — a motor-scanned leading axis plus two detector
  axes, carrying a rank-1 y key, a rank-3 y key, and a normalization key.

  The image cube is **separable**, `image[i, j, k] = a[i] * b[j] * c[k]`, so
  every `SUM` / `MEAN` / `INDEX` combination has an exact expected value that
  a test computes from `vppem_factors()` without re-implementing the fetch
  path. `PCOEdge_stats` is the per-frame mean, so a mean reduction over both
  detector axes must reproduce it. This lets the N-D tests assert
  *correctness*, not only that the refactor preserved behavior — which
  matters because the path being replaced has four known live bugs.

  `MemoryRun` now honors `metadata["dims"]`, so a fixture declares dimension
  names instead of relying on shape inference. Omitting a key from the
  mapping still exercises the inference fallback.

  Two facts fixture-based assertions must account for: `prepare_2d_bundle`
  flips the row axis for display, so a 2-D bundle equals
  `expected[::-1, :]`; and axis 0 of a resolved 3-D cube is named
  `sampleVoltage_VSource`, not `time`, because `analyze_dimensions`
  substitutes a single associated motor for the event axis
  (`data/base.py:629-645`).
- **`get_plot_bundle`.** Table-driven tests in ``tests/test_plot_bundle.py``
  over the fixture catalog: 1-D, 2-D image, 2-D mesh, 3-D cubes with
  ``INDEX`` / ``SUM`` / ``MEAN``, crop, normalization, and transform.
  4-D and ROI-on-this-path are still the older tests. Because the cube
  is separable, each cell asserts against a closed form rather than against
  the previous implementation.
- **The pure functions stay independently tested.** `reduce_to_plot_plane`,
  `build_plot_bundle`, and the region compilers are tested with hand-built
  arrays and no `RunSource`, as `test_materialize_view.py` and
  `test_cube_view.py` already do. This is the payoff of the load / reduce
  seam and the reason not to fold everything into one method body.
- **`ViewIntent.project`.** One intent projected against ranks 1 through 4
  yields specs whose `ndim` matches the key and whose roles preserve the
  user's choice where the rank allows. Assert that a rank-1 projection needs
  no special-casing downstream.
- **Normalization rank matrix.** Done in 1b for the fixture cells
  (rank-1 y / rank-1 i0, rank-3 y INDEX / i0, rank-3 y MEAN-MEAN / i0).
  Bug 6 is the rank-3-y / rank-1-norm cell and no longer raises.
- **Regression pin.** Not captured as byte-equality against the old
  ``_fetch_plot_arrays``. The closed-form fixture assertions are the pin
  for cells the old path got right; the i0/cube cell had no old baseline.
- **`rebuild()` diff.** Property test: any sequence of add / remove / toggle
  / select / view-change operations leaves the trace set equal to the pure
  function of final state. This is the invariant the six mutation paths
  cannot currently state.
- **Selection resolution.** Session default plus per-run overrides plus
  per-run available-key filtering, asserted through the request rather than
  through two stored copies.
- **ROI preview parity and timing.** Same bundle as today for in-plane and
  N-D profiles; in-plane preview latency not worse.
- Existing `tests/` (`test_materialize_view.py`, `test_view_crop.py`,
  `test_derived_fetch.py`, `test_plot_geometry.py`, `test_region*.py`) are
  the starting corpus. `test_derived_fetch.py` and `test_view_crop.py` get
  rewritten against the unified path.

## Open items

1. **Plane coordinate arrays at resolve time.** Still open. Step 1b did
   not add a plane-coord memo. Ordinary fetches use
   ``ViewSpec.load_slice()`` with crop folded in; ROI still compiles
   through ``MaterializeRequest.fetch_context`` and extra kwargs. Decide
   with a benchmark when those kwargs fold (step 6).
2. **Fan-out API.** Deferred past the value-types slice. When added, lives
   on ``ViewIntent`` (not ``ViewSpec``): enumerate INDEX values along one
   reduce axis into a list of ``ViewSpec``s the session zips with selection.
   Affects how the image grid paginates.
3. **`Selection` as a value type.** Proposed settled in
   [Step 3](#step-3-plotsession--runcollection): override map holds full
   ``(x, y, norm)`` selections per uid; ``selection_for`` is override-or-
   default then filter; "Link Runs" clears the map. Confirm before 3b.
4. **Dynamic / live runs.** `set_dynamic` currently fans out through
   `RunListModel` to every `RunModel` to every `CatalogRun`. Under the new
   tree it is `PlotSession` → `RunSource` → `CatalogRun`, but live data means
   the bundle cache must invalidate on `data_changed`. Specify the
   invalidation rule before step 4.
5. **Cache status aggregation.** `RunListModel._refresh_cache_progress_connections`
   discovers `run._chunk_cache.progress` by `getattr` chain
   (`runListModel.py:620-628`). Needs a declared interface on `CatalogRun`,
   or move aggregation to the cache layer.
6. **Teardown.** No object in the current tree has a disciplined teardown
   (`codebase_problem_statement.md` §1). The ownership tree makes it
   possible; whether this branch does it or defers is unresolved.
7. **`KeyInfo.hinted` semantics.** `CatalogRun.get_hinted_keys`
   (`data/base.py:300`) has zero callers and is the only existing definition
   of "hinted". Confirm it produces the key set the "Show All Keys" checkbox
   was meant to toggle before wiring `KeyInfo.hinted` to it.
8. **`KeyInfo.render_hint` granularity.** `getPlotHints` is per-run and
   `get_render_mode_hint` derives a per-y-key answer from it. Projecting it
   per key at table-build time is the intent; verify no hint depends on the
   x selection.
9. **Transform toggle state.** Settled 2026-09-03: ``PlotRequest.transform``
   is the effective expression string (empty means off). The session keeps
   ``enabled: bool`` + ``text: str`` so toggling off preserves the expression
   for the typical view pattern.

## Bugs found during analysis

Record these regardless of whether the refactor proceeds.

1. **Combining runs plots the first run.** Still open. `CombinedRunModel`
   does not override `get_plot_bundle`; the inherited path reads `self._run`,
   set to `runs[0].run` by `super().__init__(first_run.run)`. Silent wrong
   answer. Fixed in step 7 by making combine a `CatalogRun`.
2. **`RunModel.get_plot_data` raised.** Fixed in 1a2/1b: it builds a
   `PlotRequest` and calls `get_plot_bundle`. The canvas still does not use
   this method, so bug 1 is unchanged.
3. **`visible_runs` and `visible_models` disagree** on the main display
   (`runListModel.py:589-606`); `PlotModel` uses both.
4. **"Show All Keys" is a no-op.** `RunDisplayWidget._show_all` is written at
   `run_display.py:55` and `:369` and never read; the checkbox only triggers
   a rebuild that ignores it. The intended backing is almost certainly
   `CatalogRun.get_hinted_keys` (`data/base.py:300`), which has zero callers.
5. **Unlinked mode double-lists synthetic keys.** `RunModel.available_keys`
   is catalog keys plus frozen keys (`runSource.py:120`), so in unlinked mode
   a frozen spectrum gets a row in the catalog loop — with an X checkbox it
   should not have — and another row in the synthetic section. The linked
   path avoids this by intersecting `catalog_keys` instead.
6. **Normalizing an N-D y key by a lower-rank norm key raised.** Fixed in
   1b. Each norm key is sliced and reduced from its own dimension names
   (`slice_info_for_key` + `reduce_loaded_array`). The fixture cell
   `ykey="PCOEdge_image"`, `norm_keys=["i0"]` is asserted in
   `tests/test_plot_bundle.py`.
7. **`BlueskyRun` infers one dimension name too many.**
   `_infer_dims_from_shape` uses `range(0, ndim)` where `MemoryRun` uses
   `range(1, ndim)` (`bluesky.py:696` vs `memory.py:301`), so a rank-3 key
   yields `("time", "dim_0", "dim_1", "dim_2")`. `analyze_dimensions` indexes
   axis hints positionally against the post-`time` dimension list
   (`data/base.py:607-619`), so every dimension receives the previous
   dimension's `axes` hint whenever `getAxisHints` is non-empty. Data without
   `axes` hints is unaffected because `get_dimension_ui_info` truncates the
   name list back to `ndim` (`data/base.py:674-679`), which masks the fault.
8. **`BlueskyRun.getRunKeys` discards y-key rank.** It ends with
   `ykeys[1] = all_keys` (`bluesky.py:514`), so `ykeys[2]` and higher are
   never populated and a rank-3 camera key is reported as rank 1.
   `MemoryRun.getRunKeys` buckets by true rank (`memory.py:174-177`), so the
   two backends disagree about what the `ykeys` grouping means. Queued as its
   own commit; until it lands, tests must not assert on `ykeys` grouping if
   they want to describe live behavior.
