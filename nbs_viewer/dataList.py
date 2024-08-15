from qtpy.QtWidgets import (
    QVBoxLayout,
    QWidget,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
)
from qtpy.QtCore import Signal
from .dataSource import DataSourcePicker


class DataList(QWidget):
    itemsSelected = Signal(list)
    itemsDeselected = Signal(list)
    itemsAdded = Signal(list)

    def __init__(self, config_file=None, parent=None):
        super().__init__(parent)
        self.config_file = config_file

        self.label = QLabel("Data Source")
        self.dropdown = QComboBox(self)
        self.dropdown.currentIndexChanged.connect(self.switch_table)
        self.new_source = QPushButton("New Data Source")
        self.new_source.clicked.connect(self.add_new_source)
        self.plot_button = QPushButton("Add Selected to Plot List", self)
        self.plot_button.clicked.connect(self.add_selected_items)

        # self.itemsSelected.connect(print)
        self.stacked_widget = QStackedWidget()

        hbox_layout = QHBoxLayout()
        hbox_layout.addWidget(self.label)
        hbox_layout.addWidget(self.dropdown)

        layout = QVBoxLayout()
        layout.addLayout(hbox_layout)
        layout.addWidget(self.new_source)
        layout.addWidget(self.stacked_widget)
        layout.addWidget(self.plot_button)
        self.setLayout(layout)

    def add_new_source(self):
        picker = DataSourcePicker(config_file=self.config_file, parent=self)
        if picker.exec_():
            sourceView, label = picker.getSource()
            if sourceView is not None and label is not None:
                sourceView.itemsSelected.connect(self.itemsSelected)
                sourceView.itemsDeselected.connect(self.itemsDeselected)
                self.stacked_widget.addWidget(sourceView)
                self.dropdown.addItem(label)
                self.dropdown.setCurrentIndex(self.dropdown.count() - 1)
            else:
                # User cancelled one of the dialogs, do nothing
                pass

    def switch_table(self):
        self.stacked_widget.setCurrentIndex(self.dropdown.currentIndex())

    def add_selected_items(self):
        current_widget = self.stacked_widget.currentWidget()
        if hasattr(current_widget, "get_selected_items"):
            selected_items = current_widget.get_selected_items()
            if selected_items:
                if hasattr(current_widget, "deselect_items"):
                    current_widget.deselect_items(selected_items)

                for item in selected_items:
                    # print("Disconnecting item")
                    item.disconnect_plot()

                # Emit the selected items
                # print("Emitting items")
                self.itemsAdded.emit(selected_items)

                # Deselect the items
