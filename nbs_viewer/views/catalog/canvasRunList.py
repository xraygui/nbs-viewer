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
)
from qtpy.QtCore import Qt, Signal
from ...plotItem import CompoundPlotItem
from ...models.plot.plotModel import PlotModel
from ...views.plot.canvasControl import CanvasControlWidget


class CanvasRunList(QWidget):
    """
    Widget for managing run selection for a canvas.

    Provides a list interface for adding/removing runs and managing their
    selection state. Matches DataSourceManager's signal interface for
    consistency.

    Signals
    -------
    selectionChanged : Signal
        Emitted when selection state changes (List[RunData], canvas_id)
    """

    selectionChanged = Signal(list, str)  # (List[RunData], canvas_id)

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

        # Create widgets
        self.list_widget = QListWidget(self)
        self.canvas_controls = CanvasControlWidget(canvas_manager, self)
        self.remove_button = QPushButton("Remove Selected")

        # Connect signals
        self.list_widget.selectionModel().selectionChanged.connect(
            self._handle_selection_change
        )
        self.remove_button.clicked.connect(self._remove_selected)
        self.selectionChanged.connect(self.canvas_controls.handle_run_selection)

        # Single layout setup
        layout = QVBoxLayout(self)
        layout.addWidget(self.list_widget)
        layout.addWidget(self.remove_button)
        layout.addWidget(self.canvas_controls)

        # Connect to model signals
        self.plot_model.run_added.connect(self._on_run_added)
        self.plot_model.run_removed.connect(self._on_run_removed)
        self.plot_model.run_selection_changed.connect(self._on_selection_changed)

        # Initialize with current runs
        for run_data in self.plot_model.available_runs:
            self._add_run_to_list(run_data)

    def _add_run_to_list(self, run_data):
        """Add a single run to the list widget."""
        # Get a more descriptive label from metadata
        label = run_data.display_name

        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, run_data.run.uid)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.list_widget.addItem(item)

        # Connect checkbox state changes
        self.list_widget.itemChanged.connect(self.handle_item_changed)

    def _on_run_added(self, run_data):
        """Handle new run added to model."""
        self._add_run_to_list(run_data)

    def _on_run_removed(self, run_data):
        """Handle run removed from model."""
        items = self.list_widget.findItems(
            str(run_data.display_name),
            Qt.MatchExactly,
        )
        for item in items:
            if item.data(Qt.UserRole) == run_data.run.uid:
                self.list_widget.takeItem(self.list_widget.row(item))

    def _handle_selection_change(self, selected, deselected):
        """Handle selection changes in the list widget."""
        # Get currently selected runs
        selected_data = []
        for index in self.list_widget.selectedIndexes():
            uid = self.list_widget.item(index.row()).data(Qt.UserRole)
            run_data = next(
                (rd for rd in self.plot_model.available_runs if rd.run.uid == uid), None
            )
            if run_data:
                selected_data.append(run_data)

        # Update model selection and emit our selection changed signal
        self.plot_model.select_runs(selected_data)
        self.selectionChanged.emit(selected_data, self.canvas_id)

    def _on_selection_changed(self, selected_runs):
        """
        Update list selection to match model.

        This is called when the plot_model selection changes.
        """
        # Block signals to prevent feedback loop
        self.list_widget.selectionModel().blockSignals(True)

        # Clear current selection
        self.list_widget.clearSelection()

        # Select items corresponding to selected runs
        selected_uids = {run.run.uid for run in selected_runs}
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) in selected_uids:
                item.setSelected(True)

        self.list_widget.selectionModel().blockSignals(False)

    def _remove_selected(self):
        """Remove selected runs from the list."""
        selected_data = []
        for item in self.list_widget.selectedItems():
            uid = item.data(Qt.UserRole)
            run_data = next(
                (rd for rd in self.plot_model.available_runs if rd.run.uid == uid), None
            )
            if run_data:
                selected_data.append(run_data)

        self.plot_model.deselect_runs(selected_data)

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
        run_data = next(
            (rd for rd in self.plot_model.available_runs if rd.run.uid == uid), None
        )
        if run_data:
            is_visible = item.checkState() == Qt.Checked
            self.plot_model.update_visibility(run_data, is_visible)
