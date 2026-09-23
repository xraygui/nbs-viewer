#!/usr/bin/env python3
"""
Test UI for expression-based run combination.

This is a standalone test widget to validate the user experience
for building mathematical expressions with run variables.
"""

import sys
from qtpy.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QSplitter,
    QGroupBox,
    QGridLayout,
    QMessageBox,
)
from qtpy.QtCore import Qt
from qtpy.QtGui import QFont


class MockRun:
    """Mock run object for testing."""

    def __init__(self, name, scan_id, plan_name):
        self.name = name
        self.scan_id = scan_id
        self.plan_name = plan_name
        self.uid = f"run_{name.lower()}"

    def __str__(self):
        return f"{self.name} ({self.scan_id})"


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


class ExpressionBuilderWidget(QWidget):
    """Test widget for building run combination expressions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.runs = []
        self.setup_ui()
        self.populate_mock_data()

    def setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("Expression Builder Test")
        self.setGeometry(100, 100, 800, 600)

        # Main layout
        main_layout = QVBoxLayout(self)

        # Title
        title = QLabel("Run Combination Expression Builder")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        main_layout.addWidget(title)

        # Create splitter for main content
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel: Run list and variable mapping
        left_panel = self.create_left_panel()
        splitter.addWidget(left_panel)

        # Right panel: Expression builder
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)

        # Set splitter proportions
        splitter.setSizes([400, 400])

        # Bottom panel: Actions
        bottom_panel = self.create_bottom_panel()
        main_layout.addWidget(bottom_panel)

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

    def create_bottom_panel(self):
        """Create the bottom panel with action buttons."""
        panel = QWidget()
        layout = QHBoxLayout(panel)

        # Test expression button
        self.test_button = QPushButton("Test Expression")
        self.test_button.clicked.connect(self.test_expression)
        layout.addWidget(self.test_button)

        # Clear button
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self.clear_expression)
        layout.addWidget(self.clear_button)

        # Status label
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        layout.addStretch()

        return panel

    def populate_mock_data(self):
        """Populate the widget with mock run data."""
        # Create mock runs
        mock_runs = [
            MockRun("Baseline", "scan_001", "count"),
            MockRun("Sample1", "scan_002", "count"),
            MockRun("Sample2", "scan_003", "count"),
            MockRun("Reference", "scan_004", "count"),
            MockRun("Dark", "scan_005", "count"),
        ]

        self.runs = mock_runs

        # Populate runs list with variable mapping
        self.update_runs_list()

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
        self.update_runs_list()
        self.status_label.setText(f"Runs reordered - variable mapping updated")

    def update_runs_list(self):
        """Update the runs list with current variable mapping."""
        self.runs_list.clear()

        for i, run in enumerate(self.runs):
            variable_name = excel_column_name(i)
            item_text = f"{variable_name} → {run.name} ({run.scan_id})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, run)
            self.runs_list.addItem(item)

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

    def test_expression(self):
        """Test the current expression."""
        expression = self.expression_input.toPlainText().strip()

        if not expression:
            self.status_label.setText("No expression entered")
            return

        # TODO: Add actual expression parsing and validation
        self.status_label.setText(f"Expression: {expression}")

        # Show a simple validation message
        QMessageBox.information(
            self,
            "Expression Test",
            f"Expression: {expression}\n\nThis is a test - actual parsing not implemented yet.",
        )

    def clear_expression(self):
        """Clear the expression input."""
        self.expression_input.clear()
        self.status_label.setText("Ready")


def main():
    """Main function to run the test UI."""
    app = QApplication(sys.argv)

    # Test the Excel column naming
    print("Testing Excel column naming:")
    for i in range(30):
        print(f"{i}: {excel_column_name(i)}")

    # Create and show the test widget
    widget = ExpressionBuilderWidget()
    widget.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
