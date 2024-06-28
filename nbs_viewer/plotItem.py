import numpy as np
from qtpy.QtWidgets import QWidget
from qtpy.QtCore import QTimer, Signal
from asteval import Interpreter


def blueskyrun_to_string(blueskyrun):
    # Replace this with your actual function
    start = blueskyrun.metadata["start"]
    scan_id = str(start["scan_id"])
    scan_desc = ["Scan", scan_id]
    if hasattr(start, "edge"):
        scan_desc.append(start.get("edge"))
        scan_desc.append("edge")
    if hasattr(start, "scantype"):
        scan_desc.append(start.get("scantype"))
    else:
        scan_desc.append(start.get("plan_name"))
    if hasattr(start, "sample_md"):
        scan_desc.append("of")
        scan_desc.append(start["sample_md"].get("name", "Unknown"))
    elif hasattr(start, "sample_name"):
        scan_desc.append("of")
        scan_desc.append(start["sample_name"])
    str_desc = " ".join(scan_desc)
    return str_desc


class PlotItem(QWidget):
    update_plot_signal = Signal()

    def __init__(self, run, catalog=None, dynamic=False, parent=None):
        super().__init__(parent)
        self._run = run
        self._catalog = catalog
        self._dynamic = dynamic
        self._connected = False
        self.dataPlotters = {}
        self._plot_hints = getPlotHints(self._run)
        self._axhints = getAxisHints(self._plot_hints)
        # print("Axhints")
        # print(self._axhints)
        xkeys, ykeys = getRunKeys(self._run)
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
        self._description = blueskyrun_to_string(self._run)
        self._uid = self._run.metadata["start"]["uid"]
        self._scanid = self._run.metadata["start"]["scan_id"]
        self._expected_points = self._run.start.get("num_points", -1)
        self._transform_text = ""
        self.update_plot_signal.connect(self.plotCheckedData)
        if self._dynamic:
            self.startDynamicUpdates()
        else:
            self._num_points = self._run.start.get("num_points", -1)
            if self._num_points == -1:
                self._num_points = (
                    self._run.metadata.get("stop", {})
                    .get("num_events", {})
                    .get("primary", -1)
                )
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
            self._expected_points = self._run.start.get("num_points", -1)
        # print("dynamic update triggered")
        if self._run.metadata.get("stop", None) is not None:
            # print("Converting from dynamic to static")
            # print(self._run.metadata["stop"])
            self.stopDynamicUpdates()
            self._num_points = self._run.start.get("num_points", -1)
            if self._num_points == -1:
                self._num_points = (
                    self._run.metadata.get("stop", {})
                    .get("num_events", {})
                    .get("primary", -1)
                )
        elif self._catalog is not None:
            # print("No Stop Doc, Updating Run from Catalog")
            self._run = self._catalog[self.uid]

        self.update_plot_signal.emit()

    def set_row_visibility(self, show_all_rows):
        self._show_all = show_all_rows

    def attach_plot(self, plot):
        self._plot = plot

    def setDynamic(self, enabled):
        if enabled:
            if not self._dynamic and self._run.metadata.get("stop", None) is None:
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
        self.update_plot_settings([], [], [], "")
        self.setDynamic(False)
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

    def transformData(self, xlist, ylist, normlist, transformText=""):
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
        if len(normlist) > 0:
            norm = np.prod(normlist, axis=0)
        else:
            norm = 1
        # Just divide y by norm for now! In the future, we will grab input from a variety of sources
        # and make a more complex transform using Asteval
        yfinal = []
        for y_temp in ylist:
            # Check if norm is not a scalar before adjusting dimensions
            if np.isscalar(norm):
                y = y_temp / norm
            else:
                # Create a temporary variable for norm to avoid modifying the original norm
                temp_norm = norm
                # Check if y_temp has more dimensions than temp_norm and adjust temp_norm accordingly
                while temp_norm.ndim < y_temp.ndim:
                    temp_norm = np.expand_dims(temp_norm, axis=-1)
                y = y_temp / temp_norm

            if transformText:
                # Update the symtable and evaluate the transformText using Asteval
                self.aeval.symtable["y"] = y
                self.aeval.symtable["x"] = xlist
                self.aeval.symtable["norm"] = norm
                y_transformed = self.aeval(transformText)
                yfinal.append(y_transformed)
            else:
                yfinal.append(y)
        return xlist, yfinal

    def removeData(self):
        remove_keys = [
            key for key in self.dataPlotters.keys() if key not in self._checked_y
        ]

        for key in remove_keys:
            data_plotter = self.dataPlotters.pop(key)
            data_plotter.remove()
            data_plotter.deleteLater()

    def plotCheckedData(self):
        # print("plotCheckedData")
        if len(self._checked_x) == 0 or len(self._checked_y) == 0:
            return

        if getattr(self, "_plot", None) is None:
            return

        # print(self._checked_x, self._checked_y)
        xlist, ylist, normlist = self.getCheckedData()
        ykeys = self._checked_y
        xdim = len(xlist)
        min_ydim = min([len(y.shape) for y in ylist])

        xlist, ylist = self.transformData(xlist, ylist, normlist, self._transform_text)

        for key, y in zip(ykeys, ylist):
            if len(y.shape) > min_ydim:
                print(
                    f"{key} with dimension {y.shape} higher dimensionality than other data"
                )
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

            xlist_reordered = []

            if len(xadditions) == 1:
                xlist_reordered = xlist[:-1] + xadditions + [xlist[-1]]
                xkeys = self._checked_x[:-1] + xadditional_keys + [self._checked_x[-1]]
                y_reordered = np.swapaxes(y, -2, -1)
            else:
                xlist_reordered = xlist + xadditions
                xkeys = self._checked_x + xadditional_keys
                y_reordered = y
            # if len(y_reordered.shape) != len(xlist_reordered):
            # print(xkeys, ykeys, xadditional_keys)
            if key in self.dataPlotters:
                # print(f"Update {key}: {y_reordered.shape}")
                self.dataPlotters[key].update_data(xlist_reordered, y_reordered)
            else:
                label = f"{key}.{self._scanid}"
                # print(f"New Data {key}: {y_reordered.shape}")
                self.dataPlotters[key] = self._plot.addPlotData(
                    xlist_reordered, y_reordered, xkeys, label
                )

    def getCheckedData(self):
        """
        Gets properly shaped x, y, norm data

        Need to return dictionaries with keys so that I can store/update DataPlotters
        """

        xlist = [self.getData(key) for key in self._checked_x]
        ylist = [self.getData(key) for key in self._checked_y]
        normlist = [self.getData(key) for key in self._checked_norm]

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

        if "shape" in self._run.start:
            xshape = self._run.start["shape"]
        else:
            xshape = [self._num_points]

        xlist_reshape = [reshape_truncated_array(x, xshape) for x in xlist]
        ylist_reshape = [reshape_truncated_array(y, xshape) for y in ylist]
        nlist_reshape = [reshape_truncated_array(n, xshape) for n in normlist]
        return xlist_reshape, ylist_reshape, nlist_reshape

    def getData(self, key):
        # re-optimize for performance later
        # if not self._dynamic:
        #    return self._data[key]
        # else:
        return self._run["primary", "data", key].read()

    def getAxis(self, keys):
        data = self._run["primary"]
        for key in keys:
            data = data[key]
        return data.read().squeeze()


def getRunKeys(run):
    allData = {key: arr.shape for key, arr in run["primary", "data"].items()}
    xkeyhints = run.start["hints"].get("dimensions", [])
    keys1d = []
    keysnd = []

    xkeys = {}
    ykeys = {}
    for key in list(allData.keys()):
        if len(allData[key]) == 1:
            keys1d.append(key)
        elif len(allData[key]) > 1:
            keysnd.append(key)
    if "time" in keys1d:
        xkeys[0] = ["time"]
        keys1d.pop(keys1d.index("time"))
    for i, dimension in enumerate(xkeyhints):
        axlist = dimension[0]
        xkeys[i + 1] = []
        for ax in axlist:
            if ax in keys1d:
                keys1d.pop(keys1d.index(ax))
                xkeys[i + 1].append(ax)
        if len(xkeys[i + 1]) == 0:
            xkeys.pop(i + 1)
    ykeys[1] = keys1d
    ykeys[2] = keysnd
    return xkeys, ykeys


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


def getPlotHints(run):
    plotHints = run.start.get("plot_hints", {})
    return plotHints


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
