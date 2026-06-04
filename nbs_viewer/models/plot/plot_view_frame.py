"""
View-frame metadata for 2D plots used by region compilation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .plot_geometry import PlotBundle, RenderMode


@dataclass(frozen=True)
class PlotViewFrame:
    """
    Coordinate frame for the currently displayed 2D plot plane.

    Parameters
    ----------
    shape : tuple of int
        Shape of the displayed ``y`` array (rows, columns).
    render_mode : RenderMode
        ``image`` or ``mesh``.
    axis_names : list of str
        Names for plot Y then plot X (vertical, horizontal).
    plot_x_dim : int
        Storage axis index mapped to the horizontal matplotlib axis.
    plot_y_dim : int
        Storage axis index mapped to the vertical matplotlib axis.
    extent : tuple of float or None
        ``imshow`` extent as left, right, bottom, top.
    mesh_x : np.ndarray or None
        ``pcolormesh`` X coordinates.
    mesh_y : np.ndarray or None
        ``pcolormesh`` Y coordinates.
    """

    shape: Tuple[int, int]
    render_mode: RenderMode
    axis_names: List[str]
    plot_x_dim: int
    plot_y_dim: int
    extent: Optional[Tuple[float, float, float, float]] = None
    mesh_x: Optional[np.ndarray] = None
    mesh_y: Optional[np.ndarray] = None

    @property
    def plot_x_name(self) -> str:
        """
        Return the axis name for the horizontal plot dimension.
        """
        if len(self.axis_names) >= 2:
            return self.axis_names[-1]
        return "x"

    @property
    def plot_y_name(self) -> str:
        """
        Return the axis name for the vertical plot dimension.
        """
        if len(self.axis_names) >= 2:
            return self.axis_names[-2]
        return "y"

    @property
    def n_plot_x(self) -> int:
        """
        Return the number of cells along plot X.
        """
        return self.shape[self.plot_x_dim]

    @property
    def n_plot_y(self) -> int:
        """
        Return the number of cells along plot Y.
        """
        return self.shape[self.plot_y_dim]


def frame_from_bundle(bundle: PlotBundle) -> PlotViewFrame:
    """
    Build a view frame from a prepared 2D :class:`PlotBundle`.

    Parameters
    ----------
    bundle : PlotBundle
        Prepared plot bundle for a 2D view.

    Returns
    -------
    PlotViewFrame
        Frame describing the displayed plane.

    Raises
    ------
    ValueError
        If the bundle is not 2D.
    """
    if bundle.ndim != 2 or bundle.render_mode not in ("image", "mesh"):
        raise ValueError(
            f"frame_from_bundle requires a 2D image or mesh bundle, got "
            f"ndim={bundle.ndim} mode={bundle.render_mode}"
        )

    names = list(bundle.axis_names)
    while len(names) < 2:
        names.append(f"dim_{len(names)}")

    shape = (int(bundle.y.shape[0]), int(bundle.y.shape[1]))
    if bundle.render_mode == "image":
        plot_x_dim = 1
        plot_y_dim = 0
        return PlotViewFrame(
            shape=shape,
            render_mode="image",
            axis_names=names[-2:],
            plot_x_dim=plot_x_dim,
            plot_y_dim=plot_y_dim,
            extent=bundle.extent,
        )

    return PlotViewFrame(
        shape=shape,
        render_mode="mesh",
        axis_names=names[-2:],
        plot_x_dim=0,
        plot_y_dim=1,
        mesh_x=np.asarray(bundle.mesh_x, dtype=float),
        mesh_y=np.asarray(bundle.mesh_y, dtype=float),
    )
