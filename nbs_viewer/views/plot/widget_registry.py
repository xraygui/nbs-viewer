"""Registry for managing available plot widgets."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Type
from importlib.metadata import entry_points
from qtpy.QtWidgets import QWidget


@dataclass
class WidgetInfo:
    """Information about a plot widget."""

    widget_class: Type[QWidget]
    name: str
    description: str
    capabilities: List[str]
    icon: Optional[str] = None
    version: str = "1.0.0"
    author: Optional[str] = None


class PlotWidgetRegistry:
    """Registry for managing available plot widgets."""

    def __init__(self):
        self._widgets: Dict[str, WidgetInfo] = {}
        self._default_widget = "matplotlib"
        self._load_widgets()

    def register_widget(
        self, widget_id: str, widget_class: Type[QWidget], metadata: dict
    ):
        """Register a widget with metadata."""
        widget_info = WidgetInfo(
            widget_class=widget_class,
            name=metadata.get("name", widget_id),
            description=metadata.get("description", ""),
            capabilities=metadata.get("capabilities", []),
            icon=metadata.get("icon"),
            version=metadata.get("version", "1.0.0"),
            author=metadata.get("author"),
        )
        self._widgets[widget_id] = widget_info

    def get_widget(self, widget_id: str) -> Type[QWidget]:
        """Get widget class by ID."""
        if widget_id not in self._widgets:
            raise ValueError(f"Unknown widget ID: {widget_id}")
        return self._widgets[widget_id].widget_class

    def get_available_widgets(self) -> List[str]:
        """Get list of available widget IDs."""
        return list(self._widgets.keys())

    def get_widget_metadata(self, widget_id: str) -> dict:
        """Get metadata for a widget."""
        if widget_id not in self._widgets:
            return {}

        widget_info = self._widgets[widget_id]
        return {
            "name": widget_info.name,
            "description": widget_info.description,
            "capabilities": widget_info.capabilities,
            "icon": widget_info.icon,
            "version": widget_info.version,
            "author": widget_info.author,
        }

    def get_default_widget(self) -> str:
        """Get the default widget ID."""
        return self._default_widget

    def set_default_widget(self, widget_id: str):
        """Set the default widget ID."""
        if widget_id not in self._widgets:
            raise ValueError(f"Unknown widget ID: {widget_id}")
        self._default_widget = widget_id

    def _load_widgets(self):
        """Load widgets from entry points."""
        for ep in entry_points(group="nbs_viewer.plot_widgets"):
            try:
                widget_class = ep.load()
                if not self._validate_widget_class(widget_class):
                    print(f"Widget {ep.name} failed validation")
                    continue

                # Extract metadata from class or use defaults
                metadata = self._extract_metadata(widget_class, ep.name)
                self.register_widget(ep.name, widget_class, metadata)
            except Exception as e:
                print(f"Failed to load widget {ep.name}: {e}")

    def _validate_widget_class(self, widget_class) -> bool:
        """Validate that widget class meets requirements."""
        # Check inheritance
        if not issubclass(widget_class, QWidget):
            return False

        # Check constructor signature - should accept plotModel as first parameter
        import inspect

        sig = inspect.signature(widget_class.__init__)
        params = list(sig.parameters.keys())

        # Skip 'self' parameter
        if len(params) > 1 and params[1] == "plotModel":
            return True

        return False

    def _extract_metadata(self, widget_class, widget_id: str) -> dict:
        """Extract metadata from widget class."""
        # Try to get metadata from class attributes
        metadata = {
            "name": getattr(widget_class, "__widget_name__", widget_id.title()),
            "description": getattr(widget_class, "__widget_description__", ""),
            "capabilities": getattr(
                widget_class, "__widget_capabilities__", ["1d", "2d"]
            ),
            "icon": getattr(widget_class, "__widget_icon__", None),
            "version": getattr(widget_class, "__widget_version__", "1.0.0"),
            "author": getattr(widget_class, "__widget_author__", None),
        }

        return metadata
