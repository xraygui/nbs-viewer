from qtpy.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QAbstractItemView,
    QInputDialog,
    QMessageBox,
)
from qtpy.QtCore import Qt, Signal
from .plot.canvasControl import CanvasControlWidget
from ..models.plot.combinedRunModel import CombinedRunModel, CombinationMethod


class CanvasRunList(QWidget):
    """
    Widget for managing run selection for a canvas.

    Provides a list interface for adding/removing runs and managing their
    selection state. Matches DataSourceManager's signal interface for
    consistency.

    Signals
    -------
    selectionChanged : Signal
        Emitted when selection state changes (List[CatalogRun], canvas_id)
    """

    selectionChanged = Signal(list, str)  # (List[CatalogRun], canvas_id)

    def __init__(self, plot_model, canvas_manager, canvas_id: str, parent=None):
        """
        Initialize the CanvasRunList.

        Parameters
        ----------
        plot_model : PlotModel
            Model to display and manage runs for
        canvas_manager : CanvasManager
            Model managing available canvases
        canvas_id : str
            Identifier for the canvas this list manages
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.plot_model = plot_model
        self.canvas_id = canvas_id
        self._handling_selection = False

        # Create widgets
        self.list_widget = QListWidget(self)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.itemChanged.connect(self.handle_item_changed)

        self.canvas_controls = CanvasControlWidget(canvas_manager, plot_model, self)
        self.remove_button = QPushButton("Remove Selected Runs")
        self.remove_button.setToolTip(
            "Permanently remove selected runs from this canvas"
        )

        # Add combine button
        self.combine_button = QPushButton("Combine Selected Runs")
        self.combine_button.clicked.connect(self._combine_selected_runs)

        # Connect signals
        self.remove_button.clicked.connect(self._remove_selected)

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.list_widget)
        layout.addWidget(self.remove_button)
        layout.addWidget(self.combine_button)
        layout.addWidget(self.canvas_controls)

        # Connect to model signals
        self.plot_model.run_added.connect(self._on_run_added)
        self.plot_model.run_removed.connect(self._on_run_removed)
        self.plot_model.visible_runs_changed.connect(self._on_selection_changed)

        # Initialize with current runs
        for run in self.plot_model.available_runs:
            self._add_run_to_list(run)

    def _add_run_to_list(self, run):
        """Add a single run to the list widget."""
        # Get a more descriptive label from metadata
        label = run.display_name

        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, run.uid)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(
            Qt.Checked if run.uid in self.plot_model._visible_runs else Qt.Unchecked
        )
        self.list_widget.addItem(item)

        # Connect checkbox state changes

    def _on_run_added(self, run):
        """Handle new run added to model."""
        self._add_run_to_list(run)

    def _on_run_removed(self, run):
        """Handle run removed from model."""
        items = self.list_widget.findItems(
            str(run.display_name),
            Qt.MatchExactly,
        )
        for item in items:
            if item.data(Qt.UserRole) == run.uid:
                self.list_widget.takeItem(self.list_widget.row(item))

    def _on_selection_changed(self, selected_runs):
        """Update checkbox states to match model's visible runs."""
        # print(f"CanvasRunList _on_selection_changed: {len(selected_runs)}")
        try:
            # Block itemChanged signal to prevent recursion
            self.list_widget.blockSignals(True)

            # Update checkbox states based on visible runs

            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                uid = item.data(Qt.UserRole)
                item.setCheckState(Qt.Checked if uid in selected_runs else Qt.Unchecked)

        finally:
            self.list_widget.blockSignals(False)

    def _remove_selected(self):
        """Remove selected runs from both the list widget and plot model."""
        selected_items = self.list_widget.selectedItems()

        for item in selected_items:
            uid = item.data(Qt.UserRole)
            # Remove from plot model first
            self.plot_model.remove_uids([uid])

            # Remove from list widget
            row = self.list_widget.row(item)
            self.list_widget.takeItem(row)

    def addPlotItem(self, plotItem):
        """
        Add a run or multiple runs to the list widget.

        Parameters
        ----------
        plotItem : PlotItem or list of PlotItem
            The plot item(s) to be added to the list widget.
        """
        if isinstance(plotItem, (list, tuple)):
            for p in plotItem:
                self._addSinglePlotItem(p)
        else:
            self._addSinglePlotItem(plotItem)

    def _addSinglePlotItem(self, plotItem):
        # print("Adding bluesky plot item")
        item = QListWidgetItem(plotItem.description)
        item.setData(Qt.UserRole, plotItem.uid)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.plot_model.add_run(plotItem)
        self.list_widget.addItem(item)
        # print("Done adding bluesky plot item")

    def removePlotItem(self, plotItem):
        """
        Remove a plot item from the list widget based on its UID.

        Parameters
        ----------
        plotItem : PlotItem
            The plot item to be removed from the list widget.
        """
        # print("Removing Plot Item from BlueskyList")
        plotItem.clear()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == plotItem.uid:
                self.list_widget.takeItem(i)
                self.plot_model.remove_run(plotItem)
                break

    def handle_item_changed(self, item):
        """Handle checkbox state changes."""
        uid = item.data(Qt.UserRole)
        # print(f"handle_item_changed: {uid}")
        if uid in self.plot_model.available_uids:
            is_visible = item.checkState() == Qt.Checked
            # print(f"Found Run, setting {uid} to {is_visible}")
            self.plot_model.set_uids_visible([uid], is_visible)

    def _combine_selected_runs(self):
        """Create a combined run from selected runs."""
        # Get selected items from list widget
        selected_items = self.list_widget.selectedItems()
        if len(selected_items) < 2:
            QMessageBox.warning(
                self, "Cannot Combine", "Please select at least 2 runs to combine"
            )
            return

        # Get CatalogRun objects for selected items
        runs = []
        for item in selected_items:
            uid = item.data(Qt.UserRole)
            run_model = self.plot_model._run_models.get(uid)
            if run_model:
                runs.append(run_model.run)

        if len(runs) < 2:  # Double check we got valid runs
            QMessageBox.warning(
                self, "Cannot Combine", "Could not get valid runs from selection"
            )
            return

        # Create combined run
        combined_run = CombinedRunModel(runs=runs, method=CombinationMethod.AVERAGE)

        # Add to plot model
        self.plot_model.add_run(combined_run)

        # Clear selection
        self.list_widget.clearSelection()
