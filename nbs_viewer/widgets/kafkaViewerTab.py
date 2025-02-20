print("In KafkaViewerTab.py")

import nslsii
from bluesky_widgets.qt.kafka_dispatcher import QtRemoteDispatcher
import uuid

from ..views.catalog.kafka import KafkaView
from ..models.catalog.kafka import KafkaCatalog

from ..models.plot.plotModel import PlotModel
from ..views.plot.plotWidget import PlotWidget

from qtpy.QtCore import Signal
from qtpy.QtWidgets import QWidget, QHBoxLayout, QSplitter
from qtpy.QtCore import Qt


def make_kafka_source(
    config_file, beamline_acronym, topic_string="bluesky.runengine.documents"
):
    kafka_config = nslsii.kafka_utils._read_bluesky_kafka_config_file(
        config_file_path=config_file
    )

    # this consumer should not be in a group with other consumers
    #   so generate a unique consumer group id for it
    unique_group_id = f"echo-{beamline_acronym}-{str(uuid.uuid4())[:8]}"
    topics = [f"{beamline_acronym}.{topic_string}"]
    kafka_dispatcher = QtRemoteDispatcher(
        topics,
        ",".join(kafka_config["bootstrap_servers"]),
        unique_group_id,
        consumer_config=kafka_config["runengine_producer_config"],
    )
    catalog = KafkaCatalog(kafka_dispatcher)
    kafka_widget = KafkaView(catalog)
    return kafka_widget, catalog


class KafkaViewerTab(QWidget):
    name = "Data Viewer"
    signal_update_widget = Signal(object)

    def __init__(self, model, parent=None):
        print("KafkaViewerTab init")
        super().__init__(parent)
        self.model = model
        self.config = model.settings.gui_config
        bl_acronym = self.config.get("kafka", {}).get("bl_acronym", "")
        kafka_config = self.config.get("kafka", {}).get("config_file", "")
        topic_string = self.config.get("kafka", {}).get(
            "topic_string", "bluesky.runengine.documents"
        )
        print(f"KafkaViewerTab config: {bl_acronym}, {kafka_config}, {topic_string}")
        kafkaSource, catalog = make_kafka_source(
            config_file=kafka_config,
            beamline_acronym=bl_acronym,
            topic_string=topic_string,
        )
        self.kafkaSource = kafkaSource
        self.catalog = catalog

        self.plotModel = PlotModel()
        self.catalog.item_selected.connect(self.plotModel.add_run)
        self.catalog.item_deselected.connect(self.plotModel.remove_run)
        self.plotWidget = PlotWidget(self.plotModel)

        self.layout = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Horizontal)
        self.layout.addWidget(self.splitter)

        # Add widgets to splitter
        self.splitter.addWidget(self.kafkaSource)
        self.splitter.addWidget(self.plotWidget)

        self.setLayout(self.layout)
        print("KafkaViewerTab init done")
