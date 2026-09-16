"""
The projection, in the vocabulary of the data.

A :class:`~nbs_viewer.models.plot.spec.projection.Projection` describes a view by
*storage axis index*: ``roles[2]`` is the role of the third dimension of the
stored array. The pipeline's arrays are ``xarray.DataArray``s whose axes are
named, and whose names survive slicing and reduction while indices do not --
that is the whole reason the axis bookkeeping could be deleted.

``PlotAxes`` is the translation between the two, derived **once** from the
request before anything is read. Every stage after the load takes it, and no
stage after the load ever sees a storage axis index again.

It is a description derived from a description, so it applies itself to
nothing: it answers questions about names and roles, and the stages do the
work.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Sequence, Tuple

from ..plane.roles import DimRole
from .projection import Projection


@dataclass(frozen=True)
class PlotAxes:
    """
    Role and order of every dimension, by name.

    Parameters
    ----------
    spec : Projection
        The projection this names. Kept because the load slice and the crop
        are still expressed over storage axes; stages read the named
        properties, not this.
    names : tuple of str
        Dimension name per storage axis, full rank. For a catalog key these
        are the plot axis names under the current X selection, so the event
        axis wears the name of whatever is being plotted against it.
    plane : tuple of str, optional
        The two dimensions of the plot plane, ``(row, column)``. For a
        profile view this is the *parent's* plane, which is not recoverable
        from the profile spec: profiling along a cube's slider axis leaves
        the plane at the leading axes.
    profile : str, optional
        The dimension the profile runs along, for a profile view.
    """

    spec: Projection
    names: Tuple[str, ...]
    plane: Optional[Tuple[str, str]] = None
    profile: Optional[str] = None

    @classmethod
    def of(
        cls,
        spec: Projection,
        names: Sequence[str],
        *,
        plane: Optional[Tuple[str, str]] = None,
        profile: Optional[str] = None,
    ) -> "PlotAxes":
        """
        Name a projection's axes.

        Parameters
        ----------
        spec : Projection
            Projection to name.
        names : sequence of str
            One name per storage axis.
        plane : tuple of str, optional
            Parent plot plane. Defaults to the projection's own plot plane
            when it has one.
        profile : str, optional
            Profile dimension.

        Returns
        -------
        PlotAxes
            Named view.

        Raises
        ------
        ValueError
            If the name count disagrees with the projection's rank, or two
            axes share a name -- roles are looked up by name, so a duplicate
            would silently give one axis another's role.
        """
        names = tuple(names)
        if len(names) != spec.ndim:
            raise ValueError(
                f"{len(names)} names for a rank-{spec.ndim} projection"
            )
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate axis names {names}")
        if plane is None and spec.plot_ndim == 2:
            order = spec.plot_axis_order()
            plane = (names[order[0]], names[order[1]])
        return cls(spec=spec, names=names, plane=plane, profile=profile)

    @property
    def roles(self) -> Mapping[str, DimRole]:
        """Role of each dimension, by name."""
        return MappingProxyType(dict(zip(self.names, self.spec.roles)))

    @property
    def order(self) -> Tuple[str, ...]:
        """
        Every dimension in plot order: slice/reduce axes, then Y, then X.

        This is what the finished array is transposed to. Axes the load
        indexed away are still listed; a caller intersects with the dims it
        actually has.
        """
        return tuple(self.names[axis] for axis in self.spec.axis_order)

    @property
    def plot_dims(self) -> Tuple[str, ...]:
        """The output's plot axes, ``(Y, X)`` or ``(X,)``."""
        return tuple(
            self.names[axis] for axis in self.spec.plot_axis_order()
        )

    @property
    def display_dims(self) -> Tuple[str, ...]:
        """
        The dimensions the user is looking at when a transform runs.

        The plot plane for a 2-D view, and for a profile view the *parent's*
        plane -- an ROI is drawn on the image, so ``x`` in a transform means
        the same thing whether or not a profile is being taken from it.
        """
        return self.plane if self.plane is not None else self.plot_dims

    def role(self, dim: str) -> DimRole:
        """
        Return one dimension's role.

        Parameters
        ----------
        dim : str
            Dimension name.

        Returns
        -------
        DimRole
            Its role in this view.
        """
        return self.spec.roles[self.names.index(dim)]

    def dims_with_role(self, *roles: DimRole) -> Tuple[str, ...]:
        """
        Return the dimensions holding any of these roles, in storage order.

        Parameters
        ----------
        *roles : DimRole
            Roles to match.

        Returns
        -------
        tuple of str
            Matching dimension names.
        """
        return tuple(
            name
            for name, role in zip(self.names, self.spec.roles)
            if role in roles
        )

    def to_profile(
        self, profile_storage_axis: int, spatial_reduce: str
    ) -> "PlotAxes":
        """
        Derive the 1-D profile view an ROI reduces this one to.

        The parent plane is carried over rather than re-derived: the profile
        spec's own plot axis is the profile, and where the plane went is not
        recoverable from it.

        Parameters
        ----------
        profile_storage_axis : int
            Storage axis the profile runs along.
        spatial_reduce : str
            ``sum`` or ``mean`` within the ROI.

        Returns
        -------
        PlotAxes
            Named profile view.
        """
        return PlotAxes.of(
            self.spec.to_profile(profile_storage_axis, spatial_reduce),
            self.names,
            plane=self.plane,
            profile=self.names[profile_storage_axis],
        )
