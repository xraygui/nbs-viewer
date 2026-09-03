"""
Static facts about a run and its keys.

``KeyInfo`` and ``RunIdentity`` are the two values on the RunSource surface.
``AxisLayout`` is the return of dimension analysis after name-list truncation;
it is not a second analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class KeyInfo:
    """
    Static, selection-independent facts about one data key.

    Parameters
    ----------
    name : str
        Catalog or synthetic key name.
    label : str
        Display label. Synthetic keys carry a friendly label; catalog keys
        use the key name.
    shape : tuple of int
        Storage shape.
    synthetic : bool
        True for frozen overlay keys.
    hinted : bool
        Whether the key is a hinted primary. Until
        ``CatalogRun.get_hinted_keys`` is confirmed as the "Show All Keys"
        backing, catalog keys are ``True`` and synthetic keys are ``False``.
    render_hint : str or None
        Per-key ``image`` / ``mesh`` override from plot hints, or None.
    """

    name: str
    label: str
    shape: Tuple[int, ...]
    synthetic: bool
    hinted: bool
    render_hint: Optional[str]


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


@dataclass(frozen=True)
class AxisLayout:
    """
    Dimension analysis for one ``(ykey, xkeys)`` pair.

    Placeholders are ``np.arange`` index arrays; real coordinates come from
    ``load_axes``. ``analysis`` is the ``analyze_dimensions`` dict for catalog
    keys and empty for synthetic keys.

    Parameters
    ----------
    shape : tuple of int
        Effective storage shape.
    names : tuple of str
        Dimension names truncated or padded to ``len(shape)``.
    placeholders : tuple of ndarray
        Index arrays, one per dimension.
    associated : mapping
        Associated-axis payload. Empty for the describe (no-load) path.
    analysis : mapping
        Raw ``analyze_dimensions`` result, or empty for synthetic keys.
    """

    shape: Tuple[int, ...]
    names: Tuple[str, ...]
    placeholders: Tuple[np.ndarray, ...]
    associated: Mapping[str, Any]
    analysis: Mapping[str, Any]
