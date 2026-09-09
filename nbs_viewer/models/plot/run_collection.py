"""
Ordered membership, visibility, and the available-key universe.

A ``QObject``: membership and visibility are state that other objects react
to, so this is where the signals announcing them live. They were moved up to
:class:`PlotSession` earlier in this refactor, on the theory that a thinner
container is a simpler one. It is not — stripping a model's signals does not
remove the work, it relocates it into whatever has to announce on the
model's behalf, and it turned ``visible_models`` from a property into a join
across two objects. This reverses that.

The available-key universe belongs here for the same reason: it is the
intersection of catalog keys over the *visible* members, which is a function
of exactly the two things this object owns.
"""

from __future__ import annotations

from typing import (
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from qtpy.QtCore import QObject, Signal

from nbs_viewer.models.catalog.base import CatalogRun
from nbs_viewer.utils import print_debug

from .combinedRunSource import CombinedRunSource, CombinationMethod, CombineError
from .frozenRunSource import FrozenRunSource
from .runSource import RunSource


class RunCollection(QObject):
    """
    Ordered uid to :class:`RunSource` membership, plus visibility.

    Parameters
    ----------
    sources : sequence of RunSource, optional
        Initial members.
    is_main_display : bool, optional
        If True, newly added runs become visible regardless of ``auto_add``.
    single_selection_mode : bool, optional
        If True, only one run can be visible at a time.
    parent : QObject, optional
        Qt parent.
    """

    run_added = Signal(object)
    run_removed = Signal(object)
    available_runs_changed = Signal()
    visible_runs_changed = Signal(set)
    available_keys_changed = Signal()

    def __init__(
        self,
        sources: Optional[Sequence[RunSource]] = None,
        *,
        is_main_display: bool = False,
        single_selection_mode: bool = False,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._sources: Dict[str, RunSource] = {}
        self._visible_uids: Set[str] = set()
        self._available_keys: List[str] = []
        self._is_main_display = is_main_display
        self._single_selection_mode = single_selection_mode
        self._auto_add = True
        if sources:
            self.add_runs(list(sources))

    # ------------------------------------------------------------------
    # Membership
    # ------------------------------------------------------------------

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

    @property
    def available_models(self) -> List[RunSource]:
        """
        Return member sources in insertion order.
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

    def wrap(self, run: Union[CatalogRun, RunSource]) -> RunSource:
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

    def add_runs(
        self, run_list: Union[List[CatalogRun], List[RunSource]]
    ) -> List[RunSource]:
        """
        Add CatalogRun or RunSource instances, in scan-id order.

        Newly added runs become visible when this collection belongs to the
        main display or ``auto_add`` is set.

        Parameters
        ----------
        run_list : list of CatalogRun or RunSource
            Runs to add.

        Returns
        -------
        list of RunSource
            The members that were newly inserted.
        """
        print_debug("RunCollection.add_runs", f"Adding {len(run_list)} runs", "run")
        run_list = sorted(run_list, key=lambda x: x.scan_id)
        uid_list = []
        added: List[RunSource] = []
        for run in run_list:
            uid = run.uid
            uid_list.append(uid)
            if uid in self._sources:
                print_debug(
                    "RunCollection.add_runs", f"Run {uid} already in model", "run"
                )
                continue

            run_model = self.wrap(run)
            self._sources[uid] = run_model
            run_model.available_keys_changed.connect(self.update_available_keys)
            added.append(run_model)
            self.run_added.emit(run_model)

        self.update_available_keys()
        if self._is_main_display or self._auto_add:
            self.set_uids_visible(uid_list, True)
        self.available_runs_changed.emit()
        return added

    def remove_uids(self, uid_list: Iterable[str]) -> None:
        """
        Remove runs by uid, dropping their visibility with them.

        Parameters
        ----------
        uid_list : iterable of str
            UIDs to remove.
        """
        print_debug(
            "RunCollection.remove_uids",
            f"Removing uids {uid_list}",
            category="runlist",
        )
        removed_any = False
        for uid in list(uid_list):
            run_model = self._sources.pop(uid, None)
            if run_model is None:
                continue
            removed_any = True
            try:
                run_model.available_keys_changed.disconnect(
                    self.update_available_keys
                )
            except (TypeError, RuntimeError):
                pass
            run_model.cleanup()
            self._visible_uids.discard(uid)
            self.run_removed.emit(run_model)

        if not removed_any:
            return
        self.update_available_keys()
        self.visible_runs_changed.emit(self.visible_uids)
        self.available_runs_changed.emit()

    # ------------------------------------------------------------------
    # Visibility
    # ------------------------------------------------------------------

    @property
    def visible_uids(self) -> Set[str]:
        """
        Return visible run uids.
        """
        return set(self._visible_uids)

    @property
    def visible_models(self) -> List[RunSource]:
        """
        Return visible run models, in membership order.
        """
        return [
            model
            for model in self._sources.values()
            if model.uid in self._visible_uids
        ]

    def set_uids_visible(self, uids: Iterable[str], is_visible: bool) -> None:
        """
        Set visibility for specific run uids.

        Parameters
        ----------
        uids : iterable of str
            UIDs to update. Unknown uids are ignored.
        is_visible : bool
            New visibility state.
        """
        uids = list(uids)
        print_debug(
            "RunCollection.set_uids_visible",
            f"Setting uids {uids} to {is_visible}",
            category="runlist",
        )
        before = set(self._visible_uids)
        if self._single_selection_mode and is_visible and uids:
            self._visible_uids.clear()
            first_uid = uids[0]
            if first_uid in self._sources:
                self._visible_uids.add(first_uid)
        else:
            for uid in uids:
                if uid not in self._sources:
                    continue
                if is_visible:
                    self._visible_uids.add(uid)
                else:
                    self._visible_uids.discard(uid)

        if self._visible_uids == before:
            return
        self.update_available_keys()
        self.visible_runs_changed.emit(self.visible_uids)

    @property
    def single_selection_mode(self) -> bool:
        """
        Whether making one run visible hides the others.
        """
        return self._single_selection_mode

    @property
    def auto_add(self) -> bool:
        """
        Whether newly added runs become visible automatically.
        """
        return self._auto_add

    def set_auto_add(self, enabled: bool) -> None:
        """
        Set whether newly added runs become visible automatically.

        Parameters
        ----------
        enabled : bool
            When True, new runs are checked/visible on add.
        """
        self._auto_add = enabled

    @property
    def dynamic_update(self) -> bool:
        """
        Whether dynamic update is enabled on all members.
        """
        models = self.sources()
        return all(model.dynamic_update for model in models) if models else True

    def set_dynamic_update(self, enabled: bool) -> None:
        """
        Set dynamic update state on every member source.

        Parameters
        ----------
        enabled : bool
            Whether to enable dynamic updates.
        """
        for model in self._sources.values():
            model.set_dynamic(enabled)

    # ------------------------------------------------------------------
    # Available keys
    # ------------------------------------------------------------------

    @property
    def available_keys(self) -> List[str]:
        """
        Return the available-key universe (visible catalog-key intersection).
        """
        return list(self._available_keys)

    def update_available_keys(self) -> None:
        """
        Recompute the intersection of catalog keys among visible runs.

        Announces only on a real change, so a redundant recompute costs
        nothing downstream.
        """
        runs = self.visible_models
        if not runs:
            if self._available_keys:
                self._available_keys = []
                self.available_keys_changed.emit()
            return

        first_run = runs[0]
        print_debug(
            "RunCollection.update_available_keys",
            f"available_keys from first_run.uid {first_run.uid}: "
            f"{first_run.available_keys}",
            "run",
        )
        available_keys = list(first_run.catalog_keys)
        for run in runs[1:]:
            available_keys = [
                key for key in available_keys if key in run.catalog_keys
            ]

        if available_keys != self._available_keys:
            self._available_keys = available_keys
            self.available_keys_changed.emit()

    def synthetic_display_entries(self) -> List[Tuple[RunSource, str, str]]:
        """
        Return frozen stack spectra for visible runs.

        Returns
        -------
        list of tuple
            ``(run_model, key, display_label)`` entries for Run Display.
        """
        entries = []
        runs = self.visible_models
        multi = len(runs) > 1
        for run_model in runs:
            for entry in run_model.frozen_spectra():
                if entry.kind != "stack_spectrum":
                    continue
                label = entry.label
                if multi:
                    label = f"{run_model.scan_id} · {label}"
                entries.append((run_model, entry.key, label))
        return entries

    # ------------------------------------------------------------------
    # Combine and freeze
    # ------------------------------------------------------------------

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

    def combine(
        self,
        runs: List[RunSource],
        method: Optional[CombinationMethod] = None,
        expression: Optional[str] = None,
    ) -> CombinedRunSource:
        """
        Build a combined run and add it to this collection.

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
            The combined run that was added.

        Raises
        ------
        CombineError
            If the runs fail :meth:`validate_combine`.
        """
        if method is None:
            method = CombinationMethod.AVERAGE
        combined = self.make_combined(runs, method=method, expression=expression)
        self.add_runs([combined])
        return combined

    def make_frozen(
        self, items: Iterable[Tuple[RunSource, str]]
    ) -> List[FrozenRunSource]:
        """
        Build frozen sources for explicit ``(run, ykey)`` pairs.

        Does not add the results to this collection. Callers resolve Y keys
        from the session selection (see :meth:`PlotSession.freeze_runs`).

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
