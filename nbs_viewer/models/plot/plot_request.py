"""
Immutable description of one plottable trace.

A :class:`PlotRequest` is frozen and hashable so it can serve as the
fingerprint of a fetch. Long-lived plot-data models are identified by
:class:`TraceKey`, a subset of the request, so view/crop/transform
changes reuse the artist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple, Union

from .cube_view import CubeViewSpec, spec_from_slice_info
from .region import MaskMode, RegionDefinition
from .view_spec import ViewCrop, ViewSpec, default_view_spec

SliceItem = Union[int, slice]


def slim_crop_from_legacy(crop) -> Optional[ViewCrop]:
    """
    Convert a legacy fat ``view_crop.ViewCrop`` to the slim value type.

    Parameters
    ----------
    crop : object or None
        Legacy crop with ``storage_bbox``, ``plot_y_axis``, and
        ``plot_x_axis``, or None.

    Returns
    -------
    ViewCrop or None
        Slim crop, or None when ``crop`` is None.
    """
    if crop is None:
        return None
    return ViewCrop(
        storage_bbox=tuple(crop.storage_bbox),
        plot_y_axis=int(crop.plot_y_axis),
        plot_x_axis=int(crop.plot_x_axis),
    )


def view_spec_from_legacy(
    *,
    shape: Sequence[int],
    plot_ndim: int = 1,
    cube_view_spec: Optional[CubeViewSpec] = None,
    slice_info: Optional[Tuple[SliceItem, ...]] = None,
    crop=None,
) -> ViewSpec:
    """
    Build a :class:`ViewSpec` from today's session fields.

    Prefer ``cube_view_spec`` when it fits the array rank. Otherwise infer
    from ``slice_info``, then fall back to a trailing-axis default.

    Parameters
    ----------
    shape : sequence of int
        Shape of the y key.
    plot_ndim : int
        Desired plot dimensionality (1 or 2).
    cube_view_spec : CubeViewSpec, optional
        Session cube view.
    slice_info : tuple, optional
        Legacy per-axis slice tuple.
    crop : object, optional
        Legacy fat view crop, or slim :class:`ViewCrop`.

    Returns
    -------
    ViewSpec
        Rank-bound view for the request.
    """
    ndim = len(shape)
    if ndim <= 0:
        raise ValueError("shape must have at least one dimension")

    effective_plot_ndim = plot_ndim if ndim >= plot_ndim else 1
    slim = crop if isinstance(crop, ViewCrop) else slim_crop_from_legacy(crop)

    if cube_view_spec is not None and cube_view_spec.ndim == ndim:
        return ViewSpec.from_cube_view_spec(cube_view_spec, crop=slim)

    if slice_info is not None and len(slice_info) == ndim:
        cube = spec_from_slice_info(tuple(slice_info), effective_plot_ndim)
        return ViewSpec.from_cube_view_spec(cube, crop=slim)

    return default_view_spec(ndim, effective_plot_ndim)


def build_plot_request(
    *,
    uid: str,
    xkeys: Sequence[str],
    ykey: str,
    shape: Sequence[int],
    norm_keys: Optional[Sequence[str]] = None,
    plot_ndim: int = 1,
    cube_view_spec: Optional[CubeViewSpec] = None,
    slice_info: Optional[Tuple[SliceItem, ...]] = None,
    crop=None,
    transform: str = "",
    region: Optional[RegionDefinition] = None,
    mask_mode: MaskMode = "inside",
) -> "PlotRequest":
    """
    Build a :class:`PlotRequest` from run identity and legacy view state.

    Parameters
    ----------
    uid : str
        Run uid.
    xkeys : sequence of str
        X-axis keys.
    ykey : str
        Y data key.
    shape : sequence of int
        Shape of ``ykey``.
    norm_keys : sequence of str, optional
        Normalization keys.
    plot_ndim : int
        Desired plot dimensionality.
    cube_view_spec : CubeViewSpec, optional
        Session cube view.
    slice_info : tuple, optional
        Legacy slice tuple.
    crop : object, optional
        Legacy or slim view crop.
    transform : str
        Effective transform expression.
    region : RegionDefinition, optional
        ROI for profile requests.
    mask_mode : str
        ROI mask mode.

    Returns
    -------
    PlotRequest
        Frozen request for the fetch path.
    """
    view = view_spec_from_legacy(
        shape=shape,
        plot_ndim=plot_ndim,
        cube_view_spec=cube_view_spec,
        slice_info=slice_info,
        crop=crop,
    )
    return PlotRequest(
        uid=uid,
        xkeys=tuple(xkeys),
        ykey=ykey,
        norm_keys=tuple(norm_keys or ()),
        view=view,
        region=region,
        mask_mode=mask_mode,
        transform=transform or "",
    )


@dataclass(frozen=True)
class TraceKey:
    """
    Object identity for a plot-data model / artist.

    A :class:`PlotRequest` is the fingerprint of *what is plotted*. This key
    is the subset that names a long-lived object so crop, transform, and
    slice changes reuse the artist.

    Parameters
    ----------
    uid : str
        Run uid.
    xkey : str
        Primary X key.
    ykey : str
        Y data key.
    fan_out_index : int, optional
        Distinct cell when several slices of the same keys are shown at once
        (image grid). ``None`` for the main display.
    """

    uid: str
    xkey: str
    ykey: str
    fan_out_index: Optional[int] = None

    def as_tuple(self) -> Tuple[str, str, str]:
        """
        Return the legacy ``(xkey, ykey, uid)`` map key.

        Returns
        -------
        tuple of str
            Compatibility triple used by crop ``source_key`` and canvas
            connection tracking.
        """
        return (self.xkey, self.ykey, self.uid)


@dataclass(frozen=True)
class PlotRequest:
    """
    Complete description of one fetch / one trace.

    Parameters
    ----------
    uid : str
        Run uid the data is read from.
    xkeys : tuple of str
        X-axis key selection used for dimension analysis.
    ykey : str
        Y data key.
    norm_keys : tuple of str
        Normalization keys. Empty means no normalization.
    view : ViewSpec
        Rank-bound view including optional plot-plane crop.
    region : RegionDefinition, optional
        ROI in data coordinates on the parent 2D plot plane. When set, the
        fetch reduces to a 1-D profile.
    mask_mode : str
        ``inside`` or ``outside`` when ``region`` is set.
    transform : str
        Effective transform expression for this fetch. Empty string means no
        transform. The session may keep a separate enabled flag and full
        expression text; only the effective string enters the request so that
        toggling off does not change request identity relative to "no
        transform", while the expression itself is preserved on the session.
    """

    uid: str
    xkeys: Tuple[str, ...]
    ykey: str
    norm_keys: Tuple[str, ...]
    view: ViewSpec
    region: Optional[RegionDefinition] = None
    mask_mode: MaskMode = "inside"
    transform: str = ""

    def __post_init__(self) -> None:
        if not self.uid:
            raise ValueError("uid must be non-empty")
        if not self.ykey:
            raise ValueError("ykey must be non-empty")
        if self.mask_mode not in ("inside", "outside"):
            raise ValueError(
                f"mask_mode must be 'inside' or 'outside', got {self.mask_mode!r}"
            )
        if self.region is not None and self.view.plot_ndim != 1:
            raise ValueError(
                "ROI profile requests require view.plot_ndim == 1, "
                f"got {self.view.plot_ndim}"
            )

    def trace_key(self, fan_out_index: Optional[int] = None) -> TraceKey:
        """
        Return the object-identity subset of this request.

        Parameters
        ----------
        fan_out_index : int, optional
            Image-grid cell index. Defaults to no fan-out.

        Returns
        -------
        TraceKey
            Key for the long-lived plot-data model.
        """
        xkey = self.xkeys[0] if self.xkeys else ""
        return TraceKey(
            uid=self.uid,
            xkey=xkey,
            ykey=self.ykey,
            fan_out_index=fan_out_index,
        )
