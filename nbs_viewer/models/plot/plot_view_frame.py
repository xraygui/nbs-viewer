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
        Names for storage dimension 0 (rows) then dimension 1 (columns).
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
        if len(self.axis_names) > self.plot_x_dim:
            return self.axis_names[self.plot_x_dim]
        return "x"

    @property
    def plot_y_name(self) -> str:
        """
        Return the axis name for the vertical plot dimension.
        """
        if len(self.axis_names) > self.plot_y_dim:
            return self.axis_names[self.plot_y_dim]
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


def _infer_mesh_plot_dims(
    mesh_x: np.ndarray, mesh_y: np.ndarray
) -> Tuple[int, int]:
    """
    Infer which storage axis maps to matplotlib horizontal (X) and vertical (Y).
    """
    mesh_x = np.asarray(mesh_x, dtype=float)
    mesh_y = np.asarray(mesh_y, dtype=float)
    x_span_col = 0.0
    x_span_row = 0.0
    if mesh_x.shape[1] > 1:
        x_span_col = float(np.nanmax(np.abs(np.diff(mesh_x, axis=1))))
    if mesh_x.shape[0] > 1:
        x_span_row = float(np.nanmax(np.abs(np.diff(mesh_x, axis=0))))
    if x_span_col >= x_span_row:
        plot_x_dim = 1
    else:
        plot_x_dim = 0
    return plot_x_dim, 1 - plot_x_dim


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
        axis_names = names[-2:]
    else:
        plot_x_dim, plot_y_dim = _infer_mesh_plot_dims(
            bundle.mesh_x, bundle.mesh_y
        )
        axis_names = list(bundle.axis_names)
        if len(axis_names) < 2:
            axis_names = names[-2:]

    return PlotViewFrame(
        shape=shape,
        render_mode=bundle.render_mode,
        axis_names=axis_names,
        plot_x_dim=plot_x_dim,
        plot_y_dim=plot_y_dim,
        extent=bundle.extent if bundle.render_mode == "image" else None,
        mesh_x=(
            np.asarray(bundle.mesh_x, dtype=float)
            if bundle.render_mode == "mesh"
            else None
        ),
        mesh_y=(
            np.asarray(bundle.mesh_y, dtype=float)
            if bundle.render_mode == "mesh"
            else None
        ),
    )


def view_fingerprint_from_bundle(bundle: PlotBundle) -> tuple:
    """
    Build a hashable fingerprint of the 2D coordinate frame.

    Used to decide whether an existing ROI in data coordinates remains valid
    after a cube-view or slice change.

    Parameters
    ----------
    bundle : PlotBundle
        Prepared 2D plot bundle.

    Returns
    -------
    tuple
        Fingerprint of shape, axis assignment, and coordinate limits.
    """
    frame = frame_from_bundle(bundle)
    parts: list = [
        frame.shape,
        frame.render_mode,
        frame.plot_x_dim,
        frame.plot_y_dim,
        tuple(frame.axis_names),
    ]
    if frame.extent is not None:
        parts.append(tuple(round(float(v), 4) for v in frame.extent))
    if frame.mesh_x is not None and frame.mesh_y is not None:
        mesh_x = np.asarray(frame.mesh_x, dtype=float)
        mesh_y = np.asarray(frame.mesh_y, dtype=float)
        parts.append(
            (
                mesh_x.shape,
                round(float(np.nanmin(mesh_x)), 4),
                round(float(np.nanmax(mesh_x)), 4),
                round(float(np.nanmin(mesh_y)), 4),
                round(float(np.nanmax(mesh_y)), 4),
            )
        )
    return tuple(parts)


def region_frame_for_bbox(
    frame: PlotViewFrame,
    bbox: Tuple[int, int, int, int],
) -> PlotViewFrame:
    """
    Crop a view frame to a storage-index bounding box.

    Parameters
    ----------
    frame : PlotViewFrame
        Full parent 2D view frame.
    bbox : tuple of int
        Half-open ``(row_start, row_stop, col_start, col_stop)`` indices.

    Returns
    -------
    PlotViewFrame
        View frame whose shape and coordinates match the cropped plane.
    """
    r0, r1, c0, c1 = bbox
    ny = r1 - r0
    nx = c1 - c0
    if ny <= 0 or nx <= 0:
        raise ValueError(f"empty ROI bbox {bbox}")

    new_shape = (ny, nx)
    if frame.render_mode == "mesh" and frame.mesh_x is not None and frame.mesh_y is not None:
        mesh_x, mesh_y = _crop_mesh_grids_for_bbox(
            frame.mesh_x,
            frame.mesh_y,
            frame.shape,
            r0,
            r1,
            c0,
            c1,
        )
        return PlotViewFrame(
            shape=new_shape,
            render_mode="mesh",
            axis_names=list(frame.axis_names),
            plot_x_dim=frame.plot_x_dim,
            plot_y_dim=frame.plot_y_dim,
            mesh_x=mesh_x,
            mesh_y=mesh_y,
        )

    new_extent = None
    if frame.render_mode == "image" and frame.extent is not None:
        from .region_mesh import _image_cell_bounds

        x_lo, _, _, y_hi = _image_cell_bounds(frame, r0, c0)
        _, x_hi, y_lo, _ = _image_cell_bounds(frame, r1 - 1, c1 - 1)
        new_extent = (x_lo, x_hi, y_lo, y_hi)

    return PlotViewFrame(
        shape=new_shape,
        render_mode=frame.render_mode,
        axis_names=list(frame.axis_names),
        plot_x_dim=frame.plot_x_dim,
        plot_y_dim=frame.plot_y_dim,
        extent=new_extent,
    )


def _crop_mesh_grids_for_bbox(
    mesh_x: np.ndarray,
    mesh_y: np.ndarray,
    shape: Tuple[int, int],
    r0: int,
    r1: int,
    c0: int,
    c1: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Crop ``pcolormesh`` coordinate grids to a storage bounding box.
    """
    ny, nx = shape
    mesh_x = np.asarray(mesh_x, dtype=float)
    mesh_y = np.asarray(mesh_y, dtype=float)
    if mesh_x.shape == (ny + 1, nx + 1) and mesh_y.shape == (ny + 1, nx + 1):
        return mesh_x[r0 : r1 + 1, c0 : c1 + 1], mesh_y[r0 : r1 + 1, c0 : c1 + 1]
    if mesh_x.shape == (ny, nx) and mesh_y.shape == (ny, nx):
        return mesh_x[r0:r1, c0:c1], mesh_y[r0:r1, c0:c1]
    raise ValueError(
        f"Mesh grid shape {mesh_x.shape} does not match cell shape {shape}"
    )
