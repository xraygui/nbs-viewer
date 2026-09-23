import numpy as np
from os.path import join
from export_tools import get_with_fallbacks, get_run_data, add_comment_to_lines, sanitize_filename
from datetime import datetime


def get_config(config, keys, default=None):
    try:
        item = get_with_fallbacks(config, keys)
        if item is None:
            return default
        return item.read()
    except:
        return default


def get_xdi_run_header(run, header_updates={}):
    """
    Generate an XDI header dictionary from a run.

    Parameters
    ----------
    run : Run
    header_updates : dict
        Dictionary of additional header fields to update or add.

    Returns
    -------
    metadata : dict
        The XDI header dictionary.
    """
    baseline = run.baseline.data.read()
    proposal = run.start.get("proposal", {})
    metadata = {}
    metadata["Facility.name"] = "NSLS-II"
    metadata["Facility.xray_source"] = "EPU60 Undulator"
    metadata["Facility.current"] = "{:.2f} mA".format(
        float(get_with_fallbacks(baseline, "NSLS-II Ring Current", default=[400])[0])
    )
    metadata["Facility.cycle"] = run.start.get("cycle", "")
    metadata["Facility.GUP"] = proposal.get("proposal_id", "")
    metadata["Facility.SAF"] = proposal.get("saf", "")

    metadata["Beamline.name"] = "7-ID-1"
    metadata["Beamline.chamber"] = "NEXAFS"

    metadata["Mono.stripe"] = str(get_config(run.baseline.config, ["en", "en_monoen_gratingx_setpoint"], [""])[0])

    metadata["Sample.name"] = run.start.get("sample_name", "")
    metadata["Sample.id"] = run.start.get("sample_id", "")

    metadata["Experiment.principal_investigator"] = proposal.get("pi_name", "")
    metadata["Experiment.start"] = run.start.get("start_datetime", "")

    metadata["Scan.transient_id"] = run.start["scan_id"]
    metadata["Scan.uid"] = run.start["uid"]
    metadata["Scan.command"] = run.start.get("plan_name", "")
    metadata["Scan.start_time"] = datetime.fromtimestamp(run.start["time"]).isoformat()
    metadata["Scan.type"] = run.start.get("scantype", "unknown")
    metadata["Scan.motors"] = run.start.get("motors", ["time"])[0]

    metadata["Element.symbol"] = run.start.get("element", "")
    metadata["Element.edge"] = run.start.get("edge", "")
    # This is just a kludge for re-export of old data where we used edge, not element in run.start
    if metadata["Element.symbol"] == "" and metadata["Element.edge"] != "":
        element = metadata["Element.edge"]
        metadata["Element.symbol"] = element
        metadata["Element.edge"] = ""  # Because it was really the element symbol
        if element.lower() in ["c", "n", "o", "f", "na", "mg", "al", "si"]:
            metadata["Element.edge"] = "K"
        elif element.lower() in ["ca", "sc", "ti", "v", "cr", "mn", "fe", "co", "ni", "cu", "zn"]:
            metadata["Element.edge"] = "L"
        elif element.lower() in ["ce"]:
            metadata["Element.edge"] = "M"

    metadata["Motors.exslit"] = float(
        get_with_fallbacks(baseline, "eslit", "Exit Slit of Mono Vertical Gap", default=[0])[0]
    )
    metadata["Motors.manipx"] = float(get_with_fallbacks(baseline, "manip_x", "Manipulator_x", default=[0])[0])
    metadata["Motors.manipy"] = float(get_with_fallbacks(baseline, "manip_y", "Manipulator_y", default=[0])[0])
    metadata["Motors.manipz"] = float(get_with_fallbacks(baseline, "manip_z", "Manipulator_z", default=[0])[0])
    metadata["Motors.manipr"] = float(get_with_fallbacks(baseline, "manip_r", "Manipulator_r", default=[0])[0])
    metadata["Motors.tesz"] = float(get_with_fallbacks(baseline, "tesz", default=[0])[0])
    metadata.update(header_updates)
    return metadata


def normalize_detector(search, replace, columns, header=None, description=None):
    if search in columns:
        columns[columns.index(search)] = replace
        if header is not None:
            if description is None:
                description = search
            header[f"Detector.{replace}"] = description


def exclude_column(search, columns, data):
    if search in columns:
        idx = columns.index(search)
        columns.pop(idx)
        data.pop(idx)


def reorder_columns(columns, data, key, index):
    """
    Reorder columns and data to move a key to a specific index.

    Parameters
    ----------
    columns : list
        The list of column names.
    data : list
        The list of data arrays.
    key : str
        The key to move.
    index : int
        The index to move the key to.
    """
    if key in columns:
        key_idx = columns.index(key)
        columns.pop(key_idx)
        column_data = data.pop(key_idx)
        columns.insert(index, key)
        data.insert(index, column_data)
    return columns, data


def make_filename(folder, metadata, ext="xdi", suffix=None):
    file_parts = []
    if metadata.get("Sample.name", "") != "":
        file_parts.append(metadata.get("Sample.name"))
    if metadata.get("Element.symbol", "") != "":
        file_parts.append(metadata.get("Element.symbol"))
    if metadata.get("Scan.command", "") != "":
        file_parts.append(metadata.get("Scan.command"))
    else:
        file_parts.append("scan")
    file_parts.append(str(metadata.get("Scan.transient_id")))
    # Undecided if we want to use uid to guarantee uniqueness
    # file_parts.append(str(metadata.get("Scan.uid"))[:8])
    if suffix is not None:
        file_parts.append(suffix)
    filename = join(folder, "_".join(file_parts) + "." + ext)
    filename = sanitize_filename(filename)

    return filename


def get_xdi_normalized_data(run, metadata, omit_array_keys=True):
    """
    Get run data, and rename detectors to standard names for XDI export. Modify metadata in place.

    Parameters
    ----------
    run : Run
        The run to normalize.
    metadata : dict
        The metadata to modify.

    Returns
    -------
    columns : list
        The column names to write to the XDI file.
    run_data : np.ndarray
        The data to write to the XDI file.
    metadata : dict
        The modified metadata.
    """
    columns, run_data, tes_rois = get_run_data(
        run, omit=["tes_scan_point_start", "tes_scan_point_end"], omit_array_keys=omit_array_keys
    )
    print("Got XDI Data")

    # Insert tes_mca_pfy if tes_mca_counts is present but tes_mca_pfy is not
    if "tes_mca_counts" in columns and "tes_mca_pfy" not in columns:
        index = columns.index("tes_mca_counts") + 1
        columns.insert(index, "tes_mca_pfy")
        zero_array = np.zeros_like(run_data[index - 1])
        run_data.insert(index, zero_array)

    # Add TES ROI info
    for c in columns:
        if c in tes_rois:
            metadata[f"rois.{c}"] = "{:.2f} {:.2f}".format(*tes_rois[c])

    # Rename TFY and PFY channels
    if "tes_mca_counts" in columns:
        metadata["rois.tfy"] = metadata.pop("rois.tes_mca_counts", "")
        metadata["rois.pfy"] = metadata.pop("rois.tes_mca_pfy", "")

    if "tes_mca_spectrum" in columns:
        metadata["rois.rixs"] = metadata.pop("rois.tes_mca_spectrum", "")

    # Rename energy columns if present
    normalize_detector(
        "nexafs_i0up",
        "i0",
        columns,
        metadata,
        "Beam intensity normalization via drain current from NEXAFS upstream Au mesh"
)
    normalize_detector("nexafs_i1", "itrans", columns, metadata, "Transmission intensity via downstream diode")
    normalize_detector(
        "nexafs_sc", "tey", columns, metadata, "Total electron yield via drain current from NEXAFS sample bar"
    )
    normalize_detector("nexafs_pey", "pey", columns, metadata, "Partial electron yield via NEXAFS Channeltron")
    normalize_detector(
        "nexafs_ref",
        "iref",
        columns,
        metadata,
        "Energy reference via drain current from upstream multimesh reference samples"
)
    normalize_detector(
        "tes_mca_counts", "tfy", columns, metadata, "Total fluorescence yield via counts from TES detector"
    )

    normalize_detector(
        "tes_mca_pfy", "pfy", columns, metadata, "Partial fluorescence yield via counts from TES detector"
    )
    normalize_detector("tes_mca_spectrum", "rixs", columns, metadata, "RIXS spectrum via TES detector")
    normalize_detector(
        "m4cd", "i0_m4cd", columns, metadata, "Drain current from M4 mirror, sometimes useful as a secondary i0"
    )
    normalize_detector("en_energy_setpoint", "energy", columns)
    normalize_detector("seconds", "measurement_time", columns)
    if metadata.get("Scan.motors", "") == "en_energy":
        metadata["Scan.motors"] = "energy"
    if "energy" in columns:
        normalize_detector("en_energy", "energy_readback", columns, metadata, "Monochromator energy encoder readback")
    else:
        normalize_detector("en_energy", "energy", columns)
    exclude_column("ucal_sc", columns, run_data)
    columns, run_data = reorder_columns(columns, run_data, metadata.get("Scan.motors", "time"), 0)
    return columns, run_data, metadata


def exportToXDI(
    folder,
    run,
    headerUpdates={}
):
    """
    Export data to the XAS-Data-Interchange (XDI) ASCII format.

    Parameters
    ----------
    folder : str
        Export directory where the XDI file will be saved.
    run : Run
        The run to export.
    headerUpdates : dict
        Dictionary of additional header fields to update or add.
    verbose : bool
        If True, prints export status messages.

    Returns
    -------
    None
    """
    if "primary" not in run:
        print(f"XDI Export does not support streams other than Primary, skipping {run.start['scan_id']}")
        return False
    metadata = get_xdi_run_header(run, headerUpdates)
    print("Got XDI Metadata")
    filename = make_filename(folder, metadata)

    columns, run_data, metadata = get_xdi_normalized_data(run, metadata)

    fmtStr = generate_format_string(run_data)

    data = np.vstack(run_data).T
    colStr = " ".join(columns)

    header_lines = ["# XDI/1.0 SST-1-NEXAFS/1.0"]
    for key, value in metadata.items():
        header_lines.append(f"# {key}: {value}")
    header_lines.append("# ///")
    header_lines.append(add_comment_to_lines(run.start.get("comment", "")))
    header_lines.append("#" + "-" * 50)
    header_lines.append("# " + colStr)
    header_string = "\n".join(header_lines)
    print(f"Exporting XDI to {filename}")
    with open(filename, "w") as f:
        f.write(header_string)
        f.write("\n")
        np.savetxt(f, data, fmt=fmtStr, delimiter=" ")


def generate_format_string(data):
    """
    Generate a format string for numpy.savetxt based on data type and average value.

    Parameters
    ----------
    data : np.ndarray
        The input data array.

    Returns
    -------
    str
        A format string for numpy.savetxt.
    """
    formats = []
    for column_data in data:
        try:
            if not np.any(np.isfinite(column_data)):
                formats.append("%11.4e")
            elif np.issubdtype(column_data.dtype, np.integer):
                width = len(str(np.nanmax(np.abs(column_data)))) + 1
                formats.append(f"%{width}d")
            else:
                avg_value = np.nanmean(column_data)
                max_value = np.nanmax(np.abs(column_data))
                if np.abs(avg_value) < 1:
                    formats.append("%11.4e")
                else:
                    width = len(str(int(max_value))) + 5  # Add 5 for decimal point, 3 decimals, and sign
                    formats.append(f"%{width}.3f")
        except:
            formats.append("%11.4e")

    return " ".join(formats)
