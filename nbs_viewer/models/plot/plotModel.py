"""
Plot session model bound to a run list.

Owns selected keys, transform, retain-selection, cube/slice/crop view state,
the ``PlotDataModel`` map, and the ROI set. Subscribes to the bound
``RunListModel`` for membership, visibility, and available-key changes.

Run-list protocol
-----------------
* ``run_removed`` — drop all plot-data entries for that uid.
* ``visible_runs_changed`` — keep plot-data on uncheck; emit
  ``request_plot_update`` so views plot only visible runs; ensure plot-data
  for newly visible runs when keys are selected.
* ``available_keys_changed`` — filter this plot's selected keys (honor
  retain-selection when the universe is empty).
* ``run_added`` — apply transform and current key selection to the new run;
  apply default selection when this is the first run and retain is off.

``RunModel.set_selected_keys`` is still synced from this model as a temporary
compatibility bridge for callers that read per-run selection (e.g. freeze).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from qtpy.QtCore import QObject, Signal

from nbs_viewer.utils import print_debug

from .cube_view import (
    _fetch_plot_plane_storage_axes,
    classify_profile_kind,
    default_profile_label,
    is_plot_plane_storage_axis,
    scan_profile_storage_axis,
)
from .derived_fetch import _profile_uses_nd_load, build_roi_profile_request_from_operation
from .plotDataModel import PlotDataModel
from .plot_request import TraceKey, build_plot_request
from .plot_view_frame import (
    PlotViewFrame,
    frame_from_bundle,
    view_fingerprint_from_bundle,
)
from .region import RectRegion, RegionDefinition, expand_region_for_profile
from .roi_set import RoiEntry, RoiSetModel
from .view_crop import ViewCrop, view_crop_from_region

if TYPE_CHECKING:
    from .cube_view import CubeViewSpec, MaterializeRequest
    from .frozen_spectrum import FrozenSpectrum
    from .plot_geometry import PlotBundle
    from .runListModel import RunListModel
    from .runModel import RunModel


class PlotModel(QObject):
    """
    One plot session associated with a :class:`RunListModel`.

    Parameters
    ----------
    run_list_model : RunListModel
        Run collection and visibility source for this plot.
    parent : QObject, optional
        Qt parent.
    """

    selected_keys_changed = Signal(list, list, list)
    transform_changed = Signal(dict)
    request_plot_update = Signal()
    cube_view_changed = Signal(object)
    view_crop_changed = Signal(object)
    region_status_changed = Signal(str)
    region_invalidation_requested = Signal(str)
    roi_draw_enabled_changed = Signal(bool)
    ellipse_circle_locked_changed = Signal(bool)
    roi_live_region_sync_requested = Signal()
    plot_data_added = Signal(object)

    def __init__(self, run_list_model: "RunListModel", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._run_list_model = run_list_model
        self._roi_set = RoiSetModel(parent=self)

        self._current_x_keys: List[str] = []
        self._current_y_keys: List[str] = []
        self._current_norm_keys: List[str] = []
        self._retain_selection = False
        self._transform = {"enabled": False, "text": ""}

        self._dimension = 1
        self._slice = None
        self._cube_view_spec = None
        self._view_crop: Optional[ViewCrop] = None
        self._roi_draw_enabled = False
        self._ellipse_circle_locked = False

        self._plot_data: Dict[TraceKey, PlotDataModel] = {}
        self._connected_run_uids = set()

        self._run_list_model.run_added.connect(self._on_run_added)
        self._run_list_model.run_removed.connect(self._on_run_removed)
        self._run_list_model.visible_runs_changed.connect(
            self._on_visible_runs_changed
        )
        self._run_list_model.available_keys_changed.connect(
            self._on_available_keys_changed
        )
        self.cube_view_changed.connect(self._on_cube_view_changed_for_region)
        self.selected_keys_changed.connect(self._on_selected_keys_changed_for_region)

        for run_model in self._run_list_model.available_models:
            self._attach_run_model(run_model)

    @property
    def run_list_model(self) -> "RunListModel":
        """
        Return the bound run list model.
        """
        return self._run_list_model

    @property
    def roi_set(self) -> RoiSetModel:
        """
        Return the ROI set owned by this plot session.
        """
        return self._roi_set

    @property
    def plot_data_map(self) -> Dict[TraceKey, PlotDataModel]:
        """
        Return the live map of plot-data models keyed by :class:`TraceKey`.
        """
        return self._plot_data

    @property
    def retain_selection(self) -> bool:
        """
        Whether to keep selected keys when the available-key universe empties.
        """
        return self._retain_selection

    def set_retain_selection(self, enabled: bool) -> None:
        """
        Set whether to retain key selection when available keys clear.

        Parameters
        ----------
        enabled : bool
            Retain selection when True.
        """
        self._retain_selection = enabled

    @property
    def transform(self) -> dict:
        """
        Current transform state with defaults.
        """
        return {**{"enabled": False, "text": ""}, **self._transform}

    def set_transform(self, transform_state: dict) -> None:
        """
        Set transform state and apply it to all run models.

        Parameters
        ----------
        transform_state : dict
            Transform configuration with ``enabled`` and ``text``.
        """
        self._transform = transform_state.copy()
        for model in self._run_list_model.available_models:
            model.set_transform(self._transform)
        self.transform_changed.emit(self.transform)
        self._sync_plot_data_requests()
        print_debug(
            "PlotModel.set_transform",
            "applied (artist bus via transform_changed)",
            category="plots",
        )

    @property
    def selected_keys(self) -> tuple:
        """
        Return current ``(x_keys, y_keys, norm_keys)`` copies.
        """
        return (
            self._current_x_keys.copy(),
            self._current_y_keys.copy(),
            self._current_norm_keys.copy(),
        )

    def get_selected_keys(self):
        """
        Return current selected x, y, and norm keys.
        """
        return self._current_x_keys, self._current_y_keys, self._current_norm_keys

    def is_key_selected(self, key: str, axis: str) -> bool:
        """
        Return whether a key is selected for an axis.

        Parameters
        ----------
        key : str
            Data key.
        axis : str
            One of ``'x'``, ``'y'``, or ``'norm'``.
        """
        if axis == "x":
            return key in self._current_x_keys
        if axis == "y":
            return key in self._current_y_keys
        if axis == "norm":
            return key in self._current_norm_keys
        return False

    def set_selected_keys(
        self,
        x_keys: List[str],
        y_keys: List[str],
        norm_keys: Optional[List[str]] = None,
        force_update: bool = False,
    ) -> None:
        """
        Set key selection for this plot session.

        Temporarily syncs the same selection onto every ``RunModel`` in the
        bound list for compatibility with freeze and similar callers.

        Parameters
        ----------
        x_keys : list of str
            X-axis keys.
        y_keys : list of str
            Y-axis keys.
        norm_keys : list of str, optional
            Normalization keys.
        force_update : bool, optional
            Accepted for API compatibility; plot refresh is always requested.
        """
        self._current_x_keys = list(x_keys)
        self._current_y_keys = list(y_keys)
        self._current_norm_keys = list(norm_keys or [])

        for model in self._run_list_model.available_models:
            model.set_selected_keys(
                self._current_x_keys,
                self._current_y_keys,
                self._current_norm_keys,
                force_update=False,
            )

        self._ensure_plot_data_for_visible()
        self.selected_keys_changed.emit(
            self._current_x_keys, self._current_y_keys, self._current_norm_keys
        )
        print_debug(
            "PlotModel.set_selected_keys",
            f"request_plot_update x={x_keys} y={y_keys} norm={norm_keys}",
            category="plots",
        )
        self.request_plot_update.emit()

    @property
    def dimension(self) -> int:
        """
        Plot dimensionality (1 or 2).
        """
        return self._dimension

    @property
    def slice(self):
        """
        Current load slice info.
        """
        return self._slice

    @property
    def cube_view_spec(self):
        """
        Current cube view specification, if any.
        """
        return self._cube_view_spec

    def set_view_state(
        self,
        indices=None,
        dimension: Optional[int] = None,
        cube_view_spec: Optional["CubeViewSpec"] = None,
    ) -> None:
        """
        Update slice, plot dimension, and cube view specification.

        Parameters
        ----------
        indices : optional
            Load slice info.
        dimension : int, optional
            Plot dimensionality.
        cube_view_spec : CubeViewSpec, optional
            N-D view specification.
        """
        changed = False
        if dimension is not None and dimension != self._dimension:
            self._dimension = dimension
            changed = True
            if dimension != 2:
                self.invalidate_all_region_state("switched out of 2D mode")
        if indices != self._slice:
            self._slice = indices
            changed = True
        if cube_view_spec != self._cube_view_spec:
            self._cube_view_spec = cube_view_spec
            changed = True
            self.cube_view_changed.emit(self._cube_view_spec)

        if changed:
            self._sync_plot_data_requests()
            self.request_plot_update.emit()

    @property
    def view_crop(self) -> Optional[ViewCrop]:
        """
        Active persistent view crop, if any.
        """
        return self._view_crop

    def set_view_crop(self, crop: Optional[ViewCrop]) -> None:
        """
        Set or clear the persistent view crop.

        Parameters
        ----------
        crop : ViewCrop or None
            Crop to apply, or ``None`` to clear.
        """
        self._view_crop = crop
        self.view_crop_changed.emit(crop)
        self._sync_plot_data_requests()
        self.request_plot_update.emit()

    def clear_view_crop(self) -> None:
        """
        Clear the persistent view crop when one is set.
        """
        if self._view_crop is None:
            return
        self.set_view_crop(None)

    def apply_view_crop_from_region(
        self,
        region: RegionDefinition,
        *,
        plot_data: Optional[PlotDataModel] = None,
    ) -> ViewCrop:
        """
        Commit a drawn rectangle to the persistent view crop.

        Parameters
        ----------
        region : RegionDefinition
            Crop rectangle in matplotlib data coordinates on the oriented plot
            plane. Only :class:`RectRegion` is supported.
        plot_data : PlotDataModel, optional
            Parent 2D plot-data model. Defaults to the sole visible 2D model.

        Returns
        -------
        ViewCrop
            Applied crop state.

        Raises
        ------
        ValueError
            If the region is invalid or crop context cannot be resolved.
        """
        if self._view_crop is not None:
            raise ValueError("Clear the current crop before applying a new one")
        if not isinstance(region, RectRegion):
            raise ValueError("Crop region must be a rectangle")
        region = region.normalized()
        width = region.x1 - region.x0
        height = region.y1 - region.y0
        if width == 0.0 or height == 0.0:
            raise ValueError("Crop region has zero width or height")

        plot_data = plot_data or self.resolve_single_visible_2d_plot_data()
        if plot_data is None:
            raise ValueError("Select a single 2D dataset")
        parent_spec = self._cube_view_spec
        if parent_spec is None:
            raise ValueError("Select a single 2D dataset")

        full_frame = self._resolve_full_view_frame_for_crop(plot_data)
        slice_info = parent_spec.to_load_slice_info()
        xlist, _names, _extra = plot_data._run.get_dimension_axes(
            plot_data._ykey,
            [plot_data._xkey],
            slice_info,
        )
        plot_y_axis, plot_x_axis = _fetch_plot_plane_storage_axes(
            parent_spec,
            full_frame,
            parent_spec,
        )
        crop = view_crop_from_region(
            region,
            full_frame,
            parent_spec,
            plot_data._key,
            xlist[plot_y_axis],
            xlist[plot_x_axis],
        )
        self.set_view_crop(crop)
        return crop

    def invalidate_view_crop_if_invalid(self) -> Optional[str]:
        """
        Clear the view crop when the current plot context no longer matches it.

        Returns
        -------
        str or None
            Reason the crop was cleared, or ``None`` if the crop remains valid.
        """
        crop = self._view_crop
        if crop is None:
            return None
        plot_data = self.resolve_single_visible_2d_plot_data()
        if plot_data is None or plot_data._key != crop.source_key:
            self.clear_view_crop()
            return "dataset changed"
        parent_spec = self._cube_view_spec
        if parent_spec is None:
            self.clear_view_crop()
            return "view no longer available"
        try:
            plot_y_axis, plot_x_axis = _fetch_plot_plane_storage_axes(
                parent_spec,
                crop.full_frame,
                parent_spec,
            )
        except ValueError:
            self.clear_view_crop()
            return "plot axes changed"
        if (
            plot_y_axis != crop.plot_y_axis
            or plot_x_axis != crop.plot_x_axis
        ):
            self.clear_view_crop()
            return "plot axes changed"
        return None

    def resolve_current_view_fingerprint(self) -> Optional[tuple]:
        """
        Return a fingerprint for the sole visible 2D plot coordinate frame.

        Returns
        -------
        tuple or None
            View fingerprint from the active plot bundle, if available.
        """
        plot_data = self.resolve_single_visible_2d_plot_data()
        if plot_data is None or plot_data.last_bundle is None:
            return None
        try:
            return view_fingerprint_from_bundle(plot_data.last_bundle)
        except ValueError:
            return None

    def sync_region_state_with_view(self) -> None:
        """
        Mark stale ROIs and clear invalid crops for the current plot view.
        """
        if len(self._roi_set) > 0:
            fingerprint = self.resolve_current_view_fingerprint()
            newly_stale = self._roi_set.mark_stale_for_fingerprint(fingerprint)
            if newly_stale:
                self.region_status_changed.emit(
                    "ROI marked stale: view coordinates changed"
                )
        crop_reason = self.invalidate_view_crop_if_invalid()
        if crop_reason is not None:
            self.region_status_changed.emit(f"Crop cleared: {crop_reason}")

    def invalidate_all_region_state(self, reason: str) -> None:
        """
        Force-clear crop and mark all ROIs stale after a view-context change.

        Parameters
        ----------
        reason : str
            Short description emitted to views for status readouts.
        """
        had_crop = self._view_crop is not None
        if had_crop:
            self.clear_view_crop()

        had_rois = len(self._roi_set) > 0
        if had_rois:
            self._roi_set.mark_stale_for_fingerprint(None)

        self.region_invalidation_requested.emit(reason)

        if had_crop:
            self.region_status_changed.emit(f"Crop cleared: {reason}")
        if had_rois and self._view_crop is None:
            self.region_status_changed.emit(f"ROI marked stale: {reason}")

    def _on_cube_view_changed_for_region(self, _spec) -> None:
        self.sync_region_state_with_view()

    def _on_selected_keys_changed_for_region(
        self,
        _xkeys,
        _ykeys,
        _normkeys,
    ) -> None:
        self.invalidate_all_region_state("field selection changed")

    def _resolve_full_view_frame_for_crop(
        self,
        plot_data: PlotDataModel,
    ) -> PlotViewFrame:
        """
        Return the full oriented plot-plane frame used to commit a view crop.

        Parameters
        ----------
        plot_data : PlotDataModel
            Parent 2D plot-data model for the crop.

        Returns
        -------
        PlotViewFrame
            Full plane before crop is applied.

        Raises
        ------
        ValueError
            If no suitable 2D bundle is available.
        """
        if self._view_crop is not None:
            return self._view_crop.full_frame
        bundle = plot_data.last_bundle
        if bundle is None or bundle.ndim != 2:
            raise ValueError("Select a single 2D dataset")
        return frame_from_bundle(bundle)

    def _effective_transform_text(self, run_model: "RunModel") -> str:
        """
        Return the effective transform expression for a run.

        Parameters
        ----------
        run_model : RunModel
            Run whose transform state is read.

        Returns
        -------
        str
            Transform text when enabled on the run, otherwise empty.
        """
        return getattr(run_model, "_transform_text", "") or ""

    def _crop_for_trace(self, trace_key: TraceKey):
        """
        Return the session crop if it applies to this trace.

        Parameters
        ----------
        trace_key : TraceKey
            Trace to match against crop ``source_key``.

        Returns
        -------
        ViewCrop or None
            Active crop when it names this trace, otherwise None.
        """
        crop = self._view_crop
        if crop is None:
            return None
        if crop.source_key != trace_key.as_tuple():
            return None
        return crop

    def _build_plot_request(
        self,
        run_model: "RunModel",
        xkey: str,
        ykey: str,
        norm_keys: Optional[List[str]] = None,
    ):
        """
        Assemble a :class:`PlotRequest` from session view state.

        Parameters
        ----------
        run_model : RunModel
            Source run.
        xkey : str
            X key.
        ykey : str
            Y key.
        norm_keys : list of str, optional
            Normalization keys.

        Returns
        -------
        PlotRequest
            Frozen request for this trace.
        """
        trace_key = TraceKey(run_model.uid, xkey, ykey)
        return build_plot_request(
            uid=run_model.uid,
            xkeys=[xkey] if xkey else (),
            ykey=ykey,
            shape=run_model.get_shape(ykey),
            norm_keys=norm_keys,
            plot_ndim=self._dimension,
            cube_view_spec=self._cube_view_spec,
            slice_info=self._slice,
            crop=self._crop_for_trace(trace_key),
            transform=self._effective_transform_text(run_model),
        )

    def _sync_plot_data_requests(self) -> None:
        """
        Rewrite held requests from current session view without replacing models.
        """
        for key, plot_data in self._plot_data.items():
            request = self._build_plot_request(
                plot_data._run,
                key.xkey,
                key.ykey,
                plot_data._norm_keys,
            )
            plot_data.set_request(request)

    def ensure_plot_data(
        self,
        run_model: "RunModel",
        xkey: str,
        ykey: str,
        norm_keys: Optional[List[str]] = None,
    ) -> PlotDataModel:
        """
        Return the plot-data model for ``(xkey, ykey, run uid)``, creating it.

        Assembles a :class:`PlotRequest` from session slice / cube / crop and
        stores it on the model. Existing models keep their artist.

        Parameters
        ----------
        run_model : RunModel
            Source run.
        xkey : str
            X key.
        ykey : str
            Y key.
        norm_keys : list of str, optional
            Normalization keys.

        Returns
        -------
        PlotDataModel
            Existing or newly created plot-data model.
        """
        key = TraceKey(run_model.uid, xkey, ykey)
        request = self._build_plot_request(run_model, xkey, ykey, norm_keys)
        if key not in self._plot_data:
            plot_data = PlotDataModel(
                run_model,
                request,
                parent=self,
                trace_key=key,
            )
            self._plot_data[key] = plot_data
            self.plot_data_added.emit(plot_data)
            print_debug(
                "PlotModel.ensure_plot_data",
                f"create {xkey}/{ykey}",
                category="plots",
            )
        else:
            self._plot_data[key].set_request(request)
        return self._plot_data[key]

    def drop_plot_data_for_uid(self, uid: str) -> None:
        """
        Remove and clean up all plot-data entries for a run uid.

        Parameters
        ----------
        uid : str
            Run uid whose plot-data entries should be dropped.
        """
        keys = [key for key in self._plot_data if key.uid == uid]
        for key in keys:
            plot_data = self._plot_data.pop(key)
            try:
                plot_data.clear()
            except Exception:
                pass

    def iter_visible_plot_data(self):
        """
        Yield plot-data models whose run uid is currently visible.
        """
        visible = self._run_list_model.visible_runs
        for key, plot_data in self._plot_data.items():
            if key.uid in visible:
                yield plot_data

    def resolve_single_visible_2d_plot_data(self) -> Optional[PlotDataModel]:
        """
        Return the sole visible 2D plot-data model, if exactly one exists.

        Uses cached render mode or ``last_bundle`` dimensionality. When neither
        is available, falls back to ``dimension == 2``.

        Returns
        -------
        PlotDataModel or None
        """
        models = []
        for plot_data in self.iter_visible_plot_data():
            if not getattr(plot_data, "_visible", True):
                continue
            render_mode = plot_data.render_mode
            if render_mode in ("image", "mesh"):
                models.append(plot_data)
                continue
            bundle = plot_data.last_bundle
            if bundle is not None and bundle.ndim == 2:
                models.append(plot_data)
                continue
            if plot_data._dimension == 2 and render_mode is None and bundle is None:
                models.append(plot_data)
        if len(models) == 1:
            return models[0]
        return None

    def is_roi_draw_enabled(self) -> bool:
        """
        Return whether interactive ROI drawing is requested on the parent plot.
        """
        return self._roi_draw_enabled

    def set_roi_draw_enabled(self, enabled: bool) -> None:
        """
        Request interactive ROI drawing on the parent plot view.

        Parameters
        ----------
        enabled : bool
            True to enable ROI drawing.
        """
        enabled = bool(enabled)
        if enabled == self._roi_draw_enabled:
            return
        self._roi_draw_enabled = enabled
        self.roi_draw_enabled_changed.emit(enabled)

    def is_ellipse_circle_locked(self) -> bool:
        """
        Return whether ellipse ROI drawing is locked to a circle.
        """
        return self._ellipse_circle_locked

    def set_ellipse_circle_locked(self, locked: bool) -> None:
        """
        Request circle-locked ellipse ROI drawing on the parent plot.

        Parameters
        ----------
        locked : bool
            True to lock ellipse drawing to a circle.
        """
        locked = bool(locked)
        if locked == self._ellipse_circle_locked:
            return
        self._ellipse_circle_locked = locked
        self.ellipse_circle_locked_changed.emit(locked)

    def request_roi_live_region_sync(self) -> None:
        """
        Ask the parent plot view to commit any in-progress ROI draw geometry.
        """
        self.roi_live_region_sync_requested.emit()

    def resolve_parent_frame(
        self,
        plot_data: Optional[PlotDataModel] = None,
    ) -> Optional[PlotViewFrame]:
        """
        Return the view frame for the visible 2D plot-data model.

        Parameters
        ----------
        plot_data : PlotDataModel, optional
            Plot-data model. Defaults to the sole visible 2D model.

        Returns
        -------
        PlotViewFrame or None
        """
        plot_data = plot_data or self.resolve_single_visible_2d_plot_data()
        if plot_data is None or plot_data.last_bundle is None:
            return None
        try:
            return frame_from_bundle(plot_data.last_bundle)
        except ValueError:
            return None

    def cached_parent_bundle_for_preview(
        self,
        plot_data: PlotDataModel,
        request: Optional["MaterializeRequest"] = None,
    ) -> Optional["PlotBundle"]:
        """
        Return a cached parent bundle when it still matches the plot session.

        Parameters
        ----------
        plot_data : PlotDataModel
            Parent plot-data model.
        request : MaterializeRequest, optional
            Preview request. ND loads skip the parent-bundle cache.

        Returns
        -------
        PlotBundle or None
        """
        if plot_data.last_bundle is None:
            return None
        session_request = self._build_plot_request(
            plot_data._run,
            plot_data._xkey,
            plot_data._ykey,
            plot_data._norm_keys,
        )
        if plot_data.request.view != session_request.view:
            return None
        if request is not None and _profile_uses_nd_load(request, self._cube_view_spec):
            return None
        return plot_data.last_bundle

    def apply_roi_region_to_selected(self, region: RegionDefinition) -> None:
        """
        Update the selected ROI geometry from a region in data coordinates.

        Parameters
        ----------
        region : RegionDefinition
            ROI geometry on the oriented plot plane.

        Raises
        ------
        ValueError
            If no ROI is selected.
        """
        entry = self._roi_set.selected_entry()
        if entry is None:
            raise ValueError("Select an ROI")
        if hasattr(region, "normalized"):
            region = region.normalized()
        self._roi_set.update_region(
            entry.id,
            region,
            view_fingerprint=self.resolve_current_view_fingerprint(),
            clear_stale=True,
        )

    def apply_expanded_roi_profile_span(self, profile_axis: str) -> None:
        """
        Expand the selected ROI along a plot axis for span-full profile actions.

        Parameters
        ----------
        profile_axis : str
            ``plot_x`` or ``plot_y``.

        Raises
        ------
        ValueError
            If the ROI or parent view frame is unavailable.
        """
        entry = self._roi_set.selected_entry()
        if entry is None:
            raise ValueError("Select an ROI")
        region = entry.region
        if not region.has_area():
            raise ValueError("Draw an ROI on the parent plot first")
        frame = self.resolve_parent_frame()
        if frame is None:
            raise ValueError("Select a single 2D dataset")
        expanded = expand_region_for_profile(frame, region, profile_axis)
        self.apply_roi_region_to_selected(expanded)

    def resolve_roi_entry(self, entry_id: Optional[str] = None) -> RoiEntry:
        """
        Return a drawable, non-stale ROI entry.

        Parameters
        ----------
        entry_id : str, optional
            Entry id. Defaults to the current selection.

        Returns
        -------
        RoiEntry
            Validated ROI entry.

        Raises
        ------
        ValueError
            If the entry is missing, stale, or has no drawable area.
        """
        if entry_id is None:
            entry = self._roi_set.selected_entry()
        else:
            entry = self._roi_set.get(entry_id)
        if entry is None:
            raise ValueError("Select an ROI")
        if entry.stale:
            raise ValueError("Selected ROI is stale; redraw it before previewing")
        if not entry.region.has_area():
            raise ValueError("Draw the selected ROI on the parent plot")
        if isinstance(entry.region, RectRegion):
            region = entry.region.normalized()
            if region.x1 - region.x0 == 0.0 or region.y1 - region.y0 == 0.0:
                raise ValueError("ROI has zero width or height")
        return entry

    def build_roi_profile_request(
        self,
        entry: RoiEntry,
        *,
        parent_spec: Optional["CubeViewSpec"] = None,
        parent_frame=None,
        span_full_override: Optional[bool] = None,
        default_profile_axis=None,
    ) -> "MaterializeRequest":
        """
        Build a profile materialize request for an ROI entry.

        Parameters
        ----------
        entry : RoiEntry
            ROI geometry and operation.
        parent_spec : CubeViewSpec, optional
            Parent cube view. Defaults to this plot's cube view.
        parent_frame : PlotViewFrame, optional
            Parent view frame for span-full expansion.
        span_full_override : bool, optional
            Override the entry span-full flag.
        default_profile_axis : str or int, optional
            Profile axis when the entry does not set one.

        Returns
        -------
        MaterializeRequest
            Request for preview or commit.
        """
        spec = parent_spec if parent_spec is not None else self._cube_view_spec
        if spec is None:
            raise ValueError("Parent cube view is unavailable")
        return build_roi_profile_request_from_operation(
            spec,
            entry.region,
            entry.operation,
            parent_frame=parent_frame,
            span_full_override=span_full_override,
            default_profile_axis=default_profile_axis,
        )

    def _commit_span_full(
        self,
        parent_spec: "CubeViewSpec",
        profile_storage_axis: int,
        span_full: bool,
    ) -> bool:
        if classify_profile_kind(parent_spec, profile_storage_axis) != "stack_spectrum":
            return span_full
        if is_plot_plane_storage_axis(parent_spec, profile_storage_axis):
            return True
        return span_full

    def prepare_roi_commit(
        self,
        entry: RoiEntry,
        *,
        parent_spec: Optional["CubeViewSpec"] = None,
        parent_frame=None,
        axis_names=None,
        default_profile_axis=None,
    ) -> Tuple[bool, "MaterializeRequest"]:
        """
        Validate an ROI commit and build its materialize request.

        Parameters
        ----------
        entry : RoiEntry
            ROI entry to commit.
        parent_spec : CubeViewSpec, optional
            Parent cube view. Defaults to this plot's cube view.
        parent_frame : PlotViewFrame, optional
            Parent frame for request construction.
        axis_names : sequence of str, optional
            Axis names used in local-profile error hints.
        default_profile_axis : str or int, optional
            Fallback profile axis.

        Returns
        -------
        tuple
            ``(span_full, request)`` for the commit fetch.

        Raises
        ------
        ValueError
            If the ROI cannot be committed (missing view, local profile, etc.).
        """
        spec = parent_spec if parent_spec is not None else self._cube_view_spec
        if spec is None:
            raise ValueError("Parent cube view is unavailable")

        profile_axis = entry.operation.profile_storage_axis
        if profile_axis is None:
            profile_axis = default_profile_axis
        if profile_axis is None:
            raise ValueError("Profile axis is unavailable")
        profile_kind = classify_profile_kind(spec, profile_axis)
        if profile_kind == "local_profile":
            scan_axis = scan_profile_storage_axis(spec)
            names = tuple(axis_names or ())
            if scan_axis is not None and scan_axis < len(names):
                hint = names[scan_axis]
            else:
                hint = "the leading scan axis"
            raise ValueError(
                f"Select a profile along {hint} to save to Run Display"
            )

        span_full = self._commit_span_full(
            spec,
            profile_axis,
            entry.operation.span_full_profile_axis,
        )
        request = self.build_roi_profile_request(
            entry,
            parent_spec=spec,
            parent_frame=parent_frame,
            span_full_override=span_full,
            default_profile_axis=default_profile_axis,
        )
        return span_full, request

    def preview_roi_profile(
        self,
        entry_id: Optional[str] = None,
        *,
        entry: Optional[RoiEntry] = None,
        parent_plot_data: Optional[PlotDataModel] = None,
        parent_spec: Optional["CubeViewSpec"] = None,
        parent_frame=None,
        parent_bundle: Optional["PlotBundle"] = None,
        view_crop: Optional[ViewCrop] = None,
        span_full_override: Optional[bool] = None,
        default_profile_axis=None,
        request: Optional["MaterializeRequest"] = None,
    ) -> "PlotBundle":
        """
        Preview an ROI profile for an entry on the parent plot-data model.

        Parameters
        ----------
        entry_id : str, optional
            ROI entry id. Ignored when ``entry`` is provided.
        entry : RoiEntry, optional
            ROI entry. Defaults to resolving ``entry_id`` / selection.
        parent_plot_data : PlotDataModel, optional
            Parent 2D plot-data model. Defaults to the sole visible 2D model.
        parent_spec : CubeViewSpec, optional
            Parent cube view. Defaults to this plot's cube view.
        parent_frame : PlotViewFrame, optional
            Parent frame used when building the request.
        parent_bundle : PlotBundle, optional
            Cached parent 2D bundle.
        view_crop : ViewCrop, optional
            Active crop. Defaults to this plot's view crop.
        span_full_override : bool, optional
            Override span-full when building the request.
        default_profile_axis : str or int, optional
            Fallback profile axis.
        request : MaterializeRequest, optional
            Prebuilt request. When omitted, one is built from the entry.

        Returns
        -------
        PlotBundle
            1D ROI profile preview.
        """
        if entry is None:
            entry = self.resolve_roi_entry(entry_id)
        plot_data = parent_plot_data or self.resolve_single_visible_2d_plot_data()
        if plot_data is None:
            raise ValueError("Select a single 2D dataset")
        spec = parent_spec if parent_spec is not None else self._cube_view_spec
        if request is None:
            request = self.build_roi_profile_request(
                entry,
                parent_spec=spec,
                parent_frame=parent_frame,
                span_full_override=span_full_override,
                default_profile_axis=default_profile_axis,
            )
        crop = self._view_crop if view_crop is None else view_crop
        return plot_data.preview_roi_profile(
            request,
            parent_spec=spec,
            parent_bundle=parent_bundle,
            view_crop=crop,
        )

    def finalize_roi_commit(
        self,
        entry: RoiEntry,
        bundle: "PlotBundle",
        request: "MaterializeRequest",
        *,
        parent_plot_data: Optional[PlotDataModel] = None,
        parent_spec: Optional["CubeViewSpec"] = None,
        axis_names=None,
        cube_fingerprint=None,
        committed_xkey: Optional[str] = None,
    ) -> "FrozenSpectrum":
        """
        Build and register a frozen spectrum from a fetched ROI profile bundle.

        Parameters
        ----------
        entry : RoiEntry
            ROI entry used for labeling.
        bundle : PlotBundle
            Fetched 1D profile bundle.
        request : MaterializeRequest
            Request used for the fetch.
        parent_plot_data : PlotDataModel, optional
            Parent plot-data model. Defaults to the sole visible 2D model.
        parent_spec : CubeViewSpec, optional
            Parent cube view for labeling and kind classification.
        axis_names : sequence of str, optional
            Storage axis names for default labels.
        cube_fingerprint : tuple, optional
            Slice / cube-view snapshot. Defaults to this plot's state.
        committed_xkey : str, optional
            X key at commit time. Defaults to the plot session x selection.

        Returns
        -------
        FrozenSpectrum
            Registered frozen spectrum.
        """
        plot_data = parent_plot_data or self.resolve_single_visible_2d_plot_data()
        if plot_data is None:
            raise ValueError("Select a single 2D dataset")
        spec = parent_spec if parent_spec is not None else self._cube_view_spec
        names = tuple(axis_names or ())
        label = (
            entry.operation.label
            or entry.display_label
            or default_profile_label(request, names, parent_spec=spec)
        )
        if committed_xkey is None:
            committed_xkey = self._current_x_keys[0] if self._current_x_keys else ""
        if cube_fingerprint is None:
            cube_fingerprint = (
                tuple(self._slice) if self._slice else None,
                str(self._cube_view_spec),
            )
        frozen = plot_data.build_roi_frozen_spectrum(
            bundle,
            request,
            label=label,
            parent_spec=spec,
            cube_fingerprint=cube_fingerprint,
            committed_xkey=committed_xkey,
        )
        plot_data._run.register_frozen_spectrum(frozen)
        return frozen

    def commit_roi_profile(
        self,
        entry_id: Optional[str] = None,
        *,
        entry: Optional[RoiEntry] = None,
        parent_plot_data: Optional[PlotDataModel] = None,
        parent_spec: Optional["CubeViewSpec"] = None,
        parent_frame=None,
        parent_bundle: Optional["PlotBundle"] = None,
        view_crop: Optional[ViewCrop] = None,
        axis_names=None,
        default_profile_axis=None,
        cube_fingerprint=None,
        committed_xkey: Optional[str] = None,
    ) -> "FrozenSpectrum":
        """
        Preview, build, and register an ROI profile on the parent run.

        Parameters
        ----------
        entry_id : str, optional
            ROI entry id. Ignored when ``entry`` is provided.
        entry : RoiEntry, optional
            ROI entry. Defaults to resolving ``entry_id`` / selection.
        parent_plot_data : PlotDataModel, optional
            Parent 2D plot-data model.
        parent_spec : CubeViewSpec, optional
            Parent cube view.
        parent_frame : PlotViewFrame, optional
            Parent frame for request construction.
        parent_bundle : PlotBundle, optional
            Cached parent 2D bundle.
        view_crop : ViewCrop, optional
            Active crop.
        axis_names : sequence of str, optional
            Axis names for default labels.
        default_profile_axis : str or int, optional
            Fallback profile axis.
        cube_fingerprint : tuple, optional
            Slice / cube-view snapshot.
        committed_xkey : str, optional
            X key at commit time.

        Returns
        -------
        FrozenSpectrum
            Registered frozen spectrum.

        Raises
        ------
        ValueError
            If the ROI cannot be committed (stale, local profile, etc.).
        """
        if entry is None:
            entry = self.resolve_roi_entry(entry_id)
        plot_data = parent_plot_data or self.resolve_single_visible_2d_plot_data()
        if plot_data is None:
            raise ValueError("Select a single 2D dataset")
        spec = parent_spec if parent_spec is not None else self._cube_view_spec
        span_full, request = self.prepare_roi_commit(
            entry,
            parent_spec=spec,
            parent_frame=parent_frame,
            axis_names=axis_names,
            default_profile_axis=default_profile_axis,
        )
        del span_full
        bundle = self.preview_roi_profile(
            entry=entry,
            parent_plot_data=plot_data,
            parent_spec=spec,
            parent_bundle=parent_bundle,
            view_crop=view_crop,
            request=request,
        )
        return self.finalize_roi_commit(
            entry,
            bundle,
            request,
            parent_plot_data=plot_data,
            parent_spec=spec,
            axis_names=axis_names,
            cube_fingerprint=cube_fingerprint,
            committed_xkey=committed_xkey,
        )

    def _ensure_plot_data_for_visible(self) -> None:
        if not (self._current_x_keys and self._current_y_keys):
            return
        for run_model in self._run_list_model.visible_models:
            for xkey in self._current_x_keys:
                for ykey in self._current_y_keys:
                    self.ensure_plot_data(
                        run_model, xkey, ykey, self._current_norm_keys
                    )

    def _attach_run_model(self, run_model: "RunModel") -> None:
        if run_model.uid in self._connected_run_uids:
            return
        run_model.plot_update_needed.connect(self.request_plot_update)
        self._connected_run_uids.add(run_model.uid)

    def _detach_run_model(self, run_model: "RunModel") -> None:
        if run_model.uid not in self._connected_run_uids:
            return
        try:
            run_model.plot_update_needed.disconnect(self.request_plot_update)
        except (TypeError, RuntimeError):
            pass
        self._connected_run_uids.discard(run_model.uid)

    def _on_run_added(self, run_model: "RunModel") -> None:
        self._attach_run_model(run_model)
        run_model.set_transform(self._transform)
        run_model.set_selected_keys(
            self._current_x_keys,
            self._current_y_keys,
            self._current_norm_keys,
            force_update=False,
        )
        self._maybe_apply_default_selection()

    def _on_run_removed(self, run_model: "RunModel") -> None:
        self._detach_run_model(run_model)
        self.drop_plot_data_for_uid(run_model.uid)
        self.request_plot_update.emit()

    def _on_visible_runs_changed(self, _visible_uids) -> None:
        self._ensure_plot_data_for_visible()
        self.request_plot_update.emit()

    def _on_available_keys_changed(self) -> None:
        available_keys = self._run_list_model.available_keys
        if not available_keys:
            if not self._retain_selection:
                self.set_selected_keys([], [], [])
            return

        valid_x = [k for k in self._current_x_keys if k in available_keys]
        valid_y = [k for k in self._current_y_keys if k in available_keys]
        valid_norm = [k for k in self._current_norm_keys if k in available_keys]
        if (
            valid_x != self._current_x_keys
            or valid_y != self._current_y_keys
            or valid_norm != self._current_norm_keys
        ):
            self.set_selected_keys(valid_x, valid_y, valid_norm)

    def _maybe_apply_default_selection(self) -> None:
        if self._retain_selection:
            return
        if self._current_x_keys or self._current_y_keys or self._current_norm_keys:
            return
        models = self._run_list_model.available_models
        if len(models) != 1:
            return
        x_keys, y_keys, norm_keys = models[0].run.get_default_selection()
        self.set_selected_keys(x_keys, y_keys, norm_keys)
