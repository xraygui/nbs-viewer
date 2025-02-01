from qtpy.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QDialog,
    QVBoxLayout,
    QDialogButtonBox,
)


def is_a_container_key(key):
    return len(str(key)) < 36


def fillTree(value, parentItem):
    children = {}
    if not hasattr(value, "keys"):
        return
    for key in value.keys():
        print(key)
        if is_a_container_key(key):
            print("Is container")
            child = QTreeWidgetItem()
            child.setText(0, str(key))
            children[key] = child
        else:
            return
    for key, child in children.items():
        try:
            newval = value[key]
        except Exception as e:
            print(f"Got exception for {key}")
            raise e
        fillTree(newval, child)
        parentItem.addChild(child)


class CatalogPicker(QDialog):
    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        fillTree(catalog, self.tree.invisibleRootItem())
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        layout = QVBoxLayout()
        layout.addWidget(self.tree)
        layout.addWidget(self.buttonBox)
        self.setLayout(layout)

    def accept(self):
        selected_items = self.tree.selectedItems()
        if selected_items:
            item = selected_items[0]
            self.selected_entry = []
            while item is not None:
                self.selected_entry.append(item.text(0))
                item = item.parent()
            self.selected_entry.reverse()
            super().accept()


if __name__ == "__main__":
    from tiled.client import from_uri
    from qtpy.QtWidgets import QApplication

    app = QApplication([])
    catalog = from_uri("https://tiled.nsls2.bnl.gov")

    dialog = CatalogPicker(catalog)
    dialog.tree.expandAll()
    dialog.exec_()

    print(dialog.selected_entry)
