"""CAN message codec for the 5EAT TCU (8AF0237300), derived from the firmware
catalog (CAN_MAP_RAW.md / CAN_CATALOG.md).

Two halves:
  RX_MESSAGES  - frames the SIMULATOR sends TO the TCU (the whole car bus). The
                 TCU runs a per-message timeout supervisor over 10 IDs; if any
                 goes silent ~500 ms it forces failsafe. So ALL of these must be
                 broadcast continuously, which is the whole reason a real sim
                 (not an engine-only injector) is required.
  decode_tx    - frames the TCU broadcasts (0x420/421/422); we decode current
                 gear, lockup, DTCs, ATF temp to close the loop and show status.

All multi-byte signals are little-endian on the wire (LSB at lower byte index).
Signals marked "scale uncertain" in the catalog use the documented formula and
are calibrated on-bench.
"""
from __future__ import annotations
from typing import Callable, Dict, Tuple
from .vehicle import SimState

# 0x512 vehicle speed / 0x513 wheel speed use (raw<<n)/0x11C7 -> km/h
SPEED_DIV = 0x11C7


def _u16le(v: int) -> Tuple[int, int]:
    v &= 0xFFFF
    return v & 0xFF, (v >> 8) & 0xFF


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------- encoders: SimState -> 8 data bytes ----------

def enc_410(s: SimState) -> bytes:
    """ECM engine status + RPM. B5-6 LE = rpm x1. B7 bit0x20 = manual mode."""
    rpm = int(_clamp(round(s.engine_rpm), 0, 0xFFFF))
    lo, hi = _u16le(rpm)
    b7 = 0x20 if s.selector == "M" else 0x00
    return bytes([0x00, 0x00, 0x00, 0x00, 0x00, lo, hi, b7])


def enc_411(s: SimState) -> bytes:
    """ECM flags + engine-load index (B3, default 64). Load tracks throttle."""
    load = int(_clamp(round(48 + s.throttle * 180), 0, 255))
    return bytes([0x00, 0x00, 0x00, load, 0x00, 0x00, 0x00, 0x00])


def enc_412(s: SimState) -> bytes:
    """ECM accelerator pedal (B0, raw/255*100%) + 2x LE16 throttle/torque."""
    pedal = int(_clamp(round(s.throttle * 255), 0, 255))
    thr = int(_clamp(round(4000 + s.throttle * 4000), 0, 0xFFFF))  # default 4000
    tq = thr
    t_lo, t_hi = _u16le(thr)
    q_lo, q_hi = _u16le(tq)
    return bytes([pedal, t_lo, t_hi, q_lo, q_hi, 0x40, 0x00, 0x00])


def enc_511(s: SimState) -> bytes:
    """VDC yaw/steering (signed LE16). Neutral at rest / straight line."""
    return bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


def enc_512(s: SimState) -> bytes:
    """VDC/ABS status + vehicle speed. B1 gates 0x511(0x20) & 0x513(0x40) RX -
    both must be set or the TCU ignores those frames and times them out.
    B2-3 LE = speed: km/h = (raw<<16)/0x11C7  ->  raw = km/h*0x11C7/65536.
    B4 bit7 = brake."""
    raw = int(_clamp(round(s.speed_kmh * SPEED_DIV / 65536.0), 0, 0xFFFF))
    lo, hi = _u16le(raw)
    b1 = 0x60  # enable 0x511 + 0x513 processing
    b4 = 0x80 if s.brake > 0.05 else 0x00
    return bytes([0x00, b1, lo, hi, b4, 0x00, 0x00, 0x00])


def enc_513(s: SimState) -> bytes:
    """Four wheel speeds, each km/h = (raw<<8)/0x11C7 -> raw = km/h*0x11C7/256."""
    raw = int(_clamp(round(s.speed_kmh * SPEED_DIV / 256.0), 0, 0xFFFF))
    lo, hi = _u16le(raw)
    return bytes([lo, hi, lo, hi, lo, hi, lo, hi])


def enc_514(s: SimState) -> bytes:
    """Brake / cruise / body. B0 bit1(0x02) = brake."""
    b0 = 0x02 if s.brake > 0.05 else 0x00
    return bytes([b0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


def enc_515(s: SimState) -> bytes:
    """Drive-mode select. B7 = raw&7 (default 5)."""
    return bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, s.drive_mode & 0x07])


def enc_520(s: SimState) -> bytes:
    """Body / gateway flags. B0 bit0 = coast flag."""
    return bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


def enc_600(s: SimState) -> bytes:
    """Body / HVAC. B3 = body range (default 0x28). B7 = ambient temp, valid
    window 0x84 <= x < 0xFF (0xFF = invalid)."""
    return bytes([0x00, 0x00, 0x00, 0x28, 0x00, 0x00, 0x00, 0x90])


# id -> (rate_hz, encoder). Engine fast for smooth rpm; rest well under the
# ~500 ms timeout. All 10 are the TCU's monitored set.
RX_MESSAGES: Dict[int, Tuple[float, Callable[[SimState], bytes]]] = {
    0x410: (100.0, enc_410),
    0x411: (100.0, enc_411),
    0x412: (100.0, enc_412),
    0x511: (50.0, enc_511),
    0x512: (50.0, enc_512),
    0x513: (50.0, enc_513),
    0x514: (50.0, enc_514),
    0x515: (25.0, enc_515),
    0x520: (25.0, enc_520),
    0x600: (25.0, enc_600),
}


# ---------- decoders: TCU broadcast -> update SimState ----------

def _gear_from_nibble(n: int) -> int:
    """0x420 B1 hi nibble: 0x1-0x5 = 1st-5th, 0x7 = R, 0x8 = P/N."""
    if 1 <= n <= 5:
        return n
    if n == 7:
        return -1  # R
    return 0       # P/N


def decode_tx(can_id: int, data: bytes, s: SimState) -> bool:
    """Fold a TCU broadcast into SimState. Returns True if it was one of ours."""
    if len(data) < 8:
        return False
    if can_id == 0x420:
        b1 = data[1]
        s.tcu_current_gear = _gear_from_nibble((b1 >> 4) & 0x0F)
        s.tcu_target_gear = _gear_from_nibble(b1 & 0x0F)
        s.tcu_lockup = bool(data[2] & 0x80)
        s.tcu_output_shaft = data[4]
        s.can_link_up = True
        return True
    if can_id == 0x421:
        return True
    if can_id == 0x422:
        s.tcu_selector_code = data[2]
        code = data[3] | (data[4] << 8)
        pcode = code & 0x3FFF
        slot = code >> 14
        if pcode != 0x3FFF:
            tag = "P%04X(slot%d)" % (pcode, slot)
            if tag not in s.tcu_dtcs:
                s.tcu_dtcs.append(tag)
        s.atf_temp1 = float(max(0, data[5] - 15))   # 0x422 B5 = ATF temp 1
        s.atf_temp2 = float(max(0, data[6] - 15))   # 0x422 B6 = ATF temp 2
        s.tcu_atf_temp_c = s.atf_temp1
        s.can_link_up = True
        return True
    return False


TX_IDS = (0x420, 0x421, 0x422)


# ---------- full-CAN capture for logging ----------

_GEAR_NIB = {1: 0x10, 2: 0x20, 3: 0x30, 4: 0x40, 5: 0x50, -1: 0x70, 0: 0x80}


def encode_all_rx(s: SimState) -> dict:
    """The frames the simulated car puts on the bus (all 10 monitored IDs)."""
    return {"%03X" % cid: enc(s).hex().upper() for cid, (rate, enc) in RX_MESSAGES.items()}


def encode_tx_demo(s: SimState) -> dict:
    """Synthesize the TCU's broadcast (0x420/421/422) from demo state, so the log
    is a full bidirectional CAN capture even without hardware. On real hardware
    these come straight off the bus instead."""
    hi = _GEAR_NIB.get(s.tcu_current_gear, 0x80)
    lo = _GEAR_NIB.get(s.tcu_target_gear, 0x80) >> 4
    out = (int(s.output_rpm) >> 3) & 0xFF
    b420 = bytes([0x00, hi | (lo & 0x0F), 0x80 if s.tcu_lockup else 0x00, 0x00, out, 0x00, 0x00, 0x80])
    b421 = bytes([0x00, 0x00, 0x00, int(s.tcu_output_shaft) & 0xFF, 0x00, 0x00, 0x00, 0x00])
    atf1 = int(max(0, min(255, s.atf_temp1 + 15)))
    atf2 = int(max(0, min(255, s.atf_temp2 + 15)))
    sel = int(s.tcu_selector_code or 0) & 0xFF
    b422 = bytes([0x41, 0x00, sel, 0xFF, 0x3F, atf1, atf2, 0x00])   # DTC 0x3FFF = none
    return {"420": b420.hex().upper(), "421": b421.hex().upper(), "422": b422.hex().upper()}


# id -> (name, source module) for the live CAN monitor
FRAME_INFO = {
    "410": ("Engine status + RPM", "ECM"),
    "411": ("Engine flags + load", "ECM"),
    "412": ("Pedal + throttle/torque", "ECM"),
    "511": ("Yaw / steering", "VDC"),
    "512": ("VDC status + veh speed", "VDC/ABS"),
    "513": ("Four wheel speeds", "VDC/ABS"),
    "514": ("Brake / cruise / body", "Body"),
    "515": ("Drive-mode select", "Body"),
    "520": ("Body / gateway flags", "Body"),
    "600": ("HVAC ambient + flags", "Body/HVAC"),
    "420": ("Gear display + status", "TCU"),
    "421": ("Shift pressure + alive", "TCU"),
    "422": ("Lockup/DTC/ATF", "TCU"),
}

_GEAR_DISP = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 7: "R", 8: "P/N"}


def decode_frame_display(cid, data) -> str:
    """Short human decode of a frame for the live CAN monitor."""
    b = bytes.fromhex(data) if isinstance(data, str) else bytes(data)
    if len(b) < 8:
        return ""
    c = int(cid, 16) if isinstance(cid, str) else cid
    if c == 0x410:
        return "%d rpm%s" % (b[5] | (b[6] << 8), "  manual" if b[7] & 0x20 else "")
    if c == 0x411:
        return "load %d" % b[3]
    if c == 0x412:
        return "pedal %d%%  throttle %d" % (round(b[0] / 255 * 100), b[1] | (b[2] << 8))
    if c == 0x512:
        raw = b[2] | (b[3] << 8)
        return "veh speed %.0f km/h%s" % ((raw << 16) / 0x11C7 / 1000.0, "  brake" if b[4] & 0x80 else "")
    if c == 0x513:
        return "wheels %.0f km/h" % (((b[0] | (b[1] << 8)) << 8) / 0x11C7 / 1000.0)
    if c == 0x514:
        return "brake" if b[0] & 0x02 else "-"
    if c == 0x515:
        return "mode %d" % (b[7] & 7)
    if c == 0x600:
        return "ambient %d  range %d" % (b[7], b[3])
    if c == 0x420:
        return "gear %s -> %s%s" % (_GEAR_DISP.get((b[1] >> 4) & 0xF, "?"),
                                    _GEAR_DISP.get(b[1] & 0xF, "?"),
                                    "  TCC-lock" if b[2] & 0x80 else "")
    if c == 0x421:
        return "adaptive / alive"
    if c == 0x422:
        code = b[3] | (b[4] << 8)
        dtc = "none" if (code & 0x3FFF) == 0x3FFF else "P%04X" % (code & 0x3FFF)
        return "ATF %d/%d C  DTC %s" % (max(0, b[5] - 15), max(0, b[6] - 15), dtc)
    return ""
