from qtpy.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QSplitter,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QLabel,
)
from qtpy.QtCore import Qt


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


class ExpressionBuilder(QWidget):
    """Widget for building custom run combination expressions."""

    def __init__(self, runs, parent=None):
        super().__init__(parent)
        self.runs = runs
        self.expression = ""
        self.setup_ui()
        self.populate_runs()

    def setup_ui(self):
        """Set up the widget UI."""
        # Main layout
        layout = QVBoxLayout(self)

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

    def get_expression(self):
        """Get the parsed expression."""
        return parse_expression(self.expression_input.toPlainText().strip())

    def get_runs(self):
        """Get the current runs list."""
        return self.runs


class ExpressionBuilderDialog(QDialog):
    """Dialog for building custom run combination expressions."""

    def __init__(self, runs, parent=None):
        super().__init__(parent)
        self.runs = runs
        self.expression = ""
        self.setup_ui()

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

        # Expression builder widget
        self.expression_builder = ExpressionBuilder(self.runs)
        layout.addWidget(self.expression_builder)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self):
        """Handle dialog acceptance."""
        self.expression = self.expression_builder.get_expression()
        if not self.expression:
            QMessageBox.warning(self, "No Expression", "Please enter an expression.")
            return

        super().accept()
