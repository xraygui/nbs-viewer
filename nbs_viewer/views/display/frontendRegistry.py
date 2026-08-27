"""Registry of plot frontend widgets (entry-point discovery).

Lives in views: models must not import Qt widget classes or load display
entry points. The GUI shell owns this registry and uses it to build menus
and instantiate tabs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Type

from importlib.metadata import entry_points
from qtpy.QtWidgets import QWidget

_frontend_registry = None


def set_frontend_registry(registry: Optional["FrontendRegistry"]) -> None:
    """
    Set the process-wide frontend registry for the GUI shell.

    Parameters
    ----------
    registry : FrontendRegistry or None
        Registry instance, or None to clear.
    """
    global _frontend_registry
    _frontend_registry = registry


def get_frontend_registry() -> "FrontendRegistry":
    """
    Return the process-wide frontend registry.

    Returns
    -------
    FrontendRegistry
        The registry set by the GUI shell.

    Raises
    ------
    RuntimeError
        If called before the registry has been set.
    """
    if _frontend_registry is None:
        raise RuntimeError(
            "get_frontend_registry() called before the frontend registry "
            "was set. Create FrontendRegistry in the GUI shell first."
        )
    return _frontend_registry


@dataclass
class FrontendInfo:
    """Information about a plot frontend widget."""

    display_class: Type[QWidget]
    name: str
    description: str
    capabilities: List[str]
    icon: Optional[str] = None
    version: str = "1.0.0"
    author: Optional[str] = None
    single_selection_mode: bool = False


class FrontendRegistry:
    """
    Discover and hold plot frontend widget classes.

    Loads ``nbs_viewer.plot_displays`` entry points. Used only by views /
    the app shell — not by ``AppModel`` or ``DisplayManager``.
    """

    def __init__(self):
        self._displays: Dict[str, FrontendInfo] = {}
        self._default_display = "matplotlib"
        self._load_displays()

    def register_display(
        self, display_id: str, display_class: Type[QWidget], metadata: dict
    ) -> None:
        """
        Register a frontend widget with metadata.

        Parameters
        ----------
        display_id : str
            Frontend type id (e.g. ``matplotlib``).
        display_class : type
            QWidget subclass to instantiate for tabs.
        metadata : dict
            Display name, capabilities, ``single_selection_mode``, etc.
        """
        display_info = FrontendInfo(
            display_class=display_class,
            name=metadata.get("name", display_id),
            description=metadata.get("description", ""),
            capabilities=metadata.get("capabilities", []),
            icon=metadata.get("icon"),
            version=metadata.get("version", "1.0.0"),
            author=metadata.get("author"),
            single_selection_mode=bool(metadata.get("single_selection_mode", False)),
        )
        self._displays[display_id] = display_info

    def get_display(self, display_id: str) -> Type[QWidget]:
        """
        Return the widget class for a frontend id.

        Parameters
        ----------
        display_id : str
            Frontend type id.

        Returns
        -------
        type
            QWidget subclass.
        """
        if display_id not in self._displays:
            raise ValueError(f"Unknown display ID: {display_id}")
        return self._displays[display_id].display_class

    def get_available_displays(self) -> List[str]:
        """Return registered frontend type ids."""
        return list(self._displays.keys())

    def get_display_metadata(self, display_id: str) -> dict:
        """
        Return metadata for a frontend type.

        Parameters
        ----------
        display_id : str
            Frontend type id.

        Returns
        -------
        dict
            Name, description, capabilities, ``single_selection_mode``, etc.
        """
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
            "single_selection_mode": display_info.single_selection_mode,
        }

    def single_selection_mode_for_type(self, display_type: str) -> bool:
        """
        Return whether a frontend type wants single-selection run lists.

        Parameters
        ----------
        display_type : str
            Frontend type id.

        Returns
        -------
        bool
            Policy from frontend metadata, default False.
        """
        return bool(
            self.get_display_metadata(display_type).get("single_selection_mode", False)
        )

    def get_default_display(self) -> str:
        """Return the default frontend type id."""
        return self._default_display

    def set_default_display(self, display_id: str) -> None:
        """
        Set the default frontend type id.

        Parameters
        ----------
        display_id : str
            Must already be registered.
        """
        if display_id not in self._displays:
            raise ValueError(f"Unknown display ID: {display_id}")
        self._default_display = display_id

    def _load_displays(self) -> None:
        """Load frontends from entry points."""
        for ep in entry_points(group="nbs_viewer.plot_displays"):
            try:
                print(f"Loading display {ep.name}")
                display_class = ep.load()
                if not self._validate_display_class(display_class):
                    print(f"display {ep.name} failed validation")
                    continue
                metadata = self._extract_metadata(display_class, ep.name)
                self.register_display(ep.name, display_class, metadata)
            except Exception as e:
                print(f"Failed to load display {ep.name}: {e}")

    def _validate_display_class(self, display_class) -> bool:
        """Return True if ``display_class`` is a PlotDisplay subclass."""
        from nbs_viewer.views.display.plotDisplay import PlotDisplay

        return issubclass(display_class, PlotDisplay)

    def _extract_metadata(self, display_class, display_id: str) -> dict:
        """Extract menu/policy metadata from a frontend class."""
        return {
            "name": getattr(
                display_class,
                "__widget_name__",
                getattr(display_class, "__display_name__", display_id.title()),
            ),
            "description": getattr(
                display_class,
                "__widget_description__",
                getattr(display_class, "__display_description__", ""),
            ),
            "capabilities": getattr(
                display_class,
                "__widget_capabilities__",
                getattr(display_class, "__display_capabilities__", ["1d", "2d"]),
            ),
            "icon": getattr(
                display_class,
                "__widget_icon__",
                getattr(display_class, "__display_icon__", None),
            ),
            "version": getattr(
                display_class,
                "__widget_version__",
                getattr(display_class, "__display_version__", "1.0.0"),
            ),
            "author": getattr(
                display_class,
                "__widget_author__",
                getattr(display_class, "__display_author__", None),
            ),
            "single_selection_mode": bool(
                getattr(display_class, "__single_selection_mode__", False)
            ),
        }
