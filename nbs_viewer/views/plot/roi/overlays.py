"""
Per-shape ROI overlay artists for the parent plot canvas.
"""

from __future__ import annotations

from typing import Sequence, Tuple

from matplotlib.colors import to_rgba
from matplotlib.patches import Ellipse, Polygon, Rectangle

from nbs_viewer.models.plot.region import (
    EllipseRegion,
    PolygonRegion,
    RectRegion,
    RegionDefinition,
)

_ROI_EDGE_WIDTH = 2.5
_ROI_HALO_WIDTH = 4.5
_ROI_FILL_ALPHA = 0.12
_ROI_STALE_FILL_ALPHA = 0.08


def _edge_and_face(color: str, stale: bool) -> Tuple[str, tuple]:
    """
    Return edge color and RGBA face color for an overlay.
    """
    edge = "#bdbdbd" if stale else color
    face_alpha = _ROI_STALE_FILL_ALPHA if stale else _ROI_FILL_ALPHA
    return edge, to_rgba(edge, face_alpha)


def overlay_artists_for_region(
    region: RegionDefinition,
    *,
    color: str,
    stale: bool,
) -> Sequence:
    """
    Build overlay artists for a region geometry.

    Parameters
    ----------
    region : RegionDefinition
        Geometry in data coordinates.
    color : str
        Overlay color when the entry is not stale.
    stale : bool
        When True, draw a muted overlay.

    Returns
    -------
    sequence
        Matplotlib patch artists to add to the axes.
    """
    if isinstance(region, RectRegion):
        return rect_overlay_artists(region, color=color, stale=stale)
    if isinstance(region, EllipseRegion):
        return ellipse_overlay_artists(region, color=color, stale=stale)
    if isinstance(region, PolygonRegion):
        return polygon_overlay_artists(region, color=color, stale=stale)
    return ()


def rect_overlay_artists(
    region: RectRegion, *, color: str, stale: bool
) -> Tuple:
    """
    Build rectangle overlay patches with an opaque edge and light halo.
    """
    region = region.normalized()
    edge, face = _edge_and_face(color, stale)
    xy = (region.x0, region.y0)
    width = region.x1 - region.x0
    height = region.y1 - region.y0
    halo = Rectangle(
        xy,
        width,
        height,
        linewidth=_ROI_HALO_WIDTH,
        edgecolor="white",
        facecolor="none",
        alpha=0.85 if not stale else 0.45,
        fill=False,
        zorder=20,
    )
    body = Rectangle(
        xy,
        width,
        height,
        linewidth=_ROI_EDGE_WIDTH,
        edgecolor=edge,
        facecolor=face,
        fill=True,
        zorder=21,
    )
    return halo, body


def ellipse_overlay_artists(
    region: EllipseRegion, *, color: str, stale: bool
) -> Tuple:
    """
    Build ellipse overlay patches with an opaque edge and light halo.
    """
    region = region.normalized()
    edge, face = _edge_and_face(color, stale)
    halo = Ellipse(
        (region.cx, region.cy),
        width=2.0 * region.rx,
        height=2.0 * region.ry,
        angle=region.angle,
        linewidth=_ROI_HALO_WIDTH,
        edgecolor="white",
        facecolor="none",
        alpha=0.85 if not stale else 0.45,
        fill=False,
        zorder=20,
    )
    body = Ellipse(
        (region.cx, region.cy),
        width=2.0 * region.rx,
        height=2.0 * region.ry,
        angle=region.angle,
        linewidth=_ROI_EDGE_WIDTH,
        edgecolor=edge,
        facecolor=face,
        fill=True,
        zorder=21,
    )
    return halo, body


def polygon_overlay_artists(
    region: PolygonRegion, *, color: str, stale: bool
) -> Tuple:
    """
    Build polygon overlay patches with an opaque edge and light halo.
    """
    if len(region.vertices) < 3:
        return ()
    edge, face = _edge_and_face(color, stale)
    xy = list(region.vertices)
    halo = Polygon(
        xy,
        closed=True,
        linewidth=_ROI_HALO_WIDTH,
        edgecolor="white",
        facecolor="none",
        alpha=0.85 if not stale else 0.45,
        fill=False,
        zorder=20,
    )
    body = Polygon(
        xy,
        closed=True,
        linewidth=_ROI_EDGE_WIDTH,
        edgecolor=edge,
        facecolor=face,
        fill=True,
        zorder=21,
    )
    return halo, body
