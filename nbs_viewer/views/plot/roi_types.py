"""
View-side ROI type registry: selectors, overlays, and shape option widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
)

from matplotlib.colors import to_rgba
from matplotlib.widgets import EllipseSelector, PolygonSelector, RectangleSelector
from qtpy.QtCore import Signal
from qtpy.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nbs_viewer.models.plot.region import (
    EllipseRegion,
    PolygonRegion,
    RectRegion,
    RegionDefinition,
)

from .roi_overlays import (
    _ROI_EDGE_WIDTH,
    _ROI_FILL_ALPHA,
    overlay_artists_for_region,
)

PLACEHOLDER_RECT = RectRegion(x0=0.0, x1=0.0, y0=0.0, y1=0.0)
PLACEHOLDER_ELLIPSE = EllipseRegion(cx=0.0, cy=0.0, rx=0.0, ry=0.0, angle=0.0)
PLACEHOLDER_POLYGON = PolygonRegion(vertices=())


class ShapeOptionsWidget(QWidget):
    """
    Base widget for type-specific shape fields.

    Signals
    -------
    region_edited : object
        Emitted with a :class:`RegionDefinition` when the user edits fields.
    """

    region_edited = Signal(object)

    def set_region(self, region: RegionDefinition) -> None:
        """
        Update the form from a region definition.
        """

    def current_region(self) -> Optional[RegionDefinition]:
        """
        Return the region currently represented by the form, if any.
        """
        return None


class DescribeOptionsWidget(ShapeOptionsWidget):
    """
    Read-only shape summary using :meth:`RegionDefinition.describe`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("—")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        self._region: Optional[RegionDefinition] = None
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.setMinimumWidth(260)

    def set_region(self, region: Optional[RegionDefinition]) -> None:
        self._region = region
        self._label.setText(region.describe() if region is not None else "—")

    def current_region(self) -> Optional[RegionDefinition]:
        return self._region

    def clear_summary(self) -> None:
        """
        Reset the readout to an empty placeholder.
        """
        self._region = None
        self._label.setText("—")


class EllipseOptionsWidget(ShapeOptionsWidget):
    """
    Editable ellipse parameters with an optional circle constraint.

    Signals
    -------
    region_edited : object
        Emitted with a :class:`RegionDefinition` when the user edits fields.
    circle_lock_changed : bool
        Emitted when the circle-lock checkbox is toggled.
    """

    circle_lock_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        self.cx_spin = self._make_spin()
        self.cy_spin = self._make_spin()
        self.rx_spin = self._make_spin(minimum=0.0)
        self.ry_spin = self._make_spin(minimum=0.0)
        self.angle_spin = self._make_spin(minimum=-180.0, maximum=180.0)
        layout.addLayout(self._spin_row("Center X:", self.cx_spin))
        layout.addLayout(self._spin_row("Center Y:", self.cy_spin))
        layout.addLayout(self._spin_row("Radius X:", self.rx_spin))
        layout.addLayout(self._spin_row("Radius Y:", self.ry_spin))
        layout.addLayout(self._spin_row("Angle °:", self.angle_spin))
        self.circle_checkbox = QCheckBox("Circle (lock equal radii)")
        self.circle_checkbox.setToolTip(
            "When checked, resize is constrained to a circle "
            "(same as holding Shift while drawing)."
        )
        self.circle_checkbox.setMinimumHeight(24)
        layout.addWidget(self.circle_checkbox)
        for spin in (
            self.cx_spin,
            self.cy_spin,
            self.rx_spin,
            self.ry_spin,
            self.angle_spin,
        ):
            spin.valueChanged.connect(self._on_field_changed)
        self.circle_checkbox.toggled.connect(self._on_circle_toggled)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.setMinimumWidth(260)

    @staticmethod
    def _spin_row(label: str, spin: QDoubleSpinBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        text = QLabel(label)
        text.setMinimumWidth(80)
        text.setMinimumHeight(28)
        row.addWidget(text)
        row.addWidget(spin, stretch=1)
        return row

    def _make_spin(self, minimum=-1e9, maximum=1e9) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(4)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(0.1)
        spin.setKeyboardTracking(False)
        spin.setMinimumHeight(28)
        return spin

    def is_circle_locked(self) -> bool:
        """
        Return whether resize is constrained to a circle.
        """
        return self.circle_checkbox.isChecked()

    def set_region(
        self, region: RegionDefinition, *, sync_circle_lock: bool = False
    ) -> None:
        if not isinstance(region, EllipseRegion):
            return
        region = region.normalized()
        self._loading = True
        try:
            if sync_circle_lock:
                self.circle_checkbox.setChecked(
                    region.rx == region.ry and region.rx > 0.0
                )
            locked = self.circle_checkbox.isChecked()
            radius = max(region.rx, region.ry) if locked else region.rx
            self.cx_spin.setValue(region.cx)
            self.cy_spin.setValue(region.cy)
            self.rx_spin.setValue(radius if locked else region.rx)
            self.ry_spin.setValue(radius if locked else region.ry)
            self.angle_spin.setValue(region.angle)
            self.ry_spin.setEnabled(not locked)
        finally:
            self._loading = False
        if sync_circle_lock:
            self.circle_lock_changed.emit(self.circle_checkbox.isChecked())

    def current_region(self) -> Optional[RegionDefinition]:
        rx = float(self.rx_spin.value())
        ry = rx if self.circle_checkbox.isChecked() else float(self.ry_spin.value())
        return EllipseRegion(
            cx=float(self.cx_spin.value()),
            cy=float(self.cy_spin.value()),
            rx=rx,
            ry=ry,
            angle=float(self.angle_spin.value()),
        ).normalized()

    def _on_circle_toggled(self, checked: bool):
        self.ry_spin.setEnabled(not checked)
        if checked and not self._loading:
            self._loading = True
            try:
                radius = max(self.rx_spin.value(), self.ry_spin.value())
                self.rx_spin.setValue(radius)
                self.ry_spin.setValue(radius)
            finally:
                self._loading = False
        self.circle_lock_changed.emit(checked)
        self._on_field_changed()

    def _on_field_changed(self, *_args):
        if self._loading:
            return
        if self.circle_checkbox.isChecked():
            self._loading = True
            try:
                self.ry_spin.setValue(self.rx_spin.value())
            finally:
                self._loading = False
        region = self.current_region()
        if region is not None:
            self.region_edited.emit(region)


def _selector_props(color: str) -> dict:
    return dict(
        facecolor=to_rgba(color, _ROI_FILL_ALPHA),
        edgecolor=color,
        fill=True,
        linewidth=_ROI_EDGE_WIDTH,
    )


def _line_props(color: str) -> dict:
    return dict(color=color, linestyle="-", linewidth=_ROI_EDGE_WIDTH, alpha=0.9)


class LockedEllipseSelector(EllipseSelector):
    """
    EllipseSelector that can keep the square/circle constraint permanently.

    Matplotlib clears ``square`` on Shift key-release. When circle lock is
    enabled this subclass restores that state so the checkbox behaves like
    holding Shift continuously.
    """

    def __init__(self, *args, lock_circle: bool = False, **kwargs):
        self._nbs_lock_circle = bool(lock_circle)
        super().__init__(*args, **kwargs)
        if self._nbs_lock_circle:
            self._state.add("square")

    def set_lock_circle(self, locked: bool) -> None:
        """
        Enable or disable persistent circle constraint.
        """
        self._nbs_lock_circle = bool(locked)
        if self._nbs_lock_circle:
            self._state.add("square")
        else:
            self._state.discard("square")

    def on_key_release(self, event):
        super().on_key_release(event)
        if self._nbs_lock_circle:
            self._state.add("square")

    def _onmove(self, event):
        if self._nbs_lock_circle:
            self._state.add("square")
        return super()._onmove(event)


def _create_rect_selector(ax, on_region, *, color: str, region: RegionDefinition):
    def _onselect(_eclick, _erelease):
        result = _region_from_rect_selector(selector)
        if result is not None:
            on_region(result)

    selector = RectangleSelector(
        ax,
        _onselect,
        useblit=False,
        button=[1],
        minspanx=0,
        minspany=0,
        spancoords="data",
        interactive=True,
        props=_selector_props(color),
    )
    if isinstance(region, RectRegion) and region.has_area():
        _apply_rect_to_selector(selector, region)
    return selector


def _region_from_rect_selector(selector) -> Optional[RectRegion]:
    if selector is None:
        return None
    x0, x1, y0, y1 = selector.extents
    return RectRegion(x0=x0, x1=x1, y0=y0, y1=y1).normalized()


def _apply_rect_to_selector(selector, region: RegionDefinition) -> None:
    if not isinstance(region, RectRegion):
        return
    region = region.normalized()
    selector.extents = (region.x0, region.x1, region.y0, region.y1)


def _create_ellipse_selector(
    ax, on_region, *, color: str, region: RegionDefinition, lock_circle: bool = False
):
    def _onselect(_eclick, _erelease):
        locked = bool(getattr(selector, "_nbs_lock_circle", False))
        result = _region_from_ellipse_selector(selector, lock_circle=locked)
        if result is not None:
            on_region(result)

    selector = LockedEllipseSelector(
        ax,
        _onselect,
        useblit=False,
        button=[1],
        minspanx=0,
        minspany=0,
        spancoords="data",
        interactive=True,
        props=_selector_props(color),
        use_data_coordinates=True,
        lock_circle=lock_circle,
    )
    if isinstance(region, EllipseRegion) and region.has_area():
        to_apply = region.normalized()
        if lock_circle:
            radius = max(to_apply.rx, to_apply.ry)
            to_apply = EllipseRegion(
                cx=to_apply.cx,
                cy=to_apply.cy,
                rx=radius,
                ry=radius,
                angle=to_apply.angle,
            )
        _apply_ellipse_to_selector(selector, to_apply)
    return selector


def _region_from_ellipse_selector(
    selector, *, lock_circle: bool = False
) -> Optional[EllipseRegion]:
    if selector is None:
        return None
    locked = lock_circle or bool(getattr(selector, "_nbs_lock_circle", False))
    x0, x1, y0, y1 = selector.extents
    cx = 0.5 * (x0 + x1)
    cy = 0.5 * (y0 + y1)
    rx = 0.5 * abs(x1 - x0)
    ry = 0.5 * abs(y1 - y0)
    if locked or "square" in getattr(selector, "_state", ()):
        radius = max(rx, ry)
        rx = ry = radius
    angle = float(getattr(selector, "rotation", 0.0) or 0.0)
    return EllipseRegion(cx=cx, cy=cy, rx=rx, ry=ry, angle=angle).normalized()


def _apply_ellipse_to_selector(selector, region: RegionDefinition) -> None:
    if not isinstance(region, EllipseRegion):
        return
    region = region.normalized()
    selector.extents = (
        region.cx - region.rx,
        region.cx + region.rx,
        region.cy - region.ry,
        region.cy + region.ry,
    )
    try:
        selector.rotation = region.angle
    except Exception:
        pass


def set_ellipse_selector_circle_lock(selector, locked: bool) -> None:
    """
    Persistently constrain an ellipse selector to equal radii.
    """
    if selector is None:
        return
    if hasattr(selector, "set_lock_circle"):
        selector.set_lock_circle(locked)
        return
    selector._nbs_lock_circle = bool(locked)
    if locked:
        selector._state.add("square")
    else:
        selector._state.discard("square")


def _create_polygon_selector(ax, on_region, *, color: str, region: RegionDefinition):
    def _onselect(verts):
        result = PolygonRegion(
            vertices=tuple((float(x), float(y)) for x, y in verts)
        )
        on_region(result)

    selector = PolygonSelector(
        ax,
        _onselect,
        useblit=False,
        props=_line_props(color),
        handle_props=dict(markeredgecolor=color, markerfacecolor=color),
    )
    if isinstance(region, PolygonRegion) and len(region.vertices) >= 3:
        _apply_polygon_to_selector(selector, region)
    return selector


def _region_from_polygon_selector(selector) -> Optional[PolygonRegion]:
    if selector is None:
        return None
    verts = getattr(selector, "verts", None)
    if not verts or len(verts) < 3:
        return None
    return PolygonRegion(
        vertices=tuple((float(x), float(y)) for x, y in verts)
    )


def _apply_polygon_to_selector(selector, region: RegionDefinition) -> None:
    if not isinstance(region, PolygonRegion):
        return
    if len(region.vertices) < 3:
        return
    selector.verts = list(region.vertices)


@dataclass(frozen=True)
class RoiTypeSpec:
    """
    View-side metadata for one ROI geometry type.

    Parameters
    ----------
    type_id : str
        Stable id matching :attr:`RegionDefinition.region_type`.
    display_name : str
        Name shown in the Add ROI dropdown.
    short_name : str
        Compact label for the ROI list.
    create_placeholder : callable
        Factory for an empty region awaiting a draw.
    create_selector : callable
        ``(ax, on_region, *, color, region) -> selector``.
    region_from_selector : callable
        Read geometry from an active selector.
    apply_region_to_selector : callable
        Push geometry onto an active selector.
    overlay_artists : callable
        Build overlay patches for a committed region.
    create_options_widget : callable
        Factory for the shape-options form.
    """

    type_id: str
    display_name: str
    short_name: str
    create_placeholder: Callable[[], RegionDefinition]
    create_selector: Callable[..., Any]
    region_from_selector: Callable[[Any], Optional[RegionDefinition]]
    apply_region_to_selector: Callable[[Any, RegionDefinition], None]
    overlay_artists: Callable[..., Sequence]
    create_options_widget: Callable[[Optional[QWidget]], ShapeOptionsWidget]


_ROI_TYPES: Dict[str, RoiTypeSpec] = {}
_ROI_TYPE_ORDER: List[str] = []


def register_roi_type(spec: RoiTypeSpec) -> RoiTypeSpec:
    """
    Register a view-side ROI type specification.
    """
    _ROI_TYPES[spec.type_id] = spec
    if spec.type_id not in _ROI_TYPE_ORDER:
        _ROI_TYPE_ORDER.append(spec.type_id)
    return spec


def get_roi_type(type_id: str) -> Optional[RoiTypeSpec]:
    """
    Look up a registered ROI type by id.
    """
    return _ROI_TYPES.get(type_id)


def iter_roi_types() -> Iterable[RoiTypeSpec]:
    """
    Iterate registered ROI types in display order.
    """
    for type_id in _ROI_TYPE_ORDER:
        yield _ROI_TYPES[type_id]


def roi_type_for_region(region: RegionDefinition) -> Optional[RoiTypeSpec]:
    """
    Return the registry entry for a region, if any.
    """
    return get_roi_type(getattr(region, "region_type", ""))


def _overlay_factory(region, *, color: str, stale: bool):
    return overlay_artists_for_region(region, color=color, stale=stale)


register_roi_type(
    RoiTypeSpec(
        type_id="rect",
        display_name="Rectangle",
        short_name="Rect",
        create_placeholder=lambda: PLACEHOLDER_RECT,
        create_selector=_create_rect_selector,
        region_from_selector=_region_from_rect_selector,
        apply_region_to_selector=_apply_rect_to_selector,
        overlay_artists=_overlay_factory,
        create_options_widget=DescribeOptionsWidget,
    )
)
register_roi_type(
    RoiTypeSpec(
        type_id="ellipse",
        display_name="Ellipse",
        short_name="Ellipse",
        create_placeholder=lambda: PLACEHOLDER_ELLIPSE,
        create_selector=_create_ellipse_selector,
        region_from_selector=_region_from_ellipse_selector,
        apply_region_to_selector=_apply_ellipse_to_selector,
        overlay_artists=_overlay_factory,
        create_options_widget=EllipseOptionsWidget,
    )
)
register_roi_type(
    RoiTypeSpec(
        type_id="polygon",
        display_name="Polygon",
        short_name="Polygon",
        create_placeholder=lambda: PLACEHOLDER_POLYGON,
        create_selector=_create_polygon_selector,
        region_from_selector=_region_from_polygon_selector,
        apply_region_to_selector=_apply_polygon_to_selector,
        overlay_artists=_overlay_factory,
        create_options_widget=DescribeOptionsWidget,
    )
)
