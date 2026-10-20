from typing import Literal
"""
This script exploits the function lppHandleShortPacket() in lpp.c from the Loco Positioning nodes firmware
to change anchor settings without needing a crazyflie or a direct micro-USB connection.

The target anchor should be in TWR, TDOA2 or TDOA3 mode, as these are the ones that use lppHandleShortPacket().

The message format for a short LPP packet is:
[Frame Control (2 bytes), SEQ (1 byte), PAN ID (2 bytes), Destination Addr (8 bytes), Source Addr (8 bytes), LPP_SHORT_TAG (1 byte)]
followed by:
[LPP_SHORT_TYPE (1 byte), payload...]

The different short-packet types supported by the firmware are:
LPP_SHORT_ANCHOR_POSITION 0x01 -> 3 x float32 values (x, y, z)
LPP_SHORT_REBOOT          0x02 -> 0x00 reboots to bootloader, 0x01 reboots to firmware
LPP_SHORT_MODE            0x03 -> 0x01 TWR, 0x02 TDOA2, 0x03 TDOA3
LPP_SHORT_UWB             0x04 -> [flags, tx_power[4 bytes]]
LPP_SHORT_UWB_MODE        0x05 -> [flags]

Flags are documented in the firmware as:
- UWB:      000000__FORCE_TX_POWER_BIT__SMART_TX_POWER_BIT
- UWB_MODE: 000000__LONG_PREAMBLE_BIT__LOW_BITRATE_BIT
"""
########################################## CONFIGURATION AREA - CHANGE THESE PARAMS ##########################################
# Target anchor - unfortunately can't change ID remotely
ANCHOR_IDS:list|int = [1,2,3,4,5,6,7,8] 

# Configuration parameters; set None to not change
ANCHOR_POS:None|tuple[int,int,int]                    = (1,1,1)  # (x, y, z) 
REBOOT:    None|Literal[1,2]                          = None     # 1 = reboot to firmware, 2 = reboot to bootloader
MODE:      None|Literal[1,2,3]                        = 1        # 1 = TWR, 2 = TDOA2, 3 = TDOA3
UWB_POWER:None|tuple[Literal[0,1], Literal[0,1], int] = None     # (smart_tx_enabled, force_tx_enabled, 32bit_tx_power_value). Example: Force max power: (0, 1, 0xFFFFFFFF)
# NOTE: Careful with UWB settings - if you want to change them back, you will have to change the DW1000 settings below 
# the DW1000 is config'ed by default to match normal operation (0,0). 
UWB_RADIO:None|tuple[Literal[0,1], Literal[0,1]]      = None       # (low_bitrate_enabled, long_preamble_enabled)

########################################## CODE - LOGIC BASED ON LOCO POSITIONING NODE FIRMWARE ##########################################
import struct
from pathlib import Path
import sys
import time

# The anchor firmware rejects configuration updates in TWR mode unless the source address is 0.
# Keeping this explicit so it is obvious that the config packets intentionally use the global zero address.
SOURCE_ADDR = 0 

LPP_SHORT_TAG = 0xF0
LPP_SHORT_ANCHOR_POSITION = 0x01
LPP_SHORT_REBOOT = 0x02
LPP_SHORT_MODE = 0x03
LPP_SHORT_UWB = 0x04
LPP_SHORT_UWB_MODE = 0x05

gen_cfg_msg_header = lambda target_id: [0x41, 0xDC, 0x00, 0xCF, 0xBC] + list(target_id.to_bytes(6, 'little') + b'\xcf\xbc') + list(SOURCE_ADDR.to_bytes(6, 'little') + b'\xcf\xbc') + [LPP_SHORT_TAG]

# Add parent directory to sys.path
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from dw_1000 import DW1000

def build_uwb_power_payload(smart_tx_power: int, force_tx_power: int, tx_power: int) -> list[int]:
    smart_tx_power = int(bool(smart_tx_power)) & 0x01
    force_tx_power = int(bool(force_tx_power)) & 0x01
    flags = (force_tx_power << 1) | smart_tx_power
    tx_power = int(tx_power) & 0xFFFFFFFF
    return [flags] + list(tx_power.to_bytes(4, 'little'))

def build_uwb_radio_payload(low_bitrate: int, long_preamble: int) -> list[int]:
    low_bitrate = int(bool(low_bitrate)) & 0x01
    long_preamble = int(bool(long_preamble)) & 0x01
    flags = (long_preamble << 1) | low_bitrate
    return [flags]

def build_config_messages() -> list[list[int]]:
    to_send: list[list[int]] = []

    if ANCHOR_POS is not None:
        to_send.append([LPP_SHORT_ANCHOR_POSITION] + list(struct.pack('<fff', *ANCHOR_POS)))

    if REBOOT is not None:
        if REBOOT == 1:
            to_send.append([LPP_SHORT_REBOOT, 0x01])
        elif REBOOT == 2:
            to_send.append([LPP_SHORT_REBOOT, 0x00])
        else:
            raise ValueError(f"REBOOT must be None, 1, or 2; got {REBOOT!r}")

    if MODE is not None:
        if MODE not in (1, 2, 3):
            raise ValueError(f"MODE must be None, 1, 2, or 3; got {MODE!r}")
        to_send.append([LPP_SHORT_MODE, MODE])

    if UWB_POWER is not None:
        smart_tx_power, force_tx_power, tx_power = UWB_POWER
        to_send.append([LPP_SHORT_UWB] + build_uwb_power_payload(smart_tx_power, force_tx_power, tx_power))

    if UWB_RADIO is not None:
        low_bitrate, long_preamble = UWB_RADIO
        to_send.append([LPP_SHORT_UWB_MODE] + build_uwb_radio_payload(low_bitrate, long_preamble))

    return to_send

def confirm_mode_changed(id, mode:Literal[1,2,3])->bool: 
    """
    Confirms if an anchor's mode was indeed changed as expected. 
    NOTE TODO: Currently only supporting TWR and TDOA3 - look in firmware to implement TDOA2 if needed. 
    """
    def validate_heard_msg(exp_src, exp_dest, exp_type): 
        ## Listens for 100ms to see if we receive a specific message
        exp_src_addr = list(exp_src.to_bytes(6, 'little') + b'\xcf\xbc')
        exp_dest_addr = list(exp_dest.to_bytes(6, 'little') + b'\xcf\xbc')
        tstart = time.perf_counter() 
        while (time.perf_counter()-tstart)<0.3: 
            msg = dw.listen()
            if not msg: 
                continue 
            try:
                dest_addr = msg[5:13]
                source_addr = msg[13:21]
                trans_type = msg[21]
            except IndexError:
                continue    
            if dest_addr==exp_dest_addr and source_addr==exp_src_addr and exp_type==trans_type:
                return True 
        return False 

    if mode==1: 
        # If we want to confirm anchor is in TWR we simply send it a direct POLL and check if it responds 
        twr_msg = gen_cfg_msg_header(id)[:-1] + [0x01] + [0x01] 
        dw.transmit(twr_msg, False) 
        return validate_heard_msg(exp_src=id, exp_dest=0, exp_type=0x02) 
    elif mode==2: 
        print("[INFO] Currently not supporting mode validation for TDOA2. Cannot confirm mode was properly changed!")
    elif mode==3: 
        # TDOA3 anchor are periodically broadcasting to 0xFF
        return validate_heard_msg(exp_src=id, exp_dest=0xFF, exp_type=0x30)
        
        
if __name__ == "__main__":
    CFG_TIMEOUT = 1 # seconds to try to confirm settings changed 

    try:
        config_messages = build_config_messages()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    with DW1000(0, 0, 2, 64, 6, 128, 9, True, None) as dw:

        if isinstance(ANCHOR_IDS, int): 
            ANCHOR_IDS = [ANCHOR_IDS]

        for ANCHOR_ID in ANCHOR_IDS: 
            header = gen_cfg_msg_header(ANCHOR_ID)
            # If the tag is CURRENTLY in TWR mode, an internal check is performed to ensure the ID of the sender matches the latest ID the tag communicated with
            # Sending a POLL request resets this variable (curr_tag in the firmware), which allows us to set the source address to 0 and have the anchor accept the modifs
            if MODE!=1: 
                # This function will send a POLL which will accomplish the curr_tag reset 
                confirm_mode_changed(ANCHOR_ID, mode=1) 

            for cfg in config_messages:
                msg = header + cfg
                tstart = time.perf_counter() 
                while (time.perf_counter()-tstart)<CFG_TIMEOUT: 
                    dw.transmit(data=msg, ranging=False)
                    if confirm_mode_changed(ANCHOR_ID, mode=MODE):
                        break 
                else: 
                    print(f"[WARN] Anchor {ANCHOR_ID}: config for mode {MODE} not confirmed after {CFG_TIMEOUT}s. Try again?")
                time.sleep(0.1) 

        print(f"ATTEMPTED CONFIGURATION FOR ANCHORS {ANCHOR_IDS}:")
        print(f"  anchor_pos      = {ANCHOR_POS}")
        print(f"  reboot          = {REBOOT}")
        print(f"  mode            = {MODE}")
        print(f"  uwb_power       = {UWB_POWER}")
        print(f"  uwb_radio       = {UWB_RADIO}")
        print(f"ANCHORS WITH WARNINGS COULD NOT BE CONFIRMED.")