import numpy as np


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


class PlotItem:
    def __init__(self, run, catalog=None, dynamic=False):
        # super(PlotItem, self).__init__()
        self._run = run
        self._catalog = catalog
        self._dynamic = dynamic
        self._plot_hints = getPlotHints(self._run)
        xkeys, ykeys = getRunKeys(self._run)
        yfiltered = filterHintedKeys(self._plot_hints, ykeys)
        self.xkeyDict = xkeys
        self.ykeyDict = yfiltered
        self.all_ykeyDict = ykeys
        self.setDefaultChecked()
        self._description = blueskyrun_to_string(self._run)
        self._uid = self._run.metadata["start"]["scan_id"]

    def setDefaultChecked(self):
        self._checked_x = []
        if 1 in self.xkeyDict:
            for n in self.xkeyDict.keys():
                if n != 0:
                    self._checked_x.append(self.xkeyDict[n][0])
        elif 0 in self.xkeyDict:
            self._checked_x = [self.xkeyDict[0][0]]

        self._checked_y = getFlattenedFields(self._plot_hints.get("primary"))
        self._checked_norm = getFlattenedFields(self._plot_hints.get("normalization"))

    def update_checkboxes(self, checked_x, checked_y, checked_norm):
        self._checked_x = checked_x
        self._checked_y = checked_y
        self._checked_norm = checked_norm
        if checked_x is not None and checked_y is not None:
            self.update_plot_signal.emit()

    def transformData(self, xlist, ylist, normlist):

        # Assumption time! Assume that we are just dividing by all norms
        norm = np.prod(normlist, axis=0)

        # Just divide y by norm for now! In the future, we will grab input from a variety of sources
        # and make a more complex transform using Asteval
        yfinal = [y / norm for y in ylist]
        return xlist, yfinal

    def plotCheckedData(self):
        xlist, ylist, normlist = self.getCheckedData()
        xdim = len(xlist)
        max_ydim = max([len(y.shape) for y in ylist])
        plot_dim = max_ydim

        xlist, ylist = self.transformData(xlist, ylist, normlist)
        if plot_dim == 1:
            for n, k in enumerate(self._checked_y):
                line_id = f"{self._checked_x};{k}"
                self._lines[line_id] = self._plot.plot(xlist[0], ylist[n], label=k)[0]

    def getCheckedData(self):
        xlist = [self.getData(key) for key in self._checked_x]
        ylist = [self.getData(key) for key in self._checked_y]
        normlist = [self.getData(key) for key in self._checked_norm]

        xshape = self._run.start["shape"]

        if self._dynamic:
            # Lengths may be off due to uneven data updates
            xmin = min([x.shape[0] for x in xlist])
            ymin = min([y.shape[0] for y in ylist])
            normmin = min([norm.shape[0] for norm in normlist])

            minidx = min(xmin, ymin, normmin)
            minslice = slice(None, minidx)
            xlist = [x[minslice] for n, x in enumerate(xlist)]
            ylist = [y[minslice] for y in ylist]
            normlist = [norm[minslice] for norm in normlist]

            if minidx == self._expected_points:
                self._dynamic = False

        xlist_reshape = [reshape_truncated_array(x, xshape) for x in xlist]
        ylist_reshape = [reshape_truncated_array(y, xshape) for y in ylist]
        nlist_reshape = [reshape_truncated_array(n, xshape) for n in normlist]
        return xlist_reshape, ylist_reshape, nlist_reshape

    def getData(self, key):
        if not self._dynamic:
            return self._data[key]
        else:
            return self._run["primary", "data", key].read()


def getRunKeys(run):
    allData = {key: arr.shape for key, arr in run["primary", "data"].items()}
    xkeyhints = run.start["hints"]["dimensions"]
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
    ykeys[1] = keys1d
    ykeys[2] = keysnd
    return xkeys, ykeys


def getPlotHints(run):
    plotHints = run.start.get("plot_hints", {})
    return plotHints


def filterHintedKeys(plotHints, ykeys):

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
    reshaped_arr = arr[: np.prod(new_shape), ...].reshape(final_shape)
    return reshaped_arr
