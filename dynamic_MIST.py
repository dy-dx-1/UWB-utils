"""
Continuously positions a DW1000 tag and dynamically plots the position
in matplotlib using WebAgg.

SETUP:

1. On your main computer, create an SSH tunnel:

       ssh -L 8988:127.0.0.1:8988 pi@raspberrypi_ip

2. On the Raspberry Pi, run this script:

       python3 your_script.py

3. On your main computer, open:

       http://localhost:8988/

The DW1000 ranging runs in a background thread so that the WebAgg
server remains responsive.
"""

import sys
import threading
from pathlib import Path

import numpy as np


# ============================================================
# MATPLOTLIB WEBAGG CONFIGURATION
# ============================================================

# IMPORTANT:
# This must happen BEFORE importing pyplot.
import matplotlib

matplotlib.use("WebAgg")

matplotlib.rcParams["webagg.address"] = "127.0.0.1"
matplotlib.rcParams["webagg.port"] = 8988
matplotlib.rcParams["webagg.open_in_browser"] = False

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from scipy.optimize import least_squares


# ============================================================
# IMPORT YOUR PROJECT
# ============================================================

parent_dir = str(Path(__file__).resolve().parent.parent)

if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from src.clamour.interfaces.bitcraze_tag import BitcrazeTag
from src.clamour.interfaces.anchors import Anchors


# ============================================================
# CONFIGURATION
# ============================================================

REFRESH_RATE = 1.0  # Plot updates per second

TAG_ID = 11

DW1000_BUS = 0
DW1000_CS = 0

CHANNEL = 2
PRF = 64
BITRATE = 6.8
PREAMBLE_LENGTH = 128
PREAMBLE_CODE = 9

SMART_TX_POWER = True
TX_POWER_SETTINGS = None


# ============================================================
# TRILATERATION
# ============================================================

def trilaterate(anchor_positions, distances, initial_position=None):
    """
    Estimate a 2D tag position from at least three ranges.

    anchor_positions:
        Nx2 array containing anchor X/Y positions.

    distances:
        N-element array containing distances to each anchor.

    Returns:
        [x, y] estimated position, or None if unsuccessful.
    """

    anchor_positions = np.asarray(
        anchor_positions,
        dtype=float
    )

    distances = np.asarray(
        distances,
        dtype=float
    )

    if len(anchor_positions) < 3:
        return None

    if initial_position is None:
        initial_position = np.mean(
            anchor_positions,
            axis=0
        )

    def residuals(position):
        estimated_distances = np.linalg.norm(
            anchor_positions - position,
            axis=1
        )

        return estimated_distances - distances

    result = least_squares(
        residuals,
        np.asarray(initial_position, dtype=float)
    )

    if not result.success:
        return None

    return result.x


# ============================================================
# LOAD ANCHORS
# ============================================================

print("Loading anchors...")

anchors = Anchors().anchors_dict

anchor_positions = np.array(
    [
        anchor[:2]
        for anchor in anchors.values()
    ],
    dtype=float
)

print()
print("Anchors:")

for anchor_id, anchor in anchors.items():
    print(
        f"  Anchor {anchor_id}: "
        f"X={anchor[0]}, Y={anchor[1]}"
    )

print()


# ============================================================
# SHARED STATE BETWEEN THREADS
# ============================================================

# The DW1000 thread writes latest_position.
# The Matplotlib/WebAgg thread reads it.

latest_position = None

state_lock = threading.Lock()

stop_event = threading.Event()


# ============================================================
# DW1000 RANGING WORKER
# ============================================================

def ranging_worker():
    """
    Runs continuously in the background.

    This thread does all blocking DW1000 operations.
    It NEVER directly modifies Matplotlib.
    """

    global latest_position

    print("Starting DW1000 ranging worker...")

    try:

        with BitcrazeTag(
            tag_id=TAG_ID,
            dw1000_bus=DW1000_BUS,
            dw1000_cs=DW1000_CS,
            channel=CHANNEL,
            PRF=PRF,
            bitrate=BITRATE,
            preamble_length=PREAMBLE_LENGTH,
            preamble_code=PREAMBLE_CODE,
            smart_tx_power=SMART_TX_POWER,
            tx_power_settings=TX_POWER_SETTINGS,
        ) as tag:

            print("DW1000 tag initialized.")
            print()

            while not stop_event.is_set():

                measured_positions = []
                measured_distances = []

                # ------------------------------------------------
                # Range to every anchor
                # ------------------------------------------------

                for anchor_id, anchor_pos in anchors.items():

                    if stop_event.is_set():
                        break

                    try:

                        distance, _ = tag.compute_range(
                            anchor_id
                        )

                    except Exception as exc:

                        print(
                            f"Range error for anchor "
                            f"{anchor_id}: {exc}"
                        )

                        continue

                    if distance is not None:

                        measured_positions.append(
                            anchor_pos[:2]
                        )

                        measured_distances.append(
                            distance
                        )

                        print(
                            f"  Anchor {anchor_id}: "
                            f"{distance:.2f}"
                        )

                    else:

                        print(
                            f"  Anchor {anchor_id}: "
                            f"no range"
                        )

                # ------------------------------------------------
                # Check whether we have enough ranges
                # ------------------------------------------------

                number_of_ranges = len(
                    measured_positions
                )

                print(
                    f"Successful ranges: "
                    f"{number_of_ranges}/{len(anchors)}"
                )

                if number_of_ranges >= 3:

                    # --------------------------------------------
                    # Calculate position
                    # --------------------------------------------

                    position = trilaterate(
                        measured_positions,
                        measured_distances
                    )

                    if position is not None:

                        position = np.asarray(
                            position,
                            dtype=float
                        )

                        # ----------------------------------------
                        # Store position for plotting thread
                        # ----------------------------------------

                        with state_lock:

                            latest_position = position.copy()

                        print(
                            f"POSITION: "
                            f"X={position[0]:.2f} cm, "
                            f"Y={position[1]:.2f} cm"
                        )

                    else:

                        print(
                            "Trilateration failed."
                        )

                else:

                    print(
                        "Not enough valid ranges "
                        "for trilateration."
                    )

                print()

    except Exception as exc:

        print()
        print(
            "DW1000 worker crashed:"
        )

        print(exc)

    finally:

        print(
            "DW1000 ranging worker stopped."
        )


# ============================================================
# CREATE MATPLOTLIB FIGURE
# ============================================================

figure, axis = plt.subplots(
    figsize=(6, 6)
)

axis.set_title(
    "Dynamic DW1000 Tag Position"
)

axis.set_xlabel(
    "X (cm)"
)

axis.set_ylabel(
    "Y (cm)"
)


# ============================================================
# DRAW ANCHORS
# ============================================================

axis.plot(
    anchor_positions[:, 0],
    anchor_positions[:, 1],
    "b*",
    markersize=12,
    label="Anchors"
)


# ============================================================
# TRAJECTORY
# ============================================================

axis.set_aspect(
    "equal",
    adjustable="datalim"
)

trajectory_line, = axis.plot(
    [],
    [],
    "r-",
    linewidth=1.5,
    label="Trajectory"
)

position_point, = axis.plot(
    [],
    [],
    "ro",
    markersize=6,
    label="Tag"
)

axis.legend()


# Stores all positions seen by the plotting thread.
trajectory = []


# ============================================================
# MATPLOTLIB UPDATE FUNCTION
# ============================================================

def update_plot(frame):
    """
    Called periodically by Matplotlib's event loop.

    IMPORTANT:
    This runs in the WebAgg/main thread.

    It reads the latest position produced by the DW1000
    background thread and updates the plot.
    """

    global trajectory

    # ----------------------------------------------------------
    # Safely copy the latest position
    # ----------------------------------------------------------

    with state_lock:

        if latest_position is None:
            position = None

        else:
            position = latest_position.copy()

    # ----------------------------------------------------------
    # No position yet
    # ----------------------------------------------------------

    if position is None:

        return (
            trajectory_line,
            position_point,
        )

    # ----------------------------------------------------------
    # Add position to trajectory
    # ----------------------------------------------------------

    trajectory.append(position)

    trajectory_array = np.asarray(
        trajectory
    )

    # ----------------------------------------------------------
    # Update trajectory line
    # ----------------------------------------------------------

    trajectory_line.set_data(
        trajectory_array[:, 0],
        trajectory_array[:, 1]
    )

    # ----------------------------------------------------------
    # Update current position marker
    # ----------------------------------------------------------

    position_point.set_data(
        [position[0]],
        [position[1]]
    )

    # ----------------------------------------------------------
    # Update axes
    # ----------------------------------------------------------

    axis.relim()

    axis.autoscale_view()

    return (
        trajectory_line,
        position_point,
    )


# ============================================================
# START ANIMATION
# ============================================================

animation = FuncAnimation(
    figure,
    update_plot,
    interval=int(
        1000 / REFRESH_RATE
    ),
    blit=False,
    cache_frame_data=False,
)


# ============================================================
# START DW1000 THREAD
# ============================================================

worker = threading.Thread(
    target=ranging_worker,
    daemon=True,
    name="DW1000-Ranging"
)

worker.start()


# ============================================================
# START WEBAGG
# ============================================================

print()
print("==============================================")
print(" WebAgg server starting")
print()
print(" Open this on your MAIN COMPUTER:")
print()
print(" http://localhost:8988/")
print()
print(" SSH tunnel should be:")
print()
print(" ssh -L 8988:127.0.0.1:8988 pi@RASPBERRY_PI_IP")
print("==============================================")
print()


# ============================================================
# RUN WEBAGG
# ============================================================

try:

    # IMPORTANT:
    #
    # WebAgg owns the main thread.
    #
    # The DW1000 ranging is running in the background,
    # so WebAgg can continuously process browser requests.

    plt.show()

except KeyboardInterrupt:

    print()
    print("Ctrl-C received.")

finally:

    print()
    print("Stopping...")

    # Tell DW1000 thread to stop.
    stop_event.set()

    # Give it a few seconds to finish.
    worker.join(
        timeout=5
    )

    # Close Matplotlib.
    plt.close(
        "all"
    )

    print(
        "Stopped."
    )