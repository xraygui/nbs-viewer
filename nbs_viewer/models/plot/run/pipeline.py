"""
Fetch for one run: from a plot request to a plot bundle.

``RunSource`` is the union of a catalog run and its frozen synthetic keys
under one key space, and it is the reader for them. Turning a request into a
bundle is a different job -- plan the load, normalize, reduce, transform,
mask, pack -- and it reaches the source through ``load_coords``, ``describe``
and ``block`` only. It lived on ``RunSource`` as nine methods, about half the
class, and was the only user of every plot-layer module that class imported.

Holding the block is a third job again, and lives in :mod:`.cache`. This
module is the sequencer over the two, and moves onto ``PlotRequest`` next.

``RunSource`` owns one :class:`RunFetch` and hands it out as ``fetch``, so
callers ask it directly rather than through a forwarding method.
"""

from __future__ import annotations

import time as ttime
from typing import TYPE_CHECKING, List, Optional, Tuple

import numpy as np
import xarray as xr

from ..spec.stages import (
    apply_normalization,
    apply_transform,
    mask_to_profile,
    reduce_before_mask,
    reduce_to_plane,
)
from ..plane.frame import PlotViewFrame
from ..plane.orientation import classify_render_mode, display_flips
from ..spec.bundle import PlotBundle
from ..spec.request import PlotRequest
from ..spec.plan import FetchPlan
from nbs_viewer.utils import print_debug

if TYPE_CHECKING:
    from .source import RunSource


class RunFetch:
    """
    Serve plot bundles for one run's keys, holding the last block read.

    Parameters
    ----------
    source : RunSource
        The run whose keys are read. Only ``load``, ``load_coords``,
        ``read``, ``describe`` and ``plot_axis_names`` are used.
    """

    def __init__(self, source: "RunSource") -> None:
        self._source = source

    def get_plot_bundle(
        self,
        request: PlotRequest,
        *,
        cached_plane: Optional[PlotBundle] = None,
        label: str = "",
    ) -> PlotBundle:
        """
        Load, normalize, reduce, transform, mask and pack a request.

        The request is the whole description: the projection, the crop, and
        for an ROI the region, the profile axis and the spatial reduce. What
        the plot plane's coordinate frame is, and which storage indices to
        read, are both derived from it here.

        The stage order is the content of the pipeline:

        - Normalization happens first, on the whole block, so a norm key is
          divided in per element before anything is summed.
        - The transform runs on the finished plot plane, *before* the ROI
          mask. The user already sees ``f(y)`` on the image and draws the ROI
          on what they see, so summing the ROI must sum what they see.

        The load depends only on the fetch plan, so the block is held as
        read, with its norm arrays beside it: editing a transform, toggling a
        normalization already read, or moving an ROI inside a box already
        read re-runs only the arithmetic.

        Parameters
        ----------
        request : PlotRequest
            Frozen plot description.
        cached_plane : PlotBundle, optional
            Plot plane already in memory for ``request.view``. Used to skip
            rebuilding the plane an in-plane ROI profile reduces; ignored
            otherwise.
        label : str
            Optional display label for 1D ROI output.

        Returns
        -------
        PlotBundle
            Prepared plot payload for the view layer.
        """
        plane_axes = request.plane_axes

        # An ROI whose profile runs along an axis the plane already shows is
        # a reduction of the finished plane, so it is served by masking that
        # plane -- from memory when the caller has one, otherwise by building
        # it here. One implementation of masking a 2-D plane, and what it
        # masks is f(y), which is what the ROI was drawn on.
        if request.region is not None and request.profile_axis in (
            plane_axes or ()
        ):
            plane = cached_plane
            if plane is None or plane.ndim != 2:
                plane = self.get_plot_bundle(request.plane_request)
            return request.reduce_cached_plane(plane, label=label)

        data, norms, plan = self._load_block(request)

        t0 = ttime.time()
        data = apply_normalization(data, norms)
        if request.region is None:
            axes = request.axes
            data = reduce_to_plane(data, axes)
            data = apply_transform(data, axes, request.transform)
        else:
            # Off-plane profile: the plane the user sees is one slice of the
            # block, so reduce to that stack, transform it, and only then
            # mask. The profile axis is read in full by the plan. The
            # transform sees the plane's own coordinates either way, so ``x``
            # means the same thing here as when the plane itself is drawn.
            profile = request.profile_axes
            data = reduce_before_mask(data, profile)
            data = apply_transform(data, profile, request.transform)
            data = mask_to_profile(
                data,
                profile,
                request.region,
                request.mask_mode,
                plan.region_frame,
            )
        t_tail = ttime.time() - t0

        print_debug(
            "RunFetch.get_plot_bundle",
            f"{request.ykey} shape={data.shape} tail={t_tail:.4f}s",
            category="plots",
        )

        info = self._source.describe(request.ykey)
        if info.synthetic and data.ndim == 1:
            data = data.rename({data.dims[0]: label or info.label})
        return PlotBundle.pack(
            data,
            is_roi_profile=request.region is not None,
            render_mode_hint=self._render_hint(request.ykey),
            label=label,
        )

    def _load_block(
        self, request: PlotRequest
    ) -> Tuple[xr.DataArray, List[xr.DataArray], FetchPlan]:
        """
        Return the block a request needs and its norms.

        Planning the fetch and asking for the block always happen together
        and in this order, so they are one call rather than three lines
        repeated at the call site. The plan comes back with the block because
        it is not free to make -- an ROI plan compiles the region against the
        parent plane -- and the mask stage needs the frame it produced.

        Whether a read happens is :class:`~.cache.BlockCache`'s business, not
        this method's.

        Parameters
        ----------
        request : PlotRequest
            Request being served.

        Returns
        -------
        tuple
            ``(data, norms, plan)``: the block narrowed to the plan, one norm
            array per ``plan.norm_keys`` in order, and the plan.
        """
        plan = request.plan(plane_frame=self._plane_frame(request))
        data, norms = self._source.block(plan)
        return data, norms, plan

    def _plane_frame(
        self, request: PlotRequest
    ) -> Optional[PlotViewFrame]:
        """
        Derive the display frame of the request's full plot plane.

        An ROI is geometry in data coordinates, so something has to say which
        cell each coordinate falls in. That is a pure function of the plane's
        shape, its two coordinate arrays and the render mode, all of which are
        1-D and cheap to read, so the frame is derived here rather than passed
        in from whichever bundle the canvas happened to have drawn.

        Parameters
        ----------
        request : PlotRequest
            Request whose ``view`` describes the plane.

        Returns
        -------
        PlotViewFrame or None
            Frame of the uncropped plane, or None when there is no region to
            compile against it.
        """
        if request.region is None:
            return None
        plane_axes = request.plane_axes
        if plane_axes is None:
            raise ValueError("cannot resolve the plot plane for an ROI fetch")
        row_axis, col_axis = plane_axes
        names = request.dims
        coords = self._source.load_coords(
            request.ykey, request.view.base_slice(), request.xkeys, dims=names
        )
        rows = np.atleast_1d(np.asarray(coords[names[row_axis]].values))
        cols = np.atleast_1d(np.asarray(coords[names[col_axis]].values))
        plane_shape = (int(rows.size), int(cols.size))
        render_mode = classify_render_mode(
            plane_shape,
            [rows, cols],
            render_mode_hint=self._render_hint(request.ykey),
        )
        row_reversed, col_reversed = display_flips(rows, cols, render_mode)
        return PlotBundle.from_2d(
            np.broadcast_to(np.float64(0.0), plane_shape),
            [
                rows[::-1] if row_reversed else rows,
                cols[::-1] if col_reversed else cols,
            ],
            [names[row_axis], names[col_axis]],
            render_mode_hint=render_mode,
            row_reversed=row_reversed,
            col_reversed=col_reversed,
        ).view_frame()

    def _render_hint(self, ykey: str) -> Optional[str]:
        """
        Return the declared render mode for a key, if any.

        It is on the description, which both sources fill in -- a frozen
        payload declares none. This used to read the key table and then fall
        back to the run's plot hints, which meant two sources of one answer
        that had to agree.

        Parameters
        ----------
        ykey : str
            Y data key.

        Returns
        -------
        str or None
            ``image`` or ``mesh`` from the key table or plot hints.
        """
        return self._source.describe(ykey).render_hint
