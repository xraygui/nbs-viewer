from typing import Dict, List
from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QTreeWidget,
)

from .controls.run_display import RunDisplayWidget
from .controls.auto_add import AutoAddControl
from .controls.dynamic_update import DynamicUpdateControl
from .controls.transform import TransformControl


class PlotControls(QWidget):
    """
    A widget for interactive plotting controls.

    Manages multiple runs and their display settings through RunModels.
    Includes transform options and metadata display.

    Parameters
    ----------
    plot : MPLCanvas or similar
        The plotting canvas where the data will be displayed
    parent : QWidget, optional
        The parent widget, by default None
    """

    def __init__(self, plotModel, parent=None):
        super().__init__(parent)
        self.plotModel = plotModel

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
        self.auto_add = AutoAddControl(self.plotModel)
        self.plot_control_layout.addWidget(self.auto_add)

        # Dynamic update control
        self.dynamic_update = DynamicUpdateControl(self.plotModel)
        self.plot_control_layout.addWidget(self.dynamic_update)

        # Transform control
        self.transform = TransformControl(self.plotModel)
        self.plot_control_layout.addWidget(self.transform)

        # Run display widget
        self.run_display = RunDisplayWidget(self.plotModel)
        self.plot_control_layout.addWidget(self.run_display)

    '''

    def add_models(self, models: List[RunModel]) -> None:
        """
        Add new run controllers to manage.

        Parameters
        ----------
        controllers : List[RunModel]
            List of controllers to add
        """
        if not isinstance(models, (list, tuple)):
            models = [models]

        # Disconnect old controllers
        for model in self._models:
            try:
                model.data_updated.disconnect(self._on_data_updated)
                model.line_removed.disconnect(self._on_line_removed)
            except (TypeError, RuntimeError):
                # Ignore if signals were not connected
                pass

        # Create new list with unique controllers
        new_models = []
        existing_ids = {id(m) for m in self._models}

        for model in models:
            if id(model) not in existing_ids:
                new_models.append(model)
                existing_ids.add(id(model))

        # Connect new controllers
        self._models.extend(new_models)
        for model in new_models:
            model.data_updated.connect(self._on_data_updated)
            model.line_removed.connect(self._on_line_removed)
            model.set_dynamic(self.dynamic_update.get_state()["dynamic"])

        # Update display
        self.run_display.set_models(self._models)

        # Update metadata with last controller's run
        if new_models:  # Only update if we actually added new controllers
            self.update_metadata_tab(new_models[-1].run_data.run.metadata)

    def _on_auto_add_changed(self) -> None:
        """Handle auto add state changes."""
        if self.auto_add.get_state()["auto_add"]:
            self.update_plot()

    def _on_dynamic_changed(self) -> None:
        """Handle dynamic update state changes."""
        is_dynamic = self.dynamic_update.get_state()["dynamic"]
        for model in self._models:
            model.set_dynamic(is_dynamic)

    def _on_transform_changed(self) -> None:
        """Handle transform state changes."""
        transform_state = self.transform.get_state()
        for model in self._models:
            model.run_data.set_transform(transform_state["text"])

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
        for model in self._models:
            model.cleanup()
        self._models.clear()

        # Clear display
        self.run_display.set_models([])

        # Clear plot
        self.plot.clearPlot()

    def update_plot(self) -> None:
        """Update the plot with current selection."""
        if not self._models:
            return

        # Get data from all controllers
        for model in self._models:
            model.update_plot()
    '''
