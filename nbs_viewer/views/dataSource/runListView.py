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
    QDialogButtonBox,
    QSplitter,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QLabel,
)
from qtpy.QtCore import Qt, Signal
from ..display.displayControl import DisplayControlWidget
from ...models.plot.combinedRunModel import CombinedRunModel, CombinationMethod
from ...models.plot.runModel import RunModel
from ...models.plot.frozenRunModel import FrozenRunModel
from typing import List
from nbs_viewer.utils import get_top_level_model


def excel_column_name(index):
    """
    Convert index to Excel-style column name.

    Parameters
    ----------
    index : int
        Zero-based index (0=A, 1=B, ..., 25=Z, 26=AA, 27=AB, ...)

    Returns
    -------
    str
        Excel-style column name
    """
    result = ""
    while index >= 0:
        result = chr(65 + (index % 26)) + result
        index = index // 26 - 1
    return result


def excel_column_name_to_index(name):
    """
    Convert Excel-style column name to index.
    """
    index = 0
    for c in name:
        index = index * 26 + (ord(c) - ord("A") + 1)
    index -= 1
    return index


def parse_expression(expression):
    """Parse the expression."""
    """
    Parse the expression and replace range expressions with individual variables.

    Returns
    -------
    str
        Parsed expression with expanded variable ranges
    """
    import re

    # Remove all whitespace
    expression = "".join(expression.split())

    # Replace "average" with "mean" (case-insensitive)
    numpy_function_mapping = {
        "average": "mean",
        "sum": "sum",
        "product": "prod",
    }

    def replace_function(match):
        old = match.group(1)
        argument = match.group(2)
        new = numpy_function_mapping[old.lower()]
        return f"{new}({argument},axis=0)"

    for f in numpy_function_mapping.keys():
        pattern = rf"({f})\(([^)]*)\)"
        expression = re.sub(pattern, replace_function, expression, flags=re.IGNORECASE)

    # Replace "count" with "len" (case-insensitive)
    expression = re.sub(r"count", "len", expression, flags=re.IGNORECASE)

    # Find all range expressions like A:E, AA:AC, etc
    pattern = r"([A-Z]+):([A-Z]+)"

    def expand_range(match):
        start_var = match.group(1)
        end_var = match.group(2)

        # Convert to indices
        start_idx = 0
        end_idx = 0

        # Convert start variable (e.g. 'AA' -> 26)
        start_idx = excel_column_name_to_index(start_var)

        # Convert end variable
        end_idx = excel_column_name_to_index(end_var) + 1  # +1 because end is inclusive

        # Generate sequence of variables
        vars = f"runlist[{start_idx}:{end_idx}]"
        return vars

    # Replace all range expressions
    parsed = re.sub(pattern, expand_range, expression)

    def replace_variables(match):
        idx = excel_column_name_to_index(match.group(1))
        return f"runlist[{idx}]"

    parsed = re.sub(r"([A-Z]+)", replace_variables, parsed)

    return parsed


class ExpressionBuilderDialog(QDialog):
    """Dialog for building custom run combination expressions."""

    def __init__(self, runs, parent=None):
        super().__init__(parent)
        self.runs = runs
        self.expression = ""
        self.setup_ui()
        self.populate_runs()

    def setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Custom Expression Builder")
        self.setGeometry(100, 100, 800, 600)

        # Main layout
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Build Custom Run Combination Expression")
        title.setStyleSheet("QLabel { font-weight: bold; font-size: 14px; }")
        title.setMaximumHeight(25)
        layout.addWidget(title)

        # Create splitter for main content
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Left panel: Run list with variable mapping
        left_panel = self.create_left_panel()
        splitter.addWidget(left_panel)

        # Right panel: Expression builder
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)

        # Set splitter proportions
        splitter.setSizes([400, 400])

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def create_left_panel(self):
        """Create the left panel with run list and variable mapping."""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Run list group with integrated variable mapping
        runs_group = QGroupBox("Selected Runs (drag to reorder)")
        runs_layout = QVBoxLayout(runs_group)

        self.runs_list = QListWidget()
        self.runs_list.setMaximumHeight(300)
        self.runs_list.setDragDropMode(QListWidget.InternalMove)
        self.runs_list.model().rowsMoved.connect(self.on_runs_reordered)
        runs_layout.addWidget(self.runs_list)

        # Add group to layout
        layout.addWidget(runs_group)

        return panel

    def create_right_panel(self):
        """Create the right panel with expression builder."""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        # Expression input group
        expr_group = QGroupBox("Expression Builder")
        expr_layout = QVBoxLayout(expr_group)

        # Instructions
        instructions = QLabel(
            "Enter a mathematical expression using variables A, B, C, etc.\n"
            "• Select text and click function buttons to wrap with functions\n"
            "• Available functions: SUM, AVERAGE, PRODUCT, COUNT\n"
            "• Examples: A + B + C, (A + B)/(C + D), SUM(A:C), PRODUCT(A, B, C)"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("QLabel { color: #666; font-size: 10px; }")
        expr_layout.addWidget(instructions)

        # Expression input
        self.expression_input = QTextEdit()
        self.expression_input.setMaximumHeight(100)
        self.expression_input.setPlaceholderText("Enter expression here...")
        expr_layout.addWidget(self.expression_input)

        # Function buttons
        functions_layout = QHBoxLayout()

        function_buttons = [
            ("SUM", "SUM()"),
            ("AVERAGE", "AVERAGE()"),
            ("PRODUCT", "PRODUCT()"),
            ("COUNT", "COUNT()"),
        ]

        for name, template in function_buttons:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, n=name: self.insert_function(n))
            functions_layout.addWidget(btn)

        expr_layout.addLayout(functions_layout)

        # Operator buttons
        operators_layout = QHBoxLayout()

        operator_buttons = [
            ("+", " + "),
            ("-", " - "),
            ("*", " * "),
            ("/", " / "),
            ("(", "("),
            (")", ")"),
        ]

        for name, template in operator_buttons:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, t=template: self.insert_operator(t))
            operators_layout.addWidget(btn)

        expr_layout.addLayout(operators_layout)

        # Add group to layout
        layout.addWidget(expr_group)

        return panel

    def populate_runs(self):
        """Populate the runs list with variable mapping."""
        self.runs_list.clear()

        for i, run in enumerate(self.runs):
            variable_name = excel_column_name(i)
            item_text = f"{variable_name} → Scan {run.scan_id}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, run)
            self.runs_list.addItem(item)

    def on_runs_reordered(self, parent, start, end, destination, row):
        """Handle run reordering and update variable mapping."""
        # Rebuild the runs list based on current QListWidget order
        self.runs = []
        for i in range(self.runs_list.count()):
            item = self.runs_list.item(i)
            if item:
                run = item.data(Qt.UserRole)
                if run:
                    self.runs.append(run)

        # Update the display with new variable mapping
        self.populate_runs()

    def insert_function(self, function_name):
        """Insert a function, wrapping selected text if any."""
        cursor = self.expression_input.textCursor()

        # Get selected text
        selected_text = cursor.selectedText()

        if selected_text:
            # Wrap selected text with function
            new_text = f"{function_name}({selected_text})"
            cursor.insertText(new_text)
        else:
            # Insert function template
            template = f"{function_name}()"
            cursor.insertText(template)

        self.expression_input.setFocus()

    def insert_operator(self, operator):
        """Insert an operator into the expression."""
        cursor = self.expression_input.textCursor()
        cursor.insertText(operator)
        self.expression_input.setFocus()

    def accept(self):
        """Handle dialog acceptance."""
        self.expression = parse_expression(self.expression_input.toPlainText().strip())
        if not self.expression:
            QMessageBox.warning(self, "No Expression", "Please enter an expression.")
            return

        super().accept()


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

    def _check_run_compatibility(self, runs: List[RunModel]):
        """
        Check if runs are compatible for combination.

        Parameters
        ----------
        runs : List[RunModel]
            List of runs to check for compatibility

        Returns
        -------
        bool
            True if runs are compatible, False otherwise
        """
        if len(runs) < 2:
            return True

        try:
            # Get common keys across all runs
            common_keys = set(runs[0].available_keys)
            for run in runs[1:]:
                common_keys &= set(run.available_keys)

            if not common_keys:
                QMessageBox.warning(
                    self,
                    "Incompatible Runs",
                    "Selected runs have no common data keys. Cannot combine runs with completely different data structures.",
                )
                return False

            # Try to find a suitable key for shape comparison
            test_key = None
            preferred_keys = ["time"]

            # Look for preferred keys first
            for key in preferred_keys:
                if key in common_keys:
                    test_key = key
                    break

            # If no preferred key found, use the first common key
            if test_key is None:
                test_key = list(common_keys)[0]

            # Check if all runs have the same shape for the test key
            shapes = []
            for run in runs:
                try:
                    shape = run._run.getShape(test_key)
                    shapes.append(shape)
                except Exception:
                    QMessageBox.warning(
                        self,
                        "Data Access Error",
                        f"Could not access data for key '{test_key}' in one or more runs.",
                    )
                    return False

            # Check if all shapes are the same
            if len(set(shapes)) > 1:
                QMessageBox.warning(
                    self,
                    "Incompatible Data Shapes",
                    f"Selected runs have different data shapes for key '{test_key}': {shapes}. "
                    "All runs must have the same data dimensions to be combined.",
                )
                return False

            return True

        except Exception as e:
            QMessageBox.warning(
                self,
                "Compatibility Check Failed",
                f"Error checking run compatibility: {str(e)}",
            )
            return False

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
        # Get selected items from list view
        selected_runs = self.get_selected_runs()
        if len(selected_runs) < 2:
            QMessageBox.warning(
                self, "Cannot Combine", "Please select at least 2 runs to combine"
            )
            return

        # Check run compatibility
        if not self._check_run_compatibility(selected_runs):
            return

        # Get selected combination method from dropdown
        method_text = self.combine_method_combo.currentText()

        if method_text == "Custom Expression":
            # Show expression builder dialog
            dialog = ExpressionBuilderDialog(selected_runs, self)
            if dialog.exec_() == QDialog.Accepted:
                # For now, create a simple combined run with the expression
                # TODO: Implement actual expression parsing and evaluation
                combined_run = CombinedRunModel(
                    runs=selected_runs,
                    method=CombinationMethod.EXPRESSION,
                    expression=dialog.expression,  # Placeholder
                )

                # Add to plot model
                self.run_list_model.add_run(combined_run)

                # Clear selection
                self.list_view.clearSelection()
        else:
            # Handle simple methods (Sum, Average)
            method_mapping = {
                "Sum": CombinationMethod.SUM,
                "Average": CombinationMethod.AVERAGE,
            }
            selected_method = method_mapping[method_text]

            # Create combined run
            combined_run = CombinedRunModel(runs=selected_runs, method=selected_method)

            # Add to plot model
            self.run_list_model.add_run(combined_run)

            # Clear selection
            self.list_view.clearSelection()

    def _freeze_selected_runs(self):
        """Freeze selected runs."""
        runs = self.get_selected_runs()
        for model in runs:
            uid = model.uid
            run = model.run
            for key in model._selected_y:
                frozen_run = FrozenRunModel(run, key)
                print(f"Adding frozen run: {frozen_run.display_name}")
                self.run_list_model.add_run(frozen_run)

    def uncheck_selected_runs(self):
        """Uncheck all selected runs."""
        uids = [run.uid for run in self.get_selected_runs()]
        self.run_list_model.set_uids_visible(uids, False)

    def check_selected_runs(self):
        """Check all selected runs."""
        uids = [run.uid for run in self.get_selected_runs()]
        self.run_list_model.set_uids_visible(uids, True)

    def move_selected_runs_to_new_display(self, display_type: str):
        self.copy_selected_runs_to_new_display(display_type)
        self._remove_selected()

    def copy_selected_runs_to_new_display(self, display_type: str):
        top_level_model = get_top_level_model()
        runs = self.get_selected_runs()
        top_level_model.display_manager.create_display_with_runs(runs, display_type)

    def move_selected_runs_to_display(self, display_id: str):
        self.copy_selected_runs_to_display(display_id)
        self._remove_selected()

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
