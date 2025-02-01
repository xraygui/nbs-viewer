from typing import Dict, List
from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
)

from ....models.plot.run_controller import RunModelController
from ..run_display import RunDisplayWidget
from .auto_add import AutoAddControl
from .dynamic_update import DynamicUpdateControl
from .transform import TransformControl


class PlotControls(QWidget):
    """
    A widget for interactive plotting controls.

    Manages multiple runs and their display settings through RunModelControllers.
    Includes transform options and metadata display.

    Parameters
    ----------
    plot : MPLCanvas or similar
        The plotting canvas where the data will be displayed
    parent : QWidget, optional
        The parent widget, by default None
    """

    def __init__(self, plot, parent=None):
        super().__init__(parent)
        self.plot = plot
        self._controllers: List[RunModelController] = []
        self._lines = {}  # Store line references by ID

        # Create the tab widget
        self.tab_widget = QTabWidget()

        # Create the plot control tab
        self.plot_control_tab = QWidget()
        self.plot_control_layout = QVBoxLayout(self.plot_control_tab)

        # Create the metadata tab
        self.metadata_tab = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_tab)
        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setHeaderLabels(["Key", "Value"])
        self.metadata_layout.addWidget(self.metadata_tree)

        # Add tabs to the tab widget
        self.tab_widget.addTab(self.plot_control_tab, "Plot Controls")
        self.tab_widget.addTab(self.metadata_tab, "Metadata")

        # Main layout
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.tab_widget)

        self.setup_plot_control_tab()

    def setup_plot_control_tab(self):
        """Setup the plot control tab with all its widgets."""
        # Auto add control
        self.auto_add = AutoAddControl()
        self.auto_add.state_changed.connect(self._on_auto_add_changed)
        self.plot_control_layout.addWidget(self.auto_add)

        # Dynamic update control
        self.dynamic_update = DynamicUpdateControl()
        self.dynamic_update.state_changed.connect(self._on_dynamic_changed)
        self.plot_control_layout.addWidget(self.dynamic_update)

        # Transform control
        self.transform = TransformControl()
        self.transform.state_changed.connect(self._on_transform_changed)
        self.plot_control_layout.addWidget(self.transform)

        # Run display widget
        self.run_display = RunDisplayWidget()
        self.run_display.selection_changed.connect(self._on_selection_changed)
        self.plot_control_layout.addWidget(self.run_display)

    def add_controllers(self, controllers: List[RunModelController]) -> None:
        """
        Add new run controllers to manage.

        Parameters
        ----------
        controllers : List[RunModelController]
            List of controllers to add
        """
        if not isinstance(controllers, (list, tuple)):
            controllers = [controllers]

        # Disconnect old controllers
        for controller in self._controllers:
            try:
                controller.data_updated.disconnect(self._on_data_updated)
                controller.line_removed.disconnect(self._on_line_removed)
            except (TypeError, RuntimeError):
                # Ignore if signals were not connected
                pass

        # Create new list with unique controllers
        new_controllers = []
        existing_ids = {id(c) for c in self._controllers}

        for controller in controllers:
            if id(controller) not in existing_ids:
                new_controllers.append(controller)
                existing_ids.add(id(controller))

        # Connect new controllers
        self._controllers.extend(new_controllers)
        for controller in new_controllers:
            controller.data_updated.connect(self._on_data_updated)
            controller.line_removed.connect(self._on_line_removed)
            controller.set_dynamic(self.dynamic_update.get_state()["dynamic"])

        # Update display
        self.run_display.set_controllers(self._controllers)

        # Update metadata with last controller's run
        if new_controllers:  # Only update if we actually added new controllers
            self.update_metadata_tab(new_controllers[-1].run_data.run.metadata)

    def _on_auto_add_changed(self) -> None:
        """Handle auto add state changes."""
        if self.auto_add.get_state()["auto_add"]:
            self.update_plot()

    def _on_dynamic_changed(self) -> None:
        """Handle dynamic update state changes."""
        is_dynamic = self.dynamic_update.get_state()["dynamic"]
        for controller in self._controllers:
            controller.set_dynamic(is_dynamic)

    def _on_transform_changed(self) -> None:
        """Handle transform state changes."""
        transform_state = self.transform.get_state()
        for controller in self._controllers:
            controller.run_data.set_transform(transform_state["text"])

    def _on_selection_changed(self) -> None:
        """Handle selection changes in run display."""
        if self.auto_add.get_state()["auto_add"]:
            self.update_plot()

    def _on_data_updated(self, x_data, y_data, style) -> None:
        """
        Handle updated data from a controller.

        Parameters
        ----------
        x_data : array_like
            X-axis data
        y_data : array_like
            Y-axis data
        style : dict
            Style properties for the line
        """
        # Create or update line in plot
        line = self.plot.axes.plot(
            x_data,
            y_data,
            color=style["color"].name(),
            linestyle=style["linestyle"],
            linewidth=style["linewidth"],
            marker=style["marker"],
            markersize=style["markersize"],
            alpha=style["alpha"],
            label=style["label"],
        )[0]

        # Store line reference
        self._lines[style["label"]] = line

        # Update canvas
        self.plot.draw_idle()

    def _on_line_removed(self, line_id: str) -> None:
        """
        Handle line removal from a controller.

        Parameters
        ----------
        line_id : str
            ID of the line to remove
        """
        # Remove line if it exists
        if line_id in self._lines:
            self._lines[line_id].remove()
            del self._lines[line_id]
            self.plot.draw_idle()

    def update_metadata_tab(self, metadata: Dict) -> None:
        """
        Update the metadata tab with new metadata.

        Parameters
        ----------
        metadata : Dict
            Dictionary of metadata to display
        """
        self.metadata_tree.clear()
        for key, value in metadata.items():
            item = QTreeWidgetItem([str(key), str(value)])
            self.metadata_tree.addTopLevelItem(item)

    def clear_plot(self) -> None:
        """Clear all controllers and reset the plot."""
        # Cleanup controllers
        for controller in self._controllers:
            controller.cleanup()
        self._controllers.clear()

        # Clear display
        self.run_display.set_controllers([])

        # Clear plot
        self.plot.clearPlot()

    def update_plot(self) -> None:
        """Update the plot with current selection."""
        if not self._controllers:
            return

        # Get data from all controllers
        for controller in self._controllers:
            controller.update_plot()
