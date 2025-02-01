from qtpy.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QFrame,
    QPushButton,
    QLineEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QMessageBox,
    QComboBox,
    QInputDialog,
)
from qtpy.QtCore import Signal


class ExclusiveCheckBoxGroup(QButtonGroup):
    def __init__(self, parent=None):
        super(ExclusiveCheckBoxGroup, self).__init__(parent)
        self.setExclusive(False)  # This allows checkboxes to be unchecked

    def addButton(self, checkbox, id=-1):
        super().addButton(checkbox, id)
        checkbox.clicked.connect(self.enforce_exclusivity)

    def enforce_exclusivity(self, checked):
        if checked:
            clicked_checkbox = self.sender()
            for checkbox in self.buttons():
                if checkbox is not clicked_checkbox:
                    checkbox.setChecked(False)


class MutuallyExclusiveCheckBoxGroups(QWidget):
    buttonsChanged = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(**kwargs)
        self.buttonGroups = args
        for group in self.buttonGroups:
            group.buttonClicked.connect(self.uncheckOtherGroups)

    def addGroup(self, buttonGroup):
        self.buttonGroups.append(buttonGroup)
        buttonGroup.buttonClicked.connect(self.uncheckOtherGroups)

    def uncheckOtherGroups(self, clickedButton):
        for group in self.buttonGroups:
            if clickedButton not in group.buttons():
                defaultExclusivity = group.exclusive()
                group.setExclusive(False)
                for button in group.buttons():
                    button.setChecked(False)
                group.setExclusive(defaultExclusivity)
        self.buttonsChanged.emit()


def getCommonAttr(plotItemList, attr):
    if len(plotItemList) == 0:
        return set()
    first_attr = getattr(plotItemList[0], attr)
    try:
        rows = set(first_attr)
    except TypeError:
        rows = set([first_attr])

    for plotItem in plotItemList:
        rows &= set(getattr(plotItem, attr))
    return rows


def getCommonRows(plotItemList):
    return getCommonAttr(plotItemList, "rows")


def getCommonXKeyDict(plotItemList):
    if len(plotItemList) == 0:
        return dict()

    xdims = set(plotItemList[0].xkeyDict.keys())
    for plotItem in plotItemList:
        xdims &= set(plotItem.xkeyDict.keys())
    xdims = sorted(list(xdims))
    xkeyDict = {}
    for dim in xdims:
        xlist = set(plotItemList[0].xkeyDict[dim])
        for plotItem in plotItemList:
            xlist &= set(plotItem.xkeyDict[dim])
        xkeyDict[dim] = sorted(list(xlist))
    return xkeyDict


def getCommonYKeyDict(plotItemList):
    if len(plotItemList) == 0:
        return dict()
    ydims = set(plotItemList[0].all_ykeyDict.keys())
    for plotItem in plotItemList:
        ydims &= set(plotItem.all_ykeyDict.keys())
    ydims = sorted(list(ydims))

    ykeyDict = {}
    for dim in ydims:
        ylist = set(plotItemList[0].all_ykeyDict[dim])
        for plotItem in plotItemList:
            ylist &= set(plotItem.all_ykeyDict[dim])
        ykeyDict[dim] = sorted(list(ylist))
    return ykeyDict


class PlotControls(QWidget):
    """
    A widget for interactive plotting controls, including a grid of checkboxes
    for selecting X data, Y data, and normalization options. It is designed to
    work with an MPLCanvas or a similar object acting as a Matplotlib FigureCanvas.

    Parameters
    ----------
    plot : MPLCanvas or similar
        The plotting canvas where the data will be displayed.
    parent : QWidget, optional
        The parent widget, by default None.
    """

    DEFAULT_TRANSFORMS = {
        "No Transform": "",
        "Invert (1/y)": "1/y",
        "Normalize to Max": "y/max(y)",
        "Normalize to Min": "y/min(y)",
        "Normalize to Pre/Post edge": "(y - mean(y[:10]))/(mean(y[-10:]) - mean(y[:10]))",
        "Normalize to Sum": "y/sum(y)",
        "Log Scale": "log(y)",
        "Log(1/y)": "log(1/y)",
    }

    def __init__(self, plot, parent=None):
        super().__init__(parent)
        self.plot = plot
        self.data = None
        self.allkeylist = []
        self.plotItemList = []
        self._transforms = self.DEFAULT_TRANSFORMS.copy()

        # Create the tab widget
        self.tab_widget = QTabWidget()

        # Create the plot control tab
        self.plot_control_tab = QWidget()
        self.plot_control_layout = QVBoxLayout(self.plot_control_tab)

        # Create the metadata tab
        self.metadata_tab = QWidget()
        self.metadata_layout = QVBoxLayout(self.metadata_tab)
        self.metadata_tree = QTreeWidget()
        self.metadata_tree.setHeaderLabels(["Key", "Value"])
        self.metadata_layout.addWidget(self.metadata_tree)

        # Add tabs to the tab widget
        self.tab_widget.addTab(self.plot_control_tab, "Plot Controls")
        self.tab_widget.addTab(self.metadata_tab, "Metadata")

        # Main layout
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(self.tab_widget)

        self.setup_plot_control_tab()

    def setup_plot_control_tab(self):
        # Move all the existing layout setup code here
        # Replace all instances of self.layout with self.plot_control_layout

        auto_add_layout = QHBoxLayout()
        auto_add_layout.addWidget(QLabel("Auto Add"))
        self.auto_add_box = QCheckBox()
        self.auto_add_box.setChecked(True)
        self.auto_add_box.clicked.connect(self.checked_changed)
        auto_add_layout.addWidget(self.auto_add_box)
        self.plot_control_layout.addLayout(auto_add_layout)

        dynamic_update_layout = QHBoxLayout()
        dynamic_update_layout.addWidget(QLabel("Dynamic Update"))
        self.dynamic_update_box = QCheckBox()
        self.dynamic_update_box.setChecked(False)

        dynamic_update_layout.addWidget(self.dynamic_update_box)
        self.plot_control_layout.addLayout(dynamic_update_layout)

        show_all_layout = QHBoxLayout()
        show_all_layout.addWidget(QLabel("Show all rows"))
        self.show_all = QCheckBox()
        self.show_all.setChecked(False)
        self.show_all.clicked.connect(self.update_display)
        show_all_layout.addWidget(self.show_all)
        self.plot_control_layout.addLayout(show_all_layout)

        transform_frame = QFrame()
        transform_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        transform_layout = QVBoxLayout(transform_frame)

        transform_header = QHBoxLayout()
        transform_header.addWidget(QLabel("Transform"))
        self.transform_box = QCheckBox()
        self.transform_box.setChecked(False)
        self.transform_box.clicked.connect(self.transform_state_changed)
        transform_header.addWidget(self.transform_box)
        transform_layout.addLayout(transform_header)

        # Transform combo box
        self.transform_combo = QComboBox()
        self.transform_combo.setEnabled(False)
        self.transform_combo.addItems(self._transforms.keys())
        self.transform_combo.currentTextChanged.connect(self.on_transform_selected)
        transform_layout.addWidget(self.transform_combo)

        # Custom transform input
        custom_transform_layout = QHBoxLayout()
        self.transform_text_edit = QLineEdit()
        self.transform_text_edit.setEnabled(False)
        self.transform_text_edit.setPlaceholderText(
            "Enter custom transform (e.g., y/max(y))"
        )
        self.transform_text_edit.editingFinished.connect(
            self.on_custom_transform_changed
        )
        custom_transform_layout.addWidget(self.transform_text_edit)

        save_transform_btn = QPushButton("Save")
        save_transform_btn.clicked.connect(self.save_custom_transform)
        custom_transform_layout.addWidget(save_transform_btn)

        transform_layout.addLayout(custom_transform_layout)
        self.plot_control_layout.addWidget(transform_frame)

        self.grid = QGridLayout()
        self.plot_control_layout.addLayout(self.grid)

        self.update_plot_button = QPushButton("Update Plot")
        self.update_plot_button.clicked.connect(self.update_plot)
        self.update_plot_button.setEnabled(False)

        self.clear_data_button = QPushButton("Uncheck All")
        self.clear_data_button.clicked.connect(self.uncheck_all)
        self.clear_data_button.setEnabled(False)
        self.plot_control_layout.addWidget(self.update_plot_button)
        self.plot_control_layout.addWidget(self.clear_data_button)

    def update_metadata_tab(self, metadata):
        self.metadata_tree.clear()
        self.add_dict_to_tree(metadata, self.metadata_tree.invisibleRootItem())
        self.metadata_tree.expandAll()  # Expand all items

    def add_dict_to_tree(self, dict_obj, parent_item):
        for key, value in dict_obj.items():
            if hasattr(value, "items"):
                item = QTreeWidgetItem(parent_item, [str(key), ""])
                self.add_dict_to_tree(value, item)
            else:
                QTreeWidgetItem(parent_item, [str(key), str(value)])

    def addPlotItems(self, plotItemList):
        # print("Adding plot items to control")
        if not isinstance(plotItemList, (list, tuple)):
            plotItemList = [plotItemList]
        for plotItem in plotItemList:
            if not plotItem._connected:
                plotItem.attach_plot(self.plot)
                self.dynamic_update_box.clicked.connect(plotItem.setDynamic)

        self.plotItemList = plotItemList
        self.update_display()
        self.checked_changed()

        # Update metadata tab with the last added PlotItem's metadata
        if plotItemList:
            last_plot_item = plotItemList[-1]
            self.update_metadata_tab(last_plot_item.metadata)

    @property
    def auto_add(self):
        t = self.auto_add_box.isChecked()
        return t

    def clear_display(self):
        for i in reversed(range(self.grid.count())):
            self.grid.itemAt(i).widget().setParent(None)

        # Clear the header from the layout
        for i in reversed(range(self.plot_control_layout.count())):
            widget = self.plot_control_layout.itemAt(i).widget()
            if isinstance(widget, QLabel):
                widget.setParent(None)
        self.update_plot_button.setEnabled(False)
        self.clear_data_button.setEnabled(False)

    def update_display(self):
        self.clear_display()
        if len(self.plotItemList) == 0:
            return

        if len(self.plotItemList) == 1:
            header = self.plotItemList[0].description
        else:
            header = "Multiple Selected Scans"
        for plotItem in self.plotItemList:
            plotItem.set_row_visibility(self.show_all.isChecked())

        header_label = QLabel(header)
        self.plot_control_layout.insertWidget(0, header_label)

        # Add column labels
        for i, label in enumerate(["X", "Y"]):
            label_widget = QLabel(label)
            self.grid.addWidget(label_widget, 0, i + 1)
        self.grid.addWidget(QLabel("Normalize"), 0, 4)

        norm_group = ExclusiveCheckBoxGroup(self)
        silly_x_group = ExclusiveCheckBoxGroup(self)
        y_group1d = QButtonGroup(self)
        y_group2d = ExclusiveCheckBoxGroup(self)
        y_group1d.setExclusive(False)

        checked_norm = getCommonAttr(self.plotItemList, "_checked_norm")
        checked_x = getCommonAttr(self.plotItemList, "_checked_x")
        checked_y = getCommonAttr(self.plotItemList, "_checked_y")

        any_y_checked = False

        def add_xyn_buttons(key, i):

            key_label = QLabel(key)
            self.grid.addWidget(key_label, i + 1, 0)
            xbox = QCheckBox()
            self.grid.addWidget(xbox, i + 1, 1)
            ybox = QCheckBox()
            self.grid.addWidget(ybox, i + 1, 2)
            vertical_line = QFrame()
            vertical_line.setFrameShape(QFrame.VLine)
            self.grid.addWidget(vertical_line, i + 1, 3)
            normbox = QCheckBox()
            self.grid.addWidget(normbox, i + 1, 4)

            if key in checked_norm:
                normbox.setChecked(True)
            if key in checked_x:
                xbox.setChecked(True)

            return xbox, ybox, normbox

        i = 0
        xgroups = {}
        allkeylist = []

        rows = getCommonRows(self.plotItemList)
        xkeyDict = getCommonXKeyDict(self.plotItemList)
        ykeyDict = getCommonYKeyDict(self.plotItemList)

        for xdim, xlist in xkeyDict.items():
            if not any([x in rows for x in xlist]):
                continue
            else:
                xgroups[xdim] = ExclusiveCheckBoxGroup()
                for x in xlist:
                    if x in rows:
                        allkeylist.append(x)
                        xbox, ybox, nbox = add_xyn_buttons(x, i)
                        xgroups[xdim].addButton(xbox, i)
                        y_group1d.addButton(ybox, i)
                        norm_group.addButton(nbox, i)
                        i += 1

        for ydim, ylist in ykeyDict.items():
            for y in ylist:
                if y in rows:
                    allkeylist.append(y)
                    xbox, ybox, nbox = add_xyn_buttons(y, i)
                    silly_x_group.addButton(xbox, i)
                    if ydim == 1:
                        if y in checked_y:
                            ybox.setChecked(True)
                            any_y_checked = True
                        y_group1d.addButton(ybox, i)
                    else:
                        y_group2d.addButton(ybox, i)
                        if y in checked_y and not any_y_checked:
                            ybox.setChecked(True)
                            any_y_checked = True
                    norm_group.addButton(nbox, i)
                    i += 1

        self.norm_group = norm_group
        self.y_group1d = y_group1d
        self.y_group2d = y_group2d
        self.extra_x_group = silly_x_group
        self.x_groups = xgroups
        self.allkeylist = allkeylist
        for group in [
            self.norm_group,
            self.extra_x_group,
        ]:
            for button in group.buttons():
                button.clicked.connect(self.checked_changed)
        for group in self.x_groups.values():
            for button in group.buttons():
                button.clicked.connect(self.checked_changed)
        self._exclusionary_y_group = MutuallyExclusiveCheckBoxGroups(
            self.y_group1d, self.y_group2d
        )
        self._exclusionary_y_group.buttonsChanged.connect(self.checked_changed)
        self.update_plot_button.setEnabled(True)
        self.clear_data_button.setEnabled(True)

    def checkedButtons(self):
        x_checked_ids = []
        y_checked_ids = []
        for group in list(self.x_groups.values()) + [self.extra_x_group]:
            for button in group.buttons():
                if button.isChecked():
                    x_checked_ids.append(self.allkeylist[group.id(button)])
        for group in [self.y_group1d, self.y_group2d]:
            for button in group.buttons():
                if button.isChecked():
                    y_checked_ids.append(self.allkeylist[group.id(button)])
        norm_checked_ids = [
            self.allkeylist[self.norm_group.id(button)]
            for button in self.norm_group.buttons()
            if button.isChecked()
        ]

        return x_checked_ids, y_checked_ids, norm_checked_ids

    def uncheck_all(self):
        for plotItem in self.plotItemList:
            plotItem.update_plot_settings([], [], [], "")
        self.update_display()

    def validate_dimensions(self, checked_y):
        """
        Validate that all selected Y data has the same dimensionality.

        Parameters
        ----------
        checked_y : list
            List of selected Y keys

        Returns
        -------
        tuple
            (is_valid, dimension, error_message)
        """
        if not checked_y:
            return True, None, ""

        dimensions = []
        for plotItem in self.plotItemList:
            for key in checked_y:
                dim = plotItem.getDimensions(key)
                dimensions.append(dim)

        if not dimensions:
            return True, None, ""

        first_dim = dimensions[0]
        if not all(dim == first_dim for dim in dimensions):
            return False, None, "Cannot mix 1D and 2D data in the same plot"

        return True, first_dim, ""

    def checked_changed(self):
        checked_x, checked_y, checked_norm = self.checkedButtons()

        # Validate dimensions before updating
        is_valid, _, error_msg = self.validate_dimensions(checked_y)
        if not is_valid:
            QMessageBox.warning(self, "Invalid Selection", error_msg)
            self.uncheck_all()
            return
        for plotItem in self.plotItemList:
            transform_text = (
                self.transform_text_edit.text()
                if self.transform_box.isChecked()
                else ""
            )
            plotItem.update_plot_settings(
                checked_x, checked_y, checked_norm, transform_text
            )
            if self.auto_add:
                plotItem.updatePlot()

    def update_plot(self):
        checked_x, checked_y, checked_norm = self.checkedButtons()

        # Validate dimensions before plotting
        is_valid, _, error_msg = self.validate_dimensions(checked_y)
        if not is_valid:
            QMessageBox.warning(self, "Invalid Selection", error_msg)
            self.uncheck_all()
            return

        self.checked_changed()
        if not self.auto_add:
            for plotItem in self.plotItemList:
                plotItem.updatePlot()

    def transform_state_changed(self):
        """Handle transform checkbox state change."""
        is_checked = self.transform_box.isChecked()
        self.transform_combo.setEnabled(is_checked)
        self.transform_text_edit.setEnabled(is_checked)
        if not is_checked:
            self.transform_combo.setCurrentText("No Transform")
        self.checked_changed()

    def on_transform_selected(self, transform_name):
        """Handle transform selection from combo box."""
        if transform_name in self._transforms:
            self.transform_text_edit.setText(self._transforms[transform_name])
            self.checked_changed()

    def on_custom_transform_changed(self):
        """Handle custom transform text changes."""
        if self.transform_combo.currentText() != "Custom":
            self.transform_combo.setCurrentText("Custom")
        self.checked_changed()

    def save_custom_transform(self):
        """Save current custom transform to the combo box."""
        custom_text = self.transform_text_edit.text().strip()
        if not custom_text:
            return

        name, ok = QInputDialog.getText(
            self, "Save Transform", "Enter a name for this transform:"
        )
        if ok and name:
            name = name.strip()
            if name in self._transforms:
                reply = QMessageBox.question(
                    self,
                    "Transform exists",
                    f"Transform '{name}' already exists. Overwrite?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    return

            self._transforms[name] = custom_text
            current_items = [
                self.transform_combo.itemText(i)
                for i in range(self.transform_combo.count())
            ]
            if name not in current_items:
                self.transform_combo.addItem(name)
            self.transform_combo.setCurrentText(name)

    def clear_plot(self):
        """Clear all data plotters and reset the plot and controls."""
        # Reset all plot items to unchecked state
        self.uncheck_all()

        # Use PlotWidget's clearPlot to handle both canvas and data plotters
        self.plot.clearPlot()

        # Reset transform state
        self.transform_box.setChecked(False)
        self.transform_combo.setCurrentText("No Transform")
        self.transform_text_edit.clear()

        # Reset checkboxes
        self.auto_add_box.setChecked(True)
        self.dynamic_update_box.setChecked(False)
        self.show_all.setChecked(False)
