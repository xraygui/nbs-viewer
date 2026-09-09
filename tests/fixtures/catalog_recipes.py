"""Named in-memory catalog recipes for headless tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List
from uuid import uuid4

import numpy as np

from nbs_viewer.models.catalog.memory import MemoryCatalog
from nbs_viewer.models.data.memory import MemoryRun

RECIPE_NAMES = ("line_scan", "motor_scan", "image_scan")


def _base_metadata(
    scan_id: int,
    *,
    plan_name: str = "test",
    motors: List[str] | None = None,
    dimensions=None,
    dims=None,
) -> dict:
    base_datetime = datetime.strptime("2026-08-01", "%Y-%m-%d")
    metadata = {
        "scan_id": scan_id,
        "plan_name": plan_name,
        "date": base_datetime + timedelta(minutes=10 * scan_id),
        "exit_status": "Success",
        "uid": str(uuid4()),
        "motors": motors or [],
        "hints": {"dimensions": dimensions or [(["time"], "primary")]},
    }
    if dims:
        metadata["dims"] = dims
    return metadata


def line_scan_run(scan_id: int = 0) -> MemoryRun:
    """
    Build a 1D line scan with ``time`` and ``y`` arrays.

    Parameters
    ----------
    scan_id : int, optional
        Scan index used to vary the waveform.

    Returns
    -------
    MemoryRun
        Synthetic run suitable for combine/freeze and 1D plots.
    """
    t = np.linspace(0, 1, 100)
    data = {
        "time": t,
        "y": np.sin((scan_id + 1) * t * np.pi),
    }
    metadata = _base_metadata(scan_id, motors=["time"])
    return MemoryRun(metadata, data)


def motor_scan_run(scan_id: int = 0) -> MemoryRun:
    """
    Build a 1D motor scan with ``time``, ``motor``, and ``det``.

    Parameters
    ----------
    scan_id : int, optional
        Scan index used to vary detector counts.

    Returns
    -------
    MemoryRun
        Synthetic run with an independent motor axis.
    """
    t = np.linspace(0, 1, 64)
    motor = np.linspace(0, 10, 64)
    data = {
        "time": t,
        "motor": motor,
        "det": np.sin((scan_id + 1) * motor) + 1.0,
    }
    metadata = _base_metadata(
        scan_id,
        plan_name="motor_scan",
        motors=["motor"],
        dimensions=[(["motor"], "primary")],
    )
    return MemoryRun(metadata, data)


def image_scan_run(
    scan_id: int = 0, *, n_y: int = 30, n_x: int = 40, n_z: int = 3
) -> MemoryRun:
    """
    Build an image scan carrying both a 2D and a 3D detector key.

    ``detector_image`` is ``(row, pixel)`` and ``detector_cube`` is
    ``(row, pixel, dim_2)`` -- the same plane with a short third axis added,
    so a test can compare a rank-2 key against a rank-3 one whose leading
    axes mean the same thing. Both live on one run deliberately: the
    mixed-rank paths only exist when a 2D and a 3D key are selectable
    together.

    ``dim_2`` is short on purpose. It is a reduce axis in every 2D view, so
    its only job is to be indexable and to make a wrong axis choice show up
    as a shape mismatch rather than a plausible-looking plane.

    Parameters
    ----------
    scan_id : int, optional
        Scan index added to detector values.
    n_y : int, optional
        Row count for both detector keys.
    n_x : int, optional
        Column count for both detector keys.
    n_z : int, optional
        Length of the third axis on ``detector_cube``.

    Returns
    -------
    MemoryRun
        Run with ``en_energy``, ``pixel``, ``row``, ``dim_2``,
        ``detector_image`` and ``detector_cube``.
    """
    en_energy = np.linspace(200.0, 1000.0, n_x)
    pixel = np.cumsum(np.linspace(0.1, 0.3, n_x))
    detector_image = (
        np.arange(n_y * n_x, dtype=float).reshape(n_y, n_x) + float(scan_id)
    )
    row_axis = np.linspace(0.0, 1.0, n_y)
    dim_2_axis = np.linspace(0.0, 1.0, n_z)
    # Each slab differs by a multiple of the plane's own range, so indexing
    # the wrong axis produces values no other slab could hold.
    detector_cube = (
        detector_image[:, :, None]
        + np.arange(n_z, dtype=float)[None, None, :] * float(n_y * n_x)
    )
    data = {
        "en_energy": en_energy,
        "pixel": pixel,
        "row": row_axis,
        "dim_2": dim_2_axis,
        "detector_image": detector_image,
        "detector_cube": detector_cube,
    }
    metadata = _base_metadata(
        scan_id,
        plan_name="image_scan",
        motors=["en_energy", "pixel"],
        dimensions=[
            (["row"], "primary"),
            (["pixel"], "primary"),
        ],
        # Declared for the cube only. Naming ``detector_image``'s axes would
        # resolve them to the real (non-uniform) ``pixel`` coordinates and
        # flip it from an image to a mesh, changing a fixture every existing
        # ROI test depends on. The 2-D key stays exactly as it was.
        dims={"detector_cube": ("row", "pixel", "dim_2")},
    )
    return MemoryRun(metadata, data)


_RECIPE_BUILDERS = {
    "line_scan": line_scan_run,
    "motor_scan": motor_scan_run,
    "image_scan": image_scan_run,
}


def build_runs(recipe: str = "line_scan", *, runs: int = 3) -> List[MemoryRun]:
    """
    Build a list of memory runs for a named recipe.

    Parameters
    ----------
    recipe : str, optional
        One of ``line_scan``, ``motor_scan``, or ``image_scan``.
    runs : int, optional
        Number of runs to synthesize.

    Returns
    -------
    list of MemoryRun
        Synthetic runs for the recipe.

    Raises
    ------
    ValueError
        If ``recipe`` is unknown.
    """
    try:
        builder = _RECIPE_BUILDERS[recipe]
    except KeyError as exc:
        names = ", ".join(RECIPE_NAMES)
        raise ValueError(f"Unknown recipe {recipe!r}; expected one of {names}") from exc
    return [builder(scan_id=i) for i in range(runs)]


def build_catalog(recipe: str = "line_scan", *, runs: int = 3) -> MemoryCatalog:
    """
    Build an in-memory catalog for a named recipe.

    Parameters
    ----------
    recipe : str, optional
        Recipe name passed to :func:`build_runs`.
    runs : int, optional
        Number of runs in the catalog.

    Returns
    -------
    MemoryCatalog
        Catalog containing synthetic runs.
    """
    return MemoryCatalog(build_runs(recipe, runs=runs))
