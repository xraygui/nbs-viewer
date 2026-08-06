from qtpy.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QListView,
    QMessageBox,
    QMenu,
    QAction,
    QComboBox,
    QDialog,
)
from qtpy.QtCore import Qt, Signal
from ..display.displayControl import DisplayControlWidget
from ...models.plot.combinedRunModel import CombinationMethod, CombineError
from ...models.plot.runModel import RunModel
from ..plot.metadataView import FullMetadataBrowser
from typing import List
from nbs_viewer.utils import get_top_level_model
from .expressionBuilder import ExpressionBuilderDialog


# TODO: Should move closer to DataSourceSwitcher (which also needs cleanup)
class RunListView(QWidget):
    """
    Widget for managing run selection for a display.

    Provides a list interface for adding/removing runs and managing their
    selection state.

    Signals
    -------
    selectionChanged : Signal
        Emitted when selection state changes (List[CatalogRun], display_id)
    """

    selectionChanged = Signal(list, str)  # (List[CatalogRun], display_id)

    def __init__(self, run_list_model, display_manager, display_id: str, parent=None):
        """
            Initialize the RunListView
        .

            Parameters
            ----------
            run_list_model : RunListModel
                Model to display and manage runs for
            display_manager : DisplayManager
                Model managing available displays
            display_id : str
                Identifier for the display this list manages
            parent : QWidget, optional
                Parent widget, by default None
        """
        super().__init__(parent)
        self.run_list_model = run_list_model
        self.display_id = display_id
        self._handling_selection = False
        self._metadata_browser_dialog = None

        # Create widgets
        self.list_view = QListView(self)
        self.list_view.setModel(self.run_list_model)
        self.list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self.showContextMenu)
        self.list_view.setSelectionMode(QListView.ExtendedSelection)

        self.display_controls = DisplayControlWidget(
            display_manager, run_list_model, self
        )
        button_layout = QHBoxLayout()
        self.remove_button = QPushButton("Remove Selected Runs")
        self.remove_button.setToolTip(
            "Permanently remove selected runs from this display"
        )

        # Add combine dropdown and button
        self.combine_method_combo = QComboBox()
        self.combine_method_combo.addItems(["Sum", "Average", "Custom Expression"])
        self.combine_method_combo.setToolTip("Select combination method")

        self.combine_button = QPushButton("Combine Selected Runs")
        self.combine_button.setToolTip("Create a combined run from selected runs")

        self.freeze_button = QPushButton("Freeze Selected Runs")
        self.freeze_button.setToolTip("Freeze selected runs")

        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.combine_method_combo)
        button_layout.addWidget(self.combine_button)
        button_layout.addWidget(self.freeze_button)
        # Connect signals
        self.combine_button.clicked.connect(self._combine_selected_runs)
        self.remove_button.clicked.connect(self._remove_selected)
        self.freeze_button.clicked.connect(self._freeze_selected_runs)

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.list_view)
        layout.addLayout(button_layout)
        layout.addWidget(self.display_controls)

        # The RunListViewModel handles all the model connections automatically

    def _remove_selected(self):
        """Remove selected runs from both the list widget and plot model."""
        selected_runs = self.get_selected_runs()
        uids_to_remove = [run.uid for run in selected_runs]

        # Remove from plot model
        self.run_list_model.remove_uids(uids_to_remove)

    def get_selected_runs(self) -> List[RunModel]:
        """Get the currently selected runs."""
        selected_indexes = self.list_view.selectedIndexes()
        selected_runs = []

        for index in selected_indexes:
            if index.column() == 0:  # Only process first column
                run = self.run_list_model.get_run_at_index(index)
                if run:
                    selected_runs.append(run)

        return selected_runs

    def deselect_all(self):
        """Deselect all items in the list widget."""
        self.list_view.clearSelection()

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
        self.run_list_model.add_run(plotItem)
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
        self.run_list_model.remove_run(plotItem)

    def _combine_selected_runs(self):
        """Create a combined run from selected runs."""
        selected_runs = self.get_selected_runs()
        try:
            self.run_list_model.validate_combine(selected_runs)
        except CombineError as e:
            QMessageBox.warning(self, "Cannot Combine", str(e))
            return

        method_text = self.combine_method_combo.currentText()

        if method_text == "Custom Expression":
            dialog = ExpressionBuilderDialog(selected_runs, self)
            if dialog.exec_() != QDialog.Accepted:
                return
            method = CombinationMethod.EXPRESSION
            expression = dialog.expression
        else:
            method_mapping = {
                "Sum": CombinationMethod.SUM,
                "Average": CombinationMethod.AVERAGE,
            }
            method = method_mapping[method_text]
            expression = None

        try:
            self.run_list_model.combine_runs(
                selected_runs, method=method, expression=expression
            )
        except CombineError as e:
            QMessageBox.warning(self, "Cannot Combine", str(e))
            return

        self.list_view.clearSelection()

    def _freeze_selected_runs(self):
        """Freeze selected runs."""
        self.run_list_model.freeze_runs(self.get_selected_runs())

    def uncheck_selected_runs(self):
        """Uncheck all selected runs."""
        uids = [run.uid for run in self.get_selected_runs()]
        self.run_list_model.set_uids_visible(uids, False)

    def check_selected_runs(self):
        """Check all selected runs."""
        uids = [run.uid for run in self.get_selected_runs()]
        self.run_list_model.set_uids_visible(uids, True)

    def move_selected_runs_to_new_display(self, display_type: str):
        runs = self.get_selected_runs()
        self._remove_selected()
        top_level_model = get_top_level_model()
        top_level_model.display_manager.create_display_with_runs(runs, display_type)

    def copy_selected_runs_to_new_display(self, display_type: str):
        top_level_model = get_top_level_model()
        runs = self.get_selected_runs()
        top_level_model.display_manager.create_display_with_runs(runs, display_type)

    def move_selected_runs_to_display(self, display_id: str):
        runs = self.get_selected_runs()
        self._remove_selected()
        top_level_model = get_top_level_model()
        top_level_model.display_manager.add_runs_to_display(runs, display_id)

    def copy_selected_runs_to_display(self, display_id: str):
        runs = self.get_selected_runs()
        top_level_model = get_top_level_model()
        top_level_model.display_manager.add_runs_to_display(runs, display_id)

    def showContextMenu(self, pos):
        """
        Show context menu for run management.

        Parameters
        ----------
        pos : QPoint
            Position where the context menu should appear
        """
        # Get the index at the clicked position
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            return

        # Get selected runs
        selected_runs = self.get_selected_runs()
        if not selected_runs:
            return
        clicked_run = self.run_list_model.get_run_at_index(index)
        if clicked_run is None:
            return

        menu = QMenu(self)
        app_model = get_top_level_model()
        # Add to new display
        uncheck_action = QAction("Uncheck Selected Runs", self)
        uncheck_action.triggered.connect(self.uncheck_selected_runs)
        uncheck_action.setToolTip("Stop plotting selected runs")
        menu.addAction(uncheck_action)

        check_action = QAction("Check Selected Runs", self)
        check_action.triggered.connect(self.check_selected_runs)
        check_action.setToolTip("Plot selected runs")
        menu.addAction(check_action)

        browse_action = QAction("Browse Metadata", self)
        browse_action.setToolTip("Open metadata browser for this run")
        browse_action.triggered.connect(
            lambda checked=False, run=clicked_run: self._browse_metadata_for_run(run)
        )
        menu.addAction(browse_action)

        menu.addSeparator()

        new_canvas_menu = QMenu("Move to New Display", self)
        display_types = app_model.display_manager.get_available_display_types()
        for display_type in display_types:
            metadata = app_model.display_manager.get_display_metadata(display_type)
            display_name = metadata.get("name", display_type)
            action = QAction(display_name, self)
            action.setToolTip(
                f"Create a new {display_type} display and move selected runs to it"
            )
            action.triggered.connect(
                lambda checked, name=display_type: self.move_selected_runs_to_new_display(
                    name
                )
            )
            new_canvas_menu.addAction(action)
        menu.addMenu(new_canvas_menu)

        new_canvas_copy_menu = QMenu("Copy to New Display", self)
        display_types = app_model.display_manager.get_available_display_types()
        for display_type in display_types:
            metadata = app_model.display_manager.get_display_metadata(display_type)
            display_name = metadata.get("name", display_type)
            action = QAction(display_name, self)
            action.setToolTip(
                f"Create a new {display_type} display and copy selected runs to it"
            )
            action.triggered.connect(
                lambda checked, name=display_type: self.copy_selected_runs_to_new_display(
                    name
                )
            )
            new_canvas_copy_menu.addAction(action)
        menu.addMenu(new_canvas_copy_menu)
        menu.addSeparator()
        # Add submenu for existing displays
        available_displays = app_model.display_manager.get_display_ids()
        # We can't move a run to the same display or the main display
        available_displays = [
            d for d in available_displays if d not in [self.display_id, "main"]
        ]
        if available_displays:
            move_menu = QMenu("Move to Display", self)
            for display_name in available_displays:
                action = QAction(display_name, self)
                action.triggered.connect(
                    lambda checked, name=display_name: self.move_selected_runs_to_display(
                        name
                    )
                )
                action.setToolTip(f"Move selected runs to {display_name}")
                move_menu.addAction(action)
            menu.addMenu(move_menu)

            move_menu = QMenu("Copy to Display", self)
            for display_name in available_displays:
                action = QAction(display_name, self)
                action.triggered.connect(
                    lambda checked, name=display_name: self.copy_selected_runs_to_display(
                        name
                    )
                )
                action.setToolTip(f"Copy selected runs to {display_name}")
                move_menu.addAction(action)
            menu.addMenu(move_menu)

        menu.addSeparator()

        # Remove from current display
        remove_action = QAction("Remove from Display", self)
        remove_action.setToolTip("Permanently remove selected runs from this display")
        remove_action.triggered.connect(self._remove_selected)
        menu.addAction(remove_action)

        menu.exec_(self.list_view.mapToGlobal(pos))

    def _browse_metadata_for_run(self, run):
        runs = self.run_list_model.available_models
        if not runs:
            return
        self._metadata_browser_dialog = FullMetadataBrowser(
            runs, selected_run=run, parent=self
        )
        self._metadata_browser_dialog.show()
        self._metadata_browser_dialog.raise_()
        self._metadata_browser_dialog.activateWindow()
