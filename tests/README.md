# nbs-viewer test suite

Active pytest suite. Legacy tests live in `oldtests/` until promoted file-by-file.

See [`planDocuments/headless_testing_plan.md`](../planDocuments/headless_testing_plan.md)
for the full migration plan.

## Running tests

```bash
pixi run pytest tests/           # preferred (project env)
pytest tests/                    # or PYTHONPATH=. pytest tests/
pytest tests/test_view_spec.py   # single file
```

`oldtests/` is excluded via `testpaths` in `pyproject.toml`. To run a legacy
file during promotion:

```bash
pytest oldtests/test_foo.py -v
```

## Promoting a test from oldtests

1. Copy `oldtests/test_foo.py` → `tests/test_foo.py`
2. Run `pytest tests/test_foo.py -v`
3. Commit the new file and remove `oldtests/test_foo.py`

Promote H0 (pure logic) files before H1 model tests. H1 files should use
shared fixtures from `conftest.py` once Phase 1 lands.

## Fixtures (Phase 1)

Shared helpers live under `tests/fixtures/`:

- `catalog_recipes.py` — `line_scan`, `motor_scan`, `image_scan` recipes.
  `image_scan` carries both `detector_image` (rank 2) and `detector_cube`
  (rank 3), so mixed-rank and reduce-axis paths are reachable
- `session.py` — `HeadlessSession` wrapper around `AppModel`

Pytest fixtures in `conftest.py`:

- `qapp` — session-scoped, autouse **`QApplication`** on the offscreen
  platform. It is a `QCoreApplication` subclass, so model tests are
  unaffected, but it also permits constructing a `QWidget`. Autouse because
  a `QWidget` built without a `QApplication` makes Qt call `abort()`, which
  kills the pytest process rather than failing a test
- `app_model` — fresh `AppModel` per test
- `headless_session` — `HeadlessSession` with a default line-scan catalog

Example:

```python
def test_fetch(headless_session):
    run = headless_session.select_run(0)
    bundle = headless_session.fetch_bundle(["time"], ["y"])
    assert bundle.y.ndim == 1
```

## Widget tests

`test_widgets.py` builds real widgets. Prefer a model-side test whenever the
behaviour can be reached without one: widget tests wait on the Qt event loop
and are an order of magnitude slower. Reach for that file when the thing under
test *is* the widget wiring — artist lifetime, constructor coupling, or a
control populating itself.


| Tier | Meaning | Examples |
|------|---------|----------|
| H0 | Pure numpy / logic; no Qt | `test_view_spec.py`, `test_plot_geometry.py` |
| H1 | QObject models; no widgets | `test_plot_model.py`, `test_plot_presenter.py` |
| H2 | Qt widgets / manual scripts | deferred to `test/` or `scripts/` |

Manual / network scripts remain under `test/` (not collected by pytest).
