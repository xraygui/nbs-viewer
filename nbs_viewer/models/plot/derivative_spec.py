"""
Specification for ROI-derived plot products.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MaskMode = Literal["inside", "outside"]
OutputKind = Literal["profile", "plane"]
ProfileAxis = Literal["plot_x", "plot_y"]
ReduceOp = Literal["sum", "mean"]


@dataclass(frozen=True)
class DerivativeSpec:
    """
    User-selected derivative operation parameters.

    Parameters
    ----------
    mask_mode : str
        ``inside`` or ``outside`` the ROI.
    output_kind : str
        ``profile`` for a 1D reduced curve or ``plane`` for a masked 2D crop.
    profile_axis : str
        Axis along which profile coordinates run when ``output_kind`` is
        ``profile``.
    reduce : str
        ``sum`` or ``mean`` along the orthogonal axis for profiles.
    label : str
        Optional display label for the derivative product.
    """

    mask_mode: MaskMode = "inside"
    output_kind: OutputKind = "profile"
    profile_axis: ProfileAxis = "plot_x"
    reduce: ReduceOp = "sum"
    label: str = ""

    def default_label(self, profile_axis_name: str = "") -> str:
        """
        Return a short default label from the operation settings.
        """
        region = "in" if self.mask_mode == "inside" else "out"
        if self.output_kind == "plane":
            return f"2D ({region} ROI)"
        axis = profile_axis_name or self.profile_axis
        return f"{self.reduce} ({region} ROI) · {axis}"
