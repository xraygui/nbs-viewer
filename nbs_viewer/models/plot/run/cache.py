"""
The one block a run holds, and how a new plan is served from it.

Reading is the expensive stage and the only one that depends solely on the
fetch plan, so the block is held *as read* -- in storage order, unnormalized,
with every norm array read against it beside it. Editing a transform,
toggling a normalization already read, or moving an ROI inside a box already
read then re-runs arithmetic and no I/O.

The cache does not know what a run is. It is given a reader and asks it for
arrays; everything else here is window arithmetic over
:class:`~..spec.plan.FetchPlan` objects, which is why it can be tested
against a stub.
"""

from __future__ import annotations

import time as ttime
from typing import List, Optional, Sequence, Tuple

import xarray as xr

from ..spec.plan import FetchPlan
from ..spec.stages import slice_info_for_key
from nbs_viewer.utils import print_debug


class BlockCache:
    """
    Hold one loaded block for a run, and serve plans contained in it.

    Parameters
    ----------
    reader : object
        Whatever reads this run's keys. Four methods are required, and no
        more -- the contract is deliberately narrow enough to stub in a test:

        ``load(key, slice_info, *, xkeys, dims) -> xarray.DataArray``
            Read a key and label it, applying the X selection as
            coordinates under the given dimension names.
        ``read(key, slice_info) -> numpy.ndarray``
            Read a key's raw values, for a synthetic norm that carries no
            names of its own.
        ``describe(key) -> KeyInfo``
            Only ``.synthetic`` is consulted, to choose between the two.
        ``plot_axis_names(key, xkeys) -> sequence of str``
            Dimension names a norm key loads under.

        In the application this is the ``RunSource``, which is the reader for
        its own key space; the cache is a collaborator it owns rather than a
        layer wrapped around it.
    """

    def __init__(self, reader) -> None:
        self._reader = reader
        # One loaded block: ``(plan, block as read, {norm key: norm array})``.
        # One entry, not a map of blocks: it covers the still-on-this-plane
        # case and it cannot grow past the norms toggled while it is held.
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

    def block(
        self, plan: FetchPlan
    ) -> Tuple[xr.DataArray, List[xr.DataArray]]:
        """
        Return the block a plan asks for and its norms, from memory or read.

        The cache holds the block *as read* and, beside it, every norm array
        read against it. It used to hold the normalized block, which put the
        norm keys into its identity, so toggling a normalization re-read the
        whole detector array. Now a norm costs one read of its own key the
        first time it is wanted and nothing after; the divide is re-run by
        the caller, which is arithmetic rather than I/O.

        Norms are read against the *held* block rather than the narrowed one,
        so everything in the entry lines up, and all of it is narrowed by the
        same window on the way out.

        Parameters
        ----------
        plan : FetchPlan
            What to read and which indices of it. It carries the keys and the
            dimension names as well as the window, so it is the whole cache
            key and names its own axes.

        Returns
        -------
        tuple
            ``(data, norms)``: the block narrowed to the plan, and one norm
            array per ``plan.norm_keys`` in order.
        """
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
        )

    def _held_windows(
        self, plan: FetchPlan
    ) -> Optional[List[Optional[Tuple[int, Optional[int]]]]]:
        """
        Locate a plan inside the held block, if it is there.

        Parameters
        ----------
        plan : FetchPlan
            Plan the caller is about to execute.

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
        data = self._reader.load(
            ykey, slice_info, xkeys=plan.xkeys, dims=plan.dims
        ).astype(float, copy=False)
        t_load = ttime.time() - t0

        print_debug(
            "BlockCache._read_block",
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
        if self._reader.describe(norm_key).synthetic:
            values = self._reader.read(norm_key, plan.slice_info)
            return xr.DataArray(values, dims=list(data.dims[: values.ndim]))
        xkeys = list(plan.xkeys)
        norm_names = self._reader.plot_axis_names(norm_key, xkeys)
        key_slice = slice_info_for_key(plan.slice_info, plan.dims, norm_names)
        return self._reader.load(
            norm_key, key_slice, xkeys=xkeys, dims=norm_names
        )
