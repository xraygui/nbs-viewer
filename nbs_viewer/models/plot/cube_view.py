"""
N-dimensional cube view specification and application.

Pure numpy logic with no Qt dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import List, Literal, Optional, Sequence, Tuple, Union

import numpy as np

from .plot_view_frame import PlotViewFrame, region_frame_for_bbox
from .region import RectRegion, compile_rect_with_mask_mode

SliceItem = Union[int, slice]
MaskMode = Literal["inside", "outside"]
SpatialReduce = Literal["sum", "mean"]
PlotAxisName = Literal["plot_x", "plot_y"]


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
class MaterializeRequest:
    """
    Frozen view request applied to loaded storage-cube arrays.

    Parameters
    ----------
    spec : CubeViewSpec
        Slice, reduce, and orient roles for the output view.
    region : RectRegion, optional
        ROI in matplotlib data coordinates on the parent 2D plot plane.
    mask_mode : str
        ``inside`` or ``outside`` the ROI when reducing masked data.
    """

    spec: CubeViewSpec
    region: Optional[RectRegion] = None
    mask_mode: MaskMode = "inside"

    def to_fetch_slice_info(
        self,
        *,
        region_frame: PlotViewFrame,
        parent_spec: Optional[CubeViewSpec] = None,
    ) -> Tuple[SliceItem, ...]:
        """
        Build ``slice_info`` for ``getData`` with ROI bbox limits applied.

        Parameters
        ----------
        region_frame : PlotViewFrame
            Parent 2D view frame used to compile the ROI.
        parent_spec : CubeViewSpec, optional
            Parent cube view for plot-plane storage axis lookup on profile
            requests.

        Returns
        -------
        tuple
            Per-storage-axis slice or index tuple for chunked loading.
        """
        slice_info, _frame = self.fetch_context(
            region_frame=region_frame,
            parent_spec=parent_spec,
        )
        return slice_info

    def fetch_context(
        self,
        *,
        region_frame: PlotViewFrame,
        parent_spec: Optional[CubeViewSpec] = None,
        base_slice_info: Optional[Tuple[SliceItem, ...]] = None,
    ) -> Tuple[Tuple[SliceItem, ...], PlotViewFrame]:
        """
        Return fetch slices and the region frame matching a narrowed load.

        When ``region`` is set, spatial plot-plane axes in ``slice_info`` are
        limited to the compiled ROI bounding box. The returned view frame is
        cropped to that box so ``materialize_view`` sees matching plane shape.

        Parameters
        ----------
        region_frame : PlotViewFrame
            Full parent 2D view frame used to compile the ROI.
        parent_spec : CubeViewSpec, optional
            Parent cube view for plot-plane storage axis lookup.

        base_slice_info : tuple, optional
            Pre-narrowed load slices, for example after a persistent view crop.
            Defaults to :meth:`CubeViewSpec.to_load_slice_info` for ``spec``.

        Returns
        -------
        tuple
            ``(slice_info, region_frame)`` for ``getData`` and materialization.
        """
        if self.region is None:
            if base_slice_info is not None:
                return base_slice_info, region_frame
            return self.spec.to_load_slice_info(), region_frame

        compiled = compile_rect_with_mask_mode(
            region_frame,
            self.region.normalized(),
            self.mask_mode,
        )
        if compiled.pixel_count == 0:
            raise ValueError("ROI does not cover any cells")

        r0, r1, c0, c1 = compiled.bbox
        if r1 <= r0 or c1 <= c0:
            raise ValueError("ROI bounding box is empty")

        plot_y_axis, plot_x_axis = _fetch_plot_plane_storage_axes(
            self.spec,
            region_frame,
            parent_spec,
        )
        if base_slice_info is not None:
            items = list(base_slice_info)
        else:
            items = list(self.spec.to_load_slice_info())
        items[plot_y_axis] = _narrow_fetch_slice(
            items[plot_y_axis], r0, r1, region_frame.n_plot_y
        )
        items[plot_x_axis] = _narrow_fetch_slice(
            items[plot_x_axis], c0, c1, region_frame.n_plot_x
        )
        cropped_frame = region_frame_for_bbox(region_frame, compiled.bbox)
        return tuple(items), cropped_frame


def _fetch_plot_plane_storage_axes(
    spec: CubeViewSpec,
    region_frame: PlotViewFrame,
    parent_spec: Optional[CubeViewSpec],
) -> Tuple[int, int]:
    """
    Resolve storage axis indices for plot Y and plot X used in ROI fetch.
    """
    if parent_spec is not None and parent_spec.plot_ndim == 2:
        plot_order = parent_spec.plot_axis_order()
        if len(plot_order) >= 2:
            return plot_order[-2], plot_order[-1]
    if spec.plot_ndim == 2:
        plot_order = spec.plot_axis_order()
        if len(plot_order) >= 2:
            return plot_order[-2], plot_order[-1]
    if spec.ndim == 2:
        return region_frame.plot_y_dim, region_frame.plot_x_dim
    raise ValueError("cannot resolve plot-plane storage axes for ROI fetch")


def _narrow_fetch_slice(
    item: SliceItem,
    start: int,
    stop: int,
    dim_size: int,
) -> slice:
    """
    Intersect a load slice with half-open ``[start, stop)`` fetch bounds.
    """
    if isinstance(item, int):
        raise ValueError("cannot apply ROI fetch bounds to an indexed axis")
    if not isinstance(item, slice):
        return slice(start, stop)
    current_start = 0 if item.start is None else int(item.start)
    current_stop = dim_size if item.stop is None else int(item.stop)
    new_start = max(current_start, start)
    new_stop = min(current_stop, stop)
    if new_start >= new_stop:
        raise ValueError("ROI fetch bounds do not intersect the requested slice")
    return slice(new_start, new_stop)


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

        INDEX dimensions use integer indices. Plot X and all reduce roles
        request the full axis from storage, including profile-output specs
        where a former INDEX axis is assigned Plot X.
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


def plot_axis_to_storage_axis(parent: CubeViewSpec, plot_axis: PlotAxisName) -> int:
    """
    Map a plot axis name to its storage dimension index on a 2D parent spec.

    Parameters
    ----------
    parent : CubeViewSpec
        Parent view with ``plot_ndim == 2``.
    plot_axis : str
        ``plot_x`` or ``plot_y``.

    Returns
    -------
    int
        Storage axis index for the named plot dimension.
    """
    if parent.plot_ndim != 2:
        raise ValueError("plot_axis_to_storage_axis requires a 2D parent spec")
    plot_order = parent.plot_axis_order()
    if plot_axis == "plot_x":
        return plot_order[-1]
    if plot_axis == "plot_y":
        return plot_order[-2]
    raise ValueError(f"Unknown plot axis {plot_axis!r}")


def eligible_profile_axes(spec: CubeViewSpec) -> List[int]:
    """
    Return storage axis indices valid as profile axis choices.

    Parameters
    ----------
    spec : CubeViewSpec
        Parent cube view.

    Returns
    -------
    list of int
        Parent plot axes and INDEX axes, excluding SUM and MEAN axes.
    """
    if spec.plot_ndim != 2:
        return []
    plot_axes = set(spec.plot_axis_order())
    eligible: List[int] = []
    for storage_axis in spec.axis_order:
        role = spec.roles[storage_axis]
        if role in (DimRole.SUM, DimRole.MEAN):
            continue
        if storage_axis in plot_axes or role == DimRole.INDEX:
            eligible.append(storage_axis)
    return eligible


def default_profile_label(
    request: MaterializeRequest,
    axis_names: Sequence[str],
    *,
    parent_spec: Optional[CubeViewSpec] = None,
) -> str:
    """
    Return a short default legend label from a profile materialize request.

    Parameters
    ----------
    request : MaterializeRequest
        Frozen profile view request.
    axis_names : sequence of str
        Names per parent storage axis.
    parent_spec : CubeViewSpec, optional
        Parent cube view for axis naming.

    Returns
    -------
    str
        Label summarizing mask mode, reduce op, and profile axis.
    """
    region = "in" if request.mask_mode == "inside" else "out"
    if request.spec.plot_ndim != 1:
        return f"2D ({region} ROI)"
    profile_axis = profile_storage_axis(request.spec)
    name_spec = parent_spec if parent_spec is not None else request.spec
    axis_label = profile_axis_name(name_spec, profile_axis, axis_names)
    plot_plane = (
        set(parent_spec.plot_axis_order()) if parent_spec is not None else set()
    )
    spatial_roles = [
        request.spec.roles[storage_axis]
        for storage_axis in plot_plane
        if storage_axis in request.spec.roles
        and request.spec.roles[storage_axis] in (DimRole.SUM, DimRole.MEAN)
    ]
    if not spatial_roles:
        spatial_roles = [
            role
            for role in request.spec.roles
            if role in (DimRole.SUM, DimRole.MEAN)
        ]
    reduce = "sum" if spatial_roles and spatial_roles[0] == DimRole.SUM else "mean"
    return f"{reduce} ({region} ROI) · {axis_label}"


def profile_axis_name(
    spec: CubeViewSpec,
    storage_axis: int,
    axis_names: Sequence[str],
) -> str:
    """
    Return a display name for a profile axis dropdown entry.

    Parameters
    ----------
    spec : CubeViewSpec
        Parent cube view.
    storage_axis : int
        Storage dimension index.
    axis_names : sequence of str
        Names per storage axis.

    Returns
    -------
    str
        Axis label for UI display.
    """
    if storage_axis < len(axis_names):
        return axis_names[storage_axis]
    return f"axis {storage_axis}"


def profile_view_spec(
    parent: CubeViewSpec,
    profile_storage_axis: int,
    spatial_reduce: SpatialReduce,
) -> CubeViewSpec:
    """
    Build a 1D profile output spec from a 2D parent view.

    Parameters
    ----------
    parent : CubeViewSpec
        Parent cube view with ``plot_ndim == 2``.
    profile_storage_axis : int
        Storage axis along which profile coordinates run.
    spatial_reduce : str
        ``sum`` or ``mean`` over plot-plane axes within the ROI.

    Returns
    -------
    CubeViewSpec
        Output view with ``plot_ndim == 1``.
    """
    if parent.plot_ndim != 2:
        raise ValueError("profile_view_spec requires a 2D parent spec")
    reduce_role = (
        DimRole.SUM if spatial_reduce == "sum" else DimRole.MEAN
    )
    parent_plot_axes = set(parent.plot_axis_order())
    roles = list(parent.roles)

    if profile_storage_axis in parent_plot_axes:
        for storage_axis in parent_plot_axes:
            if storage_axis == profile_storage_axis:
                roles[storage_axis] = DimRole.PLOT_X
            else:
                roles[storage_axis] = reduce_role
    elif parent.roles[profile_storage_axis] == DimRole.INDEX:
        roles[profile_storage_axis] = DimRole.PLOT_X
        for storage_axis in parent_plot_axes:
            roles[storage_axis] = reduce_role
    else:
        raise ValueError(
            f"profile axis {profile_storage_axis} must be a parent plot axis "
            "or INDEX role"
        )

    axis_order = list(parent.axis_order)
    axis_order = [
        storage_axis
        for storage_axis in axis_order
        if storage_axis != profile_storage_axis
    ] + [profile_storage_axis]
    return CubeViewSpec(
        ndim=parent.ndim,
        plot_ndim=1,
        roles=tuple(roles),
        indices=tuple(parent.indices),
        axis_order=tuple(axis_order),
    )


def profile_storage_axis(spec: CubeViewSpec) -> int:
    """
    Return the storage axis assigned Plot X in a 1D output spec.
    """
    profile_axes = [
        i for i, role in enumerate(spec.roles) if role == DimRole.PLOT_X
    ]
    if len(profile_axes) != 1:
        raise ValueError("expected exactly one profile axis in output spec")
    return profile_axes[0]


def _spatial_reduce_storage_axes(
    spec: CubeViewSpec,
    plot_plane_storage_axes: Optional[Tuple[int, int]],
) -> frozenset[int]:
    """
    Return storage axes reduced within the ROI on the parent plot plane.
    """
    if spec.plot_ndim != 1:
        return frozenset()
    profile_axis = profile_storage_axis(spec)
    if plot_plane_storage_axes is not None:
        return frozenset(
            storage_axis
            for storage_axis in plot_plane_storage_axes
            if spec.roles[storage_axis] in (DimRole.SUM, DimRole.MEAN)
        )
    order = spec.axis_order
    if len(order) < 2:
        return frozenset()
    plot_plane = {order[-2], order[-1]}
    return frozenset(
        storage_axis
        for storage_axis in plot_plane
        if storage_axis != profile_axis
        and spec.roles[storage_axis] in (DimRole.SUM, DimRole.MEAN)
    )


def _global_reduce_storage_axes(
    spec: CubeViewSpec,
    spatial_storage_axes: frozenset[int],
) -> frozenset[int]:
    """
    Return SUM/MEAN storage axes reduced before ROI masking.
    """
    return frozenset(
        storage_axis
        for storage_axis, role in enumerate(spec.roles)
        if role in (DimRole.SUM, DimRole.MEAN)
        and storage_axis not in spatial_storage_axes
    )


def scan_profile_storage_axis(parent_spec: CubeViewSpec) -> Optional[int]:
    """
    Return the leading scan storage axis in tensor order.

    Among axes that are not globally reduced (SUM or MEAN), returns the
    minimum storage index. This is the external scan axis for stack spectra,
    whether its role is INDEX or a plot axis (e.g. mesh ``en_energy``).

    Parameters
    ----------
    parent_spec : CubeViewSpec
        Parent cube view.

    Returns
    -------
    int or None
        Scan storage axis index, or None when no candidates exist.
    """
    candidates = [
        sa
        for sa in range(parent_spec.ndim)
        if parent_spec.roles[sa] not in (DimRole.SUM, DimRole.MEAN)
    ]
    return min(candidates) if candidates else None


def classify_profile_kind(
    parent_spec: CubeViewSpec, profile_storage_axis: int
) -> Literal["stack_spectrum", "local_profile"]:
    """
    Classify a profile axis for save routing.

    Parameters
    ----------
    parent_spec : CubeViewSpec
        Parent cube view.
    profile_storage_axis : int
        Selected profile storage axis.

    Returns
    -------
    str
        ``stack_spectrum`` for the scan axis; ``local_profile`` otherwise.
    """
    scan_axis = scan_profile_storage_axis(parent_spec)
    if scan_axis is not None and profile_storage_axis == scan_axis:
        return "stack_spectrum"
    return "local_profile"


def is_plot_plane_storage_axis(
    parent_spec: CubeViewSpec, storage_axis: int
) -> bool:
    """
    Return whether a storage axis lies on the parent 2D plot plane.

    Parameters
    ----------
    parent_spec : CubeViewSpec
        Parent cube view with ``plot_ndim == 2``.
    storage_axis : int
        Storage dimension index.

    Returns
    -------
    bool
        True when ``storage_axis`` is a parent plot Y or plot X axis.
    """
    if parent_spec.plot_ndim != 2:
        return False
    return storage_axis in set(parent_spec.plot_axis_order())


def storage_axis_to_plot_axis(
    frame: PlotViewFrame,
    profile_storage_axis: int,
    *,
    parent_spec: Optional[CubeViewSpec] = None,
) -> PlotAxisName:
    """
    Return the plot axis name for a profile storage dimension.

    Parameters
    ----------
    frame : PlotViewFrame
        Parent 2D view frame.
    profile_storage_axis : int
        Storage axis index on the parent cube view.
    parent_spec : CubeViewSpec, optional
        Full parent view used to map N-D storage axes to plot X / plot Y.

    Returns
    -------
    str
        ``plot_x`` or ``plot_y``.
    """
    if parent_spec is not None and parent_spec.ndim == 2 and parent_spec.plot_ndim == 2:
        if profile_storage_axis == frame.plot_x_dim:
            return "plot_x"
        if profile_storage_axis == frame.plot_y_dim:
            return "plot_y"
    if parent_spec is not None and parent_spec.plot_ndim == 2:
        plot_order = parent_spec.plot_axis_order()
        if len(plot_order) >= 2:
            if profile_storage_axis == plot_order[-1]:
                return "plot_x"
            if profile_storage_axis == plot_order[-2]:
                return "plot_y"
    if profile_storage_axis == frame.plot_x_dim:
        return "plot_x"
    if profile_storage_axis == frame.plot_y_dim:
        return "plot_y"
    raise ValueError(
        f"profile storage axis {profile_storage_axis} is not on the plot plane"
    )


def display_plane_profile_spec(
    parent_spec: CubeViewSpec,
    profile_storage_axis: int,
    spatial_reduce: SpatialReduce,
) -> CubeViewSpec:
    """
    Build a 2D profile output spec for an already-displayed plot plane.

    Parameters
    ----------
    parent_spec : CubeViewSpec
        Parent cube view with ``plot_ndim == 2``.
    profile_storage_axis : int
        Profile axis in parent storage-index space.
    spatial_reduce : str
        ``sum`` or ``mean`` over the orthogonal plot axis.

    Returns
    -------
    CubeViewSpec
        Two-axis output view for materializing from a 2D bundle.
    """
    plot_order = parent_spec.plot_axis_order()
    if len(plot_order) < 2:
        raise ValueError("display_plane_profile_spec requires a 2D parent spec")
    plot_y_storage, plot_x_storage = plot_order[-2], plot_order[-1]
    if profile_storage_axis == plot_y_storage:
        bundle_profile_axis = 0
    elif profile_storage_axis == plot_x_storage:
        bundle_profile_axis = 1
    else:
        raise ValueError(
            f"profile axis {profile_storage_axis} is not on the plot plane"
        )
    plane_parent = CubeViewSpec(
        ndim=2,
        plot_ndim=2,
        roles=(DimRole.PLOT_Y, DimRole.PLOT_X),
        indices=(0, 0),
    )
    return profile_view_spec(plane_parent, bundle_profile_axis, spatial_reduce)


def _reduce_axis_index(
    remaining: Sequence[int],
    storage_axis: int,
) -> int:
    """
    Return the tensor axis index for a storage dimension.
    """
    return list(remaining).index(storage_axis)


def _tensor_axis_for_plane_storage(
    remaining: Sequence[int],
    storage_axis: int,
    region_frame: PlotViewFrame,
    y_ndim: int,
) -> int:
    """
    Map a plot-plane storage axis to the tensor axis in ``y``.

    Mesh bundles transpose storage axes relative to the displayed ``y`` array.
    """
    j = _reduce_axis_index(remaining, storage_axis)
    if (
        region_frame.render_mode == "mesh"
        and len(remaining) >= 2
        and j >= len(remaining) - 2
    ):
        plane_offset = y_ndim - 2
        if storage_axis == region_frame.plot_x_dim:
            return plane_offset + 1
        if storage_axis == region_frame.plot_y_dim:
            return plane_offset + 0
    return j


def _materialize_without_region(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    axis_names: Sequence[str],
    spec: CubeViewSpec,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Apply a cube view spec without ROI masking.
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


def _reduce_along_axis(y: np.ndarray, axis: int, role: DimRole) -> np.ndarray:
    """
    Collapse one tensor axis using the spec role semantics.
    """
    if role == DimRole.SUM:
        return np.sum(y, axis=axis)
    if role == DimRole.MEAN:
        return np.mean(y, axis=axis)
    raise ValueError(f"cannot reduce axis with role {role!r}")


def _masked_reduce_along_axes(
    y: np.ndarray,
    axes: Tuple[int, ...],
    role: DimRole,
) -> np.ndarray:
    """
    Collapse tensor axes after ROI masking with NaN-aware reducers.
    """
    if role == DimRole.SUM:
        profile = np.nansum(y, axis=axes)
    elif role == DimRole.MEAN:
        profile = np.nanmean(y, axis=axes)
    else:
        raise ValueError(f"unexpected spatial reduce role {role!r}")
    empty_bins = np.isnan(y).all(axis=axes)
    return np.where(empty_bins, np.nan, profile)


def _materialize_roi_profile(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    axis_names: Sequence[str],
    spec: CubeViewSpec,
    request: MaterializeRequest,
    region_frame: PlotViewFrame,
    *,
    plot_plane_storage_axes: Optional[Tuple[int, int]] = None,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Reduce masked plot-plane data to a 1D profile using the output view spec.
    """
    if spec.plot_ndim != 1:
        raise ValueError("ROI profile materialization requires plot_ndim=1")

    profile_axis_idx = profile_storage_axis(spec)
    spatial_storage_axes = _spatial_reduce_storage_axes(
        spec, plot_plane_storage_axes
    )
    if not spatial_storage_axes:
        raise ValueError("expected at least one spatial reduce axis")
    global_storage_axes = _global_reduce_storage_axes(
        spec, spatial_storage_axes
    )

    remaining = [i for i in range(spec.ndim) if spec.roles[i] != DimRole.INDEX]
    arrays = [np.asarray(axis_arrays[i]) for i in remaining]
    names = [axis_names[i] for i in remaining]
    roles = [spec.roles[i] for i in remaining]

    for j in range(len(remaining) - 1, -1, -1):
        storage_axis = remaining[j]
        role = roles[j]
        if storage_axis in global_storage_axes:
            y = _reduce_along_axis(y, j, role)
            del arrays[j], names[j], roles[j], remaining[j]

    if y.ndim < 2:
        raise ValueError(
            f"expected at least 2D plot plane before ROI reduction, got {y.shape}"
        )
    if y.shape[-2:] != region_frame.shape:
        raise ValueError(
            f"plot plane shape {y.shape[-2:]} does not match region frame "
            f"{region_frame.shape}"
        )

    compiled = compile_rect_with_mask_mode(
        region_frame,
        request.region.normalized(),
        request.mask_mode,
    )
    if compiled.pixel_count == 0:
        raise ValueError("ROI does not cover any cells")

    y = np.asarray(y, dtype=float)
    lead_shape = y.shape[:-2]
    if lead_shape:
        mask = compiled.mask.reshape((1,) * len(lead_shape) + compiled.mask.shape)
    else:
        mask = compiled.mask
    y = np.where(mask, y, np.nan)

    spatial_tensor_axes = tuple(
        _tensor_axis_for_plane_storage(
            remaining, storage_axis, region_frame, y.ndim
        )
        for storage_axis in sorted(spatial_storage_axes)
    )
    spatial_roles = {spec.roles[storage_axis] for storage_axis in spatial_storage_axes}
    if len(spatial_roles) != 1:
        raise ValueError("mixed spatial reduce roles are not supported")
    spatial_role = next(iter(spatial_roles))
    profile = _masked_reduce_along_axes(y, spatial_tensor_axes, spatial_role)

    if plot_plane_storage_axes is not None:
        on_plot_plane = profile_axis_idx in plot_plane_storage_axes
    else:
        on_plot_plane = profile_axis_idx in (
            region_frame.plot_x_dim,
            region_frame.plot_y_dim,
        )
    if on_plot_plane:
        if plot_plane_storage_axes is not None:
            plot_y_storage, plot_x_storage = plot_plane_storage_axes
            profile_axis = (
                "plot_x"
                if profile_axis_idx == plot_x_storage
                else "plot_y"
            )
        else:
            profile_axis = storage_axis_to_plot_axis(
                region_frame, profile_axis_idx
            )
        from .region_reduce import _profile_coords

        coords = _profile_coords(
            region_frame, profile_axis, int(profile.shape[-1])
        )
        axis_name = (
            region_frame.plot_x_name
            if profile_axis == "plot_x"
            else region_frame.plot_y_name
        )
    else:
        profile_axis_index = _reduce_axis_index(remaining, profile_axis_idx)
        coords = np.asarray(arrays[profile_axis_index], dtype=float)
        if coords.shape != profile.shape:
            raise ValueError(
                f"profile coordinate length {coords.shape} does not match "
                f"profile shape {profile.shape}"
            )
        axis_name = axis_names[profile_axis_idx]

    return np.asarray(profile, dtype=float).reshape(-1), [coords], [axis_name]


def _orient_for_plot_ndim(
    y: np.ndarray,
    arrays: List[np.ndarray],
    names: List[str],
    spec: CubeViewSpec,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Transpose reduced data to match the output plot dimensionality.
    """
    roles = list(spec.roles[i] for i in range(spec.ndim) if spec.roles[i] != DimRole.INDEX)
    if len(roles) != y.ndim:
        roles = [spec.roles[i] for i in range(y.ndim)]
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


def _materialize_roi_plane(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    axis_names: Sequence[str],
    spec: CubeViewSpec,
    request: MaterializeRequest,
    region_frame: PlotViewFrame,
    *,
    plot_plane_storage_axes: Optional[Tuple[int, int]] = None,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Apply ROI masking to a 2D plot plane using the output view spec.
    """
    if spec.plot_ndim != 2:
        raise ValueError("ROI plane materialization requires plot_ndim=2")

    if plot_plane_storage_axes is not None:
        plot_axes = set(plot_plane_storage_axes)
    else:
        plot_axes = set(spec.plot_axis_order())

    global_storage_axes = frozenset(
        storage_axis
        for storage_axis, role in enumerate(spec.roles)
        if role in (DimRole.SUM, DimRole.MEAN) and storage_axis not in plot_axes
    )

    remaining = [i for i in range(spec.ndim) if spec.roles[i] != DimRole.INDEX]
    arrays = [np.asarray(axis_arrays[i]) for i in remaining]
    names = [axis_names[i] for i in remaining]
    roles = [spec.roles[i] for i in remaining]

    for j in range(len(remaining) - 1, -1, -1):
        storage_axis = remaining[j]
        role = roles[j]
        if storage_axis in global_storage_axes:
            y = _reduce_along_axis(y, j, role)
            del arrays[j], names[j], roles[j], remaining[j]

    if y.ndim < 2:
        raise ValueError(
            f"expected at least 2D plot plane before ROI masking, got {y.shape}"
        )
    if y.shape[-2:] != region_frame.shape:
        raise ValueError(
            f"plot plane shape {y.shape[-2:]} does not match region frame "
            f"{region_frame.shape}"
        )

    compiled = compile_rect_with_mask_mode(
        region_frame,
        request.region.normalized(),
        request.mask_mode,
    )
    if compiled.pixel_count == 0:
        raise ValueError("ROI does not cover any cells")

    y = np.asarray(y, dtype=float)
    lead_shape = y.shape[:-2]
    if lead_shape:
        mask = compiled.mask.reshape((1,) * len(lead_shape) + compiled.mask.shape)
    else:
        mask = compiled.mask
    y = np.where(mask, y, np.nan)

    orient_spec = CubeViewSpec(
        ndim=len(roles),
        plot_ndim=2,
        roles=tuple(roles),
        indices=tuple(0 for _ in roles),
    )
    return _orient_for_plot_ndim(y, arrays, names, orient_spec)


def materialize_view(
    y: np.ndarray,
    axis_arrays: Sequence[np.ndarray],
    axis_names: Sequence[str],
    request: MaterializeRequest,
    *,
    region_frame: Optional[PlotViewFrame] = None,
    plot_plane_storage_axes: Optional[Tuple[int, int]] = None,
) -> Tuple[np.ndarray, List[np.ndarray], List[str]]:
    """
    Reduce and transpose loaded data to match a materialize request.

    Parameters
    ----------
    y : np.ndarray
        Array loaded with :meth:`CubeViewSpec.to_load_slice_info` for
        ``request.spec``.
    axis_arrays : sequence of np.ndarray
        Per-storage-axis coordinate arrays (full length along each axis).
    axis_names : sequence of str
        Names per storage axis.
    request : MaterializeRequest
        View specification and optional ROI masking parameters.
    region_frame : PlotViewFrame, optional
        Parent 2D view frame required when ``request.region`` is set.
    plot_plane_storage_axes : tuple of int, optional
        Parent plot Y and plot X storage axis indices for stack profiles.

    Returns
    -------
    tuple
        ``(y, axis_arrays, axis_names)`` oriented for plot_geometry.
    """
    if request.region is None:
        return _materialize_without_region(
            y, axis_arrays, axis_names, request.spec
        )
    if region_frame is None:
        raise ValueError("region_frame is required when request.region is set")
    if request.spec.plot_ndim == 2:
        return _materialize_roi_plane(
            y,
            axis_arrays,
            axis_names,
            request.spec,
            request,
            region_frame,
            plot_plane_storage_axes=plot_plane_storage_axes,
        )
    if request.spec.plot_ndim != 1:
        raise ValueError(
            f"ROI materialization supports plot_ndim 1 or 2, got {request.spec.plot_ndim}"
        )
    return _materialize_roi_profile(
        y,
        axis_arrays,
        axis_names,
        request.spec,
        request,
        region_frame,
        plot_plane_storage_axes=plot_plane_storage_axes,
    )


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
    return materialize_view(
        y,
        axis_arrays,
        axis_names,
        MaterializeRequest(spec),
    )
