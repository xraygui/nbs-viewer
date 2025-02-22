from qtpy.QtWidgets import QTreeView, QWidget, QVBoxLayout
from qtpy.QtGui import QStandardItemModel, QStandardItem
from qtpy.QtCore import Qt


class MetadataModel(QStandardItemModel):
    """Model for displaying run metadata in a tree structure."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["Key", "Value"])

    def update_metadata(self, runs):
        """
        Update metadata from selected runs.

        Parameters
        ----------
        runs : list
            List of CatalogRun objects
        """
        self.clear()
        self.setHorizontalHeaderLabels(["Key", "Value"])

        if len(runs) > 1:
            # Multiple runs - create parent nodes for each
            for run in runs:
                run_item = QStandardItem(f"Run {run.scan_id}")
                self.appendRow([run_item, QStandardItem()])
                self._add_metadata_dict(run.metadata, run_item)
        elif len(runs) == 1:
            # Single run - show metadata directly
            self._add_metadata_dict(runs[0].metadata, self.invisibleRootItem())

    def _add_metadata_dict(self, md_dict, parent_item, depth=0):
        """
        Recursively add metadata dictionary to tree.

        Parameters
        ----------
        md_dict : dict
            Dictionary of metadata to add
        parent_item : QStandardItem
            Parent item to add children to
        depth : int
            Current recursion depth
        """
        if depth > 10:  # Prevent infinite recursion
            return

        # Sort keys for consistent display
        for key in sorted(md_dict.keys()):
            value = md_dict[key]
            key_item = QStandardItem(str(key))

            if isinstance(value, dict):
                # Dictionary becomes a parent node
                value_item = QStandardItem()
                parent_item.appendRow([key_item, value_item])
                self._add_metadata_dict(value, key_item, depth + 1)
            else:
                # Format value for display
                if value is None:
                    str_value = "None"
                else:
                    try:
                        str_value = str(value)
                    except Exception:
                        str_value = "<unprintable value>"
                value_item = QStandardItem(str_value)
                parent_item.appendRow([key_item, value_item])


class MetadataViewer(QWidget):
    """Widget for displaying run metadata in a tree view."""

    def __init__(self, plot_model, parent=None):
        super().__init__(parent)
        self.plot_model = plot_model

        # Create tree view
        self.tree_view = QTreeView(self)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setUniformRowHeights(True)  # Optimization
        self.metadata_model = MetadataModel(self)
        self.tree_view.setModel(self.metadata_model)

        # Adjust column widths
        self.tree_view.header().setStretchLastSection(True)
        self.tree_view.setColumnWidth(0, 200)  # Key column

        # Layout
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree_view)
        self.setLayout(layout)

        # Connect signals
        self.plot_model.run_selection_changed.connect(self._update_metadata)

    def _update_metadata(self, selected_runs):
        """Update displayed metadata when selection changes."""
        self.metadata_model.update_metadata(selected_runs)

        # Expand top-level items if multiple runs
        if len(selected_runs) > 1:
            for row in range(self.metadata_model.rowCount()):
                index = self.metadata_model.index(row, 0)
                self.tree_view.expand(index)
