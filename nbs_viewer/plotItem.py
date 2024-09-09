import numpy as np
from qtpy.QtWidgets import QWidget
from qtpy.QtCore import QTimer, Signal
from asteval import Interpreter


class CompoundPlotItem(QWidget):
    update_plot_signal = Signal()

    def __init__(self, plot_items, label, parent=None):
        super().__init__(parent)
        self._plot_items = plot_items
        self._label = label
        self._connected = False
        self.dataPlotters = {}

        # Combine plot hints and axis hints from all plot items
        self._plot_hints = self._combine_plot_hints()
        self._axhints = self._combine_axis_hints()

        # Combine x and y keys
        self.xkeyDict = self._combine_x_keys()
        self.all_ykeyDict = self._combine_y_keys()
        self.ykeyDict = self._combine_hinted_keys()

        print("xkeydict combined", self.xkeyDict)
        print("ykeydict combined", self.all_ykeyDict)

        self._show_all = False
        self._allrows = []
        self._hintedrows = []
        for xlist in self.xkeyDict.values():
            self._hintedrows += xlist
            self._allrows += xlist
        for ylist in self.ykeyDict.values():
            self._hintedrows += ylist
        for ylist in self.all_ykeyDict.values():
            self._allrows += ylist
        print("allrows", self._allrows)
        print("hinted", self._hintedrows)
        self.setDefaultChecked()
        self._description = f"Average of {len(self._plot_items)} scans: {self._label}"
        self._uid = f"compound_{self._label}"
        self._scanid = self._label
        self._transform_text = ""

    def _combine_plot_hints(self):
        # Implement logic to combine plot hints from all plot items
        return {}  # Placeholder

    def _combine_axis_hints(self):
        # Implement logic to combine axis hints from all plot items
        return {}  # Placeholder

    def _combine_x_keys(self):
        # Combine x keys from all plot items
        combined = {}
        for item in self._plot_items:
            for dim, keys in item.xkeyDict.items():
                if dim not in combined:
                    combined[dim] = set()
                combined[dim].update(keys)
        return {dim: list(keys) for dim, keys in combined.items()}

    def _combine_hinted_keys(self):
        # Combine y keys from all plot items
        combined = {}
        for item in self._plot_items:
            for dim, keys in item.ykeyDict.items():
                if dim not in combined:
                    combined[dim] = set()
                combined[dim].update(keys)
        return {dim: list(keys) for dim, keys in combined.items()}

    def _combine_y_keys(self):
        # Combine y keys from all plot items
        combined = {}
        for item in self._plot_items:
            for dim, keys in item.all_ykeyDict.items():
                if dim not in combined:
                    combined[dim] = set()
                combined[dim].update(keys)
        return {dim: list(keys) for dim, keys in combined.items()}

    @property
    def metadata(self):
        md = {item.uid: item.metadata for item in self._plot_items}
        return md

    @property
    def description(self):
        return self._description

    @property
    def rows(self):
        return self._hintedrows if not self._show_all else self._allrows

    @property
    def uid(self):
        return self._uid

    def set_row_visibility(self, show_all_rows):
        self._show_all = show_all_rows

    def attach_plot(self, plot):
        self._plot = plot
        self._connected = True

    def disconnect_plot(self):
        self.removeData()
        self._plot = None
        self._connected = False

    def setDefaultChecked(self):
        self._checked_x = self.xkeyDict[1][0] if 1 in self.xkeyDict else []
        self._checked_y = list(self.ykeyDict.values())[0] if self.ykeyDict else []
        self._checked_norm = []

    def clear(self):
        self.update_plot_settings([], [], [], "")
        self.removeData()

    def update_plot_settings(
        self, checked_x, checked_y, checked_norm, transformText=""
    ):
        self._checked_x = checked_x
        self._checked_y = checked_y
        self._checked_norm = checked_norm
        self._transform_text = transformText

    def updatePlot(self):
        self.removeData()
        self.plotCheckedData()

    def removeData(self):
        remove_keys = list(self.dataPlotters.keys())
        for key in remove_keys:
            data_plotter = self.dataPlotters.pop(key)
            data_plotter.remove()
            data_plotter.deleteLater()

    def plotCheckedData(self):
        if len(self._checked_x) == 0 or len(self._checked_y) == 0:
            return

        if getattr(self, "_plot", None) is None:
            return

        ykeys = self._checked_y
        xkeys = self._checked_x
        nkeys = self._checked_norm
        print(ykeys)
        for ykey in ykeys:
            yplotlist = []
            xlist = 0
            xkeylist = []
            for item in self._plot_items:
                xlist, yplot, xkeylist, _ = item.getPlotData(xkeys, [ykey], nkeys)
                # print(xlist)
                xlist = xlist[0]
                xkeylist = xkeylist[0]
                yplotlist.append(yplot[0])
            y = np.mean(yplotlist, axis=0)

            if ykey in self.dataPlotters:
                self.dataPlotters[ykey].update_data(xlist, y)
            else:
                label = f"{ykey}.{self._scanid}"
                self.dataPlotters[ykey] = self._plot.addPlotData(
                    xlist, y, xkeylist, label
                )

    def setDynamic(self, *args):
        pass


class PlotItem(QWidget):
    update_plot_signal = Signal()

    def __init__(self, run, catalog=None, dynamic=False, parent=None):
        super().__init__(parent)
        self._run = run  # This is now a BlueskyRun object
        self._catalog = catalog
        self._dynamic = dynamic
        self._connected = False
        self.dataPlotters = {}
        self._plot_hints = self._run.getPlotHints()
        self._axhints = getAxisHints(self._plot_hints)
        # print("Axhints")
        # print(self._axhints)
        xkeys, ykeys = self._run.getRunKeys()
        yfiltered = filterHintedKeys(self._plot_hints, ykeys)
        self.xkeyDict = xkeys
        self.ykeyDict = yfiltered
        # print(self.xkeyDict)
        # print(self.ykeyDict)
        self.all_ykeyDict = ykeys
        self._show_all = False
        self._hintedrows = []
        self._allrows = []
        for xlist in xkeys.values():
            self._hintedrows += xlist
            self._allrows += xlist
        for ylist in self.ykeyDict.values():
            self._hintedrows += ylist
        for ylist in self.all_ykeyDict.values():
            self._allrows += ylist
        self.setDefaultChecked()
        self._description = str(self._run)
        self._uid = self._run.uid
        self._scanid = self._run.scan_id
        self._expected_points = self._run.num_points
        self._transform_text = ""
        self.update_plot_signal.connect(self.plotCheckedData)
        if self._dynamic:
            self.startDynamicUpdates()
        else:
            self._num_points = self._run.num_points
            self.timer = None
        self.aeval = Interpreter()  # Create an Asteval interpreter once

    def startDynamicUpdates(self):
        self.stopDynamicUpdates()
        self._dynamic = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._dynamic_update)
        self.timer.start(2000)
        self._num_points = None

    def stopDynamicUpdates(self):
        self._dynamic = False
        # print("Stopping Dynamic Updates")
        if self.timer is not None:
            self.timer.stop()
            self.timer = None

    @property
    def metadata(self):
        return self._run.metadata

    @property
    def description(self):
        return self._description

    @property
    def rows(self):
        if self._show_all:
            return self._allrows
        else:
            return self._hintedrows

    @property
    def uid(self):
        return self._uid

    def _dynamic_update(self):
        if self._expected_points is None:
            self._expected_points = self._run.num_points
        # print("dynamic update triggered")
        if self._run.scanFinished():
            # print("Converting from dynamic to static")
            # print(self._run.metadata["stop"])
            self.stopDynamicUpdates()
            self._num_points = self._run.num_points
        elif self._catalog is not None:
            # print("No Stop Doc, Updating Run from Catalog")
            self._run.refresh()

        self.update_plot_signal.emit()

    def set_row_visibility(self, show_all_rows):
        self._show_all = show_all_rows

    def attach_plot(self, plot):
        self._plot = plot
        self._connected = True

    def disconnect_plot(self):
        # print("In item disconnect plot")
        self.removeData()
        self._plot = None
        self._connected = False

    def setDynamic(self, enabled):
        if enabled:
            if not self._dynamic and not self._run.scanFinished():
                self.startDynamicUpdates()
        elif self._dynamic:
            self.stopDynamicUpdates()
        print(f"Dynamic set to {self._dynamic} for {self._scanid}")

    def setDefaultChecked(self):
        self._checked_x = []
        if 1 in self.xkeyDict:
            for n in self.xkeyDict.keys():
                if n != 0:
                    self._checked_x.append(self.xkeyDict[n][0])
        elif 0 in self.xkeyDict:
            self._checked_x = [self.xkeyDict[0][0]]

        self._checked_y = getFlattenedFields(self._plot_hints.get("primary", []))
        self._checked_norm = getFlattenedFields(
            self._plot_hints.get("normalization", [])
        )

    def clear(self):
        # print("Clearing PlotItem")
        self.update_plot_settings([], [], [], "")
        self.setDynamic(False)
        self.removeData()

    def update_plot_settings(
        self, checked_x, checked_y, checked_norm, transformText=""
    ):
        # print("Updating Plot Settings to", checked_x, checked_y)
        self._checked_x = checked_x
        self._checked_y = checked_y
        self._checked_norm = checked_norm
        self._transform_text = transformText

    def updatePlot(self):
        self.removeData()
        self.plotCheckedData()

    def transformData(self, xlist, y, norm, transformText=""):
        """
        Transform the data based on normalization and optional transformation text.

        Parameters
        ----------
        xlist : list of np.ndarray
            List of x data arrays.
        ylist : list of np.ndarray
            List of y data arrays.
        normlist : list of np.ndarray
            List of normalization arrays.
        transformText : str, optional
            Transformation expression to be evaluated, by default "".

        Returns
        -------
        tuple
            Transformed x and y data arrays.
        """
        # Assumption time! Assume that we are just dividing by all norms
        # Just divide y by norm for now! In the future, we will grab input from a variety of sources
        # and make a more complex transform using Asteval
        yfinal = 0

        if np.isscalar(norm):
            yfinal = y / norm
        else:
            # Create a temporary variable for norm to avoid modifying the original norm
            temp_norm = norm
            # Check if y_temp has more dimensions than temp_norm and adjust temp_norm accordingly
            while temp_norm.ndim < y.ndim:
                temp_norm = np.expand_dims(temp_norm, axis=-1)
            yfinal = y / temp_norm

        if transformText:
            # Update the symtable and evaluate the transformText using Asteval
            self.aeval.symtable["y"] = yfinal
            self.aeval.symtable["x"] = xlist
            self.aeval.symtable["norm"] = norm
            yfinal = self.aeval(transformText)
        return xlist, yfinal

    def removeData(self):
        # print("Remove data")
        remove_keys = [key for key in self.dataPlotters.keys()]

        for key in remove_keys:
            data_plotter = self.dataPlotters.pop(key)
            data_plotter.remove()
            data_plotter.deleteLater()
        # print("Done remove data")

    def getPlotData(self, xkeys, ykeys, nkeys):
        xlist, ylist, normlist = self.getCheckedData(xkeys, ykeys, nkeys)

        if len(normlist) > 0:
            norm = np.prod(normlist, axis=0)
        else:
            norm = 1

        xplotlist = []
        yplotlist = []
        xkeylist = []
        ykeylist = []
        for key, y in zip(ykeys, ylist):
            _, y = self.transformData(xlist, y, norm, self._transform_text)
            xlist_reordered, xkeys, y_reordered = self.reorderDimensions(key, xlist, y)
            xplotlist.append(xlist_reordered)
            yplotlist.append(y_reordered)
            xkeylist.append(xkeys)
            ykeylist.append(key)
        return xplotlist, yplotlist, xkeylist, ykeylist

    def plotCheckedData(self):
        if len(self._checked_x) == 0 or len(self._checked_y) == 0:
            return

        if getattr(self, "_plot", None) is None:
            return
        xkeys = self._checked_x
        ykeys = self._checked_y
        nkeys = self._checked_norm
        xplotlist, yplotlist, xkeylist, ykeylist = self.getPlotData(xkeys, ykeys, nkeys)
        for xlist, y, xkeys, ykey in zip(xplotlist, yplotlist, xkeylist, ykeylist):
            if ykey in self.dataPlotters:
                self.dataPlotters[ykey].update_data(xlist, y)
            else:
                label = f"{ykey}.{self._scanid}"
                self.dataPlotters[ykey] = self._plot.addPlotData(xlist, y, xkeys, label)

    def reorderDimensions(self, key, xlist, y):
        """
        Reorder dimensions of x and y data based on axis hints and data shape.

        Parameters
        ----------
        key : str
            The key for the current y data.
        xlist : list
            List of x data arrays.
        y : np.ndarray
            The y data array.

        Returns
        -------
        tuple
            Containing reordered xlist, xkeys, and y data.
        """
        xdim = len(xlist)

        if key in self._axhints:
            xadditions = [self.getAxis(axkey) for axkey in self._axhints[key]]
            xadditional_keys = [axkey[-1] for axkey in self._axhints[key]]
        else:
            xadditions = []
            xadditional_keys = []

        current_dim = xdim + len(xadditions)
        if current_dim < len(y.shape):
            for n in range(current_dim, len(y.shape)):
                xadditions.append(np.arange(y.shape[n]))
                xadditional_keys.append(f"Dimension {n}")

        if len(xadditions) == 1:
            xlist_reordered = xlist[:-1] + xadditions + [xlist[-1]]
            xkeys = self._checked_x[:-1] + xadditional_keys + [self._checked_x[-1]]
            y_reordered = np.swapaxes(y, -2, -1)
        else:
            xlist_reordered = xlist + xadditions
            xkeys = self._checked_x + xadditional_keys
            y_reordered = y

        if len(y_reordered.shape) > len(y.shape):
            print(
                f"{key} with dimension {y_reordered.shape} higher dimensionality than other data"
            )

        return xlist_reordered, xkeys, y_reordered

    def getCheckedData(self, xkeys, ykeys, nkeys):
        """
        Gets properly shaped x, y, norm data

        Need to return dictionaries with keys so that I can store/update DataPlotters
        """

        xlist = [self._run.getData(key) for key in xkeys]
        ylist = [self._run.getData(key) for key in ykeys]
        normlist = [self._run.getData(key) for key in nkeys]

        if self._dynamic:
            # Lengths may be off due to uneven data updates
            xmin = min([x.shape[0] for x in xlist])
            ymin = min([y.shape[0] for y in ylist])
            if len(normlist) == 0:
                normmin = ymin
            else:
                normmin = min([norm.shape[0] for norm in normlist])

            minidx = min(xmin, ymin, normmin)
            self._num_points = minidx
            minslice = slice(None, minidx)
            xlist = [x[minslice] for n, x in enumerate(xlist)]
            ylist = [y[minslice] for y in ylist]
            normlist = [norm[minslice] for norm in normlist]

            if minidx == self._expected_points:
                self.stopDynamicUpdates()

        xshape = self._run.getShape()

        xlist_reshape = [reshape_truncated_array(x, xshape) for x in xlist]
        ylist_reshape = [reshape_truncated_array(y, xshape) for y in ylist]
        nlist_reshape = [reshape_truncated_array(n, xshape) for n in normlist]
        return xlist_reshape, ylist_reshape, nlist_reshape

    def getData(self, key):
        return self._run.getData(key)

    def getAxis(self, keys):
        return self._run.getAxis(keys)


def getAxisHints(plotHints):
    axhints = {}
    for dlist in plotHints.values():
        for d in dlist:
            if isinstance(d, dict) and "axes" in d:
                signal = d["signal"]
                # Kludge because I am too lazy to update container
                if isinstance(signal, list):
                    signal = signal[-1]
                axhints[signal] = d["axes"]
    return axhints


def filterHintedKeys(plotHints, ykeys):
    if plotHints == {}:
        return ykeys
    hintedKeys = flattenPlotHints(plotHints)
    yfiltered = {}
    for key, dlist in ykeys.items():
        yfiltered[key] = []
        for d in dlist:
            if d in hintedKeys:
                yfiltered[key].append(d)
    return yfiltered


def flattenPlotHints(plotHints):
    allkeys = []
    for fieldList in plotHints.values():
        allkeys += getFlattenedFields(fieldList)
    return allkeys


def getFlattenedFields(fieldList):
    flatKeys = []
    for f in fieldList:
        if isinstance(f, dict):
            if isinstance(f["signal"], list):
                flatKeys.append(f["signal"][-1])
            else:
                flatKeys.append(f["signal"])
        else:
            flatKeys.append(f)
    return flatKeys


def reshape_truncated_array(arr, original_shape):
    """
    Reshape a truncated 1D array to the maximum filled sub-array of its original shape,
    adjusting the first dimension first and continuing to the next dimension if the current
    dimension cannot be filled.

    Parameters
    ----------
    arr : np.ndarray
        The 1D numpy array that has been truncated.
    original_shape : tuple
        The original shape of the array before flattening and truncation.

    Returns
    -------
    np.ndarray
        The reshaped array with the maximum filled sub-array shape.
    """

    # Calculate the number of elements in the truncated array
    truncated_length = arr.shape[0]

    # Initialize the new shape with the original shape
    new_shape = list(original_shape)

    # Iterate over dimensions to adjust the first dimension first
    for i in range(len(original_shape)):
        # Calculate the product of the dimensions after the current one
        product_of_remaining = (
            np.prod(new_shape[i + 1 :]) if i + 1 < len(new_shape) else 1
        )

        # Calculate the number of full elements that can fit in the current dimension
        if product_of_remaining == 0:  # Avoid division by zero for the last dimension
            full_elements_in_dim = truncated_length
        else:
            full_elements_in_dim = truncated_length // product_of_remaining

        if full_elements_in_dim == 0:
            # If no elements can fit in the current dimension, move to the next dimension
            new_shape[i] = 1
            continue
        elif full_elements_in_dim <= original_shape[i]:
            # Adjust the dimension size
            new_shape[i] = full_elements_in_dim
            break  # Break after adjusting the first dimension that can be fully or partially filled
        else:
            # If the dimension can be fully filled, update the truncated length for the next iteration
            truncated_length -= full_elements_in_dim * product_of_remaining

    # Ensure the array is truncated to fit the new shape exactly
    final_shape = new_shape + list(arr.shape[1:])
    # print(f"Original shape: {original_shape}, Final shape: {final_shape}")
    reshaped_arr = arr[: np.prod(new_shape), ...].reshape(final_shape)
    return reshaped_arr
