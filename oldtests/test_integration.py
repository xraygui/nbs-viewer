#!/usr/bin/env python3
"""
Test script to verify the expression builder integration.
"""

import sys
from qtpy.QtWidgets import QApplication
from nbs_viewer.views.dataSource.runListView import ExpressionBuilderDialog


class MockRun:
    """Mock run object for testing."""

    def __init__(self, name, scan_id):
        self.name = name
        self.scan_id = scan_id
        self.uid = f"run_{name.lower()}"


def test_expression_dialog():
    """Test the expression builder dialog."""
    app = QApplication(sys.argv)

    # Create mock runs
    runs = [
        MockRun("Baseline", "scan_001"),
        MockRun("Sample1", "scan_002"),
        MockRun("Sample2", "scan_003"),
        MockRun("Reference", "scan_004"),
    ]

    # Create and show dialog
    dialog = ExpressionBuilderDialog(runs)
    result = dialog.exec_()

    if result == dialog.Accepted:
        print(f"Expression: {dialog.expression}")
        print("Dialog accepted!")
    else:
        print("Dialog cancelled")

    return result


if __name__ == "__main__":
    test_expression_dialog()

