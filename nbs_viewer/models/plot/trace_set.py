"""
The set of traces a session currently retains, keyed by :class:`TraceKey`.

Membership is a pure function of session state — membership x selection x
fan-out — and :meth:`PlotSession.rebuild` is its only mutator. Visibility is
not membership: hiding a run leaves its traces here, with their bundles, so
showing it again costs nothing.
"""

from typing import Dict, Iterator, Optional, Tuple

from qtpy.QtCore import QObject, Signal

from .spec.request import PlotRequest, TraceKey
from .trace import Trace


class TraceSet(QObject):
    """
    Mapping of :class:`TraceKey` to :class:`Trace`, owned by a session.

    Parameters
    ----------
    parent : QObject, optional
        Qt parent. Traces are created as children of this object.
    """

    trace_added = Signal(object)
    trace_removed = Signal(object)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._traces: Dict[TraceKey, Trace] = {}

    def __contains__(self, key: TraceKey) -> bool:
        return key in self._traces

    def __iter__(self) -> Iterator[TraceKey]:
        return iter(self._traces)

    def __len__(self) -> int:
        return len(self._traces)

    def keys(self):
        return self._traces.keys()

    def values(self):
        return self._traces.values()

    def items(self):
        return self._traces.items()

    def get(self, key: TraceKey) -> Optional[Trace]:
        """
        Return the trace filed under ``key``, or None.
        """
        return self._traces.get(key)

    def keys_for_uid(self, uid: str):
        """
        Return the trace keys belonging to one run uid.

        Parameters
        ----------
        uid : str
            Run uid.

        Returns
        -------
        list of TraceKey
        """
        return [key for key in self._traces if key.uid == uid]

    def ensure(
        self,
        run,
        request: PlotRequest,
        key: TraceKey,
        *,
        label: Optional[str] = None,
    ) -> Tuple[Trace, bool]:
        """
        Return the trace for ``key``, creating it if absent.

        An existing trace keeps its identity, its bundle, and the canvas-side
        artist filed under the same key; only its request is replaced.

        Parameters
        ----------
        run : RunSource
            Source run for a newly created trace.
        request : PlotRequest
            Request to hold.
        key : TraceKey
            Trace identity.
        label : str, optional
            Display label override for a newly created trace.

        Returns
        -------
        tuple of (Trace, bool)
            The trace, and whether this call created it.
        """
        trace = self._traces.get(key)
        if trace is not None:
            trace.set_request(request)
            return trace, False
        trace = Trace(run, request, label=label, parent=self, trace_key=key)
        self._traces[key] = trace
        self.trace_added.emit(trace)
        return trace, True

    def discard(self, key: TraceKey) -> Optional[Trace]:
        """
        Remove the trace for ``key`` and announce it.

        Announcing the key rather than the trace is what lets a canvas drop
        the artist it filed under the same key without the session ever
        holding one.

        Parameters
        ----------
        key : TraceKey
            Trace to remove.

        Returns
        -------
        Trace or None
            The removed trace, if there was one.
        """
        trace = self._traces.pop(key, None)
        if trace is None:
            return None
        trace.dispose()
        self.trace_removed.emit(key)
        return trace
