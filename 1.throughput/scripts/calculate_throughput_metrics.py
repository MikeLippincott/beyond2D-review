#!/usr/bin/env python

# In[ ]:


import numpy as np
import pandas as pd

# ## Plot Throughput Concerns
# https://www.yokogawa.com/us/solutions/products-and-services/life-science/high-content-analysis/cv8000/#Details__Specifications
# Data volume (assuming 2560×2160 sCMOS frames at 16-bit, about 11 MB each, no binning)
# * x-axis is the number of samples
# * y-axis is the throughput (samples per unit time) or the GBs

# ## Functions and constants

# In[ ]:


TIME_UNITS_IN_SECONDS = {"ms": 1 / 1000, "s": 1, "min": 60, "h": 3600}
BYTE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


def time_conversions(time: float, in_unit: str, out_unit: str) -> float:
    """Convert a duration between time units.

    Parameters
    ----------
    time : float
        The duration to convert, expressed in ``in_unit``.
    in_unit : str
        Unit of ``time``. One of "ms", "s", "min", "h".
    out_unit : str
        Unit to convert to. One of "ms", "s", "min", "h".

    Returns
    -------
    float
        The duration expressed in ``out_unit``.

    Raises
    ------
    ValueError
        If either unit is not supported.
    """
    if in_unit not in TIME_UNITS_IN_SECONDS or out_unit not in TIME_UNITS_IN_SECONDS:
        raise ValueError(f"Conversion from {in_unit} to {out_unit} is not supported.")
    return time * TIME_UNITS_IN_SECONDS[in_unit] / TIME_UNITS_IN_SECONDS[out_unit]


def calculate_timepoints(total_time: float, interval: float) -> int:
    """Number of timepoints that fit in an experiment at a fixed interval.

    The first timepoint is acquired at time zero, so an experiment of
    ``total_time`` with one timepoint every ``interval`` has
    ``total_time // interval + 1`` timepoints.

    Parameters
    ----------
    total_time : float
        Length of the experiment. Must use the same unit as ``interval``.
        Zero means a single static acquisition.
    interval : float
        Time between the start of consecutive timepoints. Zero means a
        single static acquisition.

    Returns
    -------
    int
        The number of timepoints, 1 for a static acquisition.

    Raises
    ------
    ValueError
        If ``interval`` is longer than ``total_time``, since not even a
        second timepoint can then be acquired.
    """
    if interval <= 0 or total_time <= 0:
        return 1
    if interval > total_time:
        raise ValueError(
            f"The interval ({interval}) is longer than the total time ({total_time})."
        )
    return int(total_time // interval) + 1


def check_interval_sufficiency(interval_s: float, time_per_plate_s: float) -> bool:
    """Check that one full pass over the plate fits inside the interval.

    Parameters
    ----------
    interval_s : float
        Time between the start of consecutive timepoints, in seconds.
    time_per_plate_s : float
        Time to image every FOV on the plate once, in seconds.

    Returns
    -------
    bool
        True if a pass finishes before the next timepoint is due.
    """
    return time_per_plate_s <= interval_s


def check_interval_size_vs_total_time(interval_s: float, total_time_s: float) -> bool:
    """Check that the interval is not longer than the whole experiment.

    Parameters
    ----------
    interval_s : float
        Time between the start of consecutive timepoints, in seconds.
    total_time_s : float
        Length of the whole experiment, in seconds. 0 means no total time
        is set, so any interval is accepted.

    Returns
    -------
    bool
        False if ``interval_s`` is longer than ``total_time_s``, since a
        second timepoint could then never be acquired.
    """
    return total_time_s <= 0 or interval_s <= total_time_s


def calculate_data_volume(image_size_bytes: int, num_images: int) -> int:
    """Total size of a set of equally sized images.

    Parameters
    ----------
    image_size_bytes : int
        Size of one image in bytes.
    num_images : int
        Number of images acquired.

    Returns
    -------
    int
        Total data volume in bytes.
    """
    return image_size_bytes * num_images


def convert_bytes(bytes_num_in: float, in_unit: str, out_unit: str) -> float:
    """Convert a data size between binary (1024-based) units.

    Parameters
    ----------
    bytes_num_in : float
        The size to convert, expressed in ``in_unit``.
    in_unit : str
        Unit of ``bytes_num_in``. One of "B", "KB", "MB", "GB", "TB", "PB".
    out_unit : str
        Unit to convert to. One of "B", "KB", "MB", "GB", "TB", "PB".

    Returns
    -------
    float
        The size expressed in ``out_unit``.

    Raises
    ------
    ValueError
        If either unit is not supported.
    """
    if in_unit not in BYTE_UNITS or out_unit not in BYTE_UNITS:
        raise ValueError(f"Conversion from {in_unit} to {out_unit} is not supported.")
    return bytes_num_in * 1024 ** (BYTE_UNITS.index(in_unit) - BYTE_UNITS.index(out_unit))


# In[ ]:


def calculate_throughput(
    plates: int,
    wells: int,
    fovs_per_well: int,
    channels_exposure_dict: dict,
    motor_movement_time: float,
    z_motor_movement_time: float,
    z_steps: int,
    timepoints: int,
    interval: float = 0,
    total_time: float = 0,
) -> dict:
    """Time, image count and dimensionality of a plate acquisition.

    One pass images every FOV on the plate. The scope cannot start the next
    timepoint before the current pass is done, so when a pass takes longer
    than ``interval`` the cycle stretches to the length of a pass. If
    ``total_time`` is given, the timepoints that fit are recomputed from the
    real cycle time; a pass longer than ``total_time`` is still imaged once
    (a static acquisition).

    Parameters
    ----------
    plates : int
        Number of plates imaged.
    wells : int
        Number of wells per plate.
    fovs_per_well : int
        Number of fields of view imaged in each well.
    channels_exposure_dict : dict
        Maps each channel name to its exposure time in milliseconds.
    motor_movement_time : float
        Time in milliseconds for one stage or z motor move.
    z_motor_movement_time : float
        Time in milliseconds for one z motor move.
    z_steps : int
        Number of z planes acquired per FOV (1 for no z stack).
    timepoints : int
        Requested number of timepoints (1 for no time series).
    interval : float, default 0
        Seconds between the start of consecutive timepoints. 0 means a
        static acquisition (one timepoint).
    total_time : float, default 0
        Length of the whole experiment in seconds. 0 means a static
        acquisition (one timepoint).

    Returns
    -------
    dict
        total_fovs : int
            FOVs imaged in one pass over all plates.
        total_time_per_fov : float
            Seconds to image one FOV (exposures, stage move and z moves).
        time_per_plate : float
            Seconds for one pass over every FOV.
        cycle_time : float
            Seconds between the start of consecutive passes.
        timepoints_requested : int
            The ``timepoints`` that was passed in.
        timepoints : int
            Timepoints actually acquired, at least 1.
        total_plate_time : float
            Seconds from the start of the first pass to the end of the last.
        imaging_time : float
            Seconds spent imaging, excluding idle time between passes.
        duty_cycle : float
            ``time_per_plate / cycle_time``; 1 means the scope never idles.
        total_images : int
            Images acquired across all timepoints, z planes and channels.
        dimensions : str
            "XY", "XYZ", "XYT" or "XYZT" depending on what was acquired.
        interval_is_valid : bool
            False if a pass is longer than ``interval``.
    """
    num_channels = len(channels_exposure_dict)
    total_fovs = plates * wells * fovs_per_well
    total_exposure_time = sum(channels_exposure_dict.values())
    zstep_time = z_steps * z_motor_movement_time
    total_time_per_fov = (total_exposure_time + motor_movement_time + zstep_time) / 1000  # seconds
    time_per_plate = total_fovs * total_time_per_fov  # seconds

    interval_is_valid = True
    cycle_time = time_per_plate
    if interval > 0:
        interval_is_valid = check_interval_sufficiency(interval, time_per_plate)
        if interval_is_valid:
            interval_is_valid = check_interval_size_vs_total_time(interval, total_time)
        cycle_time = max(interval, time_per_plate)
    elif interval == 0 and total_time == 1:
        interval_is_valid = False

    timepoints_requested = timepoints
    if interval <= 1 or total_time <= 1:
        # no interval or no total time: a single static acquisition (XY or XYZ)
        timepoints = 1
    else:
        timepoints = max(1, int((total_time - time_per_plate) // cycle_time) + 1)

    total_plate_time = (timepoints - 1) * cycle_time + time_per_plate
    dimensions = "XY"
    if z_steps > 1:
        dimensions += "Z"
    if timepoints > 1:
        dimensions += "T"

    return {
        "total_fovs": total_fovs,
        "total_time_per_fov": total_time_per_fov,
        "time_per_plate": time_per_plate,
        "cycle_time": cycle_time,
        "timepoints_requested": timepoints_requested,
        "timepoints": timepoints,
        "total_plate_time": total_plate_time,
        "imaging_time": timepoints * time_per_plate,
        "duty_cycle": time_per_plate / cycle_time if cycle_time else np.nan,
        "total_images": total_fovs * timepoints * z_steps * num_channels,
        "dimensions": dimensions,
        "interval_is_valid": interval_is_valid,
    }


# In[ ]:


# define the time it takes to screen a sample (imaging time)
IMAGE_SIZE = (2560, 2160) # pixels
IMAGE_BIT_DEPTH = 16 # bits
IMAGE_SIZE_BYTES = IMAGE_SIZE[0] * IMAGE_SIZE[1] * IMAGE_BIT_DEPTH // 8 # bytes
PLATES = 1
WELLS = 308
FOVS_PER_WELL = 4
CHANNELS_EXPOSURE_DICT = {
    "channel_1": 100,
    "channel_2": 100,
    "channel_3": 100,
    "channel_4": 100
}
MOTOR_MOVEMENT_TIME = 350 # ms
Z_MOTOR_MOVEMENT_TIME = 30 # ms
Z_STEPS = 5
INTERVAL = 30 # min
TOTAL_TIME = 24 # hours
SEARCH_SPACE = {
    "wells" : [60,308],
    "fovs_per_well": [1,2,4,9,16,25],
    "interval_min": [0,1, 5, 10, 30, 60, 120, 180, 240, 300, 360, 720, 1440,],
    "total_time_h": [0,1, 3, 6, 12, 24, 72, 96],
    "z_steps": [1, 5, 25, 50, 100],
}

STATIC_VALUES = (0, 1)  # interval_min / total_time_h allowed for acquisitions without a time dimension


# In[ ]:


timepoints = calculate_timepoints(
    total_time=time_conversions(TOTAL_TIME, "h", "s"),
    interval=time_conversions(INTERVAL, "min", "s")
)
throughput_dict = calculate_throughput(
    plates=PLATES,
    wells=WELLS,
    fovs_per_well=FOVS_PER_WELL,
    channels_exposure_dict=CHANNELS_EXPOSURE_DICT,
    motor_movement_time=MOTOR_MOVEMENT_TIME,
    z_motor_movement_time=Z_MOTOR_MOVEMENT_TIME,
    z_steps=Z_STEPS,
    timepoints=timepoints,
    interval=time_conversions(INTERVAL, "min", "s"),
    total_time=time_conversions(TOTAL_TIME, "h", "s")
)
throughput_dict


# ## Parameter sweep
# Sweep samples (wells x FOVs per well), imaging interval, total experiment time and z steps.
# Only the product wells x FOVs matters for throughput, so samples are swept directly.

# In[ ]:


import itertools


def run_sweep(
    search_space: dict,
    plates: int,
    channels_exposure_dict: dict,
    motor_movement_time: float,
    z_motor_movement_time: float,
) -> pd.DataFrame:
    """Evaluate ``calculate_throughput`` over every combination of a search space.

    Combinations whose interval is longer than the total time are skipped,
    since no second timepoint could ever be acquired, as are combinations
    with ``interval_min == 0`` and ``total_time_h == 1``. Combinations that end
    up without a time dimension (XY or XYZ) are flagged
    ``interval_is_valid=False`` unless both ``interval_min`` and
    ``total_time_h`` are 0 or 1.

    Parameters
    ----------
    search_space : dict
        Maps each swept parameter to a list of values. Must contain
        "wells" (number of wells), "fovs_per_well" (FOVs per well), "interval_min" (minutes),
        "total_time_h" (hours) and "z_steps".
    plates : int
        Number of plates imaged.
    channels_exposure_dict : dict
        Maps each channel name to its exposure time in milliseconds.
    motor_movement_time : float
        Time in milliseconds for one stage move.
    z_motor_movement_time : float
        Time in milliseconds for one z motor move.

    Returns
    -------
    pandas.DataFrame
        One row per valid combination, with the swept parameters, the
        outputs of ``calculate_throughput`` (times in seconds) and the data
        volume in TB.
    """
    rows = []
    keys = list(search_space)
    for values in itertools.product(*search_space.values()):
        p = dict(zip(keys, values))
        if p["interval_min"] == 0 and p["total_time_h"] == 1:
            # a total time with no interval is not a valid combination
            continue
        interval_s = time_conversions(p["interval_min"], "min", "s")
        total_time_s = time_conversions(p["total_time_h"], "h", "s")
        try:
            tp = calculate_timepoints(total_time=total_time_s, interval=interval_s)
        except ValueError:
            continue
        res = calculate_throughput(
            plates=plates,
            wells=p["wells"],
            fovs_per_well=p["fovs_per_well"],
            channels_exposure_dict=channels_exposure_dict,
            motor_movement_time=motor_movement_time,
            z_motor_movement_time=z_motor_movement_time,
            z_steps=p["z_steps"],
            timepoints=tp,
            interval=interval_s,
            total_time=total_time_s,
        )
        # a combination without a time dimension is a static acquisition, which
        # only makes sense for an interval and total time of 0 or 1
        interval_is_valid = res["interval_is_valid"]
        if "T" not in res["dimensions"] and not (
            p["interval_min"] in STATIC_VALUES and p["total_time_h"] in STATIC_VALUES
        ):
            interval_is_valid = False
        rows.append({
            **p,
            "timepoints_requested": tp,
            "timepoints": res["timepoints"],
            "total_images": res["total_images"],
            "data_TB": convert_bytes(calculate_data_volume(IMAGE_SIZE_BYTES, res["total_images"]), "B", "TB"),
            "total_time_per_fov_s": res["total_time_per_fov"],
            "time_per_plate_s": res["time_per_plate"],
            "cycle_time_s": res["cycle_time"],
            "total_plate_time_s": res["total_plate_time"],
            "imaging_time_s": res["imaging_time"],
            "duty_cycle": res["duty_cycle"],
            "dimensions": res["dimensions"],
            "interval_is_valid": interval_is_valid,
        })
    return pd.DataFrame(rows)

sweep_df = run_sweep(
    SEARCH_SPACE,
    plates=PLATES,
    channels_exposure_dict=CHANNELS_EXPOSURE_DICT,
    motor_movement_time=MOTOR_MOVEMENT_TIME,
    z_motor_movement_time=Z_MOTOR_MOVEMENT_TIME,
)
# set the total plate_time_s to the total_time_h if total_time_h > 0
sweep_df['total_plate_time_s'] = sweep_df.apply(
    lambda row: time_conversions(row['total_time_h'], 'h', 's') if row['total_time_h'] > 0 else row['total_plate_time_s'],
    axis=1
)
sweep_df.head()


# In[ ]:


from pathlib import Path

results_dir = Path("../results")
results_dir.mkdir(exist_ok=True)

# derived columns used by the plots
sweep_df["samples"] = PLATES * sweep_df["wells"] * sweep_df["fovs_per_well"]
sweep_df["interval_h"] = sweep_df["interval_min"] / 60
sweep_df["voxel_number"] = sweep_df["total_images"] * IMAGE_SIZE[0] * IMAGE_SIZE[1]
sweep_df["log_ratio"] = np.log10(sweep_df["time_per_plate_s"] / (sweep_df["interval_h"] * 3600))  # inf where interval is 0

# the default plate (WELLS x FOVS_PER_WELL) if it is in the sweep, otherwise the largest sample count
default_samples = PLATES * WELLS * FOVS_PER_WELL
plot_samples = default_samples if default_samples in sweep_df["samples"].values else sweep_df["samples"].max()
plotted = sweep_df[(sweep_df["samples"] == plot_samples) & (sweep_df["interval_min"] > 0)]

# plot 1, data volume vs total time: needs a time series (total time > 0). Without a
# time dimension (XY, XYZ) one pass is acquired whatever the interval or total time is,
# so those rows are identical copies; keep the shortest total time at which one pass fits
series_df = plotted[plotted["total_time_h"] > 0]
static = ~series_df["dimensions"].str.contains("T")
series_df = pd.concat([
    series_df[~static],
    series_df[static].sort_values(["total_time_h", "interval_min"]).drop_duplicates(["samples", "z_steps"]),
]).sort_values(["dimensions", "z_steps", "interval_min", "total_time_h"]).reset_index(drop=True)

# plot 2, which z steps and intervals are possible: one row per z steps and interval
feasibility_df = (
    plotted[["samples", "z_steps", "interval_min", "interval_h", "time_per_plate_s", "log_ratio"]]
    .drop_duplicates(["z_steps", "interval_min"])
    .reset_index(drop=True)
)

# plot 3, which samples are possible: z steps vs samples at the default interval, and
# samples vs interval at the default z steps
feasibility_all = (
    sweep_df[sweep_df["interval_min"] > 0]
    [["samples", "z_steps", "interval_min", "interval_h", "time_per_plate_s", "log_ratio"]]
    .drop_duplicates(["samples", "z_steps", "interval_min"])
    .sort_values(["samples", "z_steps", "interval_min"])
)
feasibility_z_samples_df = feasibility_all[feasibility_all["interval_min"] == INTERVAL].reset_index(drop=True)
feasibility_samples_interval_df = feasibility_all[feasibility_all["z_steps"] == Z_STEPS].reset_index(drop=True)

sweep_df.to_csv(results_dir / "throughput_sweep.csv", index=False)
series_df.to_csv(results_dir / "throughput_series.csv", index=False)
feasibility_df.to_csv(results_dir / "throughput_feasibility.csv", index=False)
feasibility_z_samples_df.to_csv(results_dir / "throughput_feasibility_z_samples.csv", index=False)
feasibility_samples_interval_df.to_csv(results_dir / "throughput_feasibility_samples_interval.csv", index=False)
sweep_df.shape, series_df.shape, feasibility_df.shape, feasibility_z_samples_df.shape, feasibility_samples_interval_df.shape


# ## Samples that can be profiled per added dimension
# How many well-FOVs (wells x FOVs per well) the scope can image in a given amount of scope time, up to `MAX_PLATES` plates of `WELLS_PER_PLATE` wells, for each dimension acquired. Each well is imaged at every number of FOVs in `fovs_per_well_space`, with `Z_STEPS` z planes for the Z dimensions and a time series of `TOTAL_TIME` hours with an image every `INTERVAL` minutes for the T dimensions.
#
# - XY and XYZ: one pass over every well, so well-FOVs = FOVs per well x scope time / time per well.
# - XYT and XYZT: a batch of wells is imaged for the whole time series. The scope can only image as many wells as fit in one interval (interval / time per well), and the next batch can only start when the time series ends, so well-FOVs = FOVs per well x whole time series that fit in the scope time x wells per interval.

# In[ ]:


WELLS_PER_PLATE = 308
MAX_PLATES = 10000
fovs_per_well_space = [4,9,16,25]
BUDGET_DAYS = np.arange(1, 101)  # scope time available, in days

def time_per_well(z_steps: int, fovs_per_well: int) -> float:
    """Seconds to image one well: ``fovs_per_well`` FOVs with ``z_steps`` planes in every channel."""
    return calculate_throughput(
        plates=1,
        wells=1,
        fovs_per_well=fovs_per_well,
        channels_exposure_dict=CHANNELS_EXPOSURE_DICT,
        motor_movement_time=MOTOR_MOVEMENT_TIME,
        z_motor_movement_time=Z_MOTOR_MOVEMENT_TIME,
        z_steps=z_steps,
        timepoints=1,
    )["time_per_plate"]


def wells_profiled(budget_s: float, z_steps: int, fovs_per_well: int, time_series: bool) -> int:
    """Wells that can be profiled in a scope time budget, capped at ``MAX_PLATES`` plates.

    Parameters
    ----------
    budget_s : float
        Scope time available, in seconds.
    z_steps : int
        Z planes per FOV (1 for no z stack).
    fovs_per_well : int
        FOVs imaged in each well.
    time_series : bool
        If True, every well is imaged every ``INTERVAL`` minutes for ``TOTAL_TIME``
        hours, so a batch is limited to the wells that fit in one interval and a
        batch occupies the scope for the whole time series.

    Returns
    -------
    int
        Number of wells profiled.
    """
    well_s = time_per_well(z_steps, fovs_per_well)
    if time_series:
        interval_s = time_conversions(INTERVAL, "min", "s")
        batches = budget_s // time_conversions(TOTAL_TIME, "h", "s")
        wells = batches * (interval_s // well_s)
    else:
        wells = budget_s // well_s
    return int(min(wells, MAX_PLATES * WELLS_PER_PLATE))


DIMENSIONS = {"XY": (1, False), "XYZ": (Z_STEPS, False), "XYT": (1, True), "XYZT": (Z_STEPS, True)}
capacity_df = pd.DataFrame([
    {
        "dimensions": dimensions,
        "z_steps": z_steps,
        "fovs_per_well": fovs_per_well,
        "budget_days": days,
        "wells": wells_profiled(time_conversions(days * 24, "h", "s"), z_steps, fovs_per_well, time_series),
    }
    for fovs_per_well in fovs_per_well_space
    for dimensions, (z_steps, time_series) in DIMENSIONS.items()
    for days in BUDGET_DAYS
])
capacity_df["plates"] = capacity_df["wells"] / WELLS_PER_PLATE
capacity_df["wells_per_plate"] = WELLS_PER_PLATE
capacity_df["max_plates"] = MAX_PLATES
capacity_df["well_fovs"] = capacity_df["wells"] * capacity_df["fovs_per_well"]
capacity_df.to_csv(results_dir / "throughput_capacity.csv", index=False)
capacity_df.groupby(["fovs_per_well", "dimensions"]).agg(
    seconds_per_well=("z_steps", lambda z: time_per_well(z.iloc[0], capacity_df.loc[z.index[0], "fovs_per_well"])),
    max_plates_profiled=("plates", "max"),
)


# In[ ]:


sweep_df


# In[ ]:
