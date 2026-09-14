"""
The coordinate frame of a displayed 2D plane, and where its cells sit.

A frame records the shape, render mode, axis assignment and coordinates of
what is on screen, which is enough to map a drawn rectangle back to storage
indices. It also answers where any one cell lies in data coordinates, since
that is a question about the frame and nothing else: the rasterizers in
:mod:`region_mesh` turn those bounds into masks, but they do not own them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .plot_geometry import PlotBundle, RenderMode, prepare_2d_bundle


@dataclass(frozen=True)
class PlotViewFrame:
    """
    Coordinate frame for the currently displayed 2D plot plane.

    Display rows are plot Y and display columns are plot X, in both render
    modes, so frames built by :func:`frame_from_bundle` always have
    ``plot_y_dim == 0`` and ``plot_x_dim == 1``. Orientation is chosen by the
    view spec upstream, not by the render mode.

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
    row_reversed : bool
        Whether display row order is the reverse of storage order. Recorded
        by whoever performed the flip, because it cannot be recovered from a
        finished frame: ``extent`` is normalised so ``bottom < top`` either
        way. This is what makes the frame self-sufficient for mapping a drawn
        bounding box back to storage indices.
    col_reversed : bool
        Same for display columns.
    """

    shape: Tuple[int, int]
    render_mode: RenderMode
    axis_names: List[str]
    plot_x_dim: int
    plot_y_dim: int
    extent: Optional[Tuple[float, float, float, float]] = None
    mesh_x: Optional[np.ndarray] = None
    mesh_y: Optional[np.ndarray] = None
    row_reversed: bool = False
    col_reversed: bool = False

    def storage_bbox(
        self, bbox: Tuple[int, int, int, int]
    ) -> Tuple[int, int, int, int]:
        """
        Map a half-open bounding box between display and storage indices.

        Regions are compiled on the display plane but chunked loads address
        storage, so a drawn box has to be reflected on whichever axes were
        reversed to reach display order. The mapping is its own inverse, so
        the same method also converts a storage box back to display.

        Parameters
        ----------
        bbox : tuple of int
            Half-open ``(row_start, row_stop, col_start, col_stop)``.

        Returns
        -------
        tuple of int
            The box in the other index space.
        """
        r0, r1, c0, c1 = bbox
        n_rows, n_cols = self.shape
        if self.row_reversed:
            r0, r1 = n_rows - r1, n_rows - r0
        if self.col_reversed:
            c0, c1 = n_cols - c1, n_cols - c0
        return r0, r1, c0, c1

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
        return _plot_axis_length(self, self.plot_x_dim)

    @property
    def n_plot_y(self) -> int:
        """
        Return the number of cells along plot Y.
        """
        return _plot_axis_length(self, self.plot_y_dim)


def _plot_axis_length(frame: PlotViewFrame, storage_dim: int) -> int:
    """
    Return the number of cells along a storage axis on the displayed plane.
    """
    return frame.shape[storage_dim]


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

    return PlotViewFrame(
        shape=shape,
        render_mode=bundle.render_mode,
        axis_names=names[-2:],
        plot_x_dim=1,
        plot_y_dim=0,
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
        row_reversed=bundle.row_reversed,
        col_reversed=bundle.col_reversed,
    )


def frame_for_plane(
    plane_shape: Tuple[int, int],
    row_axis: np.ndarray,
    col_axis: np.ndarray,
    axis_names: Sequence[str],
    *,
    render_mode_hint: Optional[str] = None,
    row_reversed: bool = False,
    col_reversed: bool = False,
) -> PlotViewFrame:
    """
    Build the frame of a plot plane from its coordinates, without its data.

    A frame is a pure function of the plane's shape, its two coordinate
    arrays, their names and the render hint, so a caller that has to compile
    a region *before* reading the big array can derive one rather than being
    handed a cached frame from whatever happened to be drawn last. It packs
    through :func:`prepare_2d_bundle` so the extent and mesh grids cannot
    drift from the ones the renderer will see.

    Parameters
    ----------
    plane_shape : tuple of int
        ``(rows, columns)`` of the plane.
    row_axis, col_axis : np.ndarray
        Coordinate arrays in display order, one per row and column.
    axis_names : sequence of str
        Row name then column name.
    render_mode_hint : str, optional
        Explicit ``image`` / ``mesh`` hint.
    row_reversed, col_reversed : bool
        Whether display order reverses storage order on each axis.

    Returns
    -------
    PlotViewFrame
        Frame of the plane described by these coordinates.
    """
    return frame_from_bundle(
        prepare_2d_bundle(
            np.broadcast_to(np.float64(0.0), plane_shape),
            [row_axis, col_axis],
            list(axis_names),
            render_mode_hint=render_mode_hint,
            row_reversed=row_reversed,
            col_reversed=col_reversed,
        )
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
        frame.row_reversed,
        frame.col_reversed,
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
    Crop a view frame to a display-index bounding box.

    Parameters
    ----------
    frame : PlotViewFrame
        Full parent 2D view frame.
    bbox : tuple of int
        Half-open ``(row_start, row_stop, col_start, col_stop)`` on the
        display plane. Use :meth:`PlotViewFrame.storage_bbox` to convert a
        storage-index box first.

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
            row_reversed=frame.row_reversed,
            col_reversed=frame.col_reversed,
        )

    new_extent = None
    if frame.render_mode == "image" and frame.extent is not None:
        x_lo, _, _, y_hi = image_cell_bounds(frame, r0, c0)
        _, x_hi, y_lo, _ = image_cell_bounds(frame, r1 - 1, c1 - 1)
        new_extent = (x_lo, x_hi, y_lo, y_hi)

    return PlotViewFrame(
        shape=new_shape,
        render_mode=frame.render_mode,
        axis_names=list(frame.axis_names),
        plot_x_dim=frame.plot_x_dim,
        plot_y_dim=frame.plot_y_dim,
        extent=new_extent,
        row_reversed=frame.row_reversed,
        col_reversed=frame.col_reversed,
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


# ---------------------------------------------------------------------------
# Cell geometry -- where one cell of a frame sits in data coordinates
# ---------------------------------------------------------------------------
#
# These answer a question about a frame and nothing else, so they live with
# the frame. They used to sit with the rasterizers in :mod:`region_mesh`,
# which is why cropping a frame meant reaching into the mask module.


def data_limits(frame: PlotViewFrame) -> Tuple[float, float, float, float]:
    """
    Return axis data limits as x_lo, x_hi, y_lo, y_hi.
    """
    if frame.render_mode == "image":
        if frame.extent is None:
            ny, nx = frame.shape
            return (-0.5, nx - 0.5, -0.5, ny - 0.5)
        left, right, bottom, top = frame.extent
        return (float(left), float(right), float(bottom), float(top))

    mesh_x = frame.mesh_x
    mesh_y = frame.mesh_y
    if mesh_x is None or mesh_y is None:
        raise ValueError("Mesh frame requires mesh_x and mesh_y")
    return (
        float(np.nanmin(mesh_x)),
        float(np.nanmax(mesh_x)),
        float(np.nanmin(mesh_y)),
        float(np.nanmax(mesh_y)),
    )


def _image_row_y_bounds(
    frame: PlotViewFrame, row: int
) -> Tuple[float, float]:
    """
    Return vertical data bounds for an image row.

    Matches ``imshow(..., origin="upper")``: storage row 0 is at the top of
    the axes (near ``top``), increasing row index moves toward ``bottom``.
    """
    _, _, bottom, top = data_limits(frame)
    ny, _ = frame.shape
    dy = (top - bottom) / ny if ny else 1.0
    y_hi = top - row * dy
    y_lo = top - (row + 1) * dy
    return y_lo, y_hi


def image_cell_bounds(
    frame: PlotViewFrame, row: int, col: int
) -> Tuple[float, float, float, float]:
    """
    Return x_lo, x_hi, y_lo, y_hi for an image cell at storage (row, col).
    """
    left, right, bottom, top = data_limits(frame)
    _, nx = frame.shape
    dx = (right - left) / nx if nx else 1.0
    x_lo = left + col * dx
    x_hi = left + (col + 1) * dx
    y_lo, y_hi = _image_row_y_bounds(frame, row)
    return x_lo, x_hi, y_lo, y_hi


def mesh_cell_bounds(
    frame: PlotViewFrame, row: int, col: int
) -> Tuple[float, float, float, float]:
    """
    Return x_lo, x_hi, y_lo, y_hi for a mesh cell at storage (row, col).
    """
    mesh_x = frame.mesh_x
    mesh_y = frame.mesh_y
    ny, nx = frame.shape
    corners_x = [mesh_x[row, col]]
    corners_y = [mesh_y[row, col]]
    if row + 1 < ny:
        corners_x.append(mesh_x[row + 1, col])
        corners_y.append(mesh_y[row + 1, col])
    if col + 1 < nx:
        corners_x.append(mesh_x[row, col + 1])
        corners_y.append(mesh_y[row, col + 1])
    if row + 1 < ny and col + 1 < nx:
        corners_x.append(mesh_x[row + 1, col + 1])
        corners_y.append(mesh_y[row + 1, col + 1])
    return (
        float(np.nanmin(corners_x)),
        float(np.nanmax(corners_x)),
        float(np.nanmin(corners_y)),
        float(np.nanmax(corners_y)),
    )


def _cell_bounds(
    frame: PlotViewFrame, row: int, col: int
) -> Tuple[float, float, float, float]:
    """
    Return ``(x_lo, x_hi, y_lo, y_hi)`` for the cell at display (row, col).

    Display rows are plot Y and display columns are plot X in both render
    modes, so no per-mode index juggling is needed here.
    """
    if frame.render_mode == "image":
        return image_cell_bounds(frame, row, col)
    return mesh_cell_bounds(frame, row, col)


def cell_x_bounds_mesh(
    frame: PlotViewFrame, index: int, along: int
) -> Tuple[float, float]:
    """
    Return horizontal data bounds for a cell along plot X.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame.
    index : int
        Cell index along plot X (display column).
    along : int
        Reference index along plot Y (display row), which matters only for
        curvilinear mesh grids.

    Returns
    -------
    tuple of float
        ``(x_lo, x_hi)``.
    """
    x_lo, x_hi, _, _ = _cell_bounds(frame, along, index)
    return x_lo, x_hi


def cell_y_bounds_mesh(
    frame: PlotViewFrame, index: int, along: int
) -> Tuple[float, float]:
    """
    Return vertical data bounds for a cell along plot Y.

    Parameters
    ----------
    frame : PlotViewFrame
        View frame.
    index : int
        Cell index along plot Y (display row).
    along : int
        Reference index along plot X (display column), which matters only
        for curvilinear mesh grids.

    Returns
    -------
    tuple of float
        ``(y_lo, y_hi)``.
    """
    _, _, y_lo, y_hi = _cell_bounds(frame, index, along)
    return y_lo, y_hi


def mesh_separable_edge_grids(
    frame: PlotViewFrame,
) -> Tuple[np.ndarray, np.ndarray] | None:
    """
    Return 1D X and Y edge arrays when the mesh is a separable grid.
    """
    mesh_x = frame.mesh_x
    mesh_y = frame.mesh_y
    if mesh_x is None or mesh_y is None:
        return None
    ny, nx = frame.shape
    if mesh_x.shape != mesh_y.shape:
        return None
    if mesh_x.shape == (ny + 1, nx + 1):
        x_edges = np.asarray(mesh_x[0, :], dtype=float)
        y_edges = np.asarray(mesh_y[:, 0], dtype=float)
        if not (
            np.allclose(mesh_x, mesh_x[0:1, :], equal_nan=True)
            and np.allclose(mesh_y, mesh_y[:, 0:1], equal_nan=True)
        ):
            return None
        return x_edges, y_edges
    if mesh_x.shape != (ny, nx):
        return None
    if not (
        np.allclose(mesh_x, mesh_x[0:1, :], equal_nan=True)
        and np.allclose(mesh_y, mesh_y[:, 0:1], equal_nan=True)
    ):
        return None
    x_edges = np.asarray(mesh_x[0, :], dtype=float)
    y_edges = np.asarray(mesh_y[:, 0], dtype=float)
    return x_edges, y_edges
