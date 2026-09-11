"""
Deterministic in-memory run fixtures for headless tests and interactive use.

Unlike :mod:`nbs_viewer.models.sources.testSource`, every builder here is
reproducible: uids are fixed strings and array contents follow closed-form
expressions. Reductions and slices of the fixture data therefore have exact
expected values that a test can compute without re-implementing the fetch
path, which lets the N-D tests assert correctness rather than only asserting
that a refactor preserved behavior.
"""

from typing import Dict, List, Tuple

import numpy as np

from ..catalog.memory import MemoryCatalog
from ..data.memory import MemoryRun

VPPEM_UID = "vppem-3d-0001"
VPPEM_SHAPE = (11, 24, 32)


def voltage_axis(n_points: int) -> np.ndarray:
    """
    Build a monotonic, non-uniformly spaced coordinate axis.

    Non-uniform spacing distinguishes coordinate values from storage indices,
    so a consumer that plots index positions instead of coordinates produces a
    visibly different result.

    Parameters
    ----------
    n_points : int
        Number of points along the axis.

    Returns
    -------
    np.ndarray
        Strictly increasing values spanning ``[-2.0, 2.0]``, shape
        ``(n_points,)``.
    """
    ramp = np.linspace(-2.0, 2.0, n_points)
    return ramp**3 / 4.0


def vppem_factors(
    shape: Tuple[int, int, int] = VPPEM_SHAPE,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build the separable factors of the fixture image cube.

    The cube is ``a[i] * b[j] * c[k]``, so a reduction over any subset of axes
    is the product of the corresponding factor reductions. Tests import these
    factors to build expected values rather than duplicating the formula.

    Parameters
    ----------
    shape : tuple of int, optional
        Cube shape as ``(n_voltage, n_rows, n_cols)``.

    Returns
    -------
    tuple of np.ndarray
        Factors ``(a, b, c)`` with shapes ``(n_voltage,)``, ``(n_rows,)`` and
        ``(n_cols,)``. All values are strictly positive and distinct within
        each factor.
    """
    n_voltage, n_rows, n_cols = shape
    a = 3.0 + voltage_axis(n_voltage)
    b = 1.0 + np.arange(n_rows, dtype=float)
    c = 1.0 + 0.5 * np.arange(n_cols, dtype=float)
    return a, b, c


def vppem_image(shape: Tuple[int, int, int] = VPPEM_SHAPE) -> np.ndarray:
    """
    Build the separable 3-D image cube.

    Parameters
    ----------
    shape : tuple of int, optional
        Cube shape as ``(n_voltage, n_rows, n_cols)``.

    Returns
    -------
    np.ndarray
        Cube of shape ``shape`` equal to the outer product of
        :func:`vppem_factors`.
    """
    a, b, c = vppem_factors(shape)
    return a[:, None, None] * b[None, :, None] * c[None, None, :]


def make_vppem_data(
    shape: Tuple[int, int, int] = VPPEM_SHAPE,
) -> Dict[str, np.ndarray]:
    """
    Build the data dictionary for the 3-D fixture run.

    Parameters
    ----------
    shape : tuple of int, optional
        Cube shape as ``(n_voltage, n_rows, n_cols)``.

    Returns
    -------
    dict
        Mapping of data key to array. ``PCOEdge_stats`` is the per-frame mean
        of ``PCOEdge_image``, so a mean reduction over both detector axes
        reproduces it exactly.
    """
    n_voltage = shape[0]
    a, b, c = vppem_factors(shape)
    return {
        "time": 0.5 * np.arange(n_voltage, dtype=float),
        "sampleVoltage_VSource": voltage_axis(n_voltage),
        "i0": np.linspace(2.0, 3.0, n_voltage),
        "PCOEdge_stats": a * b.mean() * c.mean(),
        "PCOEdge_image": vppem_image(shape),
    }


def make_vppem_metadata(
    uid: str = VPPEM_UID,
    scan_id: int = 102,
    date: str = "2026-08-04",
) -> Dict:
    """
    Build the metadata document for the 3-D fixture run.

    Models vppem scan 102: a voltage sweep with a camera collecting one frame
    per step. Dimension names are declared explicitly rather than inferred, so
    the fixture describes the run the way stored data should describe itself.

    Parameters
    ----------
    uid : str, optional
        Run uid.
    scan_id : int, optional
        Run scan id.
    date : str, optional
        Run date in ``YYYY-MM-DD`` form.

    Returns
    -------
    dict
        Metadata document accepted by :class:`MemoryRun`.
    """
    return {
        "uid": uid,
        "scan_id": scan_id,
        "plan_name": "nd_scan",
        "date": date,
        "exit_status": "success",
        "motors": ["sampleVoltage_VSource"],
        "hints": {"dimensions": [(["sampleVoltage_VSource"], "primary")]},
        "plot_hints": {"auxiliary": ["PCOEdge_image", "PCOEdge_stats"]},
        "dims": {
            "time": ("time",),
            "sampleVoltage_VSource": ("time",),
            "i0": ("time",),
            "PCOEdge_stats": ("time",),
            "PCOEdge_image": ("time", "dim_1", "dim_2"),
        },
    }


def make_vppem_run(
    shape: Tuple[int, int, int] = VPPEM_SHAPE,
    uid: str = VPPEM_UID,
    scan_id: int = 102,
    catalog=None,
) -> MemoryRun:
    """
    Build a 3-D fixture run modeled on vppem scan 102.

    The run carries a motor-scanned leading axis and two detector axes, so
    :meth:`CatalogRun.plot_axis_names` resolves ``time`` to
    ``sampleVoltage_VSource`` and reports
    ``[sampleVoltage_VSource, dim_1, dim_2]``. Y keys of rank 1
    (``PCOEdge_stats``) and rank 3 (``PCOEdge_image``) are both present, along
    with a normalization key (``i0``).

    Parameters
    ----------
    shape : tuple of int, optional
        Cube shape as ``(n_voltage, n_rows, n_cols)``.
    uid : str, optional
        Run uid.
    scan_id : int, optional
        Run scan id.
    catalog : object, optional
        Parent catalog.

    Returns
    -------
    MemoryRun
        Run holding the fixture data.
    """
    metadata = make_vppem_metadata(uid=uid, scan_id=scan_id)
    return MemoryRun(metadata, make_vppem_data(shape), catalog=catalog)


def make_vppem_catalog(
    shape: Tuple[int, int, int] = VPPEM_SHAPE,
) -> MemoryCatalog:
    """
    Build a catalog containing only the 3-D fixture run.

    Parameters
    ----------
    shape : tuple of int, optional
        Cube shape as ``(n_voltage, n_rows, n_cols)``.

    Returns
    -------
    MemoryCatalog
        Catalog holding one run from :func:`make_vppem_run`.
    """
    return MemoryCatalog([make_vppem_run(shape)])


def make_fixture_runs(
    shape: Tuple[int, int, int] = VPPEM_SHAPE,
) -> List[MemoryRun]:
    """
    Build every deterministic fixture run.

    Parameters
    ----------
    shape : tuple of int, optional
        Cube shape passed to :func:`make_vppem_run`.

    Returns
    -------
    list of MemoryRun
        All fixture runs, currently the 3-D vppem analogue only.
    """
    return [make_vppem_run(shape)]
