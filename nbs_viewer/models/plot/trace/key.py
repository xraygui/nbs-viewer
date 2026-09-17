"""
Object identity for a trace, and how a request names one.

The key is deliberately *not* the request. A request is the fingerprint of
what is plotted and changes whenever a crop, a transform or a slice does; the
key names the long-lived object those changes happen to, so the artist on the
canvas survives them.

This lives in ``trace/`` and not beside ``PlotRequest`` because the dependency
only runs one way: a trace is built from a request, and ``spec/`` knows
nothing about traces. ``TraceKey.of`` was a ``PlotRequest`` method, which put
the arrow backwards -- the description package cannot name a thing in the
package above it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:  # pragma: no cover - annotation only
    from ..spec.request import PlotRequest


@dataclass(frozen=True)
class TraceKey:
    """
    Object identity for a :class:`Trace` and its artist.

    A :class:`PlotRequest` is the fingerprint of *what is plotted*. This key
    is the subset that names a long-lived object so crop, transform, and
    slice changes reuse the artist.

    Parameters
    ----------
    uid : str
        Run uid.
    xkey : str
        Primary X key.
    ykey : str
        Y data key.
    fan_out_index : int, optional
        Distinct cell when several slices of the same keys are shown at once
        (image grid). ``None`` for the main display.
    """

    uid: str
    xkey: str
    ykey: str
    fan_out_index: Optional[int] = None

    def as_tuple(self) -> Tuple[str, str, str]:
        """
        Return the legacy ``(xkey, ykey, uid)`` map key.

        Returns
        -------
        tuple of str
            Compatibility triple used by crop ``source_key`` and canvas
            connection tracking.
        """
        return (self.xkey, self.ykey, self.uid)

    @classmethod
    def of(
        cls,
        request: "PlotRequest",
        fan_out_index: Optional[int] = None,
    ) -> "TraceKey":
        """
        Return the object-identity subset of a request.

        Parameters
        ----------
        request : PlotRequest
            Description to take the identity from.
        fan_out_index : int, optional
            Image-grid cell index. Defaults to no fan-out.

        Returns
        -------
        TraceKey
            Key for the long-lived trace.
        """
        return cls(
            uid=request.uid,
            xkey=request.xkeys[0] if request.xkeys else "",
            ykey=request.ykey,
            fan_out_index=fan_out_index,
        )
