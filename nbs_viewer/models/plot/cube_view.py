"""
N-dimensional cube view specification and application.

Pure numpy logic with no Qt dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np

SliceItem = Union[int, slice]


class DimRole(str, Enum):
    """How a storage dimension participates in the cube view."""

    INDEX = "index"
    PLOT_X = "plot_x"
    PLOT_Y = "plot_y"
    SUM = "sum"
    MEAN = "mean"


ROLE_LABELS = {
    DimRole.INDEX: "Index",
    DimRole.PLOT_X: "Plot X",
    DimRole.PLOT_Y: "Plot Y",
    DimRole.SUM: "Sum",
    DimRole.MEAN: "Mean",
}

SLICE_ROLES = (DimRole.INDEX, DimRole.SUM, DimRole.MEAN)


@dataclass(frozen=True)
class CubeViewSpec:
    """
    Describe how to slice, reduce, and orient an N-D array for plotting.

    Parameters
    ----------
    ndim : int
        Number of storage dimensions in the source array.
    plot_ndim : int
        Target plot dimensionality (1 or 2).
    roles : tuple of DimRole
        Role per storage axis index.
    indices : tuple of int
        Index value per storage axis when role is INDEX.
    axis_order : tuple of int, optional
        Storage axis indices in UI row order. Defaults to ``range(ndim)``.
    """

    ndim: int
    plot_ndim: int
    roles: Tuple[DimRole, ...]
    indices: Tuple[int, ...]
    axis_order: Tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.plot_ndim not in (1, 2):
            raise ValueError(f"plot_ndim must be 1 or 2, got {self.plot_ndim}")
        if len(self.roles) != self.ndim:
            raise ValueError("roles length must match ndim")
        if len(self.indices) != self.ndim:
            raise ValueError("indices length must match ndim")
        if not self.axis_order:
            object.__setattr__(self, "axis_order", tuple(range(self.ndim)))
        elif len(self.axis_order) != self.ndim:
            raise ValueError("axis_order length must match ndim")
        resolved = _resolved_roles_tuple(
            self.ndim, self.plot_ndim, self.axis_order, self.roles
        )
        if resolved != self.roles:
            object.__setattr__(self, "roles", resolved)
        self.validate()

    def validate(self) -> None:
        """
        Raise ValueError if role assignment is inconsistent with plot_ndim.
        """
        plot_x = sum(1 for r in self.roles if r == DimRole.PLOT_X)
        plot_y = sum(1 for r in self.roles if r == DimRole.PLOT_Y)
        if plot_x != 1:
            raise ValueError(f"exactly one Plot X required, got {plot_x}")
        if self.plot_ndim == 1 and plot_y != 0:
            raise ValueError("1D plots cannot assign Plot Y")
        if self.plot_ndim == 2 and plot_y != 1:
            raise ValueError(f"2D plots require exactly one Plot Y, got {plot_y}")

    def to_load_slice_info(self) -> Tuple[SliceItem, ...]:
        """
        Build a slice tuple for chunked data loading.

        INDEX dimensions use integer indices; all other roles request the
        full axis from storage.
        """
        items: List[SliceItem] = []
        for i in range(self.ndim):
            if self.roles[i] == DimRole.INDEX:
                items.append(self.indices[i])
            else:
                items.append(slice(None))
        return tuple(items)

    def swap_rows(self, row_index: int) -> "CubeViewSpec":
        """
        Swap two adjacent rows in ``axis_order`` and reassign plot axes.

        Plot X and Plot Y are always the last one or two rows; swapping rows
        is the only way to change which storage dimension maps to each plot
        axis.

        Parameters
        ----------
        row_index : int
            Row to move up (must be >= 1).

        Returns
        -------
        CubeViewSpec
            Updated specification.
        """
        if row_index < 1 or row_index >= self.ndim:
            return self
        order = list(self.axis_order)
        d0, d1 = order[row_index - 1], order[row_index]
        order[row_index - 1], order[row_index] = d1, d0
        roles = list(self.roles)
        indices = list(self.indices)
        roles[d0], roles[d1] = roles[d1], roles[d0]
        indices[d0], indices[d1] = indices[d1], indices[d0]
        spec = replace(
            self,
            axis_order=tuple(order),
            roles=tuple(roles),
            indices=tuple(indices),
        )
        return resolve_roles(spec)

    def with_slice_role(self, storage_axis: int, role: DimRole) -> "CubeViewSpec":
        """
        Assign a slice/reduce role to a non-plot storage axis.

        Parameters
        ----------
        storage_axis : int
            Storage dimension index.
        role : DimRole
            Must be INDEX, SUM, or MEAN.

        Returns
        -------
        CubeViewSpec
            Updated specification.
        """
        if role not in SLICE_ROLES:
            raise ValueError(f"slice role must be one of {SLICE_ROLES}")
        roles = list(self.roles)
        roles[storage_axis] = role
        return resolve_roles(replace(self, roles=tuple(roles)))

    def with_index(self, storage_axis: int, index: int) -> "CubeViewSpec":
        """
        Set the index value for an INDEX storage axis.

        Parameters
        ----------
        storage_axis : int
            Storage dimension index.
        index : int
            Slice index along that axis.

        Returns
        -------
        CubeViewSpec
            Updated specification.
        """
        indices = list(self.indices)
        indices[storage_axis] = index
        return replace(self, indices=tuple(indices))

    @property
    def n_slice_axes(self) -> int:
        """
        Number of leading axes in ``axis_order`` used for slice/reduce.
        """
        return self.ndim - self.plot_ndim

    def slice_axis_order(self) -> Tuple[int, ...]:
        """
        Storage axis indices for the slice/reduce section of the UI.
        """
        return self.axis_order[: self.n_slice_axes]

    def plot_axis_order(self) -> Tuple[int, ...]:
        """
        Storage axis indices for plot axes (Y then X when 2D).
        """
        return self.axis_order[self.n_slice_axes :]


def _resolved_roles_tuple(
    ndim: int,
    plot_ndim: int,
    axis_order: Tuple[int, ...],
    roles: Tuple[DimRole, ...],
) -> Tuple[DimRole, ...]:
    """
    Compute roles with plot axes taken from trailing ``axis_order`` rows.
    """
    order = axis_order
    n_slice = ndim - plot_ndim
    resolved = list(roles)
    for pos, storage_axis in enumerate(order):
        if pos < n_slice:
            if resolved[storage_axis] in (DimRole.PLOT_X, DimRole.PLOT_Y):
                resolved[storage_axis] = DimRole.INDEX
        elif plot_ndim == 2 and pos == len(order) - 2:
            resolved[storage_axis] = DimRole.PLOT_Y
        elif pos == len(order) - 1:
            resolved[storage_axis] = DimRole.PLOT_X
    return tuple(resolved)


def resolve_roles(spec: CubeViewSpec) -> CubeViewSpec:
    """
    Assign Plot X / Plot Y from trailing ``axis_order`` rows.

    Parameters
    ----------
    spec : CubeViewSpec
        Input specification.

    Returns
    -------
    CubeViewSpec
        Specification with plot roles derived from axis order.
    """
    resolved = _resolved_roles_tuple(
        spec.ndim, spec.plot_ndim, spec.axis_order, spec.roles
    )
    if resolved == spec.roles:
        return spec
    return replace(spec, roles=resolved)


def default_spec(ndim: int, plot_ndim: int = 1) -> CubeViewSpec:
    """
    Build the legacy trailing-axis plot convention as a cube view spec.

    Parameters
    ----------
    ndim : int
        Number of storage dimensions.
    plot_ndim : int
        1 for line plots, 2 for image plots.

    Returns
    -------
    CubeViewSpec
        Index on leading axes, plot axes on trailing dimensions.
    """
    if ndim <= 0:
        raise ValueError("ndim must be positive")
    roles: List[DimRole] = [DimRole.INDEX] * (ndim - plot_ndim)
    if plot_ndim == 1:
        roles.append(DimRole.PLOT_X)
    else:
        roles.extend([DimRole.PLOT_Y, DimRole.PLOT_X])
    return CubeViewSpec(
        ndim=ndim,
        plot_ndim=plot_ndim,
        roles=tuple(roles),
        indices=tuple(0 for _ in range(ndim)),
        axis_order=tuple(range(ndim)),
    )


def spec_from_slice_info(
    slice_info: Tuple[SliceItem, ...], plot_ndim: int
) -> CubeViewSpec:
    """
    Infer a cube view spec from a legacy slice tuple.

    Parameters
    ----------
    slice_info : tuple
        Per-dimension slice or integer index.
    plot_ndim : int
        Plot dimension count (1 or 2).

    Returns
    -------
    CubeViewSpec
        Equivalent cube view specification.
    """
    ndim = len(slice_info)
    roles: List[DimRole] = []
    indices: List[int] = []
    plot_slots = list(range(ndim - plot_ndim, ndim))
    for i, item in enumerate(slice_info):
        if isinstance(item, slice):
            if i == plot_slots[-1]:
                roles.append(DimRole.PLOT_X)
            elif plot_ndim == 2 and i == plot_slots[-2]:
                roles.append(DimRole.PLOT_Y)
            else:
                roles.append(DimRole.SUM)
            indices.append(0)
        else:
            roles.append(DimRole.INDEX)
            indices.append(int(item))
    return CubeViewSpec(
        ndim=ndim,
        plot_ndim=plot_ndim,
        roles=tuple(roles),
        indices=tuple(indices),
    )


def spec_for_plot_ndim(
    spec: CubeViewSpec, plot_ndim: int, shapes: Optional[Sequence[int]] = None
) -> CubeViewSpec:
    """
    Adapt a spec when the user switches between 1D and 2D plot modes.

    Parameters
    ----------
    spec : CubeViewSpec
        Current specification.
    plot_ndim : int
        Target plot dimension count.
    shapes : sequence of int, optional
        Per-storage-axis sizes for clamping indices.

    Returns
    -------
    CubeViewSpec
        Updated specification using trailing-axis defaults when needed.
    """
    if plot_ndim == spec.plot_ndim:
        return spec
    indices = list(spec.indices)
    if shapes is not None:
        for i, size in enumerate(shapes):
            if size > 0:
                indices[i] = max(0, min(indices[i], size - 1))
    roles = list(spec.roles)
    for i, role in enumerate(roles):
        if role not in SLICE_ROLES:
            roles[i] = DimRole.INDEX
    spec = CubeViewSpec(
        ndim=spec.ndim,
        plot_ndim=plot_ndim,
        roles=tuple(roles),
        indices=tuple(indices),
        axis_order=spec.axis_order,
    )
    return resolve_roles(spec)


def apply_cube_view(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    axis_names: Sequence[str],
    spec: CubeViewSpec,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Reduce and transpose loaded data to match the cube view spec.

    Parameters
    ----------
    y : np.ndarray
        Array loaded with :meth:`CubeViewSpec.to_load_slice_info`.
    axis_arrays : sequence of np.ndarray
        Per-storage-axis coordinate arrays (full length along each axis).
    axis_names : sequence of str
        Names per storage axis.
    spec : CubeViewSpec
        View specification.

    Returns
    -------
    tuple
        ``(y, axis_arrays, axis_names)`` oriented for plot_geometry.
    """
    remaining = [i for i in range(spec.ndim) if spec.roles[i] != DimRole.INDEX]
    arrays = [np.asarray(axis_arrays[i]) for i in remaining]
    names = [axis_names[i] for i in remaining]
    roles = [spec.roles[i] for i in remaining]

    for j in range(len(remaining) - 1, -1, -1):
        role = roles[j]
        if role == DimRole.SUM:
            y = np.sum(y, axis=j)
            del arrays[j], names[j], roles[j], remaining[j]
        elif role == DimRole.MEAN:
            y = np.mean(y, axis=j)
            del arrays[j], names[j], roles[j], remaining[j]

    non_plot = [
        j for j, role in enumerate(roles) if role not in (DimRole.PLOT_X, DimRole.PLOT_Y)
    ]
    y_positions = [j for j, role in enumerate(roles) if role == DimRole.PLOT_Y]
    x_positions = [j for j, role in enumerate(roles) if role == DimRole.PLOT_X]

    if spec.plot_ndim == 1:
        perm = non_plot + x_positions
    else:
        perm = non_plot + y_positions + x_positions

    if len(perm) != y.ndim:
        raise ValueError(
            f"transpose rank {len(perm)} does not match data ndim {y.ndim}"
        )

    if perm != list(range(y.ndim)):
        y = np.transpose(y, perm)
        arrays = [arrays[p] for p in perm]
        names = [names[p] for p in perm]

    if spec.plot_ndim == 1:
        arrays = arrays[-1:]
        names = names[-1:]
    elif spec.plot_ndim == 2:
        arrays = arrays[-2:]
        names = names[-2:]

    return y, arrays, names
