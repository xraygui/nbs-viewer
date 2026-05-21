import numpy as np


def deduplicate_motor_data(timestamps, data):

    # Motors often have duplicate timestamps, so we need to deduplicate them
    unique_ts, unique_ts_idx = np.unique(timestamps, return_index=True)
    unique_data = data[unique_ts_idx]

    # Motors often have a long settling time at the end of a scan, so we remove points where the motor is not moving
    data_diff = np.abs(np.gradient(unique_data))
    diff_threshold = 0.1
    data_idx = data_diff > diff_threshold * np.mean(data_diff)
    unique_ts = unique_ts[data_idx]
    unique_data = unique_data[data_idx]

    return unique_ts, unique_data
