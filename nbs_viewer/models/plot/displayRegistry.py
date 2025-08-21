"""Registry for managing available plot displays."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Type
from importlib.metadata import entry_points
from qtpy.QtWidgets import QWidget
from nbs_viewer.views.display.plotDisplay import PlotDisplay


@dataclass
class DisplayInfo:
    """Information about a plot display."""

    display_class: Type[QWidget]
    name: str
    description: str
    capabilities: List[str]
    icon: Optional[str] = None
    version: str = "1.0.0"
    author: Optional[str] = None


class DisplayRegistry:
    """Registry for managing available plot displays."""

    def __init__(self):
        self._displays: Dict[str, DisplayInfo] = {}
        self._default_display = "matplotlib"
        self._load_displays()

    def register_display(
        self, display_id: str, display_class: Type[QWidget], metadata: dict
    ):
        """Register a display with metadata."""
        display_info = DisplayInfo(
            display_class=display_class,
            name=metadata.get("name", display_id),
            description=metadata.get("description", ""),
            capabilities=metadata.get("capabilities", []),
            icon=metadata.get("icon"),
            version=metadata.get("version", "1.0.0"),
            author=metadata.get("author"),
        )
        self._displays[display_id] = display_info

    def get_display(self, display_id: str) -> Type[QWidget]:
        """Get display class by ID."""
        if display_id not in self._displays:
            raise ValueError(f"Unknown display ID: {display_id}")
        return self._displays[display_id].display_class

    def get_available_displays(self) -> List[str]:
        """Get list of available display IDs."""
        return list(self._displays.keys())

    def get_display_metadata(self, display_id: str) -> dict:
        """Get metadata for a display."""
        if display_id not in self._displays:
            return {}

        display_info = self._displays[display_id]
        return {
            "name": display_info.name,
            "description": display_info.description,
            "capabilities": display_info.capabilities,
            "icon": display_info.icon,
            "version": display_info.version,
            "author": display_info.author,
        }

    def get_default_display(self) -> str:
        """Get the default display ID."""
        return self._default_display

    def set_default_display(self, display_id: str):
        """Set the default display ID."""
        if display_id not in self._displays:
            raise ValueError(f"Unknown display ID: {display_id}")
        self._default_display = display_id

    def _load_displays(self):
        """Load displays from entry points."""
        for ep in entry_points(group="nbs_viewer.plot_displays"):
            try:
                print(f"Loading display {ep.name}")
                display_class = ep.load()
                if not self._validate_display_class(display_class):
                    print(f"display {ep.name} failed validation")
                    continue

                # Extract metadata from class or use defaults
                metadata = self._extract_metadata(display_class, ep.name)
                self.register_display(ep.name, display_class, metadata)
            except Exception as e:
                print(f"Failed to load display {ep.name}: {e}")

    def _validate_display_class(self, display_class) -> bool:
        """Validate that display class meets requirements."""
        # Check inheritance
        if not issubclass(display_class, PlotDisplay):
            return False
        return True

    def _extract_metadata(self, display_class, display_id: str) -> dict:
        """Extract metadata from display class."""
        # Try to get metadata from class attributes
        metadata = {
            "name": getattr(display_class, "__display_name__", display_id.title()),
            "description": getattr(display_class, "__display_description__", ""),
            "capabilities": getattr(
                display_class, "__display_capabilities__", ["1d", "2d"]
            ),
            "icon": getattr(display_class, "__display_icon__", None),
            "version": getattr(display_class, "__display_version__", "1.0.0"),
            "author": getattr(display_class, "__display_author__", None),
        }

        return metadata
