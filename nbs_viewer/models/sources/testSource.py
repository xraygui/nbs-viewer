from .base import SourceModel
from .fixtures import make_fixture_runs
from ..catalog.memory import MemoryCatalog
from ..data.memory import MemoryRun
from uuid import uuid4
import numpy as np
from datetime import datetime, timedelta

def create_metadata(date='2026-08-01', runs=10):
    base_datetime = datetime.strptime(date, "%Y-%m-%d")
    return [
        {
            "scan_id": i,
            "plan_name": "test",
            "date": base_datetime + timedelta(minutes=10 * i),
            "exit_status": "Success",
            "uid": str(uuid4()),
            "motors": ["x"],
            "hints": {"dimensions": [(["x"], "primary")]},
        }
        for i in range(runs)
    ]

def create_data(runs=10, n_depth=4):
    """
    Build the demo data keys for the test catalog.

    ``image`` stays a 2-D key and ``image_cube`` is the same plane with a
    short third axis added, so the catalog offers a rank-2 and a rank-3
    detector whose leading axes mean the same thing. The 3-D key is what
    exercises reduce sliders, ROI profiles along a cube, and the mixed-rank
    paths that only exist when a 2-D and a 3-D key can be selected together.

    ``n_depth`` is small on purpose: the third axis is a reduce axis in every
    2-D view, so it only has to be indexable, and a short one makes a wrong
    axis choice show up as a shape mismatch rather than a plausible plane.

    Parameters
    ----------
    runs : int, optional
        Number of runs to generate.
    n_depth : int, optional
        Length of ``image_cube``'s third axis.

    Returns
    -------
    list of dict
        One data dictionary per run.
    """
    t = np.linspace(0, 1, 100)
    x = np.linspace(0, 1, 32)
    depth = np.linspace(0.5, 1.5, n_depth)
    data = []
    for i in range(runs):
        image = np.outer(np.sin(i * t * np.pi), np.cos(x * np.pi))
        data.append(
            {
                "time": t,
                "x": np.pi * t,
                "y": np.sin(i * t * np.pi),
                "image": image,
                # Each slab is the plane scaled by a distinct factor, so a
                # slice taken along the wrong axis cannot look like a right
                # one.
                "image_cube": image[:, :, None] * depth[None, None, :],
            }
        )
    return data

def create_runs(runs=10, include_nd=False):
    """
    Build demo runs for the test catalog.

    Parameters
    ----------
    runs : int, optional
        Number of generated 1-D/2-D demo runs. ``include_nd`` runs are added
        on top of this count.
    include_nd : bool, optional
        Append the deterministic N-D fixture runs from
        :mod:`nbs_viewer.models.sources.fixtures`. Off by default so
        ``runs`` remains the exact catalog size.

    Returns
    -------
    list of MemoryRun
        Demo runs.
    """
    metadata = create_metadata(runs=runs)
    data = create_data(runs=runs)
    generated = [MemoryRun(m, d) for m, d in zip(metadata, data)]
    if include_nd:
        generated.extend(make_fixture_runs())
    return generated

def create_test_catalog(runs=10, include_nd=False):
    runs = create_runs(runs, include_nd=include_nd)
    c = MemoryCatalog(runs)
    return c

class TestSourceModel(SourceModel):
    def __init__(self, runs=10, include_nd=False):
        super().__init__()
        self.runs = runs
        self.include_nd = include_nd

    def get_source(self, **kwargs):
        return (
            create_test_catalog(self.runs, include_nd=self.include_nd),
            "Test Catalog",
        )

    def is_configured(self):
        return True

    def get_display_label(self):
        return "Test Catalog"