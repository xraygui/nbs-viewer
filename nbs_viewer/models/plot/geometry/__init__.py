"""
Where a plot plane sits in data coordinates, and what covers part of it.

Five files, in dependency order. :mod:`orientation` decides how a plane
should be drawn -- ``image`` or ``mesh``, the extent, the mesh grids, which
axes reverse. :mod:`bundle` packs a finished array and those decisions into
the :class:`PlotBundle` the view layer draws. :mod:`frame` is that plane's
coordinate frame, and answers where any one cell of it lies. :mod:`region`
holds the shapes a user draws on it, and :mod:`mask` rasterizes a shape
against a frame into a boolean mask.

Nothing here knows about a run, a request, or a session: given an array and
its coordinates, these say where it goes on screen.

**What this surface exports** is what production code outside the package
imports, completed so that no family is half-exported: ``prepare_2d_bundle``
joins its 1-D twin, ``AxisSliceRegion`` joins the other three shapes,
``CompiledRegion`` names what the two compilers return, and
``region_from_dict`` is the inverse of the shapes' own serialization.

**What it hides** is the arithmetic. The four ``mask_from_*`` rasterizers,
the per-mode cell bounds, the extent and edge builders, and the uniformity
tests are all reached through the doors above -- ``compile_with_mask_mode``
is how a caller turns a shape into a mask, and there is no reason to pick a
rasterizer by hand.

Tests that exercise that arithmetic import its module directly, which is the
intended asymmetry: a test of the cell-bounds maths should break when the
maths moves, whereas an application caller should not.
"""

from .bundle import (
    PlotBundle,
    build_plot_bundle,
    prepare_1d_bundle,
    prepare_2d_bundle,
)
from .frame import (
    PlotViewFrame,
    cell_x_bounds_mesh,
    cell_y_bounds_mesh,
    frame_for_plane,
    frame_from_bundle,
    mesh_separable_edge_grids,
    region_frame_for_bbox,
    view_fingerprint_from_bundle,
)
from .orientation import RenderMode, classify_render_mode, display_flips
from .region import (
    AxisSliceRegion,
    CompiledRegion,
    EllipseRegion,
    MaskMode,
    PolygonRegion,
    RectRegion,
    RegionDefinition,
    compile_covering_rect,
    compile_with_mask_mode,
    expand_region_for_profile,
    region_from_dict,
)

__all__ = [
    "AxisSliceRegion",
    "CompiledRegion",
    "EllipseRegion",
    "MaskMode",
    "PlotBundle",
    "PlotViewFrame",
    "PolygonRegion",
    "RectRegion",
    "RegionDefinition",
    "RenderMode",
    "build_plot_bundle",
    "cell_x_bounds_mesh",
    "cell_y_bounds_mesh",
    "classify_render_mode",
    "compile_covering_rect",
    "compile_with_mask_mode",
    "display_flips",
    "expand_region_for_profile",
    "frame_for_plane",
    "frame_from_bundle",
    "mesh_separable_edge_grids",
    "prepare_1d_bundle",
    "prepare_2d_bundle",
    "region_frame_for_bbox",
    "region_from_dict",
    "view_fingerprint_from_bundle",
]
