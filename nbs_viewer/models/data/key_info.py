"""
What a data source says about one key without reading it.

``KeyInfo`` is the return of :meth:`CatalogRun.describe`. It is static: it
depends on the key alone, never on which X key is selected, so it can be
cached for the life of a run. That was always its documented intent; what
makes it true is that the axis a key is plotted *against* is a coordinate
choice rather than a dimension name -- a scanned motor is a separate 1-D key
living *on* the event axis, as a labelled Bluesky run shows directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class KeyInfo:
    """
    Static, selection-independent facts about one data key.

    ``axes`` carries the key's dimensions in storage order, mapping each
    name to its length. One mapping rather than a name tuple beside a shape
    tuple, because the two can disagree -- which is what bug 6 was -- and a
    mapping cannot hold two axes with one name, which is what bug 15 was.
    Build it through :meth:`from_dims`, which rejects both.

    Parameters
    ----------
    name : str
        Catalog or synthetic key name.
    label : str
        Display label. Synthetic keys carry a friendly label; catalog keys
        use the key name.
    axes : mapping of str to int
        Dimension name to length, in storage order.
    synthetic : bool
        True for frozen overlay keys.
    hinted : bool
        Whether the key is a hinted primary. Until
        ``CatalogRun.get_hinted_keys`` is confirmed as the "Show All Keys"
        backing, catalog keys are ``True`` and synthetic keys are ``False``.
    render_hint : str or None
        Per-key ``image`` / ``mesh`` override from plot hints, or None.
    """

    name: str
    label: str
    axes: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    synthetic: bool = False
    hinted: bool = False
    render_hint: Optional[str] = None

    @classmethod
    def from_dims(
        cls,
        name: str,
        dims: Sequence[str],
        shape: Sequence[int],
        *,
        label: Optional[str] = None,
        synthetic: bool = False,
        hinted: bool = False,
        render_hint: Optional[str] = None,
    ) -> "KeyInfo":
        """
        Build a ``KeyInfo`` from a source's dimension names and shape.

        This is the one boundary where name/rank agreement is enforced. It
        used to be patched downstream instead, by a consumer that padded or
        truncated the name list until it fit -- which meant a backend could
        disagree with its own arrays indefinitely and the only symptom was an
        axis silently wearing another axis's name.

        Parameters
        ----------
        name : str
            Data key name.
        dims : sequence of str
            Dimension names, one per axis, in storage order.
        shape : sequence of int
            Axis lengths, in storage order.
        label : str, optional
            Display label; defaults to ``name``.
        synthetic : bool, optional
            True for frozen overlay keys.
        hinted : bool, optional
            Whether the key is a hinted primary.
        render_hint : str or None, optional
            Per-key render-mode override.

        Returns
        -------
        KeyInfo
            Validated description.

        Raises
        ------
        ValueError
            If the name count disagrees with the rank, or two axes share a
            name.
        """
        dims = tuple(dims)
        shape = tuple(int(size) for size in shape)
        if len(dims) != len(shape):
            raise ValueError(
                f"key {name!r} has rank {len(shape)} but {len(dims)} dimension "
                f"names {dims}: a source must agree with its own arrays"
            )
        if len(set(dims)) != len(dims):
            raise ValueError(
                f"key {name!r} names two axes the same thing: {dims}. "
                "Normalization aligns arrays by axis name, so a duplicate is "
                "a silent wrong answer rather than a cosmetic problem."
            )
        return cls(
            name=name,
            label=name if label is None else label,
            axes=MappingProxyType(dict(zip(dims, shape))),
            synthetic=synthetic,
            hinted=hinted,
            render_hint=render_hint,
        )

    @property
    def dims(self) -> Tuple[str, ...]:
        """Dimension names in storage order."""
        return tuple(self.axes)

    @property
    def shape(self) -> Tuple[int, ...]:
        """Storage shape."""
        return tuple(self.axes.values())

    @property
    def ndim(self) -> int:
        """Storage rank."""
        return len(self.axes)
