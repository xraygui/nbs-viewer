"""
Identity of a run, as the views read it.

``KeyInfo`` -- the other value on the RunSource surface -- moved down to
``models/data``: what a key is, is a question for the source that holds it,
and the data layer now answers it directly. ``AxisLayout`` is gone; it was
dimension analysis after a name list had been padded or truncated to fit,
and there is nothing left to pad.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RunIdentity:
    """
    Snapshot of run identity fields used by views.

    Parameters
    ----------
    uid : str
        Unique run identifier.
    scan_id : str
        Scan id as a string.
    plan_name : str
        Plan name.
    display_name : str
        Human-readable header text.
    metadata : mapping
        Shallow snapshot of run metadata.
    """

    uid: str
    scan_id: str
    plan_name: str
    display_name: str
    metadata: Mapping[str, Any]
