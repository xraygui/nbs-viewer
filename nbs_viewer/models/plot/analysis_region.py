"""
Analysis region binding a ROI definition to derivative parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .derivative_spec import MaskMode, ProfileAxis, ReduceOp
from .region import RectRegion

MaskModeLiteral = MaskMode
ProfileAxisLiteral = ProfileAxis
ReduceOpLiteral = ReduceOp


@dataclass(frozen=True)
class AnalysisRegion:
    """
    Region definition with profile-reduction settings.

    Parameters
    ----------
    definition : RectRegion
        ROI in matplotlib data coordinates.
    profile_axis : str
        ``plot_x`` or ``plot_y`` for 1D profiles.
    reduce : str
        ``sum`` or ``mean``.
    label : str
        Display label for the derivative product.
    mask_mode : str
        ``inside`` or ``outside`` the ROI when reducing.
    """

    definition: RectRegion
    profile_axis: ProfileAxisLiteral = "plot_x"
    reduce: ReduceOpLiteral = "sum"
    label: str = ""
    mask_mode: MaskModeLiteral = "inside"
