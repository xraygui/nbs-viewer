"""
Fetch for one run: from a plot request to a plot bundle.

``RunSource`` is the union of a catalog run and its frozen synthetic keys
under one key space. Turning a request into a bundle is a different job --
plan the load, hold the block, normalize, reduce, transform, mask, pack --
and it reaches the source through ``load``, ``load_coords``, ``read``,
``describe`` and ``plot_axis_names`` only. It lived on ``RunSource``
as nine methods, about half the class, and was the only user of every
plot-layer module that class imported.

``RunSource`` owns one :class:`RunFetch` and hands it out as ``fetch``, so
callers ask it directly rather than through a forwarding method. It also
clears the block cache directly -- before it announces a data change, since
traces refetch on that signal.
"""

from __future__ import annotations

import time as ttime
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

import numpy as np
import xarray as xr

from ..fetch.stages import (
    apply_normalization,
    apply_transform,
    mask_to_profile,
    reduce_before_mask,
    reduce_cached_plane,
    reduce_to_plane,
    slice_info_for_key,
)
from ..geometry import (
    PlotBundle,
    PlotViewFrame,
    build_plot_bundle,
    classify_render_mode,
    display_flips,
    frame_for_plane,
)
from ..fetch.request import PlotRequest
from ..fetch.plan import FetchPlan, plan_fetch
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
        # One loaded block, kept so a transform edit, a norm toggle, or an
        # ROI moved inside a box already read re-runs only the tail of the
        # pipeline: ``(plan, block as read, {norm key: norm array})``. One
        # entry, not a map of blocks: it covers the still-on-this-plane case
        # and it cannot grow past the norms toggled while it is held.
        self._block: Optional[Tuple] = None

    def clear(self) -> None:
        """
        Drop the held block and its norms.

        Called by the owning ``RunSource``, directly and before it emits
        ``data_changed``: traces refetch on that signal, so a cache that
        cleared itself by listening to it would depend on being connected
        first.
        """
        self._block = None

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
            return reduce_cached_plane(plane, request, label=label)

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
            # mask. The profile axis is read in full by plan_fetch. The
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
            f"{request.ykey} shape={data.shape} "
            f"cached={self._block is not None} tail={t_tail:.4f}s",
            category="plots",
        )

        info = self._source.describe(request.ykey)
        if info.synthetic and data.ndim == 1:
            data = data.rename({data.dims[0]: label or info.label})
        return build_plot_bundle(
            data,
            request,
            render_mode_hint=self._render_hint(request.ykey),
            label=label,
        )

    def _load_block(
        self, request: PlotRequest
    ) -> Tuple[xr.DataArray, List[xr.DataArray], FetchPlan]:
        """
        Return the block a request needs and its norms, from memory or read.

        The one accessor. Planning the fetch, asking the cache and reading are
        three steps that always happen together and in this order, so they are
        one call rather than four lines repeated at the call site. The plan
        comes back with the block because it is not free to make -- an ROI
        plan compiles the region against the parent plane -- and the mask
        stage needs the frame it produced.

        The cache holds the block *as read* and, beside it, every norm array
        read against it. It used to hold the normalized block, which put the
        norm keys into its identity, so toggling a normalization re-read the
        whole detector array. Now a norm costs one read of its own key the
        first time it is wanted and nothing after; the divide is re-run by the
        caller, which is arithmetic rather than I/O.

        Norms are read against the *held* block rather than the narrowed one,
        so everything in the entry lines up, and all of it is narrowed by the
        same window on the way out.

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
        plan = plan_fetch(request, plane_frame=self._plane_frame(request))
        windows = self._held_windows(plan)
        if windows is None:
            self._block = (plan, self._read_block(plan), {})
            windows = [None] * len(plan.slice_info)
        held_plan, block, norms = self._block
        for norm_key in plan.norm_keys:
            if norm_key not in norms:
                norms[norm_key] = self._norm_array(held_plan, norm_key, block)
        return (
            self._narrowed(block, plan.dims, windows),
            [
                self._narrowed(norms[norm_key], plan.dims, windows)
                for norm_key in plan.norm_keys
            ],
            plan,
        )

    def _held_windows(
        self, plan: FetchPlan
    ) -> Optional[List[Optional[Tuple[int, Optional[int]]]]]:
        """
        Locate a plan inside the held block, if it is there.

        Parameters
        ----------
        plan : FetchPlan
            Plan the caller is about to execute. It carries the keys and the
            dimension names as well as the window, so it is the whole cache
            key and names its own axes.

        Returns
        -------
        list or None
            Per-storage-axis windows into the held block, as from
            :meth:`_contained_window`, or None when a read is needed.
        """
        if self._block is None:
            return None
        held_plan = self._block[0]
        if not held_plan.reads_the_same(plan):
            return None
        return self._contained_window(held_plan.slice_info, plan.slice_info)

    @staticmethod
    def _contained_window(
        cached: Sequence, wanted: Sequence
    ) -> Optional[List[Optional[Tuple[int, Optional[int]]]]]:
        """
        Locate a wanted load inside one already performed.

        The containment half of the fetch comparison: shrinking a crop, or
        moving an ROI inside a box already read, asks for a sub-block of what
        is in memory and needs no round trip.

        Parameters
        ----------
        cached : sequence
            Per-storage-axis load items of the block held.
        wanted : sequence
            Per-storage-axis load items now wanted.

        Returns
        -------
        list or None
            None when the wanted load is not contained. Otherwise one entry
            per storage axis: None for an axis needing no narrowing, else
            ``(start, stop)`` offsets into the cached block, ``stop`` None
            meaning "to the end".
        """
        if len(cached) != len(wanted):
            return None
        windows: List[Optional[Tuple[int, Optional[int]]]] = []
        for have, want in zip(cached, wanted):
            if isinstance(have, int) or isinstance(want, int):
                if have != want:
                    return None
                windows.append(None)
                continue
            have_start = 0 if have.start is None else int(have.start)
            have_stop = None if have.stop is None else int(have.stop)
            want_start = 0 if want.start is None else int(want.start)
            want_stop = None if want.stop is None else int(want.stop)
            if want_start < have_start:
                return None
            if have_stop is not None and (
                want_stop is None or want_stop > have_stop
            ):
                return None
            if want_start == have_start and want_stop == have_stop:
                windows.append(None)
                continue
            windows.append(
                (
                    want_start - have_start,
                    None if want_stop is None else want_stop - have_start,
                )
            )
        return windows

    @staticmethod
    def _narrowed(
        array: xr.DataArray,
        dims: Sequence[str],
        windows: Sequence[Optional[Tuple[int, Optional[int]]]],
    ) -> xr.DataArray:
        """
        Take a window out of a held array, by dimension name.

        Applied to the block and to each held norm alike. A norm shares the
        block's names on the axes it has and was read against the same
        slice there, so the same window is the right one; an axis it lacks
        is skipped.

        Parameters
        ----------
        array : xarray.DataArray
            Held block or norm array.
        dims : sequence of str
            Dimension name per storage axis of the block.
        windows : sequence
            Per-storage-axis windows, None where nothing narrows.

        Returns
        -------
        xarray.DataArray
            The narrowed array.
        """
        for storage_axis, window in enumerate(windows):
            if window is None:
                continue
            dim = dims[storage_axis]
            if dim not in array.dims:
                continue
            start, stop = window
            stop = array.sizes[dim] if stop is None else stop
            # A plain window, because the block is in storage order. It used
            # to need mirroring on any axis the load had flipped.
            array = array.isel({dim: slice(start, stop)})
        return array

    def _read_block(self, plan: FetchPlan) -> xr.DataArray:
        """
        Read and label the block a plan asks for.

        The stage that depends only on the fetch plan, so that the ones that
        do not -- normalize, reduce, transform, mask -- can be re-run without
        a read. Values become floating point here, once, because the block is
        held and reused and everything downstream divides or sums it.

        This is the boundary where storage axis indices stop: everything it
        returns is addressed by dimension name. It is *not* where display
        order begins -- the block stays in the order the source stored it, and
        the flip that puts a plane the right way up for ``imshow`` happens
        once, at the pack.

        The X selection is applied by the load, as a coordinate, under the
        names the plan carries: the axis named after the X key carries that
        key's values. That used to be a second call beside the read, which
        re-ran the dimension analysis to produce coordinates and names, and
        dropped the names.

        Parameters
        ----------
        plan : FetchPlan
            What to read, which indices of it, and the name of each axis.

        Returns
        -------
        xarray.DataArray
            Labelled block, as read and not normalized.
        """
        slice_info = plan.slice_info
        ykey = plan.ykey

        t0 = ttime.time()
        data = self._source.load(
            ykey, slice_info, xkeys=plan.xkeys, dims=plan.dims
        ).astype(float, copy=False)
        t_load = ttime.time() - t0

        print_debug(
            "RunFetch._read_block",
            f"{ykey} shape={data.shape} load={t_load:.4f}s",
            category="plots",
        )
        return data

    def _norm_array(
        self, plan: FetchPlan, norm_key: str, data: xr.DataArray
    ) -> xr.DataArray:
        """
        Read one normalization key, labelled to match a block.

        Normalization runs on the whole block, before any SUM or MEAN,
        because that is the physically right order: a flat field divides per
        pixel and only then is summed.

        A catalog norm shares axis *names* with the block, so it takes the
        block's slice on the axes it has, and it arrives **with its own
        coordinates**. That is the guard the whole representation was chosen
        for: under ``arithmetic_join="exact"`` the divide either lines up on
        coordinate values or raises, where matching by name and shape alone
        would divide one detector into another at mismatched positions and
        give a plausible wrong answer. It is only possible because nothing in
        the pipeline is flipped any more -- a reversed coordinate does not
        compare equal to the source's, so this used to fire on correct data.

        A frozen synthetic norm shares no name with anything: it is a
        per-event
        quantity that took the block's own slice, so its axes correspond in
        order to the block's leading axes and are named after them. Without
        that renaming xarray would broadcast it into a *new* dimension instead
        of dividing element by element -- the hand-written aligner this
        replaced fell back to matching by shape, which is the same rule stated
        as a coincidence. It gets **no** coordinates: its axes are whatever
        the reduction produced and stored, not the block's, so it is the one
        norm still aligned by position alone.

        Parameters
        ----------
        plan : FetchPlan
            Plan of the block the norm has to line up with: its load slices,
            their names, and the X selection.
        norm_key : str
            Normalization key to read.
        data : xarray.DataArray
            That block, for its dimension names.

        Returns
        -------
        xarray.DataArray
            The labelled norm array.
        """
        if self._source.describe(norm_key).synthetic:
            values = self._source.read(norm_key, plan.slice_info)
            return xr.DataArray(values, dims=list(data.dims[: values.ndim]))
        xkeys = list(plan.xkeys)
        norm_names = self._source.plot_axis_names(norm_key, xkeys)
        key_slice = slice_info_for_key(plan.slice_info, plan.dims, norm_names)
        return self._source.load(
            norm_key, key_slice, xkeys=xkeys, dims=norm_names
        )

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
        return frame_for_plane(
            plane_shape,
            rows[::-1] if row_reversed else rows,
            cols[::-1] if col_reversed else cols,
            [names[row_axis], names[col_axis]],
            render_mode_hint=render_mode,
            row_reversed=row_reversed,
            col_reversed=col_reversed,
        )

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
