from qtpy.QtWidgets import (
    QApplication,
    QDateEdit,
    QWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
)
from qtpy.QtCore import QDate
from databroker.queries import TimeRange


class ScantypeSearch(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = QHBoxLayout(self)
        self.label = QLabel("Scan type")
        self.typeInput = QLineEdit()
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.typeInput)

    def filter_catalog(self, catalog):
        scantype = self.typeInput.text()
        if scantype == "":
            return catalog
        else:
            return catalog.filter_by_scantype([scantype])


class DateSearchWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.layout = QHBoxLayout(self)

        self.from_label = QLabel("From", self)
        self.from_date_edit = QDateEdit(self)
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDate(QDate.currentDate().addMonths(-1))

        self.until_label = QLabel("Until", self)
        self.until_date_edit = QDateEdit(self)
        self.until_date_edit.setCalendarPopup(True)
        self.until_date_edit.setDate(QDate.currentDate())

        self.layout.addWidget(self.from_label)
        self.layout.addWidget(self.from_date_edit)
        self.layout.addWidget(self.until_label)
        self.layout.addWidget(self.until_date_edit)

    def get_date_range(self):
        """
        Get the date range from the date edit widgets.

        Returns
        -------
        tuple
            A tuple containing the from_date and until_date in "yyyy-MM-dd" format.
            The until_date is incremented by one day to include the end date in the range.
        """
        from_date = self.from_date_edit.date().toString("yyyy-MM-dd")
        until_date = self.until_date_edit.date().addDays(1).toString("yyyy-MM-dd")
        return from_date, until_date

    def filter_catalog(self, catalog):
        from_date, until_date = self.get_date_range()
        return catalog.search(TimeRange(since=from_date, until=until_date))
        # return catalog.filter_by_time(since=from_date, until=until_date)


if __name__ == "__main__":
    app = QApplication([])
    widget = DateSearchWidget()
    widget.show()
    app.exec_()
