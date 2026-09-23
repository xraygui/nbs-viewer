"""
A run whose data is computed from several other runs.

Combining is a data-layer job: it answers "what array is under this key",
which is the only thing the plot pipeline asks a run for. Written as a
``RunSource`` subclass it was instead a *sibling* of that pipeline, and so it
inherited a fetch path that read one backing run and silently plotted the
first of its sources.

Each source carries a **key binding** saying which of its own keys to read.
:data:`REQUESTED` means "whatever key the request asked for", which is the
ordinary case; a literal key name pins that source to one measurement. The
pinned form is what expresses cross-run normalization -- a live run divided
by a frozen reference's ``i0`` -- without any source having to substitute one
key for another behind the request's back.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from asteval import Interpreter

from .base import CatalogRun


class CombinationMethod(Enum):
    """Methods for combining multiple runs."""

    AVERAGE = "average"
    SUM = "sum"
    EXPRESSION = "expression"


class CombineError(Exception):
    """Raised when runs cannot be combined."""


class _Requested:
    """Sentinel binding: read whichever key the request asked for."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "REQUESTED"


REQUESTED = _Requested()

Binding = Union[str, _Requested]
Source = Tuple[CatalogRun, Binding]


def make_scan_id(scan_ids: List[Any]) -> str:
    """
    Make a combined scan ID label from a list of scan IDs.

    Parameters
    ----------
    scan_ids : list
        Scan IDs to combine.

    Returns
    -------
    str
        Combined label, truncated to first and last if more than three.
    """
    try:
        sorted_ids = sorted(scan_ids)
    except TypeError:
        # A combination of combinations has a string scan id beside ints.
        sorted_ids = sorted(scan_ids, key=str)
    if len(sorted_ids) <= 3:
        return ", ".join(map(str, sorted_ids))
    return f"{sorted_ids[0]}...{sorted_ids[-1]}"


def truncate_to_common(arrays: Sequence[np.ndarray]) -> List[np.ndarray]:
    """
    Clip arrays to their common extent on the axes they share.

    A frozen reference is complete while the run it normalizes may still be
    growing, so the shared axes are clipped to the shortest -- which will be
    the dynamic run, since a run cannot be frozen until it has finished. Axes
    beyond the lowest rank present are left alone, so a 2-D detector combined
    with a 1-D reference keeps its detector axis.

    Parameters
    ----------
    arrays : sequence of np.ndarray
        Arrays to align.

    Returns
    -------
    list of np.ndarray
        Views clipped to the common leading extent.
    """
    arrays = [np.asarray(a) for a in arrays]
    if not arrays:
        return []
    ndim = min(a.ndim for a in arrays)
    if ndim == 0:
        return arrays
    limits = [min(a.shape[axis] for a in arrays) for axis in range(ndim)]
    if all(
        all(a.shape[axis] == limits[axis] for axis in range(ndim))
        for a in arrays
    ):
        return arrays
    index = tuple(slice(0, limit) for limit in limits)
    return [a[index] for a in arrays]


class CombinedRun(CatalogRun):
    """
    Several runs combined into one virtual run.

    Parameters
    ----------
    sources : sequence of (CatalogRun, binding)
        Runs to combine and, for each, which of its keys to read.
        :data:`REQUESTED` reads the key the caller asked for; a string pins
        that source to that key.
    method : CombinationMethod, optional
        How to combine, by default AVERAGE.
    expression : str, optional
        Required when ``method`` is EXPRESSION. Evaluated with the source
        arrays bound to ``runlist`` in source order.
    catalog : object, optional
        Parent catalog, by default None.

    Raises
    ------
    CombineError
        If no source is bound to :data:`REQUESTED`, or EXPRESSION is chosen
        with no expression.
    """

    DISPLAY_KEYS = {
        "scan_id": "Scan ID",
        "uid": "UID",
        "num_points": "Scan Points",
        "plan_name": "Plan Name",
        "exit_status": "Status",
    }

    METADATA_KEYS = [
        "scan_id",
        "plan_name",
        "num_points",
        "exit_status",
        "uid",
    ]

    def __init__(
        self,
        sources: Sequence[Source],
        method: CombinationMethod = CombinationMethod.AVERAGE,
        expression: Optional[str] = None,
        catalog: object = None,
    ):
        self._sources: List[Source] = [
            (run, binding) for run, binding in sources
        ]
        if not any(binding is REQUESTED for _run, binding in self._sources):
            raise CombineError(
                "A combination needs at least one source bound to the "
                "requested key; otherwise it has no keys to offer."
            )
        if method == CombinationMethod.EXPRESSION and not expression:
            raise CombineError("An EXPRESSION combination needs an expression")
        for run, binding in self._sources:
            if binding is REQUESTED:
                continue
            if binding not in (run.available_keys or []):
                raise CombineError(
                    f"Run {run.scan_id} is pinned to {binding!r}, which it "
                    "does not offer"
                )

        self._method = method
        self._expression = expression
        self._uid = str(uuid.uuid4())
        self._axis_keys_cache = None
        super().__init__(None, self._uid, catalog, parent=None)
        self.setup()
        for run, _binding in self._sources:
            run.data_changed.connect(self.clear_caches)
        self._initialize_keys()

    # ------------------------------------------------------------------
    # Identity and metadata
    # ------------------------------------------------------------------

    def setup(self) -> None:
        """
        Build metadata from the sources and expose the METADATA_KEYS.
        """
        runs = [run for run, _binding in self._sources]
        self.metadata = {
            "uid": self._uid,
            "source_runs": [run.uid for run in runs],
            "combination_method": self._method.value,
        }
        if self._method == CombinationMethod.EXPRESSION:
            self.metadata["expression"] = self._expression
        for run, binding in self._sources:
            entry = dict(run.metadata or {})
            entry["bound_key"] = (
                "<requested>" if binding is REQUESTED else binding
            )
            self.metadata[f"Run {run.scan_id}"] = entry

        self.scan_id = make_scan_id([run.scan_id for run in runs])
        self.plan_name = f"{len(runs)} Combined"
        self.uid = self._uid
        self.exit_status = "combined"

    @property
    def num_points(self) -> int:
        """
        Return the length of the leading axis of the primary source.
        """
        primary = self._primary
        keys = primary.available_keys or []
        if not keys:
            return 0
        shape = self.getShape(keys[0])
        return shape[0] if shape else 0

    @property
    def start(self):
        """
        Return the primary source's start document.

        Dimension analysis reads hints from here, and a combination has the
        dimension structure of the runs being combined.
        """
        return self._primary.start

    @property
    def display_name(self) -> str:
        """
        Return the run-list label, e.g. ``"Average of 2 runs"``.
        """
        if self._method == CombinationMethod.EXPRESSION:
            return f"Expression of {len(self._sources)} runs"
        method = self._method.value.capitalize()
        return f"{method} of {len(self._sources)} runs"

    def __str__(self) -> str:
        return self.display_name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.__class__.__name__}({self._uid!r})"

    def to_row(self) -> Tuple[Any, ...]:
        """
        Return values for the METADATA_KEYS, for the catalog table.
        """
        return tuple(getattr(self, attr, None) for attr in self.METADATA_KEYS)

    @classmethod
    def to_header(cls) -> List[str]:
        """
        Return display names for the metadata columns.
        """
        return [cls.DISPLAY_KEYS.get(attr, attr) for attr in cls.METADATA_KEYS]

    @property
    def combination_method(self) -> CombinationMethod:
        """
        Return the current combination method.
        """
        return self._method

    def set_combination_method(self, method: CombinationMethod) -> None:
        """
        Change how the sources are combined.

        Parameters
        ----------
        method : CombinationMethod
            New method.
        """
        if method != self._method:
            self._method = method
            self.setup()
            self.clear_caches()

    @property
    def source_runs(self) -> List[CatalogRun]:
        """
        Return the runs being combined, in order.
        """
        return [run for run, _binding in self._sources]

    @property
    def bindings(self) -> List[Source]:
        """
        Return the ``(run, binding)`` pairs, in the order ``runlist`` sees.
        """
        return list(self._sources)

    def scanFinished(self) -> bool:
        """
        Return whether every source has stopped acquiring.
        """
        return all(run.scanFinished() for run, _binding in self._sources)

    # ------------------------------------------------------------------
    # Structure, delegated to the primary source
    # ------------------------------------------------------------------

    @property
    def _primary(self) -> CatalogRun:
        """Return the first source bound to the requested key."""
        for run, binding in self._sources:
            if binding is REQUESTED:
                return run
        raise CombineError("combination has no requested-key source")

    @property
    def _requested_runs(self) -> List[CatalogRun]:
        return [
            run for run, binding in self._sources if binding is REQUESTED
        ]

    def _offered_keys(self) -> set:
        """
        Return the keys every requested-key source can supply.

        Pinned sources are excluded on purpose: a frozen reference bound to
        ``i0`` does not have to own the key being plotted.
        """
        runs = self._requested_runs
        offered = set(runs[0].available_keys or [])
        for run in runs[1:]:
            offered &= set(run.available_keys or [])
        return offered

    def getRunKeys(self) -> Tuple[Dict[int, List[str]], Dict[int, List[str]]]:
        """
        Return the primary source's key layout, restricted to shared keys.
        """
        offered = self._offered_keys()
        xkeys, ykeys = self._primary.getRunKeys()

        def _filter(groups):
            out = {}
            for dim, keys in (groups or {}).items():
                kept = [key for key in keys if key in offered]
                if kept:
                    out[dim] = kept
            return out

        return _filter(xkeys), _filter(ykeys)

    def get_dims(self, ykey: str, xkeys: List[str]):
        """
        Return dimension names from the primary source.
        """
        return self._primary.get_dims(ykey, xkeys)

    def getPlotHints(self) -> Dict[str, Any]:
        """
        Return the primary source's plot hints.
        """
        return self._primary.getPlotHints()

    def get_default_selection(self):
        """
        Return the primary source's default key selection.
        """
        return self._primary.get_default_selection()

    def getAxis(self, keys: List[str], slice_info: Optional[tuple] = None):
        """
        Return an axis-hint path from the primary source, clipped to length.

        Parameters
        ----------
        keys : list of str
            Key path; the last entry is the data key.
        slice_info : tuple, optional
            Per-axis slice tuple.
        """
        axis = np.asarray(self._primary.getAxis(keys, slice_info))
        return axis

    def refresh(self) -> None:
        """
        Refresh every source.
        """
        for run, _binding in self._sources:
            run.refresh()
        self.clear_caches()

    def _on_data_changed(self) -> None:
        """Drop the axis-key set; the sources hold the data caches."""
        self._axis_keys_cache = None

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _bound_key(self, binding: Binding, key: str) -> str:
        return key if binding is REQUESTED else binding

    def _axis_keys(self) -> set:
        """
        Return the primary source's X keys.

        Axis coordinates are read from the primary source alone, never
        combined. Two reasons, and they point the same way: an averaged
        motor position is not a coordinate anyone asked for, and an
        EXPRESSION applied to an axis is meaningless -- ``runlist[0] /
        runlist[1]`` is a statement about the measurement, not about where it
        was measured. This is also what the previous implementation did, in
        its own words: "use x data from first run".
        """
        cached = getattr(self, "_axis_keys_cache", None)
        if cached is None:
            xkeys, _ykeys = self._primary.getRunKeys()
            cached = {
                key for keys in (xkeys or {}).values() for key in keys
            }
            self._axis_keys_cache = cached
        return cached

    def getShape(self, key: str) -> Tuple[int, ...]:
        """
        Return the shape of the combined array for ``key``.

        For an axis key, the primary source's shape unchanged. Otherwise the
        primary's shape with the axes shared by every source clipped to the
        shortest, which assumes an EXPRESSION combines its sources
        elementwise -- what ``runlist`` arithmetic does.

        Parameters
        ----------
        key : str
            Requested key.

        Returns
        -------
        tuple of int
            Combined storage shape.
        """
        if key in self._axis_keys():
            return tuple(self._primary.getShape(key))
        shapes = [
            tuple(run.getShape(self._bound_key(binding, key)))
            for run, binding in self._sources
        ]
        if not shapes:
            return ()
        result = list(shapes[0])
        shared = min(len(shape) for shape in shapes)
        for axis in range(shared):
            result[axis] = min(shape[axis] for shape in shapes)
        return tuple(result)

    def getData(
        self, key: str, slice_info: Optional[tuple] = None
    ) -> np.ndarray:
        """
        Return the combined array for ``key``.

        Axis keys come from the primary source; see :meth:`_axis_keys`.
        Every other key is read from each source through its own binding with
        the same slice, the results are clipped to their common extent, and
        the combination is applied. This is the *only* place combination
        happens: everything
        after it -- orientation, crop, ROI, normalization, transform -- is the
        one plot pipeline in ``RunSource``, running over this array.

        Parameters
        ----------
        key : str
            Requested key.
        slice_info : tuple, optional
            Per-axis slice tuple, passed down to each source so a large
            combination still reads only what it needs.

        Returns
        -------
        np.ndarray
            Combined array.

        Raises
        ------
        CombineError
            If no source could supply data, or the expression fails.
        """
        if key in self._axis_keys():
            return np.asarray(self._primary.getData(key, slice_info))

        arrays = []
        errors = []
        for run, binding in self._sources:
            bound = self._bound_key(binding, key)
            try:
                arrays.append(np.asarray(run.getData(bound, slice_info)))
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(f"{run.uid}/{bound}: {exc}")
        if not arrays:
            raise CombineError(
                f"No source could supply {key!r}: {'; '.join(errors)}"
            )

        arrays = truncate_to_common(arrays)
        if self._method == CombinationMethod.EXPRESSION:
            interpreter = Interpreter()
            interpreter.symtable["runlist"] = arrays
            result = interpreter(self._expression)
            if result is None:
                raise CombineError(
                    f"Expression {self._expression!r} produced no result"
                )
            return np.asarray(result)

        stack = np.stack(arrays)
        if self._method == CombinationMethod.SUM:
            return np.sum(stack, axis=0)
        return np.mean(stack, axis=0)
