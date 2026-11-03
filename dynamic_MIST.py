"""
Continuously plots UDP position updates in matplotlib using WebAgg. 
This script is designed to be ran on a remote computer through SSH and displayed on a local computer with the web interface

SETUP:

1. On your main computer, create an SSH tunnel:

       ssh -L 8988:127.0.0.1:8988 pi@raspberrypi_ip

2. On the Raspberry Pi, run this script.

3. On your main computer, open: http://localhost:8988/

The positioning process must send each update to the configured UDP
address as a little-endian int32 tag ID followed by three float32 coordinates:
(id, x, y, z), packed with ``<ifff``.
"""

import itertools
import math
import socket
import struct
import threading

import numpy as np


# ============================================================
# CONFIGURATION
# ============================================================

REFRESH_RATE = 1.0  # Plot updates per second
UDP_HOST = "127.0.0.1"
UDP_PORT = 5005
SHOW_3D = False
# Anchor positions in the same units as the coordinates: {anchor_id: (x, y, z)}.
ANCHORS = {1: (4.736, 2.194, 1.213), 
           2: (1.373, 5.520, 2.190), 
           3: (1.372, 0.150, 0.128), 
           4: (4.736, 2.194, 0.302), 
           5: (0.793, 2.971, 2.190), 
           6: (4.582, 6.040, 1.460), 
           7: (0.223, 0.458, 2.190), 
           8: (5.045, 4.194, 1.070)} 

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
# SHARED STATE BETWEEN THREADS
# ============================================================

# The UDP thread writes the newest position for each tag.
# The Matplotlib/WebAgg thread reads it.
latest_positions = {}
pending_positions = []

state_lock = threading.Lock()
stop_event = threading.Event()


# ============================================================
# UDP POSITION RECEIVER
# ============================================================

def udp_receiver_worker():
    """Receive one little-endian int32/float32 (id, x, y, z) tuple per datagram."""

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

                if len(datagram) != struct.calcsize("<ifff"):
                    print(
                        "Ignoring UDP position packet: expected "
                        f"16 bytes, received {len(datagram)}."
                    )
                    continue

                tag_id, x, y, z = struct.unpack("<ifff", datagram)
                position = (x, y, z)
                if not all(math.isfinite(value) for value in position):
                    print("Ignoring UDP position packet with non-finite values.")
                    continue

                with state_lock:
                    latest_positions[tag_id] = np.asarray(position, dtype=float)
                    pending_positions.append((tag_id, latest_positions[tag_id].copy()))

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
# TAG TRAJECTORIES
# ============================================================

tag_colors = itertools.cycle(matplotlib.rcParams["axes.prop_cycle"].by_key()["color"])
tag_trajectories = {}
tag_lines = {}
tag_points = {}
if ANCHORS:
    axis.legend()


# ============================================================
# MATPLOTLIB UPDATE FUNCTION
# ============================================================

def update_plot(frame):
    """Read the latest UDP position and update the plot in the WebAgg thread."""

    with state_lock:
        positions = {
            tag_id: position.copy()
            for tag_id, position in latest_positions.items()
        }
        new_positions = [
            (tag_id, position.copy())
            for tag_id, position in pending_positions
        ]
        pending_positions.clear()

    for tag_id, position in new_positions:
        if tag_id not in tag_trajectories:
            color = next(tag_colors)
            tag_trajectories[tag_id] = []
            if SHOW_3D:
                tag_lines[tag_id], = axis.plot(
                    [], [], [], color=color, linewidth=1.5, label="_nolegend_"
                )
                tag_points[tag_id], = axis.plot(
                    [], [], [], "o", color=color, markersize=6,
                    label=f"Tag {tag_id}",
                )
            else:
                tag_lines[tag_id], = axis.plot(
                    [], [], color=color, linewidth=1.5, label="_nolegend_"
                )
                tag_points[tag_id], = axis.plot(
                    [], [], "o", color=color, markersize=6,
                    label=f"Tag {tag_id}",
                )
            axis.legend()

        tag_trajectories[tag_id].append(position)

    for tag_id, trajectory in tag_trajectories.items():
        trajectory_array = np.asarray(trajectory)
        if SHOW_3D:
            tag_lines[tag_id].set_data_3d(
                trajectory_array[:, 0],
                trajectory_array[:, 1],
                trajectory_array[:, 2],
            )
        else:
            tag_lines[tag_id].set_data(
                trajectory_array[:, 0],
                trajectory_array[:, 1],
            )

    for tag_id, position in positions.items():
        if SHOW_3D:
            tag_points[tag_id].set_data_3d(
                [position[0]],
                [position[1]],
                [position[2]],
            )
        else:
            tag_points[tag_id].set_data([position[0]], [position[1]])

    if new_positions and not SHOW_3D:
        tag_id, position = new_positions[-1]
        axis.set_title(
            f"Dynamic Tag Position (Tag {tag_id}, Z={position[2]:.2f} cm)"
        )

    if SHOW_3D:
        all_trajectory_points = [
            np.asarray(trajectory)
            for trajectory in tag_trajectories.values()
        ]
        if all_trajectory_points:
            all_points = np.concatenate(all_trajectory_points)
            axis.auto_scale_xyz(all_points[:, 0], all_points[:, 1], all_points[:, 2])
    else:
        if new_positions:
            axis.relim()
            axis.autoscale_view()

    return tuple(tag_lines.values()) + tuple(tag_points.values())


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
print(f" UDP position input: {UDP_HOST}:{UDP_PORT} (<ifff: int32 ID, 3 float32 coordinates)")
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
