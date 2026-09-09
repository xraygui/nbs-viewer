"""
Session view state as a model.

One :class:`ViewIntent` per plot session. It is mutable and it emits; what it
produces -- :class:`Projection` -- is a frozen value, because a projection
rides on a :class:`PlotRequest` and a request is the fingerprint of a fetch.
Immutability here is for things that are retained and compared, not for things
that are observed.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from qtpy.QtCore import QObject, Signal

from .view_spec import (
    DimRole,
    Projection,
    SLICE_ROLES,
    ViewCrop,
    resolve_axis_order,
)


def _validated_reduce(
    roles: Sequence[DimRole], indices: Sequence[int]
) -> Tuple[Tuple[DimRole, ...], Tuple[int, ...]]:
    """
    Return the reduce policy as tuples, rejecting an inconsistent one.

    Parameters
    ----------
    roles : sequence of DimRole
        INDEX / SUM / MEAN policies, outermost first.
    indices : sequence of int
        Index values parallel to ``roles``.

    Returns
    -------
    tuple of (tuple of DimRole, tuple of int)

    Raises
    ------
    ValueError
        If the lengths differ or a role is not a slice role.
    """
    roles = tuple(roles)
    indices = tuple(int(i) for i in indices)
    if len(roles) != len(indices):
        raise ValueError("reduce_roles and reduce_indices length must match")
    for role in roles:
        if role not in SLICE_ROLES:
            raise ValueError(
                f"reduce roles must be INDEX/SUM/MEAN, got {role}"
            )
    return roles, indices


def _validated_plot_ndim(plot_ndim: int) -> int:
    """
    Return ``plot_ndim`` when it names a supported plot rank.

    Raises
    ------
    ValueError
        If it is neither 1 nor 2.
    """
    plot_ndim = int(plot_ndim)
    if plot_ndim not in (1, 2):
        raise ValueError(f"plot_ndim must be 1 or 2, got {plot_ndim}")
    return plot_ndim


class ViewIntent(QObject):
    """
    Rank-agnostic session view state.

    At request-build time it is projected onto each key's own rank and
    dimension names by :meth:`project`, so a 1-D spectrum and a 1-D
    projection of a 3-D detector can be built from the same state without
    either being reinterpreted. Whether two projected keys may share a plot
    is a separate check on :func:`plot_axis_names`.

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

    Signals
    -------
    plot_ndim_changed : Signal(int)
        Plot rank changed. The payload is a plain ``int`` -- a value, not
        this object -- so a receiver running after coalescing can still act
        on it.
    orientation_changed : Signal()
        The plot plane's coordinate frame moved: ``dim_order`` or ``xkey``.
        A reduce change does **not** emit this, because slicing to another
        index leaves the frame where it was.
    changed : Signal()
        Any mutation at all, always emitted **last**. A consumer connected
        only to this never misses anything.

    Connect to exactly one of these per consumer. ``changed`` fires alongside
    the specific signals rather than instead of them, so subscribing to both
    double-handles.

    Parameters
    ----------
    plot_ndim : int, optional
        Desired plot dimensionality (1 or 2).
    reduce_roles : tuple of DimRole, optional
        INDEX / SUM / MEAN policies for non-plot axes, outermost first.
    reduce_indices : tuple of int, optional
        Index values parallel to ``reduce_roles`` (used when role is INDEX).
    dim_order : tuple of str, optional
        Manual axis arrangement as dimension names, outermost first. Empty
        means "follow :attr:`xkey`".
    xkey : str, optional
        X key the default order follows. Selecting a different X supersedes
        a manual arrangement -- see :meth:`follow_xkey`.
    parent : QObject, optional
        Qt parent.
    """

    plot_ndim_changed = Signal(int)
    orientation_changed = Signal()
    changed = Signal()

    def __init__(
        self,
        plot_ndim: int = 1,
        reduce_roles: Sequence[DimRole] = (),
        reduce_indices: Sequence[int] = (),
        dim_order: Sequence[str] = (),
        xkey: str = "",
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._plot_ndim = _validated_plot_ndim(plot_ndim)
        self._reduce_roles, self._reduce_indices = _validated_reduce(
            reduce_roles, reduce_indices
        )
        self._dim_order = tuple(dim_order)
        self._xkey = xkey or ""

    def __repr__(self) -> str:
        return (
            f"ViewIntent(plot_ndim={self._plot_ndim}, "
            f"reduce_roles={self._reduce_roles}, "
            f"reduce_indices={self._reduce_indices}, "
            f"dim_order={self._dim_order}, xkey={self._xkey!r})"
        )

    @property
    def plot_ndim(self) -> int:
        """
        Desired plot dimensionality (1 or 2).
        """
        return self._plot_ndim

    @property
    def reduce_roles(self) -> Tuple[DimRole, ...]:
        """
        INDEX / SUM / MEAN policy per non-plot axis, outermost first.
        """
        return self._reduce_roles

    @property
    def reduce_indices(self) -> Tuple[int, ...]:
        """
        Index values parallel to :attr:`reduce_roles`.
        """
        return self._reduce_indices

    @property
    def dim_order(self) -> Tuple[str, ...]:
        """
        Manual axis arrangement as dimension names, or empty to follow X.
        """
        return self._dim_order

    @property
    def xkey(self) -> str:
        """
        X key the default axis order follows.
        """
        return self._xkey

    def set_plot_ndim(self, plot_ndim: int) -> bool:
        """
        Set plot dimensionality.

        Parameters
        ----------
        plot_ndim : int
            1 for line plots, 2 for image plots.

        Returns
        -------
        bool
            True when the value actually changed.
        """
        plot_ndim = _validated_plot_ndim(plot_ndim)
        if plot_ndim == self._plot_ndim:
            return False
        self._plot_ndim = plot_ndim
        self.plot_ndim_changed.emit(plot_ndim)
        self.changed.emit()
        return True

    def follow_xkey(self, xkey: Optional[str]) -> bool:
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
        bool
            True when the selection changed and the order was re-derived.
        """
        xkey = xkey or ""
        if xkey == self._xkey:
            return False
        self._xkey = xkey
        self._dim_order = ()
        self.orientation_changed.emit()
        self.changed.emit()
        return True

    def set_axis_order(
        self, axis_order: Sequence[int], dim_names: Sequence[str]
    ) -> bool:
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
        bool
            True when the arrangement changed.
        """
        dim_order = tuple(dim_names[a] for a in axis_order)
        if dim_order == self._dim_order:
            return False
        self._dim_order = dim_order
        self.orientation_changed.emit()
        self.changed.emit()
        return True

    def set_reduce(
        self, roles: Sequence[DimRole], indices: Sequence[int]
    ) -> bool:
        """
        Replace the reduce policy.

        Emits :attr:`changed` but **not** :attr:`orientation_changed`:
        slicing to another index leaves the plot plane's coordinate frame
        where it was, so nothing that keys off the frame needs to react.

        Parameters
        ----------
        roles : sequence of DimRole
            INDEX / SUM / MEAN per reduce axis, outermost first.
        indices : sequence of int
            Index values parallel to ``roles``.

        Returns
        -------
        bool
            True when the policy changed.
        """
        roles, indices = _validated_reduce(roles, indices)
        if roles == self._reduce_roles and indices == self._reduce_indices:
            return False
        self._reduce_roles = roles
        self._reduce_indices = indices
        self.changed.emit()
        return True

    def set_reduce_from(self, projection: Projection) -> bool:
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
        bool
            True when the policy changed.
        """
        roles = []
        indices = []
        for storage_axis in projection.slice_axis_order():
            role = projection.roles[storage_axis]
            roles.append(role if role in SLICE_ROLES else DimRole.INDEX)
            indices.append(projection.indices[storage_axis])
        return self.set_reduce(roles, indices)

    def project(
        self,
        ndim: int,
        shape: Optional[Sequence[int]] = None,
        dim_names: Optional[Sequence[str]] = None,
        *,
        crop: Optional[ViewCrop] = None,
        plot_ndim: Optional[int] = None,
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
        plot_ndim : int, optional
            Plot rank to project at, overriding :attr:`plot_ndim` for this
            call only. Used for the mixed-rank case, where a key that cannot
            fill the session plot still plots on its own terms -- a 1-D
            spectrum beside a 2-D image. The override exists so that case
            does not have to manufacture a throwaway intent.

        Returns
        -------
        Projection
            Rank-bound view for this key.

        Raises
        ------
        ValueError
            If ``ndim < plot_ndim`` -- the key cannot fill this plot.
        """
        if plot_ndim is None:
            plot_ndim = self._plot_ndim
        else:
            plot_ndim = _validated_plot_ndim(plot_ndim)
        if ndim <= 0:
            raise ValueError("ndim must be positive")
        if ndim < plot_ndim:
            raise ValueError(
                f"cannot project intent with plot_ndim={plot_ndim} "
                f"onto array of rank {ndim}"
            )
        if shape is not None and len(shape) != ndim:
            raise ValueError(
                f"shape length {len(shape)} must match ndim {ndim}"
            )

        axis_order = resolve_axis_order(
            ndim,
            plot_ndim,
            dim_names=dim_names,
            dim_order=self._dim_order,
            xkey=self._xkey,
        )

        n_reduce = ndim - plot_ndim
        if len(self._reduce_roles) >= n_reduce:
            # Drop outermost axes; keep those nearest the plot plane.
            roles_reduce = self._reduce_roles[-n_reduce:] if n_reduce else ()
            indices_reduce = (
                self._reduce_indices[-n_reduce:] if n_reduce else ()
            )
        else:
            # Pad outermost with INDEX@0.
            pad = n_reduce - len(self._reduce_roles)
            roles_reduce = (DimRole.INDEX,) * pad + self._reduce_roles
            indices_reduce = (0,) * pad + self._reduce_indices

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
            elif plot_ndim == 2 and pos == ndim - 2:
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
            plot_ndim=plot_ndim,
            roles=tuple(roles),
            indices=tuple(indices),
            axis_order=axis_order,
            crop=crop,
        )
