from qtpy.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QLabel,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QStackedWidget,
    QTableView,
    QFileDialog,
)
from qtpy.QtCore import Signal, QSortFilterProxyModel
from tiled.client import from_uri, from_profile

import nslsii.kafka_utils
from bluesky_widgets.qt.kafka_dispatcher import QtRemoteDispatcher
from databroker import temp as temporaryDB
import uuid

from .catalogTree import CatalogPicker
from .catalogTable import CatalogTableModel
from .plotItem import PlotItem
from os.path import exists
from .catalogView import CatalogTableView
from .catalogModel import load_catalog_models

import toml


class ConfigSource(QWidget):

    def __init__(self, catalog_config, parent=None):
        super().__init__(parent)
        self.catalog_config = catalog_config
        self.catalog_models = load_catalog_models()

    def getSource(self):
        catalog = from_uri(self.catalog_config["url"])
        label = self.catalog_config["label"]

        if self.catalog_config.get("catalog_keys"):
            if isinstance(self.catalog_config["catalog_keys"], list):
                for key in self.catalog_config["catalog_keys"]:
                    catalog = catalog[key]
            elif isinstance(self.catalog_config["catalog_keys"], str):
                catalog = catalog[self.catalog_config["catalog_keys"]]
            else:
                raise ValueError("Invalid catalog_keys format in config")

        selected_model = self.catalog_models[self.catalog_config["catalog_model"]]
        catalog = selected_model(catalog)
        catalogView = CatalogTableView(catalog)
        return catalogView, label


class URISource(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.uri_label = QLabel("URI", self)
        self.uri_edit = QLineEdit(self)
        self.uri_edit.setText("http://localhost:8000")

        uri_hbox = QHBoxLayout()
        uri_hbox.addWidget(self.uri_label)
        uri_hbox.addWidget(self.uri_edit)

        self.profile_label = QLabel("Profile", self)
        self.profile_edit = QLineEdit(self)

        profile_hbox = QHBoxLayout()
        profile_hbox.addWidget(self.profile_label)
        profile_hbox.addWidget(self.profile_edit)

        self.catalog_models = load_catalog_models()

        uri_vstack = QVBoxLayout()
        uri_vstack.addLayout(uri_hbox)
        uri_vstack.addLayout(profile_hbox)

        self.setLayout(uri_vstack)

    def getSource(self):
        catalog = from_uri(self.uri_edit.text())
        label = self.uri_edit.text()
        if self.profile_edit.text() != "":
            catalog = catalog[self.profile_edit.text()]
            label += ":" + self.profile_edit.text()
        test_uid = catalog.items_indexer[0][0]
        # Awful dirty hack
        typical_uid4_len = 36
        if len(test_uid) < typical_uid4_len:
            # Probably not really a UID, and we have a nested catalog
            picker = CatalogPicker(catalog, self)
            if picker.exec_():
                selected_keys = picker.selected_entry
                for key in selected_keys:
                    catalog = catalog[key]
                    label += ":" + key
            else:
                return None, None  # User cancelled the dialog

        # Now that we have the final catalog, show the model selection dialog
        model_dialog = CatalogModelPicker(self.catalog_models, self)
        if model_dialog.exec_():
            selected_model = model_dialog.selected_model
            catalog = selected_model(catalog)
            catalogView = CatalogTableView(catalog)
            return catalogView, label
        else:
            return None, None  # User cancelled the model selection


class ProfileSource(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile_label = QLabel("Profile", self)
        self.profile_edit = QLineEdit(self)

        profile_hbox = QHBoxLayout()
        profile_hbox.addWidget(self.profile_label)
        profile_hbox.addWidget(self.profile_edit)

        self.catalog_models = load_catalog_models()

        profile_vstack = QVBoxLayout()
        profile_vstack.addLayout(profile_hbox)

        self.setLayout(profile_vstack)

    def getSource(self):
        catalog = from_profile(self.profile_edit.text())
        label = self.profile_edit.text()
        test_uid = catalog.items_indexer[0][0]
        # Awful dirty hack
        typical_uid4_len = 36
        if len(test_uid) < typical_uid4_len:
            # Probably not really a UID, and we have a nested catalog
            picker = CatalogPicker(catalog, self)
            if picker.exec_():
                selected_keys = picker.selected_entry
                for key in selected_keys:
                    catalog = catalog[key]
                    label += ":" + key
            else:
                return None, None  # User cancelled the dialog

        # Now that we have the final catalog, show the model selection dialog
        model_dialog = CatalogModelPicker(self.catalog_models, self)
        if model_dialog.exec_():
            selected_model = model_dialog.selected_model
            catalog = selected_model(catalog)
            catalogView = CatalogTableView(catalog)
            return catalogView, label
        else:
            return None, None  # User cancelled the model selection


class KafkaSource(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        default_file = "/etc/bluesky/kafka.yml"
        self.config = QPushButton("Pick Kafka Config File")
        if exists(default_file):
            self.selected_file = default_file
        else:
            self.selected_file = None
        self.file_label = QLabel(f"Current file: {self.selected_file}")
        self.bl_label = QLabel("Beamline Acronym")
        self.bl_input = QLineEdit()
        self.selected_file = None
        layout = QVBoxLayout(self)
        bl_layout = QHBoxLayout()
        bl_layout.addWidget(self.bl_label)
        bl_layout.addWidget(self.bl_input)
        layout.addWidget(self.config)
        layout.addWidget(self.file_label)
        layout.addLayout(bl_layout)
        self.setLayout(layout)
        self.config.clicked.connect(self.makeFilePicker)

    def makeFilePicker(self):
        file_dialog = QFileDialog()
        if file_dialog.exec_():
            self.selected_file = file_dialog.selectedFiles()[0]
            self.file_label.setText(f"Current file: {self.selected_file}")

    def getSource(self):
        config_file = self.selected_file
        beamline_acronym = self.bl_input.text()

        kafka_config = nslsii.kafka_utils._read_bluesky_kafka_config_file(
            config_file_path=config_file
        )

        # this consumer should not be in a group with other consumers
        #   so generate a unique consumer group id for it
        unique_group_id = f"echo-{beamline_acronym}-{str(uuid.uuid4())[:8]}"
        topics = [f"{beamline_acronym}.bluesky.runengine.documents"]
        kafka_dispatcher = QtRemoteDispatcher(
            topics,
            ",".join(kafka_config["bootstrap_servers"]),
            unique_group_id,
            consumer_config=kafka_config["runengine_producer_config"],
        )
        kafka_widget = KafkaView(kafka_dispatcher, topics)
        return kafka_widget, beamline_acronym


class DataSourcePicker(QDialog):
    def __init__(self, config_file=None, parent=None):
        super().__init__(parent)
        self.source_type = QComboBox(self)
        self.layout_switcher = QStackedWidget(self)
        self.data_sources = {}

        if config_file:
            config = toml.load(config_file)
            for catalog in config.get("catalog", []):
                source_name = f"Config: {catalog['label']}"
                config_source = ConfigSource(catalog)
                self.data_sources[source_name] = config_source

        self.data_sources["Tiled URI"] = URISource()
        self.data_sources["Tiled Profile"] = ProfileSource()
        # "Kafka": KafkaSource(),

        for k, s in self.data_sources.items():
            self.source_type.addItem(k)
            self.layout_switcher.addWidget(s)

        self.source_type.currentIndexChanged.connect(self.switch_widget)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.source_type)
        layout.addWidget(self.layout_switcher)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

    def switch_widget(self):
        self.layout_switcher.setCurrentIndex(self.source_type.currentIndex())

    def getSource(self):
        return self.layout_switcher.currentWidget().getSource()


class CatalogModelPicker(QDialog):
    def __init__(self, catalog_models, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Catalog Model")
        self.catalog_models = catalog_models
        self.selected_model = None

        layout = QVBoxLayout(self)

        self.model_combo = QComboBox(self)
        self.model_combo.addItems(self.catalog_models.keys())
        layout.addWidget(QLabel("Select a catalog model:"))
        layout.addWidget(self.model_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def accept(self):
        self.selected_model = self.catalog_models[self.model_combo.currentText()]
        super().accept()


class KafkaView(QWidget):
    add_rows_current_plot = Signal(object)

    def __init__(self, dispatcher, topics, parent=None):
        super().__init__(parent)
        self.dispatcher = dispatcher
        self.dispatcher.setParent(self)
        self.label = QLabel("Subscribe to Kafka topics " + " ".join(topics))
        self.plot_button1 = QPushButton("Add Data to Current Plot", self)
        self.plot_button1.clicked.connect(self.emit_add_rows)
        layout = QVBoxLayout()
        layout.addWidget(self.label)

        self.catalog = temporaryDB()
        self.data_view = QTableView(self)
        self.data_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_model = CatalogTableModel(self.catalog.v2, chunk_size=1)
        self.proxyModel = QSortFilterProxyModel()
        self.proxyModel.setSourceModel(self.table_model)
        self.data_view.setModel(self.proxyModel)

        self.filterLineEdit = QLineEdit()
        self.filterLineEdit.textChanged.connect(self.filterChanged)

        layout.addWidget(self.filterLineEdit)
        layout.addWidget(self.data_view)
        layout.addWidget(self.plot_button1)

        self.setLayout(layout)

        self.dispatcher.subscribe(self.catalog.v1.insert)
        self.dispatcher.subscribe(self.add_run, name="start")
        self.dispatcher.start()

    def emit_add_rows(self):
        selected_rows = self.data_view.selectionModel().selectedRows()
        selected_data = []
        for index in selected_rows:
            if index.column() == 0:  # Check if the column is 0
                key = index.data()  # Get the key from the cell data
                data = PlotItem(
                    self.catalog.v2[key], self.catalog.v2, dynamic=True
                )  # Fetch the data using the key
                selected_data.append(data)
        self.add_rows_current_plot.emit(selected_data)

    def add_run(self, name, doc):
        # self.runs.append(run)
        self.table_model.updateCatalog()

    def filterChanged(self, text):
        # Set the filter regexp based on the text input
        self.proxyModel.setFilterRegExp(text)
        # Assuming we're filtering based on the first column
        self.proxyModel.setFilterKeyColumn(
            2
        )  # Change to the column you want to filter by


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)

        self.custom_widget = DataSelection()
        self.setCentralWidget(self.custom_widget)


if __name__ == "__main__":
    app = QApplication([])
    main = MainWindow()
    main.show()
    app.exec_()