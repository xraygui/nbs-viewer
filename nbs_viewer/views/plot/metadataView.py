from collections.abc import Mapping, Sequence
from qtpy.QtWidgets import (
    QTreeView,
    QWidget,
    QVBoxLayout,
    QMenu,
    QDialog,
)
from qtpy.QtGui import QStandardItemModel, QStandardItem
from qtpy.QtCore import (
    Qt,
    QObject,
    Signal,
    Slot,
    QRunnable,
    QThreadPool,
    QPersistentModelIndex,
)


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


class FullMetadataModel(QStandardItemModel):
    """Model for browsing full run metadata structures."""

    OBJECT_ROLE = Qt.UserRole + 10
    LOADED_ROLE = Qt.UserRole + 11
    DEPTH_ROLE = Qt.UserRole + 12
    LOADING_ROLE = Qt.UserRole + 13
    MAX_DEPTH = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["Key", "Value"])
        self._seen = set()
        self._thread_pool = QThreadPool.globalInstance()

    def load_runs(self, runs):
        """
        Build top-level items for one or more runs.

        Parameters
        ----------
        runs : list
            List of run model objects
        """
        self.clear()
        self.setHorizontalHeaderLabels(["Key", "Value"])
        self._seen = set()
        for run_model in runs:
            label = f"Run {getattr(run_model, 'scan_id', 'Unknown')}"
            root_key = QStandardItem(label)
            root_value = QStandardItem("")
            root_obj = self._get_browse_root(run_model)
            root_key.setData(root_obj, self.OBJECT_ROLE)
            root_key.setData(False, self.LOADED_ROLE)
            root_key.setData(False, self.LOADING_ROLE)
            root_key.setData(0, self.DEPTH_ROLE)
            self.appendRow([root_key, root_value])
            if self._is_expandable(root_obj):
                self._add_placeholder(root_key)
            else:
                root_value.setText(self._format_leaf_value(root_obj))

    def expand_index(self, index):
        """
        Load children for an expanded tree index.

        Parameters
        ----------
        index : QModelIndex
            Expanded index
        """
        if not index.isValid():
            return
        item = self.itemFromIndex(index)
        if item is None:
            return
        if item.data(self.LOADED_ROLE):
            return
        if item.data(self.LOADING_ROLE):
            return
        obj = item.data(self.OBJECT_ROLE)
        depth = item.data(self.DEPTH_ROLE) or 0
        if depth >= self.MAX_DEPTH:
            self._populate_children(item, obj, depth)
            item.setData(True, self.LOADED_ROLE)
            return
        oid = id(obj)
        if oid in self._seen:
            self._populate_children(item, obj, depth)
            item.setData(True, self.LOADED_ROLE)
            return
        self._seen.add(oid)
        self._set_loading_placeholder(item)
        item.setData(True, self.LOADING_ROLE)
        persistent_index = QPersistentModelIndex(index)
        worker = MetadataChildrenWorker(persistent_index, obj)
        worker.signals.finished.connect(self._on_children_loaded)
        self._thread_pool.start(worker)

    def _get_browse_root(self, run_model):
        run = getattr(run_model, "run", run_model)
        class_name = run.__class__.__name__.lower()
        if "bluesky" in class_name or "nbsrun" in class_name:
            return getattr(run, "_run", run)
        if "kafka" in class_name:
            return {
                "start": getattr(run, "start", {}),
                "stop": getattr(run, "_stop_doc", {}),
                "descriptors": getattr(run, "_descriptors", {}),
                "hints": getattr(run, "hints", {}),
                "plot_hints": getattr(run, "_plot_hints", {}),
                "metadata": getattr(run, "metadata", {}),
            }
        return getattr(run, "_run", getattr(run, "metadata", run))

    def _add_placeholder(self, parent_item):
        key_item = QStandardItem("<expand>")
        value_item = QStandardItem("")
        parent_item.appendRow([key_item, value_item])

    def _set_loading_placeholder(self, parent_item):
        self._clear_placeholder_if_present(parent_item)
        key_item = QStandardItem("<loading...>")
        value_item = QStandardItem("")
        parent_item.appendRow([key_item, value_item])

    def _clear_placeholder_if_present(self, parent_item):
        if parent_item.rowCount() != 1:
            return
        child = parent_item.child(0, 0)
        if child is not None and child.text() in {"<expand>", "<loading...>"}:
            parent_item.removeRow(0)

    def _populate_children(self, parent_item, obj, depth):
        self._clear_placeholder_if_present(parent_item)
        if depth >= self.MAX_DEPTH:
            key_item = QStandardItem("<max depth reached>")
            value_item = QStandardItem("")
            parent_item.appendRow([key_item, value_item])
            return

        oid = id(obj)
        if oid in self._seen:
            key_item = QStandardItem("<recursive reference>")
            value_item = QStandardItem("")
            parent_item.appendRow([key_item, value_item])
            return
        self._seen.add(oid)

        children = self._iter_children(obj)
        if not children:
            key_item = QStandardItem("<empty>")
            value_item = QStandardItem("")
            parent_item.appendRow([key_item, value_item])
            return

        for key, value in children:
            key_item = QStandardItem(str(key))
            value_item = QStandardItem(self._format_branch_value(value))
            key_item.setData(value, self.OBJECT_ROLE)
            key_item.setData(False, self.LOADED_ROLE)
            key_item.setData(False, self.LOADING_ROLE)
            key_item.setData(depth + 1, self.DEPTH_ROLE)
            parent_item.appendRow([key_item, value_item])
            if self._is_expandable(value):
                self._add_placeholder(key_item)

    @Slot(object, object, object)
    def _on_children_loaded(self, persistent_index, children, error):
        if not persistent_index.isValid():
            return
        item = self.itemFromIndex(persistent_index)
        if item is None:
            return
        item.setData(False, self.LOADING_ROLE)
        self._clear_placeholder_if_present(item)
        depth = item.data(self.DEPTH_ROLE) or 0
        if error:
            key_item = QStandardItem("<error>")
            value_item = QStandardItem(error)
            item.appendRow([key_item, value_item])
            item.setData(True, self.LOADED_ROLE)
            return
        if not children:
            key_item = QStandardItem("<empty>")
            value_item = QStandardItem("")
            item.appendRow([key_item, value_item])
            item.setData(True, self.LOADED_ROLE)
            return
        for key, value in children:
            key_item = QStandardItem(str(key))
            value_item = QStandardItem(self._format_branch_value(value))
            key_item.setData(value, self.OBJECT_ROLE)
            key_item.setData(False, self.LOADED_ROLE)
            key_item.setData(False, self.LOADING_ROLE)
            key_item.setData(depth + 1, self.DEPTH_ROLE)
            item.appendRow([key_item, value_item])
            if self._is_expandable(value):
                self._add_placeholder(key_item)
        item.setData(True, self.LOADED_ROLE)

    def _iter_children(self, obj):
        return self._iter_children_static(obj)

    @staticmethod
    def _iter_children_static(obj):
        if isinstance(obj, Mapping):
            try:
                return list(obj.items())
            except Exception:
                return []

        if hasattr(obj, "keys") and hasattr(obj, "__getitem__"):
            pairs = []
            try:
                for key in obj.keys():
                    try:
                        pairs.append((key, FullMetadataModel._prepare_value_static(obj[key])))
                    except Exception as exc:
                        pairs.append((key, f"<error reading key: {exc}>"))
                return pairs
            except Exception:
                return []

        if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
            if hasattr(obj, "shape"):
                return []
            max_items = 200
            pairs = []
            try:
                size = len(obj)
            except Exception:
                size = 0
            for idx in range(min(size, max_items)):
                try:
                    pairs.append((idx, FullMetadataModel._prepare_value_static(obj[idx])))
                except Exception as exc:
                    pairs.append((idx, f"<error reading index: {exc}>"))
            if size > max_items:
                pairs.append(("<truncated>", f"{size - max_items} more items"))
            return pairs

        return []

    def _is_expandable(self, value):
        if isinstance(value, Mapping):
            return True
        if hasattr(value, "keys") and hasattr(value, "__getitem__"):
            return True
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            if hasattr(value, "shape"):
                return False
            return True
        return False

    def _format_branch_value(self, value):
        if isinstance(value, Mapping):
            try:
                return f"<dict> ({len(value)} keys)"
            except Exception:
                return "<dict>"
        if hasattr(value, "keys") and hasattr(value, "__getitem__"):
            try:
                return f"<mapping-like> ({len(list(value.keys()))} keys)"
            except Exception:
                return "<mapping-like>"
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if hasattr(value, "shape"):
                try:
                    return f"<array> shape={value.shape}"
                except Exception:
                    return "<array>"
            try:
                return f"<list> ({len(value)} items)"
            except Exception:
                return "<list>"
        return self._format_leaf_value(value)

    def _format_leaf_value(self, value):
        if value is None:
            return "None"
        try:
            text = str(value)
        except Exception:
            return "<unprintable value>"
        if len(text) > 200:
            return text[:197] + "..."
        return text

    @staticmethod
    def _prepare_value_static(value):
        count = FullMetadataModel._estimate_count_static(value)
        if count is None or count > 2:
            return value
        if not hasattr(value, "read"):
            return value
        try:
            read_value = value.read()
        except Exception:
            return value
        return FullMetadataModel._normalize_read_value_static(read_value)

    @staticmethod
    def _estimate_count_static(value):
        if hasattr(value, "shape"):
            try:
                shape = tuple(value.shape)
            except Exception:
                return None
            if len(shape) == 0:
                return 1
            total = 1
            for dim in shape:
                if dim is None:
                    return None
                try:
                    dval = int(dim)
                except Exception:
                    return None
                if dval < 0:
                    return None
                total *= dval
                if total > 2:
                    return total
            return total
        return None

    @staticmethod
    def _normalize_read_value_static(value):
        if hasattr(value, "values"):
            try:
                value = value.values
            except Exception:
                pass
        if hasattr(value, "tolist"):
            try:
                return value.tolist()
            except Exception:
                pass
        return value


class MetadataWorkerSignals(QObject):
    """Signals for background metadata loading."""

    finished = Signal(object, object, object)


class MetadataChildrenWorker(QRunnable):
    """Background worker that reads children for one tree node."""

    def __init__(self, persistent_index, obj):
        super().__init__()
        self.signals = MetadataWorkerSignals()
        self._persistent_index = persistent_index
        self._obj = obj

    @Slot()
    def run(self):
        try:
            children = FullMetadataModel._iter_children_static(self._obj)
            error = None
        except Exception as exc:
            children = []
            error = str(exc)
        self.signals.finished.emit(self._persistent_index, children, error)


class FullMetadataBrowser(QDialog):
    """Dialog window for full metadata browsing."""

    def __init__(self, runs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Browse Metadata")
        self.resize(900, 600)
        self.tree_view = QTreeView(self)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setUniformRowHeights(True)
        self.metadata_model = FullMetadataModel(self)
        self.tree_view.setModel(self.metadata_model)
        self.tree_view.header().setStretchLastSection(True)
        self.tree_view.setColumnWidth(0, 280)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree_view)
        self.setLayout(layout)
        self.metadata_model.load_runs(runs)
        self.tree_view.expanded.connect(self.metadata_model.expand_index)
        for row in range(self.metadata_model.rowCount()):
            index = self.metadata_model.index(row, 0)
            self.tree_view.expand(index)


class MetadataViewer(QWidget):
    """Widget for displaying run metadata in a tree view."""

    def __init__(self, plot_model, parent=None):
        super().__init__(parent)
        self.plot_model = plot_model

        # Create tree view
        self.tree_view = QTreeView(self)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setUniformRowHeights(True)  # Optimization
        self.tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
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
        self.plot_model.visible_runs_changed.connect(self._update_metadata)
        self.tree_view.customContextMenuRequested.connect(self._show_context_menu)
        self._browser_dialog = None

    def _update_metadata(self, selected_runs):
        """Update displayed metadata when selection changes."""

        self.metadata_model.update_metadata(self.plot_model.visible_models)

        # Expand top-level items if multiple runs
        if len(selected_runs) > 1:
            for row in range(self.metadata_model.rowCount()):
                index = self.metadata_model.index(row, 0)
                self.tree_view.expand(index)

    def _show_context_menu(self, pos):
        """
        Show right-click menu for metadata actions.

        Parameters
        ----------
        pos : QPoint
            Position where context menu should appear
        """
        menu = QMenu(self)
        browse_action = menu.addAction("browse metadata")
        browse_action.triggered.connect(self._open_full_metadata_browser)
        menu.exec_(self.tree_view.viewport().mapToGlobal(pos))

    def _open_full_metadata_browser(self):
        """Open popup browser for full metadata navigation."""
        runs = self.plot_model.visible_models
        if not runs:
            return
        self._browser_dialog = FullMetadataBrowser(runs, self)
        self._browser_dialog.show()
        self._browser_dialog.raise_()
        self._browser_dialog.activateWindow()
