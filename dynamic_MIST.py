"""
Continuously plots UDP position updates in matplotlib using WebAgg.

SETUP:

1. On your main computer, create an SSH tunnel:

       ssh -L 8988:127.0.0.1:8988 pi@raspberrypi_ip

2. On the Raspberry Pi, run this script:

       python3 dynamic_MIST.py

3. On your main computer, open:

       http://localhost:8988/

The positioning process must send each update to the configured UDP
address as three little-endian float32 values: (x, y, z).
"""

import math
import socket
import struct
import threading

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


# ============================================================
# CONFIGURATION
# ============================================================

REFRESH_RATE = 1.0  # Plot updates per second
UDP_HOST = "127.0.0.1"
UDP_PORT = 5005
SHOW_3D = False
# Anchor positions in centimeters: {anchor_id: (x, y, z)}.
ANCHORS = {}


# ============================================================
# SHARED STATE BETWEEN THREADS
# ============================================================

# The UDP thread writes the newest position.
# The Matplotlib/WebAgg thread reads it.
latest_position = None
pending_positions = []

state_lock = threading.Lock()
stop_event = threading.Event()


# ============================================================
# UDP POSITION RECEIVER
# ============================================================

def udp_receiver_worker():
    """Receive one little-endian float32 (x, y, z) tuple per UDP datagram."""

    global latest_position

    print(f"Listening for position updates on {UDP_HOST}:{UDP_PORT}...")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind((UDP_HOST, UDP_PORT))
            receiver.settimeout(0.5)

            while not stop_event.is_set():
                try:
                    datagram, _ = receiver.recvfrom(1024)
                except socket.timeout:
                    continue

                if len(datagram) != struct.calcsize("<fff"):
                    print(
                        "Ignoring UDP position packet: expected "
                        f"12 bytes, received {len(datagram)}."
                    )
                    continue

                position = struct.unpack("<fff", datagram)
                if not all(math.isfinite(value) for value in position):
                    print("Ignoring UDP position packet with non-finite values.")
                    continue

                with state_lock:
                    latest_position = np.asarray(position, dtype=float)
                    pending_positions.append(latest_position.copy())

    except OSError as exc:
        if not stop_event.is_set():
            print(f"UDP position receiver failed: {exc}")

    finally:
        print("UDP position receiver stopped.")


# ============================================================
# CREATE MATPLOTLIB FIGURE
# ============================================================

if SHOW_3D:
    figure = plt.figure(figsize=(7, 6))
    axis = figure.add_subplot(111, projection="3d")
    axis.set_zlabel("Z (cm)")
else:
    figure, axis = plt.subplots(figsize=(6, 6))
    axis.set_aspect("equal", adjustable="datalim")

axis.set_title("Dynamic Tag Position")
axis.set_xlabel("X (cm)")
axis.set_ylabel("Y (cm)")

if ANCHORS:
    anchor_positions = np.asarray(list(ANCHORS.values()), dtype=float)
    if SHOW_3D:
        axis.plot(
            anchor_positions[:, 0],
            anchor_positions[:, 1],
            anchor_positions[:, 2],
            "b*",
            markersize=12,
            label="Anchors",
        )
    else:
        axis.plot(
            anchor_positions[:, 0],
            anchor_positions[:, 1],
            "b*",
            markersize=12,
            label="Anchors",
        )


# ============================================================
# TRAJECTORY
# ============================================================

if SHOW_3D:
    trajectory_line, = axis.plot(
        [], [], [], "r-", linewidth=1.5, label="Trajectory"
    )
    position_point, = axis.plot(
        [], [], [], "ro", markersize=6, label="Tag"
    )
else:
    trajectory_line, = axis.plot(
        [], [], "r-", linewidth=1.5, label="Trajectory"
    )
    position_point, = axis.plot(
        [], [], "ro", markersize=6, label="Tag"
    )

axis.legend()

trajectory = []


# ============================================================
# MATPLOTLIB UPDATE FUNCTION
# ============================================================

def update_plot(frame):
    """Read the latest UDP position and update the plot in the WebAgg thread."""

    with state_lock:
        position = None if latest_position is None else latest_position.copy()
        new_positions = [update.copy() for update in pending_positions]
        pending_positions.clear()

    if position is None:
        return trajectory_line, position_point

    if new_positions:
        trajectory.extend(new_positions)
        trajectory_array = np.asarray(trajectory)
        if SHOW_3D:
            trajectory_line.set_data_3d(
                trajectory_array[:, 0],
                trajectory_array[:, 1],
                trajectory_array[:, 2],
            )
            axis.auto_scale_xyz(
                trajectory_array[:, 0],
                trajectory_array[:, 1],
                trajectory_array[:, 2],
            )
        else:
            trajectory_line.set_data(
                trajectory_array[:, 0],
                trajectory_array[:, 1],
            )
            axis.relim()
            axis.autoscale_view()

    if SHOW_3D:
        position_point.set_data_3d(
            [position[0]],
            [position[1]],
            [position[2]],
        )
    else:
        position_point.set_data([position[0]], [position[1]])
        axis.set_title(f"Dynamic Tag Position (Z={position[2]:.2f} cm)")

    return trajectory_line, position_point


# ============================================================
# START ANIMATION
# ============================================================

animation = FuncAnimation(
    figure,
    update_plot,
    interval=int(1000 / REFRESH_RATE),
    blit=False,
    cache_frame_data=False,
)


# ============================================================
# START UDP RECEIVER THREAD
# ============================================================

worker = threading.Thread(
    target=udp_receiver_worker,
    daemon=True,
    name="UDP-Position-Receiver",
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
print()
print(f" UDP position input: {UDP_HOST}:{UDP_PORT} (3 little-endian float32 values)")
print("==============================================")
print()


# ============================================================
# RUN WEBAGG
# ============================================================

try:
    # WebAgg owns the main thread; the UDP receiver runs in the background.
    plt.show()

except KeyboardInterrupt:
    print()
    print("Ctrl-C received.")

finally:
    print()
    print("Stopping...")

    stop_event.set()
    worker.join(timeout=5)

    plt.close("all")

    print("Stopped.")
