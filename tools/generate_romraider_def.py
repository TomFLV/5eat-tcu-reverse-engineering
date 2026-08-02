"""
Generates definitions/5eat_tcu_romraider_defs.xml -- a single RomRaider
definition covering every firmware in rom/.

Each firmware is emitted as its own STANDALONE <rom> block keyed on the
calibration ID at 0x8008, so RomRaider selects the right one automatically when
a ROM is opened.

Inheritance via <rom base="..."> is deliberately NOT used. It silently pulled the
base firmware's scalars and DTC switches into every derived block at base-ROM
addresses -- one firmware was building 24 DTC tables when it has 11. Standalone
blocks cost repetition in the output and remove a whole class of silent error.

Regenerate from here rather than hand-editing the XML. Every derived address is
re-checked against the target ROM's own embedded count field before being
written, and generation aborts if any disagree -- the offsets between firmwares
are not uniform and cannot be extrapolated.
"""
import struct
import os
import json
from xml.sax.saxutils import escape

ROM_ID = "91D1206000"

here = os.path.dirname(os.path.abspath(__file__))
rom_path = os.path.join(here, "..", "rom", f"{ROM_ID}_5EAT.bin")
out_path = os.path.join(here, "..", "definitions", "5eat_tcu_romraider_defs.xml")

data = open(rom_path, "rb").read()


def u16(off):
    return struct.unpack(">H", data[off:off + 2])[0]


def table_addrs(header_addr):
    """Given a table's header (count) address, return (n, axis_addr, data_addr)."""
    n = u16(header_addr)
    axis_addr = header_addr + 2
    data_addr = axis_addr + n * 2
    return n, axis_addr, data_addr


# ---------------------------------------------------------------------------
# Family definitions. Each family is a set of gear-indexed (or otherwise
# indexed) 2D tables sharing a naming scheme, category, axis label, and
# description template. "headers" is the list of ROM header addresses, one
# per gear/index in order.
#
# PER-FIRMWARE families: these are only emitted for a firmware that declares an
# explicit offset. Defaulting them to the base address would write addresses that
# are simply wrong for the other firmwares -- generation aborts if that happens,
# but omitting is the correct behaviour.
# ---------------------------------------------------------------------------
OPTIONAL_FAMILIES = {"ShiftCorrection"}

FAMILIES = [
    {
        "id": "SpeedTrimA",
        "category": "Transmission - Speed Trim A",
        "name_template": "Gear {i} Speed Trim A",
        "headers": [0x01040A, 0x01043C, 0x01046E, 0x0104A0, 0x0104D2],
        "axis_label": "Engine speed",
        "value_label": "raw",
        "axis_units": "RPM",
        "axis_expr": "x/8",
        "axis_to_byte": "x*8",
        "axis_format": "0",
        "description": (
            "Gear {i} of 5. Speed-based trim value, indexed by engine speed. The RPM "
            "axis scale is code-derived (raw/8), not a guess — see the Info entry."
        ),
    },
    {
        "id": "SlipThreshold",
        "value_expr": "x/256",
        "value_to_byte": "x*256",
        "value_format": "0.00",
        "category": "Transmission - Slip Detection",
        "name_template": "Gear {i} Slip Detection Threshold",
        "headers": [0x0114A8, 0x0114D2, 0x0114FC, 0x011526, 0x011550],
        "axis_label": "Engine speed",
        "value_label": "units of 1/256 (quantity not established)",
        "axis_units": "RPM",
        "axis_expr": "x/8",
        "axis_to_byte": "x*8",
        "axis_format": "0",
        "description": (
            "Gear {i} of 5. Threshold curve used to detect clutch/converter slip, "
            "indexed by engine speed. Data values are a speed in the same internal "
            "units the TCU compares against (engine speed x gear ratio)."
        ),
    },
    {
        "id": "RefSpeedBaseline",
        "value_expr": "x/256",
        "value_to_byte": "x*256",
        "value_format": "0.00",
        "category": "Transmission - Reference Speed",
        "name_template": "Gear {i} Reference Speed Baseline",
        "headers": [0x0115D0, 0x0115FA, 0x011624, 0x01164E, 0x011678],
        "axis_label": "Engine speed",
        "value_label": "units of 1/256 (quantity not established)",
        "axis_units": "RPM",
        "axis_expr": "x/8",
        "axis_to_byte": "x*8",
        "axis_format": "0",
        "description": (
            "Gear {i} of 5. Expected/baseline speed curve — the actual speed signal "
            "is compared against this to detect slip. Feeds the X-axis of the "
            "Pressure Control B/C and Shift Solenoid Control tables."
        ),
    },
    {
        "id": "PressureB",
        "category": "Transmission - Pressure Control B",
        "name_template": "Gear {i} Slip Comp Pressure B",
        "headers": [0x010D1A, 0x010D30, 0x010D46, 0x010D5C, 0x010D72],
        "axis_label": "Accelerator pedal angle x256 minus reference speed (raw)",
        "value_label": "raw",
        "description": (
            "Gear {i} of 5. Pressure/duty correction curve. The X-input is "
            "(accelerator pedal angle x 256) minus the Reference Speed Baseline "
            "lookup — a difference, so the axis itself is raw even though both "
            "operands are now identified. Pedal angle arrives on CAN 0x412 byte 0 "
            "as raw 0-255 = 0-100%. Stock values are flat (20) in every gear."
        ),
    },
    {
        "id": "PressureC",
        "category": "Transmission - Pressure Control C",
        "name_template": "Gear {i} Slip Comp Pressure C",
        "headers": [0x010D9C, 0x010DB2, 0x010DC8, 0x010DDE, 0x010DF4],
        "axis_label": "Accelerator pedal angle x256 minus reference speed (raw)",
        "value_label": "raw",
        "description": (
            "Gear {i} of 5. Alternate-mode counterpart to Pressure Control B — same "
            "role, used under a different operating condition. Stock values are "
            "flat (20) in every gear."
        ),
    },
    {
        "id": "ShiftStageD",
        "category": "Transmission - Shift Solenoid Control",
        "name_template": "Gear {i} Shift Stage Value D",
        "headers": [0x0112D0, 0x0112E6, 0x0112FC, 0x011312, 0x011328],
        "axis_label": "Accelerator pedal angle x256 minus reference speed (raw)",
        "value_label": "raw",
        "description": (
            "Gear {i} of 5. Shift solenoid control curve, indexed by slip amount. "
            "Stock data steps up with gear (6, 6, 6, 10, 10)."
        ),
    },
    {
        "id": "PressureThresholdE",
        "category": "Transmission - Pressure Control E",
        "name_template": "Mode {i} Pressure Threshold E",
        "headers": [0x010844, 0x01086E],
        "axis_label": "Accelerator pedal angle x256 minus reference speed (raw)",
        "value_label": "raw",
        "description": (
            "Mode {i} of 2 (selected by an internal mode flag, not gear). Same "
            "slip-amount X-formula as Pressure Control B/C/D (confirmed via "
            "decompilation: X = smoothed reference * 256 - Reference Speed "
            "Baseline lookup). Stock data is flat (0) in both modes — a real, "
            "editable table even though it isn't currently varying."
        ),
    },
    {
        "id": "CAN511Threshold",
        "category": "Transmission - CAN Signal Thresholds",
        "name_template": "CAN 0x511 Byte 4 Threshold Curve",
        "headers": [0x011836],
        "axis_label": "CAN 0x511 byte 4 (from VDC/ABS), raw x1.301",
        "value_label": "raw",
        "description": (
            "X-input is CAN ID 0x511 payload byte 4, scaled by a fixed 333/256 "
            "(~x1.301) factor before this lookup. CAN 0x511 originates from the "
            "VDC/ABS module (bytes 0-1 are steering wheel angle, byte 6 vehicle "
            "G-force); byte 4 is not identified in the community CAN decoding. "
            "Stock data is flat (0) — real, editable, currently inert."
        ),
    },
    {
        "id": "ShiftCorrection",
        "category": "Transmission - Shift Correction",
        "name_template": "Gear {i} Shift Correction",
        "headers": [0x0116BA, 0x0116E8, 0x011716, 0x011744, 0x011772],
        "axis_label": "Engine speed",
        "value_label": "correction (raw, signed)",
        "value_storagetype": "int16",
        "axis_units": "RPM",
        "axis_expr": "x/8",
        "axis_to_byte": "x*8",
        "axis_format": "0",
        "description": (
            "Gear {i} of 5. Signed correction curve against engine speed, selected "
            "by a gear-indexed pointer array at 0x117A0. Gear 1 is all zeros (no "
            "correction), and the magnitude falls with each higher gear (about "
            "-1970 at the top of gear 2 down to -390 in gear 5) — the shape of a "
            "shift-shock or torque-phase correction.\n\n"
            "Values are genuinely NEGATIVE and stored as signed 16-bit. Real-world "
            "units are not confirmed.\n\n"
            "This family was only found after correcting the Ghidra M32R processor "
            "definition: the pointer array that selects it was unreadable before."
        ),
    },
    {
        "id": "SignalResponseCurves",
        "category": "Transmission - Signal Response Curves",
        "name_template": "{name}",
        "headers": [0x011898, 0x0118DA, 0x0117BE],
        "axis_label": "",
        "value_label": "raw",
        "per_table": {
            0x011898: {
                "name": "CAN 0x410 Chain Response Curve",
                "axis_label": "Reference signal breakpoint (raw, pre-scale CAN 0x410 chain value)",
                "description": (
                    "X-input confirmed via decompilation: the same ceiling-clamped CAN "
                    "ID 0x410-derived reference value already traced in docs/TECHNICAL-NOTES.md "
                    "(before its x256 scale-up), NOT gear-indexed — a single "
                    "standalone curve. Stock data is a genuine hump shape: rises from 61 "
                    "to a peak of 127 around the middle of the axis, then falls back to "
                    "0 at the high end — a real, currently-populated tunable curve."
                ),
            },
            0x0118DA: {
                "name": "Signal FE Response Curve",
                # Proven fixed point: every stored value in every firmware is a
                # multiple of 8 (tools/detect_fixed_point.py). Quantity unknown.
                "value_expr": "x/8",
                "value_to_byte": "x*8",
                "value_format": "0.0",
                "value_label": "units of 1/8 (quantity not established)",
                "axis_label": "Internal signal breakpoint (raw, source not fully traced)",
                "description": (
                    "X-input is an internal RAM value (traced back through several "
                    "conditional assignments in the decompiled code, but not yet to a "
                    "specific sensor or CAN ID — see docs/TECHNICAL-NOTES.md). Stock data is a real, "
                    "populated step curve (64 up to 256), not flat/placeholder."
                ),
            },
            0x0117BE: {
                "name": "Smoothed Signal Response Curve",
                "axis_label": "Internal signal breakpoint (raw, x256 of a 0-255 byte)",
                "description": (
                    "X-input is the same internal signal as the 'Signal FE Response "
                    "Curve' table, but smoothed through a calibratable first-order "
                    "filter before this lookup (confirmed via decompilation: the "
                    "filter target is that byte shifted left 8, i.e. x256). This is a "
                    "DIFFERENT signal chain from the engine-speed tables, so the RPM "
                    "scale used on those does NOT apply here — left raw deliberately. "
                    "Stock data is a real, populated rising curve (200 up to 1189)."
                ),
            },
        },
        "description": "",
    },
]

# ---------------------------------------------------------------------------
# Direct contiguous arrays (docs/TECHNICAL-NOTES.md) — plain gear-indexed arrays read
# with ordinary array access, NOT through a lookup/interpolation function. These
# are contiguous and fixed-stride, so unlike the hysteresis-record tables they
# map cleanly onto RomRaider's native storage with no stride problem.
#
# The gear ratio table is the FIRST table in this project with a CONFIRMED
# real-world scale factor: its raw values divided by 1024 match the factory
# service manual's published 5EAT gear ratios to within 0.0007, AND the
# decompiled code itself divides by 0x400 (=1024) when using them
# (full_decompile.c ~line 34051: speed * ratio / 0x400). Both an external
# authoritative reference and the code agree — this is proven, not estimated.
# ---------------------------------------------------------------------------
DIRECT_ARRAYS = [
    {
        "id": "GearRatios",
        "category": "Transmission - Gear Ratios",
        "name": "Gear Ratios (1st-5th)",
        "addr": 0x01234C,
        "size": 5,
        "storagetype": "uint16",
        "units": "ratio",
        "expression": "x/1024",
        "to_byte": "x*1024",
        "format": "0.000",
        "fineincrement": "0.001",
        "coarseincrement": "0.010",
        "description": (
            "The transmission's five forward gear ratios, indexed by current gear. "
            "Stock values match the Subaru factory service manual exactly: 3.540, "
            "2.264, 1.471, 1.000, 0.834. The scale factor (raw/1024) is CONFIRMED — "
            "the decompiled code divides these by 0x400 when computing expected "
            "speed, and the result matches the published ratios to within 0.0007. "
            "Used by the TCU to compute expected output speed per gear and to detect "
            "gear-ratio faults (DTC P0730). Changing these does NOT change the "
            "physical gearing — it changes what the TCU BELIEVES the gearing is, "
            "which affects ratio-based fault detection and speed calculations."
        ),
    },
]

# Five parallel 14-entry bitmask arrays, packed contiguously at 0x0087AA-0x0087EF,
# each indexed by the same shift-state variable and each feeding a different
# control output. Every value is a power of two (0/1/2/4/8/16/32/64/128) — these
# are bit patterns, not scalar quantities. See docs/TECHNICAL-NOTES.md.
_BITMASK_WARNING = (
    "EXPERT/DANGEROUS. These are BIT PATTERNS (every stock value is a power of "
    "two), not scalar quantities — editing them as ordinary numbers is very "
    "likely to produce an invalid pattern. On an automatic transmission an "
    "invalid clutch/solenoid pattern can command two elements at once, which "
    "can bind the driveline and cause real mechanical damage. The exact "
    "output each bit drives is NOT decoded — do not change these unless you "
    "have independently confirmed what each bit does on this exact firmware."
)

for _i, (_addr, _out) in enumerate([
    (0x0087AA, "0x00808885"), (0x0087B8, "0x00808883"), (0x0087C6, "0x00808861"),
    (0x0087D4, "0x00808863"), (0x0087E2, "0x0080886B"),
], start=1):
    DIRECT_ARRAYS.append({
        "id": f"StatePattern{_i}",
        "category": "Transmission - Shift State Patterns (Expert)",
        "name": f"Shift State Bit Pattern {_i} of 5",
        "addr": _addr,
        "size": 14,
        "storagetype": "uint8",
        "units": "bitmask",
        "expression": "x",
        "to_byte": "x",
        "format": "0",
        "fineincrement": "1",
        "coarseincrement": "1",
        "userlevel": "5",
        "description": (
            f"One of five parallel 14-entry bit-pattern arrays (packed contiguously "
            f"at 0x0087AA-0x0087EF), all indexed by the same internal shift-state "
            f"variable (0-13) and each driving a different control output (this one "
            f"feeds RAM {_out}). Confirmed via decompilation. " + _BITMASK_WARNING
        ),
    })


def build_direct_array_xml(arr):
    name = escape(arr["name"])
    category = escape(arr["category"])
    desc = escape(arr["description"])
    userlevel = arr.get("userlevel", "1")
    return f"""  <table type="1D" name="{name}" category="{category}" storageaddress="0x{arr['addr']:06X}" storagetype="{arr['storagetype']}" endian="big" sizex="{arr['size']}" userlevel="{userlevel}">
   <scaling units="{escape(arr['units'])}" expression="{escape(arr['expression'])}" to_byte="{escape(arr['to_byte'])}" format="{arr['format']}" fineincrement="{arr['fineincrement']}" coarseincrement="{arr['coarseincrement']}" />
   <description>{desc}</description>
  </table>"""


# ---------------------------------------------------------------------------
# Standalone scalar calibration constants (docs/TECHNICAL-NOTES.md) — single tunable
# values (not curves), each confirmed by decompilation to be read directly
# into a specific, meaningful role (a filter gain or a threshold compare),
# not just any monotonic byte run. Found by enumerating every direct call
# site of the confirmed smoothing-filter function (FUN_0005c8a0) and cross-
# referencing threshold constants already traced while following this session's
# new lookup tables back to their inputs.
# ---------------------------------------------------------------------------
# Temperature scalars. Encoding CONFIRMED (docs/TECHNICAL-NOTES.md): stored byte minus
# 40 = degrees C, the standard automotive -40..+215 unsigned encoding. Proven by
# both thermistor linearization tables mapping ADC 0..255 onto output 0..255
# (= -40..215 C), and validated against the factory service manual (constants at
# 71/75 C land inside the manual's stated 70-80 C normal operating range; 55 C
# matches the top of its 45-55 C test range). Displayed in Fahrenheit here.
_F_EXPR = "(x-40)*9/5+32"
_F_TOBYTE = "(x-32)*5/9+40"


def _temp_scalar(id_, name, addr, desc):
    return {
        "id": id_, "category": "Transmission - Temperature", "name": name,
        "addr": addr, "storagetype": "uint8", "units": "°F",
        "expression": _F_EXPR, "to_byte": _F_TOBYTE, "format": "0",
        "fineincrement": "1", "coarseincrement": "9", "description": desc,
    }


SCALARS = [
    _temp_scalar(
        "TempCold5thGearLockout", "Cold ATF 5th Gear Lockout Temperature", 0x01000A,
        "Below this ATF temperature the TCU swaps in a placeholder (disabled) shift "
        "schedule specifically when in 5th gear — i.e. it restricts 5th until the "
        "fluid warms up. Stock 15 °C / 59 °F. Confirmed via decompilation: the "
        "check is gated on current gear == 5th. Raising it keeps 5th locked out "
        "longer; lowering it releases 5th sooner on a cold transmission."
    ),
    _temp_scalar(
        "TempSensorFallback", "Assumed ATF Temperature (Sensor Fallback)", 0x011CF6,
        "The temperature the TCU substitutes when the measured ATF temperature is "
        "flagged unusable. Stock 95 °C / 203 °F — a deliberately warm assumption, "
        "so a failed sensor does not make the TCU behave as if the fluid were cold."
    ),
    _temp_scalar(
        "TempColdSwitchLow", "Cold Switchover Temperature (Lower)", 0x00806E,
        "Lower half of a two-point temperature switch with built-in hysteresis "
        "(pairs with 'Cold Switchover Temperature (Upper)'). Below this the TCU "
        "selects one calibration constant; at or above the upper point it selects "
        "another. Stock -10 °C / 14 °F."
    ),
    _temp_scalar(
        "TempColdSwitchHigh", "Cold Switchover Temperature (Upper)", 0x00806F,
        "Upper half of the cold switchover hysteresis pair. Stock -5 °C / 23 °F. "
        "Keep this above the lower point — inverting them would remove the "
        "hysteresis and can cause the selection to chatter."
    ),
    {
        "id": "SpeedSensor1PPR",
        "category": "Transmission - Speed Sensors",
        "name": "Speed Sensor 1 Pulses Per Revolution",
        "addr": 0x01C2C1,
        "storagetype": "uint8",
        "description": (
            "Pulses per revolution for speed sensor channel 1. CONFIRMED: the "
            "firmware computes RPM as 60,000,000 / (this value x measured pulse "
            "period) — the standard period-to-RPM formula (60 seconds x a 1 MHz "
            "timer). Stock value 16, i.e. a 16-tooth tone ring. Change this ONLY "
            "if the physical tone ring / sensor tooth count actually differs, "
            "otherwise every speed-derived calculation in the TCU will be wrong."
        ),
    },
    {
        "id": "SpeedSensor2PPR",
        "category": "Transmission - Speed Sensors",
        "name": "Speed Sensor 2 Pulses Per Revolution",
        "addr": 0x01C2C2,
        "storagetype": "uint8",
        "description": (
            "Pulses per revolution for speed sensor channel 2 — same confirmed "
            "60,000,000/(N x period) RPM formula as channel 1, on an independent "
            "input with its own tooth count. Stock value 22. Same warning: only "
            "change this if the physical tooth count genuinely differs."
        ),
    },
    {
        "id": "SpeedCeiling",
        "category": "Transmission - Speed Sensors",
        "name": "Speed Signal Ceiling (RPM)",
        "addr": 0x01C2A8,
        "storagetype": "uint16",
        "description": (
            "Upper clamp applied to both speed-sensor channels AND to the "
            "CAN-received engine speed signal — all three are limited to this "
            "value. Stock 10000 (RPM). This shared clamp is part of the evidence "
            "that all three signals carry the same unit; it also sets the ceiling "
            "the engine-speed table axes are derived against."
        ),
    },
    {
        "id": "FilterGainCAN410",
        "category": "Transmission - Calibration Constants",
        "name": "Signal Smoothing Filter Gain (CAN 0x410 Chain)",
        "addr": 0x01137C,
        "storagetype": "uint16",
        "description": (
            "Confirmed via decompilation: the calibratable gain argument to the "
            "first-order smoothing filter that produces the CAN ID 0x410-derived "
            "reference signal (docs/TECHNICAL-NOTES.md), stock value 128. Larger = "
            "faster response to changes in the incoming CAN signal, smaller = more "
            "smoothing/lag."
        ),
    },
    {
        "id": "FilterGainSignalFE",
        "category": "Transmission - Calibration Constants",
        "name": "Signal Smoothing Filter Gain (Signal FE Chain)",
        "addr": 0x01137E,
        "storagetype": "uint16",
        "description": (
            "Confirmed via decompilation: the calibratable gain argument to the "
            "smoothing filter that feeds the 'Smoothed Signal Response Curve' table "
            "(0x0117BE), stock value 128. Larger = faster response, smaller = more "
            "smoothing/lag."
        ),
    },
    {
        "id": "GearThresholdConst",
        "category": "Transmission - Calibration Constants",
        "name": "Gear Threshold Constant",
        "addr": 0x010840,
        "storagetype": "uint8",
        "description": (
            "Confirmed via decompilation: a single-byte constant (stock value 2) "
            "compared directly against the current gear (0x0080885A) and a second "
            "gear-like index (0x0080886E) in several places in the same function — "
            "reads like a 'this logic only applies above/below gear N' cutoff. "
            "Exact effect of changing it is NOT verified on real hardware."
        ),
    },
    {
        "id": "SignalThresholdConst",
        "category": "Transmission - Calibration Constants",
        "name": "Signal Threshold Constant",
        "addr": 0x010842,
        "storagetype": "uint8",
        "description": (
            "Confirmed via decompilation: a constant compared against a computed "
            "signal delta in the same fault-detection routine that reads the "
            "Pressure Threshold E tables. Storage width (byte vs. word) was inferred "
            "from the surrounding code pattern, not independently double-checked — "
            "verify before relying on the exact stored value."
        ),
    },
]


def build_scalar_xml(scalar):
    name = escape(scalar["name"])
    category = escape(scalar["category"])
    desc = escape(scalar["description"])
    storagetype = scalar["storagetype"]
    # Scalars default to raw; ones with a confirmed real-world conversion
    # (currently the temperature constants) override these keys.
    units = escape(scalar.get("units", "raw"))
    expression = escape(scalar.get("expression", "x"))
    to_byte = escape(scalar.get("to_byte", "x"))
    fmt = scalar.get("format", "0")
    fine = scalar.get("fineincrement", "1")
    coarse = scalar.get("coarseincrement", "16")
    return f"""  <table type="1D" name="{name}" category="{category}" storageaddress="0x{scalar['addr']:06X}" storagetype="{storagetype}" endian="big" sizex="1" userlevel="1">
   <scaling units="{units}" expression="{expression}" to_byte="{to_byte}" format="{fmt}" fineincrement="{fine}" coarseincrement="{coarse}" />
   <description>{desc}</description>
  </table>"""



# ---------------------------------------------------------------------------
# Shift schedule curves (docs/TECHNICAL-NOTES.md).
#
# Each curve is an array of 8-byte records, 4 x uint16:
#     [speed_i, pedal_lo, speed_i+1, pedal_hi]
# forming a polyline in (vehicle speed, accelerator angle) space. Speed is
# continuous between consecutive records; pedal may jump, which is how the
# vertical risers in the factory shift chart are encoded.
#
# Units are CONFIRMED against a factory shift chart ("5EAT Shifting, Base
# Case", accelerator opening angle vs vehicle speed): field A/C is vehicle
# speed in km/h with no scaling, field B/D is accelerator opening angle as
# raw 0-255 mapping to 0-100%. The 4-Up curve starting at (58 km/h, 16%)
# matches the chart's yellow trace point for point.
#
# The record block is CONTIGUOUS, so it maps onto a RomRaider 3D table with
# sizex=4 (the four fields) and sizey=n (the records) without needing any
# a stride attribute -- the record block is contiguous, so sizex=4 maps onto it
# directly. Columns 3-4 repeat the following row's columns 1-2; the editor must
# keep them consistent.
# ---------------------------------------------------------------------------
# Per-firmware shift curve addresses and row counts, derived by locating the
# gear x mode pointer array in each ROM's decompiler output (the index expression
# `gear * 2 + mode * 10` is a reliable fingerprint) and dereferencing it. The
# array relocates between firmwares -- 0x17714 on the base ROM, 0x180E8 on
# ACD1A06000 -- so it cannot be offset-derived.
#
# Row counts genuinely differ per firmware: that is the calibration.
SHIFT_CURVES_BY_ROM = json.load(open(os.path.join(here, "shift_curves.json")))

SHIFT_DESC = (
    "Shift point curve, mode 0 (the fully-populated operating mode). The curve is a "
    "polyline in vehicle-speed / accelerator-angle space: the TCU shifts when the "
    "operating point crosses this line.\n\n"
    "Units are confirmed against the factory shift chart ('5EAT Shifting, Base "
    "Case'): vehicle speed is km/h with no scaling, and accelerator opening angle "
    "is stored as 0-255 for 0-100%, shown here as a percentage. A pedal value of "
    "100% in the final row is a max clamp, not a real operating point.\n\n"
    "Lowering a curve makes that shift happen earlier (at lower speed for a given "
    "pedal); raising it delays the shift. Read this table together with its "
    "companion - vertex 3a of the km/h table and vertex 3a of the % pedal table "
    "are the two coordinates of the same point on the curve."
)



# Field labels for the 4 columns of a record. RomRaider's Table3D cannot load
# without X and Y axis children: Table3D.calcCellRanges() dereferences the axis
# DataCells, so an axis-less 3D table throws inside populateTable() and shows
# "There was an error loading table". Static axes solve it with literal labels
# and need no ROM storage.
def _static_axes(col_labels, rows, y_name="Segment"):
    nl = "\n"
    xs = nl.join(f"    <data>{escape(c)}</data>" for c in col_labels)
    ys = nl.join(f"    <data>{i + 1}</data>" for i in range(rows))
    return (f'   <table type="Static X Axis" name="Field" sizex="{len(col_labels)}">{nl}'
            f'{xs}{nl}   </table>{nl}'
            f'   <table type="Static Y Axis" name="{escape(y_name)}" sizey="{rows}">{nl}'
            f'{ys}{nl}   </table>')


# ---------------------------------------------------------------------------
# Record arrays, split by physical quantity.
#
# An 8-byte record is 4 x uint16: [f0, f1, f2, f3]. f0 and f2 are the segment's
# start and end BREAKPOINT; f1 and f3 are the corresponding VALUES. Those are
# two different physical quantities, in different units.
#
# The first version of this generator emitted one 4-column table per record
# array. That was a mistake for two reasons:
#
#   * RomRaider scales a table as a whole, so a grid holding both km/h and a
#     0-255 pedal angle cannot carry a unit at all. Every cell had to be shown
#     as a raw integer, which is exactly the thing a tuner cannot read.
#   * Four long column headers do not fit the fixed 42px cell width, so they
#     were clipped to "Spee...", "Pedal..." and were unreadable anyway.
#
# skipCells fixes it. Table3D.populateTable advances the read offset by
# 1 + skipCells after the last cell of each row, so with sizex=1 EVERY cell is
# the last in its row and the stride applies to all of them. skipCells=1 walks
# every second uint16 - which is precisely one quantity's start and end values,
# in order, with nothing skipped and nothing invented. Each resulting table
# holds one quantity, so it can carry a real unit.
#
# Verified by rendering: the pedal table reads 0.0, 0.0, 18.8, 25.1, 25.1, 37.6
# ... against raw records [0,0,12,0], [12,48,17,64], [17,64,22,96] - i.e.
# 48/255 = 18.8%, 64/255 = 25.1%. See tools/romraider-cli/RenderTable.java.
# ---------------------------------------------------------------------------

# Confirmed unit conversions. Only these five are code- or chart-derived; see
# docs/TECHNICAL-NOTES.md. Anything else stays raw rather than being guessed.
Q_SPEED = {"label": "km/h", "units": "km/h",
           "expression": "x", "to_byte": "x",
           "format": "0", "fine": "1", "coarse": "5"}
Q_PEDAL = {"label": "% pedal", "units": "% pedal",
           "expression": "x/255*100", "to_byte": "x*255/100",
           "format": "0.0", "fine": "0.4", "coarse": "3.9"}
# Engine speed is stored as uint16 with a /8 scaling, so 65535 raw is the
# ceiling: 8191 RPM. That is a limit of the stored format, not of the editor,
# and it cannot be raised by rescaling without misstating what the TCU reads.
# There is real headroom for a built engine - the stock calibration already
# parks a breakpoint at 8160 RPM (65280 raw) in the slip-threshold axis of
# 91D1206000, which is deliberately just under the ceiling - but 10000 RPM is
# not representable in these tables at all.
RPM_CEILING = 8191
RPM_CEILING_NOTE = (
    f"\n\nRPM RANGE: engine speed is a uint16 scaled by 1/8, so the highest value "
    f"these tables can hold is {RPM_CEILING} RPM. The stock calibration already "
    f"uses breakpoints as high as 8160 RPM elsewhere, so there is room to raise "
    f"shift and slip breakpoints for a built engine - but a target above "
    f"{RPM_CEILING} RPM cannot be represented here, and entering one will clip."
)

Q_RPM = {"label": "RPM", "units": "RPM",
         "expression": "x/8", "to_byte": "x*8",
         "format": "0", "fine": "10", "coarse": "100",
         "note": RPM_CEILING_NOTE}
Q_ADC = {"label": "ADC", "units": "ADC counts (raw sensor reading)",
         "expression": "x", "to_byte": "x",
         "format": "0", "fine": "1", "coarse": "8"}

Q_TEMP_C = {"label": "\u00b0C", "units": "\u00b0C",
            "expression": "x-40", "to_byte": "x+40",
            "format": "0", "fine": "1", "coarse": "5"}

Q_RAW_BP = {"label": "Breakpoint", "units": "raw",
            "expression": "x", "to_byte": "x",
            "format": "0", "fine": "1", "coarse": "8"}
Q_RAW_VAL = {"label": "Value", "units": "raw",
             "expression": "x", "to_byte": "x",
             "format": "0", "fine": "1", "coarse": "8"}


def _seg_labels(rows):
    """Two vertices per record: 'a' is the segment start, 'b' the segment end.

    Kept to three characters so the fixed cell width does not clip them.
    """
    out = []
    for i in range(rows):
        out.append(f"{i + 1}a")
        out.append(f"{i + 1}b")
    return out


def _record_axes(x_label, y_labels):
    nl = "\n"
    ys = nl.join(f"    <data>{escape(l)}</data>" for l in y_labels)
    return (f'   <table type="Static X Axis" name="Field" sizex="1">{nl}'
            f'    <data>{escape(x_label)}</data>{nl}   </table>{nl}'
            f'   <table type="Static Y Axis" name="Vertex" sizey="{len(y_labels)}">{nl}'
            f'{ys}{nl}   </table>')


RECORD_SPLIT_NOTE = (
    "\n\nThis table holds ONE of the two quantities in the record array, so it can "
    "be shown in real units. Rows are the polyline vertices in order: 1a is the "
    "start of segment 1, 1b its end, 2a the start of segment 2, and so on. "
    "A segment's end normally equals the next segment's start; where it does not, "
    "the curve steps vertically at that point, which is deliberate. The companion "
    "table in the same category holds the other quantity, row for row."
)


def build_record_tables_xml(name, category, addr, rows, quantities, desc,
                            userlevel=1):
    """Emit one table per physical quantity in an 8-byte record array.

    `quantities` is a list of (field_index, quantity_dict). Field 0/2 share one
    quantity and field 1/3 the other, so only fields 0 and 1 are passed - the
    skipCells stride picks up 2 and 3 automatically.
    """
    out = []
    for field, q in quantities:
        out.append(
            f"""  <table type="3D" name="{escape(name + ' - ' + q['label'])}" category="{escape(category)}" storageaddress="0x{addr + field * 2:06X}" storagetype="uint16" endian="big" sizex="1" sizey="{rows * 2}" skipCells="1" userlevel="{userlevel}">
   <scaling units="{escape(q['units'])}" expression="{escape(q['expression'])}" to_byte="{escape(q['to_byte'])}" format="{q['format']}" fineincrement="{q['fine']}" coarseincrement="{q['coarse']}" />
{_record_axes(q['label'], _seg_labels(rows))}
   <description>{escape(desc + RECORD_SPLIT_NOTE + q.get('note', ''))}</description>
  </table>"""
        )
    return "\n".join(out)


# Every shift schedule in the ROM, not just the first.
#
# The curves hang off a pointer array indexed as gear * 2 + direction, ten entries
# per mode. Walking past the first ten shows FIFTY modes - which is the "50 sets"
# rimwall reported in the forum thread - organised as ten groups of five.
#
# Within each group the live upshifts step down 4, 3, 2, 1, 0 as the mode rises, the
# highest one being replaced by a placeholder each time. That is manual gear
# limiting: D, hold 4th, hold 3rd, hold 2nd, hold 1st. It is read off the data, not
# assumed - no fuelling or temperature state would progressively disable upshifts
# from the top down. Note this differs from rimwall's reading, where the five were
# fuelling states; his index came from a different array.
#
# The ten GROUPS are the operating conditions, and they are NOT named. Sasha_A80's
# candidate list in the thread - cold and warm engine, cold and warm ATF, catalyst
# preheat, quick shift, hill assist - was offered as "there should be", and nobody
# established which is which. They are numbered rather than guessed at.
SHIFT_MODES = json.load(open(os.path.join(here, "shift_modes.json")))

SHIFT_ORDER = [
    ("Shift 1-2 Upshift Curve", "1-2 Up"),
    ("Shift 2-3 Upshift Curve", "2-3 Up"),
    ("Shift 3-4 Upshift Curve", "3-4 Up"),
    ("Shift 4-5 Upshift Curve", "4-5 Up"),
    ("Shift 2-1 Downshift Curve", "2-1 Down"),
    ("Shift 3-2 Downshift Curve", "3-2 Down"),
    ("Shift 4-3 Downshift Curve", "4-3 Down"),
    ("Shift 5-4 Downshift Curve", "5-4 Down"),
]

SHIFT_MAP_DESC = (
    "THE SHIFT MAP. All eight shift points in one table, in the form a five-speed "
    "automatic is normally calibrated: vehicle speed against accelerator pedal "
    "angle, one row per shift event.\n\n"
    "Read a cell as: this shift happens at this road speed when the pedal is at "
    "this position. Raise a value to delay the shift, lower it to bring the shift on "
    "earlier. The upshift rows come first, then the downshifts - the gap between an "
    "upshift and its matching downshift is the hysteresis that stops the "
    "transmission hunting between two gears, so move the pair together unless you "
    "specifically intend to change it.\n\n"
    "Every value is vehicle speed in km/h, confirmed against the factory shift "
    "chart. The axis is accelerator opening angle, stored as 0-255 for 0-100%.\n\n"
    "Cells showing '-' are not editable. They are pedal positions where that "
    "particular curve has no vertex in the ROM, so there is no byte to change. Each "
    "curve is stored as its own polyline with its own breakpoints; this table lines "
    "them up on the shared pedal axis and leaves a gap where a curve does not use a "
    "position, rather than inventing a value.\n\n"
    "Requires the patched RomRaider in romraider-5eat/. The eight curves sit at "
    "eight separate addresses with different lengths, which upstream cannot express "
    "as one table - see Table3D.cellIndices."
)


def build_shift_map_xml(curves, u16_at, suffix=None, total=1):
    """All eight shift curves as ONE sparse 3D table.

    X axis is the pedal positions this firmware actually uses: the union of every
    curve's breakpoints. That union is verified to contain each individual curve's
    set as a subset, in all eleven firmwares.

    Speed cannot be the shared axis - all eight curves use different speed
    breakpoints, so there is no common grid to hang them on. Pedal can, and that is
    what makes one physically meaningful surface possible instead of eight strips.

    Cells are mapped individually because the curves are neither one contiguous
    block nor equal in length, and because any given curve only has a vertex at some
    of the pedal positions. Absent cells get -1 and render as read-only placeholders.
    """
    present = [(name, label, curves[name]) for name, label in SHIFT_ORDER
               if name in curves]
    if not present:
        return None

    pedals = sorted({u16_at(c["addr"] + r * 8 + 2)
                     for _, _, c in present for r in range(c["rows"])})

    # Cell indices are measured from the lowest field-0 address, so they all stay
    # small and positive.
    base = min(c["addr"] for _, _, c in present)

    indices = []
    for _, _, c in present:
        by_pedal = {u16_at(c["addr"] + r * 8 + 2): c["addr"] + r * 8
                    for r in range(c["rows"])}
        for p in pedals:
            speed_addr = by_pedal.get(p)
            indices.append(-1 if speed_addr is None else (speed_addr - base) // 2)

    nl = "\n"
    xs = nl.join('    <data>%.1f</data>' % (p * 100.0 / 255.0) for p in pedals)
    ys = nl.join('    <data>%s</data>' % escape(label) for _, label, _ in present)
    axes = ('   <table type="Static X Axis" name="Pedal %%" sizex="%d">%s%s%s   </table>%s'
            % (len(pedals), nl, xs, nl, nl)
            + '   <table type="Static Y Axis" name="Shift" sizey="%d">%s%s%s   </table>'
            % (len(present), nl, ys, nl))

    name = "Shift Map" if suffix is None else "Shift Map %d of %d" % (suffix, total)
    extra = "" if suffix is None else (
        "\n\nThis is schedule %d of %d in this ROM. The transmission carries several "
        "complete shift schedules and switches between them by operating condition - "
        "the thread that this work builds on lists cold and warm engine, cold and warm "
        "ATF, catalyst preheat, quick shift and hill assist as the likely candidates, "
        "but WHICH condition selects WHICH schedule has not been established, so they "
        "are numbered rather than named. Schedule 1 is the one this definition shipped "
        "on its own before the others were found.\n\nEach schedule also has four "
        "gear-limited variants for manual mode, which reuse these same curves with the "
        "upper upshifts disabled, so they are not listed separately."
        % (suffix, total))
    return (
        '  <table type="3D" name="%s" category="Transmission - Shift Schedule"'
        ' storageaddress="0x%06X" storagetype="uint16" endian="big" sizex="%d"'
        ' sizey="%d" cellIndices="%s" userlevel="1">%s'
        '   <scaling units="%s" expression="%s" to_byte="%s" format="%s"'
        ' fineincrement="%s" coarseincrement="%s" />%s'
        '%s%s'
        '   <description>%s</description>%s'
        '  </table>'
        % (escape(name), base, len(pedals), len(present),
           ",".join(str(i) for i in indices), nl,
           escape(Q_SPEED["units"]), Q_SPEED["expression"], Q_SPEED["to_byte"],
           Q_SPEED["format"], Q_SPEED["fine"], Q_SPEED["coarse"], nl,
           axes, nl,
           escape(SHIFT_MAP_DESC + extra), nl))


# ---------------------------------------------------------------------------
# Diagnostic trouble codes.
#
# Found from the CAN decoding, not by pattern scanning. CAN 0x422 bytes 3-4 carry
# a word whose top two bits are a rotating index and whose low 14 bits are the DTC
# number, and FUN_00032cac builds exactly that:
#
#   DAT_008047b6 = (ushort)DAT_008049b5 * 0x4000
#                + ((&DAT_008047b8)[DAT_008049b5] & 0x3fff);
#
# The four RAM slots are filled from a table indexed by status byte times eight
# plus bit position:
#
#   (&DAT_008047b8)[n] = (&DAT_0001ce18)[group * 8 + bit];
#
# so DAT_0001ce18 is 12 x 8 = 96 uint16 codes. Stored as the P-number in HEX:
# 0x705 is P0705, the one code the factory manual names.
#
# This replaces an earlier claim of DTC tables at 0x4090, which was wrong - that
# address is instruction stream, and those tables would have let an edit zero out
# boot code. See docs/ROM-DETAILS.md.
#
# Shipped LOCKED. The codes are real data and worth being able to read, but
# changing which code the TCU reports for a given fault is not a tuning operation
# and would only make a fault harder to diagnose.
# ---------------------------------------------------------------------------
DTC_TABLE_BY_ROM = json.load(open(os.path.join(here, "dtc_table.json")))

DTC_GROUPS = 12
DTC_BITS = 8

DTC_DESC = (
    "Diagnostic trouble codes this TCU can report, as stored in the ROM.\n\n"
    "READ THIS TO INTERPRET THE VALUES: each code is the P-number in hexadecimal, "
    "shown here in decimal because RomRaider cannot display hex. Convert the value "
    "to hex and read it as the code - 1797 is 0x705 which is P0705, 1824 is 0x720 "
    "which is P0720, and 5894 is 0x1706 which is P1706.\n\n"
    "Entries are in the order the firmware scans them: eight consecutive entries per "
    "fault-status byte, twelve bytes in all, so entry 8*g+b is the code for bit b of "
    "status byte g. When a fault bit is set, that code is what goes out on CAN 0x422 "
    "bytes 3-4. 43 of the 96 slots are zero - spare bits with no code assigned.\n\n"
    "DISABLING A CODE: set its entry to 0. That makes the slot identical to the 43 "
    "the factory already leaves at zero, so the fault bit still sets internally but "
    "no code number is attached to it. Useful after a hardware change that leaves a "
    "sensor permanently reading a fault.\n\n"
    "Be aware of what that is and is not. It suppresses the CODE, not the fault - "
    "whatever limp-home or pressure behaviour the TCU applies when that bit sets will "
    "still happen, you have only stopped it telling you why. And this is inferred "
    "from the table layout, not tested on a car: zero is what the firmware's own "
    "unused slots contain, which is the best evidence available, but nobody has "
    "confirmed on a vehicle how a scan tool reports it. Note the code you removed "
    "before you remove it.\n\n"
    "Located from the CAN decoding contributed to the RomRaider forum thread rather "
    "than by pattern matching. An earlier version of this definition claimed DTC "
    "tables at 0x4090; that was wrong - the address is M32R instruction stream, and "
    "editing it would have corrupted the TCU's start-up code."
)


DTC_SWITCH_DESC = (
    "%s - enable or disable this diagnostic trouble code.\n\n"
    "DISABLED writes zero to this code's slot, which makes it identical to the 43 "
    "slots the factory already leaves empty. The fault bit still sets internally, "
    "but no code number is attached to it, so nothing is reported.\n\n"
    "Know what that does and does not do. It suppresses the CODE, not the FAULT - "
    "whatever limp-home, pressure or shift behaviour the TCU applies when that bit "
    "sets will still happen. You have only stopped it telling you why. Useful after "
    "a hardware change that leaves a sensor permanently faulted; a poor idea as a "
    "way of silencing a fault you have not diagnosed.\n\n"
    "This behaviour is inferred from the table layout, not tested on a vehicle. "
    "Zero is what the firmware's own unused slots contain, which is the best "
    "evidence available, but nobody has confirmed how a scan tool reports it.\n\n"
    "Stored at 0x%06X as 0x%04X. The code is the P-number in hex, so this reads as "
    "%s."
)


def build_dtc_switch_xml(addr, code):
    """One switch per code, named for the code, as RomRaider ECU definitions do.

    Three shapes were tried before this one. A 12 x 8 grid mirrored the firmware's
    indexing but was mostly empty, since 43 of the 96 slots hold nothing. A flat 1D
    list of all 96 rendered as a single row four thousand pixels wide - honest
    shape, unusable table. A packed grid of just the real codes was readable but
    still made you hunt for a code by eye.

    A switch per code is how every other RomRaider definition presents DTCs: the
    tree lists them by name, so you find P0705 by reading down the list, and the
    control is a plain Enabled/Disabled rather than a number to remember.
    """
    name = "P%04X" % code
    return (
        '  <table type="Switch" name="%s" '
        'category="Transmission - Diagnostic Codes" '
        'storageaddress="0x%06X" sizey="2" userlevel="1">\n'
        '   <description>%s</description>\n'
        '   <state name="Enabled" data="%02X %02X" />\n'
        '   <state name="Disabled" data="00 00" />\n'
        '  </table>'
        % (name, addr, escape(DTC_SWITCH_DESC % (name, addr, code, name)),
           (code >> 8) & 0xFF, code & 0xFF))


def build_dtc_tables_xml(entry):
    """Every code in this firmware, as its own switch, ordered by code number."""
    base = entry["addr"]
    n = DTC_GROUPS * DTC_BITS
    found = []
    for i in range(n):
        code = u16(base + i * 2)
        if code in (0x0000, 0x3FFF, 0xFFFF):
            continue
        found.append((code, base + i * 2))
    # Sort by code so the tree reads like a code list rather than scan order.
    found.sort()
    return [build_dtc_switch_xml(a, c) for c, a in found]


# ---------------------------------------------------------------------------
# Downshift pressure control - target pressure, and how fast it is applied.
#
# A second target lookup in the same RAM block as the line pressure target:
#
#   DAT_00804a94 = FUN_00045070((&PTR_PTR_00012034)[DAT_00804a8e], 0, DAT_008047fe);
#
# Vehicle speed in, pressure out, wrapped in a timed ramp: a counter increments
# every cycle and is compared against a per-state duration, and once it elapses the
# output steps toward the target by a per-state amount.
#
#   if (timer < duration[idx])  out = floor;
#   else                        out = min(target, start + step[idx]);
#
# The state index comes from a 5x5 byte matrix that is lower triangular - valid only
# where the target gear is BELOW the current gear, with exactly ten entries. Ten
# downshifts among five gears. That is a gear transition, so this is downshift
# control and NOT the torque converter lock-up.
#
# Pressure is /10 = kPa, the scale confirmed against the factory manual in section
# 19: these maps top out at 13720, which is that manual's 1372 kPa for full throttle
# in D. Duration is a loop counter with no established period and ships raw, because
# calling it milliseconds without knowing the task rate would be a guess.
# ---------------------------------------------------------------------------
DOWNSHIFT_PRESSURE = json.load(
    open(os.path.join(here, "downshift_pressure.json")))

# Index order is fixed by the matrix: [a*5+b] with b<a, a and b zero-based gears.
DOWNSHIFT_NAMES = ["2-1", "3-1", "3-2", "4-1", "4-2", "4-3",
                   "5-1", "5-2", "5-3", "5-4"]

Q_KPA_STEP = {"label": "kPa", "units": "kPa (pressure step)",
              "expression": "x/10", "to_byte": "x*10",
              "format": "0", "fine": "5", "coarse": "50"}
Q_TICKS = {"label": "ticks", "units": "loop counts (period not established)",
           "expression": "x", "to_byte": "x",
           "format": "0", "fine": "1", "coarse": "10"}

DS_MAP_DESC = (
    "DOWNSHIFT PRESSURE TARGET, %s. The pressure commanded during this particular "
    "downshift, against vehicle speed.\n\n"
    "Pressure is in kPa on the scale confirmed against the factory manual - these "
    "maps reach 1372 kPa, which is the manual's figure for full throttle in D.\n\n"
    "Raising a value makes this downshift firmer and faster; lowering it makes it "
    "softer and slower, at the cost of more clutch slip during the change. Pair it "
    "with the ramp step and duration tables in this category, which control how "
    "quickly the pressure is allowed to get there."
)

DS_STEP_DESC = (
    "DOWNSHIFT PRESSURE RAMP STEP, one entry per downshift in the order 2-1, 3-1, "
    "3-2, 4-1, 4-2, 4-3, 5-1, 5-2, 5-3, 5-4.\n\n"
    "Once the hold period expires, the commanded pressure moves from where it "
    "started toward the target by this much. A large value - 32767 appears in the "
    "stock calibration for most entries - means effectively no limit, so the "
    "pressure goes straight to target. A small value makes the application gradual, "
    "which is what the factory calls smooth control.\n\n"
    "This is the knob for downshift harshness. Smaller steps are softer and slower."
)

DS_DUR_DESC = (
    "DOWNSHIFT PRESSURE HOLD DURATION, one entry per downshift in the order 2-1, "
    "3-1, 3-2, 4-1, 4-2, 4-3, 5-1, 5-2, 5-3, 5-4.\n\n"
    "How long the pressure is held at its floor before the ramp starts. The value is "
    "a count of controller loops. The loop period has NOT been established, so this "
    "is left as a raw count rather than converted to milliseconds - a time unit "
    "derived from a guessed task rate would look authoritative and be wrong.\n\n"
    "Larger values delay the pressure rise, which softens the initial engagement."
)


def build_downshift_xml(entry):
    """Ten target maps, plus the step and duration tables that pace them."""
    out = []
    for i, m in enumerate(entry["maps"]):
        label = DOWNSHIFT_NAMES[i] if i < len(DOWNSHIFT_NAMES) else str(i)
        out.append(build_record_tables_xml(
            "Downshift %s Pressure" % label,
            "Transmission - Downshift Pressure",
            m["addr"], m["rows"],
            [(0, Q_SPEED), (1, Q_KPA_10)], DS_MAP_DESC % label))

    ramp = entry["ramp"]
    n = len(DOWNSHIFT_NAMES)
    nl = "\n"
    ys = nl.join("    <data>%s</data>" % d for d in DOWNSHIFT_NAMES)

    def strided(name, addr, q, desc):
        # {step, duration} is a 4-byte struct, so skipCells=1 walks one field of
        # each - the same stride trick the record arrays use.
        return (
            '  <table type="3D" name="%s" category="Transmission - Downshift Pressure" '
            'storageaddress="0x%06X" storagetype="uint16" endian="big" '
            'sizex="1" sizey="%d" skipCells="1" userlevel="1">%s'
            '   <scaling units="%s" expression="%s" to_byte="%s" format="%s" '
            'fineincrement="%s" coarseincrement="%s" />%s'
            '   <table type="Static X Axis" name="%s" sizex="1">%s    <data>%s</data>%s   </table>%s'
            '   <table type="Static Y Axis" name="Downshift" sizey="%d">%s%s%s   </table>%s'
            '   <description>%s</description>%s'
            '  </table>'
            % (name, addr, n, nl,
               escape(q["units"]), q["expression"], q["to_byte"], q["format"],
               q["fine"], q["coarse"], nl,
               escape(q["label"]), nl, escape(q["label"]), nl, nl,
               n, nl, ys, nl, nl,
               escape(desc), nl))

    out.append(strided("Downshift Ramp Step", ramp, Q_KPA_STEP, DS_STEP_DESC))
    out.append(strided("Downshift Ramp Hold", ramp + 2, Q_TICKS, DS_DUR_DESC))
    return out


# ---------------------------------------------------------------------------
# Line pressure TARGET maps - engine torque in, line pressure out.
#
# The end of the chain described in forum post 184 and scaled in FINDINGS 18:
# engine torque from CAN 0x412 is multiplied by the slip factor, smoothed,
# multiplied again by the ATF temperature factor, and the result looks up a target
# here. Found by following DAT_008042fa (the twice-factored torque) to its only
# consumers, which read pointer arrays at 0x12478 and 0x12314.
#
# Both axes confirmed against documents outside this project:
#   input  /10 = Nm   - community CAN decoding, 0x412 bytes 3-4 = Engine Torque
#   output /10 = kPa  - factory manual 5AT-35, which specifies 490 kPa nominal at
#                       closed throttle (this reads 524) and 1370 kPa at full
#                       throttle in D (this reads 1372 at 400 Nm)
# ---------------------------------------------------------------------------
LINE_PRESSURE_TARGETS = json.load(
    open(os.path.join(here, "line_pressure_targets.json")))

Q_TORQUE_NM = {"label": "Nm", "units": "Nm (engine torque)",
               "expression": "x/10", "to_byte": "x*10",
               "format": "0", "fine": "1", "coarse": "10"}
Q_KPA_10 = {"label": "kPa", "units": "kPa (line pressure)",
            "expression": "x/10", "to_byte": "x*10",
            "format": "0", "fine": "5", "coarse": "50"}

LP_TARGET_DESC = (
    "LINE PRESSURE TARGET. Engine torque in, commanded line pressure out. This is "
    "what the pressure control solenoid is driven to achieve.\n\n"
    "The torque axis is the engine torque the ECU reports on CAN 0x412, after the "
    "TCU has multiplied it by the Torque Converter Slip Pressure Factor, smoothed "
    "it, and multiplied it again by the ATF temperature factor. So the axis is "
    "effective torque, not raw crank torque.\n\n"
    "Both units are confirmed against outside sources rather than inferred. The "
    "torque axis comes from the community CAN decoding of 0x412 bytes 3-4. The "
    "pressure axis reproduces the two figures in the factory manual's line pressure "
    "test: about 524 kPa at low torque against a specified 490 nominal (385-555 "
    "band), and 1372 kPa at 400 Nm against a specified 1370 at full throttle in D.\n\n"
    "RAISING THESE RAISES CLAMPING FORCE. Firmer, faster shifts and more clutch "
    "holding capacity, at the cost of harsher engagement, more pump load and more "
    "heat. Several maps exist and the TCU selects between them by operating state - "
    "which state picks which map has NOT been established, so change them as a set "
    "unless you have logged which one is active."
)


def build_line_pressure_target_xml(idx, m):
    name = "Line Pressure Target %d" % idx
    return build_record_tables_xml(
        name, "Transmission - Line Pressure", m["addr"], m["rows"],
        [(0, Q_TORQUE_NM), (1, Q_KPA_10)], LP_TARGET_DESC)


# ---------------------------------------------------------------------------
# Line pressure target curves - the first tables here with a pressure unit that
# is not a guess. See tools/extract_pressure_curves.py for how they were found
# and why the earlier "Pressure Control" families are NOT this.
#
# Layout differs from the shift curves: 4-byte records, 2 x uint16, one value
# per record rather than a start/end pair:
#
#     [engine speed x 8, pressure in kPa]
#
# So the stride is the same (skipCells=1 walks every second uint16) but sizey is
# the record count, not twice it.
# ---------------------------------------------------------------------------
PRESSURE_CURVES_BY_ROM = json.load(open(os.path.join(here, "pressure_curves.json")))

Q_KPA = {"label": "kPa", "units": "kPa",
         "expression": "x", "to_byte": "x",
         "format": "0", "fine": "5", "coarse": "50"}

PRESSURE_DESC = (
    "Line pressure target against engine speed. Both columns are in real units and "
    "neither is inferred: the breakpoint column uses the same /8 engine-speed "
    "scaling confirmed elsewhere in this definition, and the value column is "
    "already in kPa.\n\n"
    "The kPa unit is confirmed against the factory service manual line pressure "
    "test (5AT-35), which has the TCU reporting 'P/L Solenoid Target Pressure' to "
    "the Subaru Select Monitor in kPa and specifies 1370 kPa at full throttle in D "
    "and R. That value appears verbatim in this table in all eleven firmwares, at "
    "an address that relocates between them - so it is calibration data, not a "
    "coincidence.\n\n"
    "WHAT IS NOT CONFIRMED: which hydraulic circuit each of the two curves "
    "governs. The value is flat across engine speed within each curve (1370 kPa in "
    "one, 953 kPa in the other), and the consuming function has not been traced. "
    "The tables are named for what they demonstrably contain rather than for a "
    "circuit that would be a guess.\n\n"
    "The final breakpoint is 8160 RPM (65280 raw), a max sentinel rather than a "
    "real operating point. Raising line pressure increases clamping force and "
    "shift firmness; it also increases pump load and wear."
)


def build_pressure_curve_xml(idx, c):
    """One pressure curve as two single-unit tables (RPM breakpoint, kPa value)."""
    name = f"Line Pressure Target {idx} ({c['kpa']} kPa)"
    out = []
    for field, q in ((0, Q_RPM), (1, Q_KPA)):
        out.append(
            f"""  <table type="3D" name="{escape(name + ' - ' + q['label'])}" category="Transmission - Line Pressure" storageaddress="0x{c['addr'] + field * 2:06X}" storagetype="uint16" endian="big" sizex="1" sizey="{c['rows']}" skipCells="1" userlevel="1">
   <scaling units="{escape(q['units'])}" expression="{escape(q['expression'])}" to_byte="{escape(q['to_byte'])}" format="{q['format']}" fineincrement="{q['fine']}" coarseincrement="{q['coarse']}" />
{_record_axes(q['label'], [str(i + 1) for i in range(c['rows'])])}
   <description>{escape(PRESSURE_DESC + q.get('note', ''))}</description>
  </table>"""
        )
    return "\n".join(out)



# ---------------------------------------------------------------------------
# Record-format ("hysteresis") curves, base ROM addresses.
#
# Same 8-byte record layout as the shift schedule: 4 x uint16 per row, array
# terminated by a leading 0xFFFF. Column 1 is the breakpoint (monotonic), the
# rest are the values interpolated between.
#
# These were located by enumerating every call site of the record-lookup routine
# (FUN_00045070 in the base ROM) and reading the table pointer out of the
# argument, then filtering to those whose breakpoint column is genuinely
# monotonic -- which rejects the gear-indexed pointer arrays that otherwise look
# like tables.
#
# They were previously excluded because RomRaider has no stride support. The
# shift-schedule work showed that objection was wrong: the record block is
# contiguous, so a 3D table with sizex=4 maps onto it exactly. RomRaider's own
# parser accepts them.
#
# Inputs are named where traced. Where the input is only known as an internal
# RAM variable the name says so rather than inventing a meaning.
# ---------------------------------------------------------------------------
HYSTERESIS_CURVES = json.load(open(os.path.join(here, "hysteresis_curves.json")))

# Per-firmware addresses for the same curves, matched positionally against the
# base ROM's call-site order. Only firmwares whose call-site count matches the
# base exactly are present -- where it differs, positional matching is unsafe and
# the firmware is omitted rather than guessed at.
HYSTERESIS_BY_ROM = json.load(open(os.path.join(here, "hysteresis_by_rom.json")))

# Breakpoint units per curve family.
#
# The breakpoint is the quantity the TCU searches on, so its unit is whatever
# feeds the lookup. Only assign one where the input was actually traced through
# the decompilation - a wrong unit is worse than "raw", because it reads as
# confirmed. Families not listed here keep raw breakpoints deliberately.
#
# Engine Speed Curves: the lookup input is the engine speed register, the same
# raw/8 scaling already confirmed for the SpeedTrim and SlipThreshold axes.
# Reference Speed Curves: input is vehicle speed in km/h, as for the shift
# schedule - same signal, same units.
# Fixed-point multipliers, confirmed rather than pattern-matched.
#
# The forum thread (post 184, rimwall) describes the line pressure chain: engine
# torque arrives on CAN 0x412, is multiplied by a factor looked up on torque
# converter slip, smoothed, multiplied again by a factor looked up on ATF
# temperature, and the result looks up a line pressure target.
#
# Both factor tables are here, and both were checked before being scaled:
#
# SLIP FACTOR - reproduces rimwall's stated numbers exactly. Breakpoints and values
# are both /1024. Breakpoint 512 is a speed ratio of 0.5 and gives 1425/1024 =
# 1.392, against his "for high slip (~0.5) the factor is ~1.4". Breakpoint 922 =
# 0.9 gives exactly 1.000, against his "for low slip, the factor is ~1.0". Two
# independent numbers from an outside source landing on the same scale is not a
# coincidence.
#
# ATF TEMP FACTOR - confirmed from the code rather than the shape. FUN_00036e.. does
#
#     uVar4 = FUN_00045070(&DAT_00008428, 1, DAT_008047fb);  // lookup
#     iVar2 = (uVar7 & 0xffff) * (uVar4 & 0xffff);
#     ... (uVar5 * iVar2) >> 0x10
#
# and uVar7 defaults to 0x100. 256 is unity, two /256 factors multiplied then
# shifted right 16 is arithmetically exact, so the fixed point is /256. The decoded
# curve runs 1.699 down to 1.000 over breakpoints of about -40 to -5 C: more line
# pressure while the fluid is cold, unity once it is warm.
Q_FACTOR_1024 = {"label": "factor", "units": "x (multiplier)",
                 "expression": "x/1024", "to_byte": "x*1024",
                 "format": "0.000", "fine": "0.005", "coarse": "0.05"}
Q_FACTOR_256 = {"label": "factor", "units": "x (multiplier)",
                "expression": "x/256", "to_byte": "x*256",
                "format": "0.000", "fine": "0.004", "coarse": "0.04"}
Q_RATIO_1024 = {"label": "slip ratio", "units": "turbine/engine ratio",
                "expression": "x/1024", "to_byte": "x*1024",
                "format": "0.000", "fine": "0.005", "coarse": "0.05"}

# Per-curve unit overrides, by the name in hysteresis_curves.json. Only curves whose
# scale has actually been established appear here; everything else stays raw.
# Proven fixed point, quantity unknown. tools/detect_fixed_point.py shows every
# stored value in every firmware is an exact multiple of the divisor, so the low bits
# are fractional; what the number measures is still not established.
Q_FP_256 = {"label": "1/256", "units": "units of 1/256 (quantity not established)",
            "expression": "x/256", "to_byte": "x*256",
            "format": "0.00", "fine": "0.05", "coarse": "1"}
Q_FP_8 = {"label": "1/8", "units": "units of 1/8 (quantity not established)",
          "expression": "x/8", "to_byte": "x*8",
          "format": "0.0", "fine": "0.5", "coarse": "4"}

RECORD_UNIT_OVERRIDES = {
    # Proven fixed point by tools/detect_fixed_point.py; quantity still unknown.
    "Reference Speed Curve 1 of 3": (None, Q_FP_256),
    "Signal 82CC Curve 1 of 2": (None, Q_FP_256),
    "Signal FE Response Curve": (None, Q_FP_8),
    # /8 over a 517..4096 range on an engine-speed axis is the confirmed RPM
    # encoding for this family, so this one does get a real unit.
    "Engine Speed Curve 6 of 6": (None, Q_RPM),
    "Signal 82AC Curve 1 of 2": (Q_RATIO_1024, Q_FACTOR_1024),
    # The linearisation tables turn a raw ADC reading into a temperature, so the
    # value column IS a temperature and uses the -40 encoding already confirmed for
    # this family. The stored values are a clean five-step ladder - 0, 15, 20, 25,
    # 30 ... 245 - which decodes to -40 C through 205 C in 5 C steps, the standard
    # automotive range. The breakpoint is a raw ADC count and has no better unit.
    "Temp Sensor 1 Linearisation": (Q_ADC, Q_TEMP_C),
    "Temp Sensor 2 Linearisation": (Q_ADC, Q_TEMP_C),
    "ATF Temp Curve (8428)": (Q_TEMP_C, Q_FACTOR_256),
    "ATF Temp Curve A (Mode 1)": (Q_TEMP_C, Q_FACTOR_256),
    "ATF Temp Curve A (Mode 2)": (Q_TEMP_C, Q_FACTOR_256),
}

# Curves worth renaming now that what they do is established.
RECORD_RENAMES = {
    "Signal 82AC Curve 1 of 2": "Torque Converter Slip Pressure Factor",
}

RECORD_EXTRA_DESC = {
    "Temp Sensor 1 Linearisation": (
        "\n\nATF TEMPERATURE SENSOR CALIBRATION. Converts the raw ADC reading from "
        "the sensor into a temperature. The breakpoint is the ADC count, the value "
        "is what the TCU believes that count means.\n\nThis is what every "
        "temperature-dependent behaviour in the transmission ultimately reads, so "
        "changing it shifts the apparent temperature everywhere at once - including "
        "the cold-fluid pressure boost and the overheat protection. It is a "
        "calibration for the sensor, not a tuning knob."),
    "Temp Sensor 2 Linearisation": (
        "\n\nATF TEMPERATURE SENSOR CALIBRATION, second channel. See the notes on "
        "Temp Sensor 1: same role, same warning."),
    "Signal 82AC Curve 1 of 2": (
        "\n\nTORQUE CONVERTER SLIP FACTOR. Part of the line pressure chain: engine "
        "torque from CAN 0x412 is multiplied by this factor, smoothed, multiplied "
        "again by the ATF temperature factor, and the result looks up the line "
        "pressure target.\n\nThe breakpoint is the turbine-to-engine speed ratio, so "
        "1.000 is locked and lower numbers are more slip. Raising a value raises line "
        "pressure at that amount of slip, which firms up the clutches and speeds up "
        "shifts, at the cost of pump load and harsher engagement.\n\nThe scale is "
        "confirmed against the description posted by rimwall on the RomRaider forum: "
        "a ratio of 0.5 gives 1.392 here against his stated ~1.4, and low slip gives "
        "exactly 1.000 against his stated ~1.0."),
    "ATF Temp Curve (8428)": (
        "\n\nATF TEMPERATURE PRESSURE FACTOR. The second multiplier in the line "
        "pressure chain. Runs about 1.70 when the fluid is very cold down to exactly "
        "1.000 once warm, so the transmission raises line pressure while cold to "
        "compensate for fluid viscosity.\n\nThe /256 fixed point is confirmed from the "
        "code, not inferred from the shape: the lookup result is multiplied by a "
        "factor that defaults to 0x100 - which is 256, unity - and the product is "
        "shifted right by 16, which is exact only if both are /256."),
}

RECORD_BREAKPOINT_UNITS = {
    "Transmission - Engine Speed Curves": Q_RPM,
    "Transmission - Reference Speed": Q_SPEED,
}

HYST_DESC_SUFFIX = (
    "\n\nFormat: an array of 8-byte records, each one segment of a piecewise-linear "
    "curve. The array is terminated by a leading 0xFFFF."
)


def build_hyst_curve_xml(c, delta=0):
    addr = c["addr"] + delta
    override = RECORD_UNIT_OVERRIDES.get(c["name"])
    bp = RECORD_BREAKPOINT_UNITS.get(c["category"], Q_RAW_BP)
    val = Q_RAW_VAL
    if override:
        # None means "leave this column at its default" - several overrides only
        # establish the value column and have nothing to say about the breakpoint.
        o_bp, o_val = override
        bp = o_bp or bp
        val = o_val or val
    name = RECORD_RENAMES.get(c["name"], c["name"])
    desc = c["desc"] + HYST_DESC_SUFFIX + RECORD_EXTRA_DESC.get(c["name"], "")
    return build_record_tables_xml(
        name, c["category"], addr, c["rows"], [(0, bp), (1, val)], desc)


# ---------------------------------------------------------------------------
# NO DTC TABLES.
#
# An earlier version of this file shipped 19 "DTC" switch tables per firmware,
# read from 0x4090 as 8-byte [flags][code][data] records. That was WRONG and has
# been removed.
#
# 0x4090 is not data. It is M32R instruction stream inside FUN_00004000, in the
# early boot region:
#
#     00004080: a041 0074  a041 0078  a041 007c  6200 f000
#     00004090: a241 0700  6200 f000  a241 0704  6200 f000
#
# a041/a241 are opcodes; 0x0074, 0x0078, 0x007C, 0x0700, 0x0704 ... are their
# displacement operands, incrementing by 4 because they address consecutive
# words. It is port/register initialisation.
#
# The error came from scanning for uint16 values in 0x0700-0x07FF, finding a
# cluster, and assuming a P07xx code range without checking whether the bytes
# were code. Tells that were missed: the codes incremented by exactly 4 (real
# SAE lists do not), and nothing in the ROM referenced 0x4090 as data.
#
# This mattered beyond mislabelling. Each switch's "off" state zeroed bytes 2-3
# of a record -- instruction operands -- so toggling one would have corrupted
# boot code. Identified by rimwall, who noted the region is "just general
# initialisation of ports etc."
#
# If the real DTC table is found later, note that DTCs are transmitted on CAN
# 0x422 bytes 3-4 as [2-bit index][14-bit DTC number], per the CAN decoding
# thread (f=40&t=20850). Look for the code that builds that message.
# ---------------------------------------------------------------------------

ROM_PROFILES = [
    {
        "id": "91D1206000",
        "rom_file": "91D1206000_5EAT.bin",
        "xmlid": "SUBARU_5EAT_91D1206000",
        "base": None,
        "internalidstring": "MB431M",
        "caseid": "R9H",
        "year": "Pre-2005 (unconfirmed)",
        "market": "JDM",
        "submodel": "91D1206000 (JDM)",
        "filesize": "384kb",
        "offsets": {},          # base ROM: addresses are as written in FAMILIES
    },
    {
        "id": "91FE216300",
        "rom_file": "91FE216300.bin",
        "xmlid": "SUBARU_5EAT_91FE216300",
        "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB436G",
        "caseid": "QS1",
        "year": "2005",
        "market": "USDM",
        "submodel": "91FE216300 (USDM Outback XT)",
        "filesize": "512kb",
        # Verified individually from decompiled call sites, not extrapolated.
        "offsets": {"SpeedTrimA": 144, "PressureB": 144, "PressureC": 144, "ShiftStageD": 144, "PressureThresholdE": 144, "SlipThreshold": 148, "RefSpeedBaseline": 148, "CAN511Threshold": 148, "SignalResponseCurves": 148, "ShiftCorrection": 148},
    },
    {
        "id": "91D0207500", "rom_file": "91D0207500_MB436T_AH572_5EAT_JDM.bin",
        "xmlid": "SUBARU_5EAT_91D0207500", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB436T", "caseid": "Q3E", "year": "Unknown",
        "market": "JDM", "submodel": "91D0207500 (JDM)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 44, "PressureB": 44, "PressureC": 44, "ShiftStageD": 44, "PressureThresholdE": 44, "SlipThreshold": 48, "RefSpeedBaseline": 48, "CAN511Threshold": 48, "SignalResponseCurves": 48, "ShiftCorrection": 48},
    },
    {
        "id": "91F0217100", "rom_file": "91F0217100_MB436P_AG810_OBK03USDM.bin",
        "xmlid": "SUBARU_5EAT_91F0217100", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB436P", "caseid": "Q3B", "year": "2003",
        "market": "USDM", "submodel": "91F0217100 (USDM Outback 03)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 144, "PressureB": 144, "PressureC": 144, "ShiftStageD": 144, "PressureThresholdE": 144, "SlipThreshold": 148, "RefSpeedBaseline": 148, "CAN511Threshold": 148, "SignalResponseCurves": 148, "ShiftCorrection": 148},
    },
    {
        "id": "ABD1A03100", "rom_file": "ABD1A03100_A61022_LGT_JDM_2005_5EAT.bin",
        "xmlid": "SUBARU_5EAT_ABD1A03100", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB4434", "caseid": "Q1F", "year": "2005",
        "market": "JDM", "submodel": "ABD1A03100 (JDM Legacy GT 2005)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 142, "PressureB": 144, "PressureC": 144, "ShiftStageD": 144, "PressureThresholdE": 144, "SlipThreshold": 148, "RefSpeedBaseline": 148, "CAN511Threshold": 148, "SignalResponseCurves": 148, "ShiftCorrection": 148},
    },
    {
        "id": "91D1207900", "rom_file": "[91D1207900-A61022]_31711AG589.bin",
        "xmlid": "SUBARU_5EAT_91D1207900", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB4373", "caseid": "Q3P", "year": "Unknown",
        "market": "JDM", "submodel": "91D1207900 (Hitachi 31711AG589)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 42, "PressureB": 44, "PressureC": 44, "ShiftStageD": 44, "PressureThresholdE": 44, "SlipThreshold": 48, "RefSpeedBaseline": 48, "CAN511Threshold": 48, "SignalResponseCurves": 48, "ShiftCorrection": 48},
    },
    {
        "id": "AAD1A07100", "rom_file": "[AAD1A07100-A61022]_31711AJ782.bin",
        "xmlid": "SUBARU_5EAT_AAD1A07100", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB440X", "caseid": "Q2P", "year": "Unknown",
        "market": "JDM", "submodel": "AAD1A07100 (Hitachi 31711AJ782)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 162, "PressureB": 164, "PressureC": 164, "ShiftStageD": 164, "PressureThresholdE": 164, "SlipThreshold": 168, "RefSpeedBaseline": 168, "CAN511Threshold": 168, "SignalResponseCurves": 168, "ShiftCorrection": 168},
    },
    {
        "id": "ABD1207000", "rom_file": "[ABD1207000-A61022].bin",
        "xmlid": "SUBARU_5EAT_ABD1207000", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB5300", "caseid": "Q5L", "year": "2006",
        "market": "JDM", "submodel": "ABD1207000 (06 JDM Legacy GT)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 142, "PressureB": 144, "PressureC": 144, "ShiftStageD": 144, "PressureThresholdE": 144, "SlipThreshold": 148, "RefSpeedBaseline": 148, "CAN511Threshold": 148, "SignalResponseCurves": 148, "ShiftCorrection": 148},
    },
    {
        "id": "ACD1207000", "rom_file": "ACD1207000_MB558D01_LGT06_JDM.bin",
        "xmlid": "SUBARU_5EAT_ACD1207000", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB558D01", "caseid": "Q7W", "year": "2006",
        "market": "JDM", "submodel": "ACD1207000 (LGT06 JDM)", "filesize": "512kb",
        "offsets": {"SpeedTrimA": 142, "PressureB": 144, "PressureC": 144, "ShiftStageD": 96, "PressureThresholdE": 144, "SlipThreshold": 100, "RefSpeedBaseline": 100, "CAN511Threshold": 100, "SignalResponseCurves": 100, "ShiftCorrection": 100},
    },
    {
        "id": "ADE0236000", "rom_file": "5EAT_ADE0236000.bin",
        "xmlid": "SUBARU_5EAT_ADE0236000", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB562EH", "caseid": "Q8C", "year": "Unknown",
        "market": "Unknown", "submodel": "ADE0236000", "filesize": "512kb",
        "offsets": {"SpeedTrimA": 592, "PressureB": 592, "PressureC": 592,
                    "ShiftStageD": 544, "PressureThresholdE": 592,
                    "SlipThreshold": 548, "RefSpeedBaseline": 548,
                    "CAN511Threshold": 548, "SignalResponseCurves": 548,
                    "ShiftCorrection": 548},
    },
    {
        "id": "ACD1A06000", "rom_file": "ACD1A06000_JDM_5EAT_2007_M32176F4V.bin",
        "xmlid": "SUBARU_5EAT_ACD1A06000", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB558D20", "caseid": "Q6E", "year": "2007",
        "market": "JDM", "submodel": "ACD1A06000 (JDM 2007)", "filesize": "512kb",
        "offsets": {"SpeedTrimA": 142, "PressureB": 144, "PressureC": 144, "ShiftStageD": 96, "PressureThresholdE": 144, "SlipThreshold": 100, "RefSpeedBaseline": 100, "CAN511Threshold": 100, "SignalResponseCurves": 100, "ShiftCorrection": 100},
    },
    # The five below came from github.com/jimihimi/TCURoms. Their offsets were
    # derived by tools/find_rom_offsets.py rather than read out of decompiled call
    # sites one at a time; that tool reproduces the hand-derived offsets for every
    # firmware already listed here, which is what makes its answers usable.
    {
        "id": "91A0217300", "rom_file": "91A0217300_MB4365.bin",
        "xmlid": "SUBARU_5EAT_91A0217300", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB4365", "caseid": "Q0A", "year": "Unknown",
        "market": "EDM", "submodel": "91A0217300 (EDM)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 44, "SlipThreshold": 48, "RefSpeedBaseline": 48, "PressureB": 44, "PressureC": 44, "ShiftStageD": 44, "PressureThresholdE": 44, "CAN511Threshold": 48, "ShiftCorrection": 48, "SignalResponseCurves": 48},
    },
    {
        "id": "91A0217400", "rom_file": "91A0217400_MB4372_A61022.bin",
        "xmlid": "SUBARU_5EAT_91A0217400", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB4372", "caseid": "Q3M", "year": "Unknown",
        "market": "EDM", "submodel": "91A0217400 (EDM)", "filesize": "512kb",
        "offsets": {"SpeedTrimA": 44, "SlipThreshold": 48, "RefSpeedBaseline": 48, "PressureB": 44, "PressureC": 44, "ShiftStageD": 44, "PressureThresholdE": 44, "CAN511Threshold": 48, "ShiftCorrection": 48, "SignalResponseCurves": 48},
    },
    {
        "id": "91A1207300", "rom_file": "91A1207300_MB4364.bin",
        "xmlid": "SUBARU_5EAT_91A1207300", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB4364", "caseid": "QZ9", "year": "Unknown",
        "market": "EDM", "submodel": "91A1207300 (EDM)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 44, "SlipThreshold": 48, "RefSpeedBaseline": 48, "PressureB": 44, "PressureC": 44, "ShiftStageD": 44, "PressureThresholdE": 44, "CAN511Threshold": 48, "ShiftCorrection": 48, "SignalResponseCurves": 48},
    },
    {
        "id": "91FE207100", "rom_file": "91FE207100_MB436L_AG802_5EAT_LGT05USDM.bin",
        "xmlid": "SUBARU_5EAT_91FE207100", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB436L", "caseid": "Q2Z", "year": "2005",
        "market": "USDM", "submodel": "91FE207100 (USDM Legacy GT 2005)",
        "filesize": "384kb",
        "offsets": {"SpeedTrimA": 144, "SlipThreshold": 148, "RefSpeedBaseline": 148, "PressureB": 144, "PressureC": 144, "ShiftStageD": 144, "PressureThresholdE": 144, "CAN511Threshold": 148, "ShiftCorrection": 148, "SignalResponseCurves": 148},
    },
    {
        "id": "AAD1A06000", "rom_file": "AAD1A06000.bin",
        "xmlid": "SUBARU_5EAT_AAD1A06000", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB4402", "caseid": "Q0H", "year": "Unknown",
        "market": "JDM", "submodel": "AAD1A06000 (JDM)", "filesize": "512kb",
        "offsets": {"SpeedTrimA": 162, "SlipThreshold": 168, "RefSpeedBaseline": 168, "PressureB": 164, "PressureC": 164, "ShiftStageD": 164, "PressureThresholdE": 164, "CAN511Threshold": 168, "ShiftCorrection": 168, "SignalResponseCurves": 168},
    },
]


def build_romid(profile):
    return f"""  <romid>
   <xmlid>{profile['xmlid']}</xmlid>
   <internalidaddress>0x8008</internalidaddress>
   <internalidstring>{profile['internalidstring']}</internalidstring>
   <caseid>{profile['caseid']}</caseid>
   <ecuid>{profile['id']}</ecuid>
   <version>{profile['id']}</version>
   <year>{profile['year']}</year>
   <market>{profile['market']}</market>
   <make>Subaru</make>
   <model>5EAT TCU</model>
   <submodel>{escape(profile['submodel'])}</submodel>
   <transmission>5EAT</transmission>
   <memmodel>M32R</memmodel>
   <flashmethod>None</flashmethod>
   <filesize>{profile['filesize']}</filesize>
  </romid>
  <!-- RomRaider fixes the checksum itself on save. The 5EAT algorithm is a
       32-bit big-endian two's-complement additive sum stored twice at 0x8000
       and 0x8004, over a region that is NOT the same in every image - see
       ChecksumSUBARUTCU, which detects it per ROM. Requires the patched build
       in romraider-5eat/; stock RomRaider has no manager of this type and will
       warn that it cannot find one. -->
  <checksum type="subarutcu" />"""

# Kept out of the romid banner fields on purpose (they're shown in RomRaider's
# compact top banner alongside the category tree, and long strings there get
# cut off — user feedback after first seeing it in the real UI). Checked how a
# real definition (CarBerryROM, github.com/Crowley2012/SubaruTuning) handles
# this: there's no dedicated "notes" mechanism in RomRaider's schema at all —
# just an ordinary table with a rich <description>. So: ONE single locked,
# non-editable table entry holding everything as one block of text, not
# several small tables (which just looked like clutter — user feedback).
INFO_README = (
    "Subaru 5EAT TCU (5-speed automatic transmission control unit), Mitsubishi/"
    "Renesas M32R CPU.\n\n"
    "Firmware: 91D1206000 (MB431M / R9H)\n\n"
    "Origin: JDM TCU, MCU wa12212953www (M32R, 144-pin, 384KB). Most likely a "
    "2003-2004 JDM Legacy — the market is stated by the person who dumped it, "
    "but the exact year/model is NOT confirmed (the unit had no housing or "
    "part-number label). Note this is NOT the 05-06 USDM TCU, which uses a "
    "different MCU.\n\n"
    "Confirmed: table addresses, DTC list, checksum, gear ratios (raw/1024), "
    "Confirmed conversions: gear ratios (raw/1024), engine speed (raw/8), "
    "temperature (raw-40 degC), vehicle speed (km/h), accelerator pedal angle "
    "(raw/255 = 0-100%). Anything left as \"raw\" has no confirmed conversion. "
    "Pressure units are NOT confirmed and are not stored in the ROM. "
    "See docs/TECHNICAL-NOTES.md for detail.\n\n"
    "REQUIRES RomRaider 1.0.0 or later. The shift schedule and record curves are "
    "3D tables; RomRaider 0.8.2 reports \"There was an error loading table\" for "
    "them.\n\n"
    "This is a static file editor only — cannot connect live to the vehicle "
    "through RomRaider. Run tools/checksum.py after any edit, before flashing."
)


def build_info_table_xml(profile):
    # type="1D" was the wrong choice — RomRaider shows a 1D table's raw stored
    # value as its headline content (byte at 0x008008 is ASCII 'M' = 0x4D = 77
    # decimal — hence the confusing bare "77" the user saw), with the
    # description only secondary. A Switch table displays its STATE NAME
    # instead, so give it exactly one state matching the real, known, never-
    # edited byte there, so the readable label is what actually shows up.
    ident = f"{profile['id']}  (cal ID {profile['internalidstring']}, "
    ident += f"{profile['market']}, {profile['filesize']})"
    desc = escape("Firmware: " + ident + "\n\n" + INFO_README)
    return f"""  <table type="Switch" name="Read This First" category="Info" storageaddress="0x008008" sizey="1" locked="true">
   <description>{desc}</description>
   <state name="(see description below)" data="4D" />
  </table>"""

HEADER_COMMENT = """<!--
  5EAT TCU (Subaru, M32R CPU) — RomRaider static table definition.
  GENERATED by tools/generate_romraider_def.py — regenerate from there
  rather than hand-editing. Full technical derivation in docs/TECHNICAL-NOTES.md.

  Static file editor only — cannot connect live to the vehicle through
  RomRaider (different CPU/protocol family than supported engine ECUs).
  After editing, run tools/checksum.py's fix_checksum() before flashing —
  RomRaider's automatic checksum fix does not know this ROM's algorithm.
  Confirmed units: gear ratios (/1024), engine speed (/8), temperature
  (-40 C), vehicle speed (km/h), accelerator angle (raw/255). Anything
  still shown as "raw" has no confirmed conversion; it is the real
  stored value, just unlabelled. Pressure units are NOT confirmed.
-->"""


def build_table_xml(family, index, header_addr, base_addr=None):
    if base_addr is None:
        base_addr = header_addr
    n, axis_addr, data_addr = table_addrs(header_addr)

    # "per_table" lets a family hold several standalone tables that don't share
    # a single name/description template (e.g. SignalResponseCurves, where each
    # entry has a genuinely different confirmed X-input) — override the
    # family-level fields with the per-address ones when present.
    overrides = family.get("per_table", {}).get(base_addr, {})
    eff = dict(family)
    eff.update(overrides)

    if "name" in overrides:
        base_name = overrides["name"]
    else:
        base_name = family["name_template"].format(i=index)
    name = escape(base_name)
    desc_template = eff["description"]
    desc = escape(desc_template.format(i=index) if "{i}" in desc_template else desc_template)
    category = escape(family["category"])
    value_label = escape(eff.get("value_label", family["value_label"]))
    axis_name = escape(f'{base_name} ({eff.get("axis_label", "")})')

    # Axis scaling defaults to plain raw; families with a structurally-motivated
    # (but still UNCONFIRMED) estimated scale can override via these keys — see
    # docs/TECHNICAL-NOTES.md for the reasoning behind any non-raw axis_units used below.
    axis_units = escape(eff.get("axis_units", "raw"))
    axis_expr = escape(eff.get("axis_expr", "x"))
    axis_to_byte = escape(eff.get("axis_to_byte", "x"))
    axis_format = eff.get("axis_format", "0")

    value_storagetype = eff.get("value_storagetype", "uint16")

    # Some families store a FIXED-POINT value: every stored number, in every
    # firmware, is an exact multiple of a power of two, so the low bits are
    # fractional and the calibrator entered whole units. tools/detect_fixed_point.py
    # proves that from the ROM alone. Showing raw there is actively unhelpful - a
    # cell reading 19456 where 76 was typed cannot be edited sensibly - so the scale
    # is applied even where the physical QUANTITY is still unknown, and the label
    # says exactly that rather than inventing a unit.
    value_expr = escape(eff.get("value_expr", "x"))
    value_to_byte = escape(eff.get("value_to_byte", "x"))
    value_format = eff.get("value_format", "0")
    return f"""  <table type="2D" name="{name}" category="{category}" storagetype="{value_storagetype}" endian="big" storageaddress="0x{data_addr:06X}" sizex="{n}" userlevel="1">
   <scaling units="{value_label}" expression="{value_expr}" to_byte="{value_to_byte}" format="{value_format}" fineincrement="1" coarseincrement="16" />
   <table type="X Axis" name="{axis_name}" storageaddress="0x{axis_addr:06X}" storagetype="uint16" endian="big">
    <scaling units="{axis_units}" expression="{axis_expr}" to_byte="{axis_to_byte}" format="{axis_format}" fineincrement="16" coarseincrement="256" />
   </table>
   <description>{desc}</description>
  </table>"""


def verify_profile(profile, rom_bytes):
    """
    Re-derive every address for this profile and check it against the target
    ROM's own embedded count field. Returns (checked, errors).

    This is the guard that makes the offset table safe: a family whose delta is
    wrong still produces a plausible-looking address, and the resulting XML
    would silently read and write the wrong bytes. Checking the count the ROM
    itself stores catches that.
    """
    errors = []
    checked = 0

    def u16_at(off):
        if off + 2 > len(rom_bytes):
            return None
        return struct.unpack(">H", rom_bytes[off:off + 2])[0]

    hyst = HYSTERESIS_BY_ROM.get(profile["id"])
    for c in HYSTERESIS_CURVES:
        if profile.get("base") is None:
            a, r = c["addr"], c["rows"]
        elif hyst and f"0x{c['addr']:06X}" in hyst:
            m = hyst[f"0x{c['addr']:06X}"]; a, r = m["addr"], m["rows"]
        else:
            continue
        checked += 1
        term = u16_at(a + r * 8)
        if term != 0xFFFF:
            errors.append(f"{c['name']} @ 0x{a:06X}: expected 0xFFFF "
                          f"after {r} rows, got {term}")

    for cname, c in SHIFT_CURVES_BY_ROM.get(profile["id"], {}).items():
        checked += 1
        term = u16_at(c["addr"] + c["rows"] * 8)
        if term != 0xFFFF:
            errors.append(f"{cname} @ 0x{c['addr']:06X}: expected 0xFFFF terminator "
                          f"after {c['rows']} rows, got {term}")

    for family in FAMILIES:
        if (profile.get("base") is not None and family["id"] in OPTIONAL_FAMILIES
                and family["id"] not in profile["offsets"]):
            continue
        delta = profile["offsets"].get(family["id"], 0)
        for base_addr in family["headers"]:
            want = u16(base_addr)                 # count in the BASE rom
            got = u16_at(base_addr + delta)       # count in THIS rom
            checked += 1
            if got != want:
                errors.append(f"{family['id']} @ 0x{base_addr + delta:06X}: "
                              f"count {got} != expected {want}")
    return checked, errors


# ATF temperature blend window, one pair of bytes per firmware. All seven solenoid
# channels interpolate their target pressure across this window, so it is a single
# global tunable rather than anything per-gear. Addresses are per firmware and come
# from tools/extract_atf_blend.py; see FINDINGS section 29c.
ATF_BLEND = {}
_atf_blend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "atf_blend.json")
if os.path.exists(_atf_blend_path):
    with open(_atf_blend_path, encoding="utf-8") as _fh:
        ATF_BLEND = json.load(_fh)


ATF_BLEND_DESC = (
    "ATF TEMPERATURE BLEND WINDOW. Below the first temperature the transmission uses "
    "its cold calibration for solenoid target pressure; above the second it uses the "
    "warm one; between them it interpolates linearly between the two.\n\n"
    "This is not per-gear or per-solenoid - all seven solenoid channels read the same "
    "pair, so widening or narrowing the window changes when every clutch and brake "
    "hands over from cold to warm behaviour.\n\n"
    "Stock is 15 C to 135 C in every firmware examined. Raising the lower figure keeps "
    "cold-ATF pressures in use for longer; lowering the upper figure reaches full warm "
    "behaviour sooner.\n\n"
    "Confirmed by following all seven solenoid drivers in the decompiled firmware, "
    "which interpolate on exactly these two bytes against the ATF reading."
)


def build_atf_blend_xml(profile):
    """The two blend breakpoints as a 2-cell table, or None if not known."""
    entry = ATF_BLEND.get(profile["id"])
    if not entry:
        return None
    lo = entry["lo_addr"]
    if entry["hi_addr"] != lo + 1:
        return None          # only emit when the pair really is adjacent
    return f"""  <table type="2D" name="ATF Blend Window" category="Transmission - Sensor Calibration" storagetype="uint8" endian="big" storageaddress="0x{lo:06X}" sizex="2" userlevel="1">
   <scaling units="C (ATF temperature)" expression="x-40" to_byte="x+40" format="0" fineincrement="1" coarseincrement="5" />
   <table type="X Axis" name="ATF Blend Window (breakpoint)" storageaddress="0x{lo:06X}" storagetype="uint8" endian="big">
    <scaling units="1 = cold limit, 2 = warm limit" expression="x" to_byte="x" format="0" fineincrement="1" coarseincrement="1" />
   </table>
   <description>{escape(ATF_BLEND_DESC)}</description>
  </table>"""


def build_rom_block(profile, rom_bytes, is_base):
    """Full table definitions for the base ROM; address overrides for derived."""
    global data
    saved, data = data, rom_bytes            # table_addrs()/extract_dtc_records() read `data`
    try:
        off = profile["offsets"]
        # Every profile is emitted STANDALONE. RomRaider's <rom base="..."> would
        # otherwise inherit the base ROM's scalars and DTC switches into firmwares
        # where those addresses are simply wrong -- verified by loading a derived
        # ROM through RomRaider's own parser and finding 24 DTC tables on a
        # firmware that has 11, at base-ROM addresses.
        parts = [" <rom>", build_romid(profile), ""]
        total = 0

        parts.append("  <!-- ============ Info ============ -->")
        parts.append(build_info_table_xml(profile))
        parts.append("")
        total += 1

        blend = build_atf_blend_xml(profile)
        if blend:
            parts.append("  <!-- ============ ATF Blend Window ============ -->")
            parts.append(blend)
            parts.append("")
            total += 1

        for family in FAMILIES:
            if not is_base and family["id"] in OPTIONAL_FAMILIES and family["id"] not in off:
                continue
            d = off.get(family["id"], 0)
            parts.append(f"  <!-- ============ {family['category']} ============ -->")
            for i, base_addr in enumerate(family["headers"], start=1):
                parts.append(build_table_xml(family, i, base_addr + d, base_addr))
                parts.append("")
                total += 1

        # Only emit arrays/scalars whose address is verified for THIS firmware:
        # the base ROM, or a derived one that declares an explicit offset.
        for arr in DIRECT_ARRAYS:
            if not is_base and arr["id"] not in off:
                continue
            a = dict(arr); a["addr"] = arr["addr"] + off.get(arr["id"], 0)
            parts.append(build_direct_array_xml(a))
            parts.append("")
            total += 1

        for scalar in SCALARS:
            if not is_base and scalar["id"] not in off:
                continue
            sc = dict(scalar); sc["addr"] = scalar["addr"] + off.get(scalar["id"], 0)
            parts.append(build_scalar_xml(sc))
            parts.append("")
            total += 1

        hyst = HYSTERESIS_BY_ROM.get(profile["id"])
        if is_base or hyst:
            parts.append("  <!-- ============ Record-format curves ============ -->")
            for c in HYSTERESIS_CURVES:
                if is_base:
                    parts.append(build_hyst_curve_xml(c))
                else:
                    m = hyst.get(f"0x{c['addr']:06X}")
                    if not m:
                        continue
                    cc = dict(c); cc["addr"] = m["addr"]; cc["rows"] = m["rows"]
                    parts.append(build_hyst_curve_xml(cc))
                parts.append("")
                total += 1

        curves = SHIFT_CURVES_BY_ROM.get(profile["id"], {})
        if curves:
            if is_base:
                parts.append("  <!-- ============ Transmission - Shift Schedule ============ -->")
            # One table, not one per curve. Eight strips of numbers was the single
            # most-reported problem with this definition; the shift schedule is one
            # thing and belongs in one table.
            modes = SHIFT_MODES.get(profile["id"])
            groups = modes["groups"] if modes else []
            if groups:
                # One complete schedule per operating condition. Condition 1 is the
                # one this definition used to ship on its own.
                for n, g in enumerate(groups, 1):
                    m = build_shift_map_xml(g["curves"], u16, suffix=n,
                                            total=len(groups))
                    if m is None:
                        raise SystemExit(f"{profile['id']}: condition {n} map "
                                         f"could not be built")
                    parts.append(m)
                    parts.append("")
                    total += 1
            else:
                shift_map = build_shift_map_xml(curves, u16)
                if shift_map is None:
                    raise SystemExit(f"{profile['id']}: shift curves present but the "
                                     f"map could not be built")
                parts.append(shift_map)
                parts.append("")
                total += 1

        dsp = DOWNSHIFT_PRESSURE.get(profile["id"])
        if dsp:
            if is_base:
                parts.append("  <!-- ======= Downshift pressure and ramp timing ======= -->")
            for tbl in build_downshift_xml(dsp):
                parts.append(tbl)
                parts.append("")
                total += 1

        lpt = LINE_PRESSURE_TARGETS.get(profile["id"])
        if lpt:
            if is_base:
                parts.append("  <!-- ======= Line pressure targets (torque -> kPa) ======= -->")
            for i, m in enumerate(lpt["maps"], 1):
                # Re-check in THIS image rather than trusting the extract: the map
                # must still end with the 0xFFFF terminator where the row count says.
                end = m["addr"] + m["rows"] * 8
                if u16(end) != 0xFFFF:
                    raise SystemExit(
                        "%s: line pressure target %d at 0x%06X does not end with "
                        "0xFFFF after %d records" % (profile["id"], i, m["addr"],
                                                     m["rows"]))
                parts.append(build_line_pressure_target_xml(i, m))
                parts.append("")
                total += 1

        dtc = DTC_TABLE_BY_ROM.get(profile["id"])
        if dtc:
            if is_base:
                parts.append("  <!-- ============ Transmission - Diagnostics ============ -->")
            # Re-check the table really is here in THIS image rather than trusting
            # the extracted address: the first code must decode to a plausible
            # P-number, which garbage will not.
            first = u16(dtc["addr"])
            if not (0x0700 <= first <= 0x1899
                    and (first & 0xF) <= 9 and ((first >> 4) & 0xF) <= 9):
                raise SystemExit(
                    "%s: DTC table at 0x%06X does not start with a valid P-code "
                    "(found 0x%04X)" % (profile["id"], dtc["addr"], first))
            for tbl in build_dtc_tables_xml(dtc):
                parts.append(tbl)
                parts.append("")
                total += 1

        pcurves = PRESSURE_CURVES_BY_ROM.get(profile["id"], [])
        if pcurves:
            if is_base:
                parts.append("  <!-- ============ Transmission - Line Pressure ============ -->")
            for i, c in enumerate(pcurves, 1):
                # Re-derive the record count from the ROM rather than trusting the
                # extracted JSON: the terminating breakpoint is 0xFF00, so if the
                # table has moved or resized in this firmware the count will not
                # land on it and generation must fail loudly.
                end = c["addr"] + (c["rows"] - 1) * 4
                if u16(end) != 0xFF00:
                    raise SystemExit(
                        f"{profile['id']}: line pressure curve {i} at "
                        f"0x{c['addr']:06X} does not end with the 0xFF00 sentinel "
                        f"after {c['rows']} records (found 0x{u16(end):04X})")
                parts.append(build_pressure_curve_xml(i, c))
                parts.append("")
                total += 1

        parts.append(" </rom>")
        return parts, total, 0
    finally:
        data = saved


def main():
    parts = ["<roms>", HEADER_COMMENT, ""]
    summary = []

    for idx, profile in enumerate(ROM_PROFILES):
        path = os.path.join(here, "..", "rom", profile["rom_file"])
        if not os.path.exists(path):
            print(f"  skipping {profile['id']}: {profile['rom_file']} not present")
            continue
        rom_bytes = open(path, "rb").read()

        checked, errors = verify_profile(profile, rom_bytes)
        if errors:
            print(f"ERROR: {profile['id']} address verification failed:")
            for e in errors:
                print("   -", e)
            raise SystemExit(1)

        block, total, n_dtc = build_rom_block(profile, rom_bytes, is_base=(idx == 0))
        parts.extend(block)
        parts.append("")
        summary.append((profile["id"], profile["internalidstring"], total, n_dtc, checked))

    parts.append("</roms>")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")

    print(f"Wrote {out_path}")
    for rid, cal, total, n_dtc, checked in summary:
        print(f"  {rid} (cal ID {cal}): {total} tables "
              f"({n_dtc} DTC), {checked} addresses verified against the ROM")


if __name__ == "__main__":
    main()
