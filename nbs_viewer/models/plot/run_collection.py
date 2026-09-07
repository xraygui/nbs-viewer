"""
Ordered membership container for run sources.

Plain (non-QObject) container owned by :class:`PlotSession` / ``PlotModel``.
Holds combine / freeze factories; does not own visibility or selection.
"""

from __future__ import annotations

from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

from nbs_viewer.models.catalog.base import CatalogRun

from .combinedRunSource import CombinedRunSource, CombinationMethod, CombineError
from .frozenRunSource import FrozenRunSource
from .runSource import RunSource


class RunCollection:
    """
    Ordered uid → :class:`RunSource` membership.

    Parameters
    ----------
    sources : sequence of RunSource, optional
        Initial members.
    """

    def __init__(self, sources: Optional[Sequence[RunSource]] = None):
        self._sources: Dict[str, RunSource] = {}
        if sources:
            for source in sources:
                self.add(source)

    def uids(self) -> List[str]:
        """
        Return member uids in insertion order.

        Returns
        -------
        list of str
            Run uids.
        """
        return list(self._sources.keys())

    def sources(self) -> List[RunSource]:
        """
        Return member sources in insertion order.

        Returns
        -------
        list of RunSource
            Run sources.
        """
        return list(self._sources.values())

    def get(self, uid: str) -> Optional[RunSource]:
        """
        Return the source for ``uid``, or ``None``.

        Parameters
        ----------
        uid : str
            Run uid.

        Returns
        -------
        RunSource or None
            Member source.
        """
        return self._sources.get(uid)

    def __contains__(self, uid: str) -> bool:
        return uid in self._sources

    def __len__(self) -> int:
        return len(self._sources)

    def __iter__(self) -> Iterator[RunSource]:
        return iter(self._sources.values())

    def add(self, source: RunSource) -> bool:
        """
        Insert a source if its uid is not already present.

        Parameters
        ----------
        source : RunSource
            Source to add.

        Returns
        -------
        bool
            True if inserted, False if uid was already present.
        """
        uid = source.uid
        if uid in self._sources:
            return False
        self._sources[uid] = source
        return True

    def remove(self, uid: str) -> Optional[RunSource]:
        """
        Remove and return the source for ``uid``.

        Parameters
        ----------
        uid : str
            Run uid.

        Returns
        -------
        RunSource or None
            Removed source, or None if absent.
        """
        return self._sources.pop(uid, None)

    def clear(self) -> None:
        """
        Remove all members.
        """
        self._sources.clear()

    def wrap(
        self, run: Union[CatalogRun, RunSource]
    ) -> RunSource:
        """
        Return ``run`` as a :class:`RunSource`, wrapping a catalog run if needed.

        Parameters
        ----------
        run : CatalogRun or RunSource
            Run to wrap.

        Returns
        -------
        RunSource
            Existing or newly wrapped model.
        """
        if isinstance(run, RunSource):
            return run
        return RunSource(run)

    def validate_combine(self, runs: List[RunSource]) -> None:
        """
        Check whether runs can be combined.

        Parameters
        ----------
        runs : list of RunSource
            Candidate source runs.

        Raises
        ------
        CombineError
            If fewer than two runs are given, they share no keys, shapes
            disagree, or shape data cannot be read.
        """
        if len(runs) < 2:
            raise CombineError("Please select at least 2 runs to combine")

        try:
            common_keys = set(runs[0].available_keys)
            for run in runs[1:]:
                common_keys &= set(run.available_keys)

            if not common_keys:
                raise CombineError(
                    "Selected runs have no common data keys. Cannot combine "
                    "runs with completely different data structures."
                )

            preferred_keys = ["time"]
            test_key = None
            for key in preferred_keys:
                if key in common_keys:
                    test_key = key
                    break
            if test_key is None:
                test_key = list(common_keys)[0]

            shapes = []
            for run in runs:
                try:
                    shapes.append(run.get_shape(test_key))
                except Exception:
                    raise CombineError(
                        f"Could not access data for key '{test_key}' in one "
                        "or more runs."
                    ) from None

            if len(set(shapes)) > 1:
                raise CombineError(
                    f"Selected runs have different data shapes for key "
                    f"'{test_key}': {shapes}. All runs must have the same "
                    "data dimensions to be combined."
                )
        except CombineError:
            raise
        except Exception as e:
            raise CombineError(
                f"Error checking run compatibility: {str(e)}"
            ) from e

    def make_combined(
        self,
        runs: List[RunSource],
        method: CombinationMethod = CombinationMethod.AVERAGE,
        expression: Optional[str] = None,
    ) -> CombinedRunSource:
        """
        Build a :class:`CombinedRunSource` after validating ``runs``.

        Does not add the result to this collection.

        Parameters
        ----------
        runs : list of RunSource
            Source runs to combine.
        method : CombinationMethod, optional
            Combination method, by default AVERAGE.
        expression : str, optional
            Expression used when method is EXPRESSION.

        Returns
        -------
        CombinedRunSource
            Combined run model.

        Raises
        ------
        CombineError
            If the runs fail ``validate_combine``.
        """
        self.validate_combine(runs)
        return CombinedRunSource(
            runs=runs, method=method, expression=expression
        )

    def make_frozen(
        self, items: Iterable[Tuple[RunSource, str]]
    ) -> List[FrozenRunSource]:
        """
        Build frozen sources for explicit ``(run, ykey)`` pairs.

        Does not add the results to this collection. Callers resolve Y keys
        from session selection (see :meth:`PlotModel.freeze_runs`).

        Parameters
        ----------
        items : iterable of (RunSource, str)
            Catalog-backed run and Y key to freeze.

        Returns
        -------
        list of FrozenRunSource
            Frozen run models.
        """
        return [
            FrozenRunSource(source.run, key) for source, key in items
        ]
