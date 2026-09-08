"""
Rank-agnostic view intent and concrete view specifications.

``ViewIntent`` is what a plot session holds and the dimension controls edit.
``ViewSpec`` is the rank-bound snapshot carried by a ``PlotRequest``. Crop
rides along as integer storage bounds on the plot plane; it is applied by
``plot_request.plan_fetch``, never here.

These types sit beside ``CubeViewSpec`` during the migration; they do not yet
replace it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Optional, Sequence, Tuple, Union

from .cube_view import DimRole, SLICE_ROLES, CubeViewSpec

SliceItem = Union[int, slice]


@dataclass(frozen=True)
class ViewCrop:
    """
    Integer storage-index crop on the 2D plot plane.

    Display-to-storage conversion happens at construction time. Only the
    bounds needed to narrow a load slice are retained, so the crop is
    hashable and safe to embed in a ``ViewSpec`` / ``PlotRequest``.

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
class ViewSpec:
    """
    Rank-bound description of how to slice, reduce, and orient an array.

    This is the concrete view embedded in a :class:`PlotRequest`. It is the
    migration counterpart of :class:`CubeViewSpec`, with optional plot-plane
    crop folded in.

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
                        "crop plot axes must match ViewSpec plot_axis_order "
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

    def with_index(self, storage_axis: int, index: int) -> "ViewSpec":
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
        ViewSpec
            Updated specification.
        """
        indices = list(self.indices)
        indices[storage_axis] = index
        return replace(self, indices=tuple(indices))

    def with_slice_role(self, storage_axis: int, role: DimRole) -> "ViewSpec":
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
        ViewSpec
            Updated specification.
        """
        if role not in SLICE_ROLES:
            raise ValueError(f"slice role must be one of {SLICE_ROLES}")
        roles = list(self.roles)
        roles[storage_axis] = role
        return replace(self, roles=tuple(roles))

    def to_cube_view_spec(self) -> CubeViewSpec:
        """
        Convert to a :class:`CubeViewSpec`, dropping crop.

        Returns
        -------
        CubeViewSpec
            Equivalent cube view without crop.
        """
        return CubeViewSpec(
            ndim=self.ndim,
            plot_ndim=self.plot_ndim,
            roles=self.roles,
            indices=self.indices,
            axis_order=self.axis_order,
        )

    @classmethod
    def from_cube_view_spec(
        cls,
        spec: CubeViewSpec,
        crop: Optional[ViewCrop] = None,
    ) -> "ViewSpec":
        """
        Build a :class:`ViewSpec` from an existing :class:`CubeViewSpec`.

        Parameters
        ----------
        spec : CubeViewSpec
            Source cube view.
        crop : ViewCrop, optional
            Optional plot-plane crop.

        Returns
        -------
        ViewSpec
            Equivalent view specification.
        """
        return cls(
            ndim=spec.ndim,
            plot_ndim=spec.plot_ndim,
            roles=spec.roles,
            indices=spec.indices,
            axis_order=spec.axis_order,
            crop=crop,
        )


def plot_axis_names(
    spec: ViewSpec,
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
    spec : ViewSpec
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


def default_view_spec(ndim: int, plot_ndim: int = 1) -> ViewSpec:
    """
    Build a trailing-axis view: INDEX on leading axes, plot on trailing.

    Parameters
    ----------
    ndim : int
        Number of storage dimensions.
    plot_ndim : int
        1 for line plots, 2 for image plots.

    Returns
    -------
    ViewSpec
        Default specification.
    """
    if ndim <= 0:
        raise ValueError("ndim must be positive")
    if ndim < plot_ndim:
        raise ValueError(f"ndim {ndim} is below plot_ndim {plot_ndim}")
    roles: List[DimRole] = [DimRole.INDEX] * (ndim - plot_ndim)
    if plot_ndim == 1:
        roles.append(DimRole.PLOT_X)
    else:
        roles.extend([DimRole.PLOT_Y, DimRole.PLOT_X])
    return ViewSpec(
        ndim=ndim,
        plot_ndim=plot_ndim,
        roles=tuple(roles),
        indices=tuple(0 for _ in range(ndim)),
        axis_order=tuple(range(ndim)),
    )


@dataclass(frozen=True)
class ViewIntent:
    """
    Rank-agnostic session view state.

    The session and dimension controls edit one intent. At request-build time
    the intent is projected onto each key's rank via :meth:`project`. Keys
    with ``ndim < plot_ndim`` cannot participate (a 1-D spectrum cannot fill
    a 2-D image plot). Whether two projected keys may share a plot is a
    separate check on :func:`plot_axis_names`.

    Reduce policy is stored outermost-first, matching the leading rows of
    the dimension UI. When projecting to a smaller rank, outermost reduce
    axes are dropped so the axes nearest the plot plane are preserved.

    Parameters
    ----------
    plot_ndim : int
        Desired plot dimensionality (1 or 2).
    reduce_roles : tuple of DimRole
        INDEX / SUM / MEAN policies for non-plot axes, outermost first.
    reduce_indices : tuple of int
        Index values parallel to ``reduce_roles`` (used when role is INDEX).
    axis_order : tuple of int, optional
        Storage-axis permutation for the rank this intent was edited against.
        When empty, or when its length does not match the projected ``ndim``,
        natural order ``range(ndim)`` is used.
    crop : ViewCrop, optional
        Persistent spatial crop. Only applied when ``plot_ndim == 2``.
    """

    plot_ndim: int
    reduce_roles: Tuple[DimRole, ...] = ()
    reduce_indices: Tuple[int, ...] = ()
    axis_order: Tuple[int, ...] = ()
    crop: Optional[ViewCrop] = None

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
        if self.crop is not None and self.plot_ndim != 2:
            raise ValueError("crop requires plot_ndim == 2")

    def project(
        self,
        ndim: int,
        shape: Optional[Sequence[int]] = None,
    ) -> ViewSpec:
        """
        Project this intent onto a concrete array rank.

        Parameters
        ----------
        ndim : int
            Storage rank of the target key.
        shape : sequence of int, optional
            Per-axis sizes used to clamp INDEX values. When omitted, indices
            are left as stored (still non-negative).

        Returns
        -------
        ViewSpec
            Rank-bound view for this key.

        Raises
        ------
        ValueError
            If ``ndim < plot_ndim`` — the key cannot fill this plot.
        """
        if ndim < self.plot_ndim:
            raise ValueError(
                f"cannot project intent with plot_ndim={self.plot_ndim} "
                f"onto array of rank {ndim}"
            )
        if ndim <= 0:
            raise ValueError("ndim must be positive")
        if shape is not None and len(shape) != ndim:
            raise ValueError(
                f"shape length {len(shape)} must match ndim {ndim}"
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

        if self.axis_order and len(self.axis_order) == ndim:
            axis_order = self.axis_order
        else:
            axis_order = tuple(range(ndim))

        roles: List[DimRole] = [DimRole.INDEX] * ndim
        indices: List[int] = [0] * ndim
        for pos, storage_axis in enumerate(axis_order):
            if pos < n_reduce:
                roles[storage_axis] = roles_reduce[pos]
                idx = int(indices_reduce[pos])
                if shape is not None:
                    size = int(shape[storage_axis])
                    if size <= 0:
                        idx = 0
                    else:
                        idx = max(0, min(idx, size - 1))
                elif idx < 0:
                    idx = 0
                indices[storage_axis] = idx
            elif self.plot_ndim == 2 and pos == ndim - 2:
                roles[storage_axis] = DimRole.PLOT_Y
            else:
                roles[storage_axis] = DimRole.PLOT_X

        crop = self.crop
        if crop is not None:
            plot_y = axis_order[n_reduce]
            plot_x = axis_order[n_reduce + 1]
            if crop.plot_y_axis != plot_y or crop.plot_x_axis != plot_x:
                crop = ViewCrop(
                    storage_bbox=crop.storage_bbox,
                    plot_y_axis=plot_y,
                    plot_x_axis=plot_x,
                )

        return ViewSpec(
            ndim=ndim,
            plot_ndim=self.plot_ndim,
            roles=tuple(roles),
            indices=tuple(indices),
            axis_order=axis_order,
            crop=crop,
        )

    @classmethod
    def from_view_spec(cls, spec: ViewSpec) -> "ViewIntent":
        """
        Lift a concrete spec into a rank-agnostic intent.

        Useful when adapting today's ``CubeViewSpec``-based UI state into the
        new model.

        Parameters
        ----------
        spec : ViewSpec
            Concrete view to lift.

        Returns
        -------
        ViewIntent
            Intent whose :meth:`project` of ``spec.ndim`` recovers ``spec``
            (crop axes may be rewritten to match plot order).
        """
        reduce_roles = []
        reduce_indices = []
        for storage_axis in spec.slice_axis_order():
            reduce_roles.append(spec.roles[storage_axis])
            reduce_indices.append(spec.indices[storage_axis])
        return cls(
            plot_ndim=spec.plot_ndim,
            reduce_roles=tuple(reduce_roles),
            reduce_indices=tuple(reduce_indices),
            axis_order=spec.axis_order,
            crop=spec.crop,
        )
