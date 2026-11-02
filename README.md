# UWB-utils
This repository contains useful files for working with DW1000/Bitcraze-based UWB localization systems. 
When interacting with hardware, it is expected:
- UWB tags are DW1000 modules accessible through a SPI connection, such as the [Bitcraze Loco Positioning Deck](https://www.bitcraze.io/products/loco-positioning-deck/)
- UWB anchors are [Bitcraze Loco Positioning Nodes](https://www.bitcraze.io/products/loco-positioning-node/), running the 2022.09 [lps-node-firmware](https://github.com/bitcraze/lps-node-firmware/releases)

### anchor_circle_plot.py 
Helps visualize geometric conditions for a TWR anchor setup. 

Requires anchor IDs and positions and either range measurements to active anchors OR a single position. The script will display (and/or save) a figure 
with 3 subplots showing the XY, XZ and YZ planes. On each plane, anchor positions are shown with a circle of radii corresponding to either 
the defined range measurement or the associated range to the fixed position. The area of the lowest LOW_RESIDUAL_PERCENTILE % TWR residuals will be highlighted in yellow. 
### config_loco_node.py
Configures anchors (Loco Positioning Nodes) without needing a Crazyflie or Micro-USB connection. 

Set the ID of the anchors to target and the desired configuration and the script will send UWB commands to modify the settings and confirm the changes. 
Requires a SPI connection with a DW1000 module / a Loco Positioning Deck. 

**NOTE:** As of 2026-10-13, I haven't added the functionality to verify that changes to the TDOA2 mode took place. Run the code multiple times if you want to be sure. 
### dynamic_MIST.py 
Dynamic visualizer of position updates at the MIST Lab on headless devices.

Run the code on a device where you have SSH access and then connect to the 8988 port on your main machine. A webserver will show the current 
position and dynamically update its trajectory. The script no longer performs UWB ranging or positioning; another program on the same device
must send a UDP datagram to `127.0.0.1:5005` for each update. Each datagram must contain exactly three little-endian float32 values in
`(x, y, z)` order (12 bytes), for example `struct.pack("<fff", x, y, z)` in Python.

Set `SHOW_3D` near the top of `dynamic_MIST.py` to `True` for a 3D plot. In its default `False` mode, it displays the XY trajectory and
includes the current Z coordinate in the title. Configure anchor positions in the `ANCHORS` dict in `dynamic_MIST.py` using
`{anchor_id: (x, y, z)}`; it is empty by default. Anchors are shown as blue stars (at their X/Y coordinates in 2D mode).

---
### Future updates 
Currently don't have time, but in the future, could: 
~~1. Shift `DW1000` into a package~~
~~2. Formalize a `requirements.txt`~~
2.5. Move BitcrazeTag from clamour to here 
3. Add verification of changes to TDOA2 in `config_loco_node.py`
