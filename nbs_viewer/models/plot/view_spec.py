"""
Rank-agnostic view intent, and the concrete projection it binds to.

``ViewIntent`` is what a plot session holds and the dimension controls edit.
``Projection`` is the rank-bound snapshot carried by a ``PlotRequest``: axis
order, per-axis roles, and the indices for axes held at one value. Crop rides
along as integer storage bounds on the plot plane; it is applied by
``plot_request.plan_fetch``, never here.

Applying a projection to loaded arrays lives in ``plot_bundle.py``. This
module only describes and queries it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import List, Literal, Optional, Sequence, Tuple, Union


SliceItem = Union[int, slice]
SpatialReduce = Literal["sum", "mean"]
PlotAxisName = Literal["plot_x", "plot_y"]


class DimRole(str, Enum):
    """How a storage dimension participates in the projection."""

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
class ViewCrop:
    """
    Integer storage-index crop on the 2D plot plane.

    Display-to-storage conversion happens at construction time. Only the
    bounds needed to narrow a load slice are retained, so the crop is
    hashable and safe to embed in a ``Projection`` / ``PlotRequest``.

    Parameters
    ----------
    storage_bbox : tuple of int
        Half-open bounding box ``(row_start, row_stop, col_start, col_stop)``
        on the raw storage plane.
    plot_y_axis : int
        Storage axis index mapped to plot Y.
    plot_x_axis : int
        Storage axis index mapped to plot X.
    """

    storage_bbox: Tuple[int, int, int, int]
    plot_y_axis: int
    plot_x_axis: int

    def __post_init__(self) -> None:
        r0, r1, c0, c1 = self.storage_bbox
        if r1 <= r0 or c1 <= c0:
            raise ValueError(
                f"storage_bbox must be non-empty half-open, got {self.storage_bbox}"
            )
        if self.plot_y_axis == self.plot_x_axis:
            raise ValueError("plot_y_axis and plot_x_axis must differ")
        if self.plot_y_axis < 0 or self.plot_x_axis < 0:
            raise ValueError("plot axis indices must be non-negative")


def _resolved_roles(
    ndim: int,
    plot_ndim: int,
    axis_order: Tuple[int, ...],
    roles: Tuple[DimRole, ...],
) -> Tuple[DimRole, ...]:
    """
    Assign plot roles from trailing ``axis_order`` rows.
    """
    n_slice = ndim - plot_ndim
    resolved = list(roles)
    for pos, storage_axis in enumerate(axis_order):
        if pos < n_slice:
            if resolved[storage_axis] in (DimRole.PLOT_X, DimRole.PLOT_Y):
                resolved[storage_axis] = DimRole.INDEX
        elif plot_ndim == 2 and pos == len(axis_order) - 2:
            resolved[storage_axis] = DimRole.PLOT_Y
        elif pos == len(axis_order) - 1:
            resolved[storage_axis] = DimRole.PLOT_X
    return tuple(resolved)


@dataclass(frozen=True)
class Projection:
    """
    Rank-bound description of how to slice, reduce, and orient an array.

    This is the concrete view embedded in a :class:`PlotRequest`. It is the
    Carries an optional plot-plane crop.

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
    crop : ViewCrop, optional
        Persistent spatial crop on the plot plane. Only valid when
        ``plot_ndim == 2``.
    """

    ndim: int
    plot_ndim: int
    roles: Tuple[DimRole, ...]
    indices: Tuple[int, ...]
    axis_order: Tuple[int, ...] = field(default_factory=tuple)
    crop: Optional[ViewCrop] = None

    def __post_init__(self) -> None:
        if self.plot_ndim not in (1, 2):
            raise ValueError(f"plot_ndim must be 1 or 2, got {self.plot_ndim}")
        if self.ndim < self.plot_ndim:
            raise ValueError(
                f"ndim {self.ndim} is below plot_ndim {self.plot_ndim}"
            )
        if len(self.roles) != self.ndim:
            raise ValueError("roles length must match ndim")
        if len(self.indices) != self.ndim:
            raise ValueError("indices length must match ndim")
        if not self.axis_order:
            object.__setattr__(self, "axis_order", tuple(range(self.ndim)))
        elif len(self.axis_order) != self.ndim:
            raise ValueError("axis_order length must match ndim")
        elif set(self.axis_order) != set(range(self.ndim)):
            raise ValueError("axis_order must be a permutation of range(ndim)")
        resolved = _resolved_roles(
            self.ndim, self.plot_ndim, self.axis_order, self.roles
        )
        if resolved != self.roles:
            object.__setattr__(self, "roles", resolved)
        if self.crop is not None:
            # The crop names the storage axes of the *plot plane*. When this
            # view is that plane they must agree with its plot-axis order;
            # when the view has been reduced to an ROI profile the plane
            # survives only in the crop, so there is nothing to agree with.
            # Requiring plot_ndim == 2 here is what made an ROI on a cropped
            # plane unrepresentable.
            if max(self.crop.plot_y_axis, self.crop.plot_x_axis) >= self.ndim:
                raise ValueError(
                    f"crop plot axes ({self.crop.plot_y_axis}, "
                    f"{self.crop.plot_x_axis}) are out of range for ndim "
                    f"{self.ndim}"
                )
            if self.plot_ndim == 2:
                plot_axes = self.plot_axis_order()
                if (
                    self.crop.plot_y_axis != plot_axes[0]
                    or self.crop.plot_x_axis != plot_axes[1]
                ):
                    raise ValueError(
                        "crop plot axes must match Projection plot_axis_order "
                        f"{plot_axes}, got "
                        f"({self.crop.plot_y_axis}, {self.crop.plot_x_axis})"
                    )
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

    @property
    def n_slice_axes(self) -> int:
        """
        Number of leading axes in ``axis_order`` used for slice/reduce.
        """
        return self.ndim - self.plot_ndim

    def slice_axis_order(self) -> Tuple[int, ...]:
        """
        Storage axis indices for the slice/reduce section.
        """
        return self.axis_order[: self.n_slice_axes]

    def plot_axis_order(self) -> Tuple[int, ...]:
        """
        Storage axis indices for plot axes (Y then X when 2D).
        """
        return self.axis_order[self.n_slice_axes :]

    def base_slice(self) -> Tuple[SliceItem, ...]:
        """
        Build the un-narrowed storage load slice for this view.

        INDEX axes become integer indices; every other role requests the full
        axis (``slice(None)``). Crop and ROI narrowing are deliberately *not*
        applied here -- ``plot_request.plan_fetch`` is the only place a load
        is narrowed, so the display-to-storage mapping has one owner.

        Returns
        -------
        tuple
            Per-storage-axis slice or index before any spatial narrowing.
        """
        items: List[SliceItem] = []
        for i in range(self.ndim):
            if self.roles[i] == DimRole.INDEX:
                items.append(int(self.indices[i]))
            else:
                items.append(slice(None))
        return tuple(items)

    def swap_rows(self, row_index: int) -> "Projection":
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
        Projection
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
        return replace(
            self,
            axis_order=tuple(order),
            roles=tuple(roles),
            indices=tuple(indices),
        )

    def with_index(self, storage_axis: int, index: int) -> "Projection":
        """
        Return a copy with a new INDEX value on ``storage_axis``.

        Parameters
        ----------
        storage_axis : int
            Storage dimension index.
        index : int
            Slice index along that axis.

        Returns
        -------
        Projection
            Updated specification.
        """
        indices = list(self.indices)
        indices[storage_axis] = index
        return replace(self, indices=tuple(indices))

    def with_slice_role(self, storage_axis: int, role: DimRole) -> "Projection":
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
        Projection
            Updated specification.
        """
        if role not in SLICE_ROLES:
            raise ValueError(f"slice role must be one of {SLICE_ROLES}")
        roles = list(self.roles)
        roles[storage_axis] = role
        return replace(self, roles=tuple(roles))


def plot_axis_names(
    spec: Projection,
    dim_names: Sequence[str],
) -> Tuple[str, ...]:
    """
    Dimension names of the plot axes for cross-key compatibility checks.

    Two projected views are compatible for overplotting when their plot-axis
    name tuples match. A rank-1 key whose sole axis is ``sampleVoltage`` is
    compatible with a rank-3 key projected so that Plot X is also
    ``sampleVoltage``, and incompatible when Plot X is a detector axis.

    Parameters
    ----------
    spec : Projection
        Concrete projected view.
    dim_names : sequence of str
        Dimension name per storage axis, length ``spec.ndim``.

    Returns
    -------
    tuple of str
        Names of plot axes in order (Y then X when 2D).
    """
    if len(dim_names) != spec.ndim:
        raise ValueError(
            f"dim_names length {len(dim_names)} must match ndim {spec.ndim}"
        )
    return tuple(dim_names[i] for i in spec.plot_axis_order())


def resolve_axis_order(
    ndim: int,
    plot_ndim: int,
    *,
    dim_names: Optional[Sequence[str]] = None,
    dim_order: Sequence[str] = (),
    xkey: str = "",
) -> Tuple[int, ...]:
    """
    Decide the storage-axis order of the plot plane.

    **The only place that decision is made.** Both the default orientation
    and a manual arrangement resolve here, so a key of any rank gets the
    same policy applied to its own dimension names.

    Orientation is a view decision, so it is expressed here rather than by a
    renderer. The rule is that a key the user picked as X is plotted
    horizontally, with one guard: when the X key names a slice axis rather
    than one of the axes the plot plane already shows -- an image stack
    scrubbed by voltage or time -- the plane keeps its own orientation and
    the selection drives nothing. Forcing the stack axis onto the plane
    would replace the camera frame with a voltage-versus-column view.

    For 1-D plots there is only one plot axis, so the selected X always
    takes it. That is the larger correction: a trailing-axis default plots a
    rank-3 detector against its own column index.

    A manual arrangement is honoured only while it still describes this key.
    Half-applying a stale order to a key of another rank would silently
    reinterpret which axis the user meant to be horizontal, so a partial
    match re-derives the default instead.

    Parameters
    ----------
    ndim : int
        Storage rank of the key.
    plot_ndim : int
        1 for line plots, 2 for image plots.
    dim_names : sequence of str, optional
        Dimension name per storage axis, as returned by
        ``RunSource.describe_axes``. Without it only the trailing-axis
        default can be expressed.
    dim_order : sequence of str, optional
        Manual arrangement as dimension names, outermost first.
    xkey : str, optional
        Selected X key the default order follows.

    Returns
    -------
    tuple of int
        Storage axis indices, outermost first; the last ``plot_ndim`` of
        them are the plot axes, X innermost.
    """
    if ndim <= 0:
        raise ValueError("ndim must be positive")
    if ndim < plot_ndim:
        raise ValueError(f"ndim {ndim} is below plot_ndim {plot_ndim}")

    natural = tuple(range(ndim))
    names = (
        list(dim_names)
        if dim_names is not None and len(dim_names) == ndim
        else []
    )

    if dim_order and names and set(dim_order) == set(names):
        return tuple(names.index(name) for name in dim_order)

    if not xkey or xkey not in names:
        return natural
    x_axis = names.index(xkey)

    plane = natural[ndim - plot_ndim :]
    if x_axis == plane[-1]:
        return natural
    if plot_ndim == 1:
        return tuple(a for a in natural if a != x_axis) + (x_axis,)
    if x_axis not in plane:
        return natural
    other = next(a for a in plane if a != x_axis)
    return tuple(a for a in natural if a not in plane) + (other, x_axis)


@dataclass(frozen=True)
class ViewIntent:
    """
    Rank-agnostic session view state.

    One intent per plot session. At request-build time it is projected onto
    each key's own rank and dimension names by :meth:`project`, so a 1-D
    spectrum and a 1-D projection of a 3-D detector can be built from the
    same state without either being reinterpreted. Whether two projected
    keys may share a plot is a separate check on :func:`plot_axis_names`.

    Axis order is stored as **dimension names**, not as a permutation, and
    that is what makes the intent rank-agnostic: a permutation only means
    something for the one rank it was written against, whereas "``x`` is
    horizontal" survives a key gaining or losing an axis. It is resolved
    against each key by :func:`resolve_axis_order`, the single place the
    order is decided.

    Reduce policy is stored outermost-first, matching the leading rows of
    the dimension UI. When projecting to a smaller rank, outermost reduce
    axes are dropped so the axes nearest the plot plane are preserved.

    The crop is deliberately *not* held here. A crop is storage indices on
    one trace's plot plane and means nothing on another, so it is trace
    state that rides on the request; the intent is session state.

    Parameters
    ----------
    plot_ndim : int
        Desired plot dimensionality (1 or 2).
    reduce_roles : tuple of DimRole
        INDEX / SUM / MEAN policies for non-plot axes, outermost first.
    reduce_indices : tuple of int
        Index values parallel to ``reduce_roles`` (used when role is INDEX).
    dim_order : tuple of str, optional
        Manual axis arrangement as dimension names, outermost first. Empty
        means "follow :attr:`xkey`".
    xkey : str, optional
        X key the default order follows. Selecting a different X supersedes
        a manual arrangement -- see :meth:`follow_xkey`.
    """

    plot_ndim: int = 1
    reduce_roles: Tuple[DimRole, ...] = ()
    reduce_indices: Tuple[int, ...] = ()
    dim_order: Tuple[str, ...] = ()
    xkey: str = ""

    def __post_init__(self) -> None:
        if self.plot_ndim not in (1, 2):
            raise ValueError(f"plot_ndim must be 1 or 2, got {self.plot_ndim}")
        if len(self.reduce_roles) != len(self.reduce_indices):
            raise ValueError("reduce_roles and reduce_indices length must match")
        for role in self.reduce_roles:
            if role not in SLICE_ROLES:
                raise ValueError(
                    f"reduce roles must be INDEX/SUM/MEAN, got {role}"
                )

    def follow_xkey(self, xkey: Optional[str]) -> "ViewIntent":
        """
        Point the default axis order at a new X selection.

        Reordering rows and picking an X key are both explicit statements
        about which dimension is horizontal, so the later one wins: a manual
        arrangement survives every rebuild until the X selection actually
        changes, and is dropped when it does.

        Parameters
        ----------
        xkey : str or None
            Newly selected X key.

        Returns
        -------
        ViewIntent
            This intent when the selection is unchanged, otherwise one
            following the new key with any manual order cleared.
        """
        xkey = xkey or ""
        if xkey == self.xkey:
            return self
        return replace(self, xkey=xkey, dim_order=())

    def project(
        self,
        ndim: int,
        shape: Optional[Sequence[int]] = None,
        dim_names: Optional[Sequence[str]] = None,
        *,
        crop: Optional[ViewCrop] = None,
    ) -> Projection:
        """
        Project this intent onto one key's rank and dimension names.

        Parameters
        ----------
        ndim : int
            Storage rank of the target key.
        shape : sequence of int, optional
            Per-axis sizes used to clamp INDEX values. When omitted, indices
            are left as stored (still non-negative).
        dim_names : sequence of str, optional
            Dimension name per storage axis. Without it the axis order falls
            back to the trailing-axis default.
        crop : ViewCrop, optional
            Trace-scoped crop to carry on the projection. Rewritten onto this
            key's plot-plane axes when they differ.

        Returns
        -------
        Projection
            Rank-bound view for this key.

        Raises
        ------
        ValueError
            If ``ndim < plot_ndim`` -- the key cannot fill this plot.
        """
        if ndim <= 0:
            raise ValueError("ndim must be positive")
        if ndim < self.plot_ndim:
            raise ValueError(
                f"cannot project intent with plot_ndim={self.plot_ndim} "
                f"onto array of rank {ndim}"
            )
        if shape is not None and len(shape) != ndim:
            raise ValueError(
                f"shape length {len(shape)} must match ndim {ndim}"
            )

        axis_order = resolve_axis_order(
            ndim,
            self.plot_ndim,
            dim_names=dim_names,
            dim_order=self.dim_order,
            xkey=self.xkey,
        )

        n_reduce = ndim - self.plot_ndim
        if len(self.reduce_roles) >= n_reduce:
            # Drop outermost axes; keep those nearest the plot plane.
            roles_reduce = self.reduce_roles[-n_reduce:] if n_reduce else ()
            indices_reduce = (
                self.reduce_indices[-n_reduce:] if n_reduce else ()
            )
        else:
            # Pad outermost with INDEX@0.
            pad = n_reduce - len(self.reduce_roles)
            roles_reduce = (DimRole.INDEX,) * pad + self.reduce_roles
            indices_reduce = (0,) * pad + self.reduce_indices

        roles: List[DimRole] = [DimRole.INDEX] * ndim
        indices: List[int] = [0] * ndim
        for pos, storage_axis in enumerate(axis_order):
            if pos < n_reduce:
                roles[storage_axis] = roles_reduce[pos]
                idx = int(indices_reduce[pos])
                if shape is not None:
                    size = int(shape[storage_axis])
                    idx = 0 if size <= 0 else max(0, min(idx, size - 1))
                elif idx < 0:
                    idx = 0
                indices[storage_axis] = idx
            elif self.plot_ndim == 2 and pos == ndim - 2:
                roles[storage_axis] = DimRole.PLOT_Y
            else:
                roles[storage_axis] = DimRole.PLOT_X

        if crop is not None:
            plot_y = axis_order[n_reduce]
            plot_x = axis_order[n_reduce + 1]
            if crop.plot_y_axis != plot_y or crop.plot_x_axis != plot_x:
                crop = ViewCrop(
                    storage_bbox=crop.storage_bbox,
                    plot_y_axis=plot_y,
                    plot_x_axis=plot_x,
                )

        return Projection(
            ndim=ndim,
            plot_ndim=self.plot_ndim,
            roles=tuple(roles),
            indices=tuple(indices),
            axis_order=axis_order,
            crop=crop,
        )

    def with_axis_order(
        self, axis_order: Sequence[int], dim_names: Sequence[str]
    ) -> "ViewIntent":
        """
        Record a manual arrangement, translated into dimension names.

        Parameters
        ----------
        axis_order : sequence of int
            Storage axis indices, outermost first.
        dim_names : sequence of str
            Dimension name per storage axis.

        Returns
        -------
        ViewIntent
            Intent carrying the arrangement as names.
        """
        return replace(
            self, dim_order=tuple(dim_names[a] for a in axis_order)
        )

    def with_reduce_from(self, projection: Projection) -> "ViewIntent":
        """
        Take reduce roles and indices back off a projection.

        The dimension rows are edited per storage axis; this reads the whole
        slice section back in the intent's outermost-first order so one
        assignment carries every row.

        Parameters
        ----------
        projection : Projection
            Projection whose slice section holds the edited values.

        Returns
        -------
        ViewIntent
            Intent with reduce policy replaced.
        """
        roles = []
        indices = []
        for storage_axis in projection.slice_axis_order():
            role = projection.roles[storage_axis]
            roles.append(role if role in SLICE_ROLES else DimRole.INDEX)
            indices.append(projection.indices[storage_axis])
        return replace(
            self,
            reduce_roles=tuple(roles),
            reduce_indices=tuple(indices),
        )


def spec_from_slice_info(
    slice_info: Tuple[SliceItem, ...], plot_ndim: int
) -> Projection:
    """
    Infer a projection from a per-axis slice tuple.

    Parameters
    ----------
    slice_info : tuple
        Per-dimension slice or integer index.
    plot_ndim : int
        Plot dimension count (1 or 2).

    Returns
    -------
    Projection
        Equivalent projection.
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
    return Projection(
        ndim=ndim,
        plot_ndim=plot_ndim,
        roles=tuple(roles),
        indices=tuple(indices),
    )


def plot_axis_to_storage_axis(parent: Projection, plot_axis: PlotAxisName) -> int:
    """
    Map a plot axis name to its storage dimension index on a 2D parent spec.

    Parameters
    ----------
    parent : Projection
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


def eligible_profile_axes(spec: Projection) -> List[int]:
    """
    Return storage axis indices valid as profile axis choices.

    Parameters
    ----------
    spec : Projection
        Parent projection.

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
    mask_mode: MaskMode,
    spatial_reduce: SpatialReduce,
    profile_axis: int,
    axis_names: Sequence[str],
) -> str:
    """
    Return a short default legend label for an ROI profile.

    Parameters
    ----------
    mask_mode : str
        ``inside`` or ``outside`` the ROI.
    spatial_reduce : str
        ``sum`` or ``mean`` within the ROI.
    profile_axis : int
        Storage axis the profile runs along.
    axis_names : sequence of str
        Names per parent storage axis.

    Returns
    -------
    str
        Label summarizing mask mode, reduce op, and profile axis.
    """
    region = "in" if mask_mode == "inside" else "out"
    return (
        f"{spatial_reduce} ({region} ROI) · "
        f"{profile_axis_name(profile_axis, axis_names)}"
    )


def profile_axis_name(storage_axis: int, axis_names: Sequence[str]) -> str:
    """
    Return a display name for a profile axis dropdown entry.

    Parameters
    ----------
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
    parent: Projection,
    profile_storage_axis: int,
    spatial_reduce: SpatialReduce,
) -> Projection:
    """
    Build a 1D profile output spec from a 2D parent view.

    Parameters
    ----------
    parent : Projection
        Parent projection with ``plot_ndim == 2``.
    profile_storage_axis : int
        Storage axis along which profile coordinates run.
    spatial_reduce : str
        ``sum`` or ``mean`` over plot-plane axes within the ROI.

    Returns
    -------
    Projection
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
    return Projection(
        ndim=parent.ndim,
        plot_ndim=1,
        roles=tuple(roles),
        indices=tuple(parent.indices),
        axis_order=tuple(axis_order),
    )


def profile_storage_axis(spec: Projection) -> int:
    """
    Return the storage axis assigned Plot X in a 1D output spec.
    """
    profile_axes = [
        i for i, role in enumerate(spec.roles) if role == DimRole.PLOT_X
    ]
    if len(profile_axes) != 1:
        raise ValueError("expected exactly one profile axis in output spec")
    return profile_axes[0]


def scan_profile_storage_axis(parent_spec: Projection) -> Optional[int]:
    """
    Return the leading scan storage axis in tensor order.

    Among axes that are not globally reduced (SUM or MEAN), returns the
    minimum storage index. This is the external scan axis for stack spectra,
    whether its role is INDEX or a plot axis (e.g. mesh ``en_energy``).

    Parameters
    ----------
    parent_spec : Projection
        Parent projection.

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
    parent_spec: Projection, profile_storage_axis: int
) -> Literal["stack_spectrum", "local_profile"]:
    """
    Classify a profile axis for save routing.

    Parameters
    ----------
    parent_spec : Projection
        Parent projection.
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
    parent_spec: Projection, storage_axis: int
) -> bool:
    """
    Return whether a storage axis lies on the parent 2D plot plane.

    Parameters
    ----------
    parent_spec : Projection
        Parent projection with ``plot_ndim == 2``.
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
    parent_spec: Optional[Projection] = None,
) -> PlotAxisName:
    """
    Return the plot axis name for a profile storage dimension.

    The view spec decides which storage axis is horizontal, at every rank
    including two. The frame cannot: since orientation moved to just after
    the load, ``frame.plot_y_dim`` and ``frame.plot_x_dim`` are always 0 and
    1 -- display positions, not storage axes -- so comparing a storage axis
    against them silently inverts the answer for any view whose plot-axis
    order is not the identity. That is only used as a last resort, when there
    is no spec to ask and "storage axis" can only mean "display position".

    Parameters
    ----------
    frame : PlotViewFrame
        Parent 2D view frame.
    profile_storage_axis : int
        Storage axis index on the parent projection.
    parent_spec : Projection, optional
        Full parent view used to map storage axes to plot X / plot Y.

    Returns
    -------
    str
        ``plot_x`` or ``plot_y``.

    Raises
    ------
    ValueError
        If the axis is not one of the two plot-plane axes.
    """
    if parent_spec is not None and parent_spec.plot_ndim == 2:
        plot_order = parent_spec.plot_axis_order()
        if len(plot_order) >= 2:
            if profile_storage_axis == plot_order[-1]:
                return "plot_x"
            if profile_storage_axis == plot_order[-2]:
                return "plot_y"
            raise ValueError(
                f"profile storage axis {profile_storage_axis} is not on the "
                f"plot plane {plot_order[-2:]}"
            )
    if profile_storage_axis == frame.plot_x_dim:
        return "plot_x"
    if profile_storage_axis == frame.plot_y_dim:
        return "plot_y"
    raise ValueError(
        f"profile storage axis {profile_storage_axis} is not on the plot plane"
    )
