from qtpy.QtWidgets import (
    QHeaderView,
    QMenu,
    QAction,
    QTableView,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QLineEdit,
    QComboBox,
    QHBoxLayout,
    QLabel,
)
from qtpy.QtCore import Qt
from .base import CatalogTableView, CustomHeaderView


class KafkaView(CatalogTableView):
    """Widget for displaying and managing Kafka streams.

    Parameters
    ----------
    dispatcher : object
        The Kafka document dispatcher
    topics : list
        List of Kafka topics to subscribe to
    parent : QWidget, optional
        Parent widget, by default None
    """

    def _setup_ui(self):
        """
        Set up the user interface components.
        """
        self.data_view = QTableView(self)
        data_header = CustomHeaderView(Qt.Horizontal, self.data_view)
        self.data_view.setHorizontalHeader(data_header)
        self.data_view.setSelectionBehavior(QTableView.SelectRows)
        self.data_view.setSelectionMode(QTableView.ExtendedSelection)

        self.invertButton = QPushButton("Reverse Data", self)
        self.invertButton.setEnabled(False)

        self.scrollToBottomButton = QPushButton("Scroll to Bottom", self)
        self.scrollToBottomButton.clicked.connect(self.data_view.scrollToBottom)

        self.scrollToTopButton = QPushButton("Scroll to Top", self)
        self.scrollToTopButton.clicked.connect(self.data_view.scrollToTop)

        self.filterLineEdit = QLineEdit(self)
        self.filterComboBox = QComboBox(self)

        filterLayout = QHBoxLayout()
        filterLayout.addWidget(QLabel("RegEx Filter"))
        filterLayout.addWidget(self.filterLineEdit)
        filterLayout.addWidget(self.filterComboBox)

        scrollLayout = QHBoxLayout()
        scrollLayout.addWidget(self.scrollToTopButton)
        scrollLayout.addWidget(self.scrollToBottomButton)

        layout = QVBoxLayout()
        layout.addLayout(filterLayout)
        layout.addLayout(scrollLayout)
        layout.addWidget(self.invertButton)
        layout.addWidget(self.data_view)
        self.setLayout(layout)

    def refresh_filters(self):
        self.setupModelAndView(self._catalog)
