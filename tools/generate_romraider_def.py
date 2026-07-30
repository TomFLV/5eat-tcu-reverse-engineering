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
# ---------------------------------------------------------------------------
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
        "category": "Transmission - Slip Detection",
        "name_template": "Gear {i} Slip Detection Threshold",
        "headers": [0x0114A8, 0x0114D2, 0x0114FC, 0x011526, 0x011550],
        "axis_label": "Engine speed",
        "value_label": "raw",
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
        "category": "Transmission - Reference Speed",
        "name_template": "Gear {i} Reference Speed Baseline",
        "headers": [0x0115D0, 0x0115FA, 0x011624, 0x01164E, 0x011678],
        "axis_label": "Engine speed",
        "value_label": "raw",
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
    "Shift point curve, mode 0 (the fully-populated operating mode). Each row is "
    "one segment of a polyline in vehicle-speed / accelerator-angle space: the TCU "
    "shifts when the operating point crosses this line.\n\n"
    "Columns: 1 = speed at the start of the segment, 2 = pedal angle at the start, "
    "3 = speed at the end, 4 = pedal angle at the end. Column 3 of a row repeats "
    "column 1 of the next row, and column 4 repeats column 2 - KEEP THEM IN SYNC "
    "when editing or the curve will break.\n\n"
    "Units are confirmed against the factory shift chart: speed is km/h directly, "
    "pedal angle is raw 0-255 shown here as 0-100%. A pedal value of 255 in the "
    "final row is a max clamp, not a real 100% point.\n\n"
    "Lowering a curve makes that shift happen earlier (at lower speed for a given "
    "pedal); raising it delays the shift."
)


def build_shift_curve_xml(name, addr, rows):
    name = escape(name)
    return f"""  <table type="3D" name="{name}" category="Transmission - Shift Schedule" storageaddress="0x{addr:06X}" storagetype="uint16" endian="big" sizex="4" sizey="{rows}" userlevel="4">
   <scaling units="raw (col 1,3 = km/h; col 2,4 = pedal 0-255)" expression="x" to_byte="x" format="0" fineincrement="1" coarseincrement="8" />
   <description>{escape(SHIFT_DESC)}</description>
  </table>"""



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

HYST_DESC_SUFFIX = (
    "\n\nFormat: each row is one segment, 4 x uint16. Column 1 is the "
    "breakpoint; columns 2-4 are the values interpolated across it. Rows chain "
    "(a row's later columns repeat the next row's earlier ones), so keep them "
    "consistent when editing. The final row is a max clamp.\n\n"
    "Values are raw: no confirmed real-world conversion for this curve."
)


def build_hyst_curve_xml(c, delta=0):
    addr = c["addr"] + delta
    return f"""  <table type="3D" name="{escape(c['name'])}" category="{escape(c['category'])}" storageaddress="0x{addr:06X}" storagetype="uint16" endian="big" sizex="4" sizey="{c['rows']}" userlevel="4">
   <scaling units="raw" expression="x" to_byte="x" format="0" fineincrement="1" coarseincrement="8" />
   <description>{escape(c['desc'] + HYST_DESC_SUFFIX)}</description>
  </table>"""


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
        "offsets": {"SpeedTrimA": 144, "PressureB": 144, "PressureC": 144, "ShiftStageD": 144, "PressureThresholdE": 144, "SlipThreshold": 148, "RefSpeedBaseline": 148, "CAN511Threshold": 148, "SignalResponseCurves": 148},
    },
    {
        "id": "91D0207500", "rom_file": "91D0207500_MB436T_AH572_5EAT_JDM.bin",
        "xmlid": "SUBARU_5EAT_91D0207500", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB436T", "caseid": "Q3E", "year": "Unknown",
        "market": "JDM", "submodel": "91D0207500 (JDM)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 44, "PressureB": 44, "PressureC": 44, "ShiftStageD": 44, "PressureThresholdE": 44, "SlipThreshold": 48, "RefSpeedBaseline": 48, "CAN511Threshold": 48, "SignalResponseCurves": 48},
    },
    {
        "id": "91F0217100", "rom_file": "91F0217100_MB436P_AG810_OBK03USDM.bin",
        "xmlid": "SUBARU_5EAT_91F0217100", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB436P", "caseid": "Q3B", "year": "2003",
        "market": "USDM", "submodel": "91F0217100 (USDM Outback 03)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 144, "PressureB": 144, "PressureC": 144, "ShiftStageD": 144, "PressureThresholdE": 144, "SlipThreshold": 148, "RefSpeedBaseline": 148, "CAN511Threshold": 148, "SignalResponseCurves": 148},
    },
    {
        "id": "ABD1A03100", "rom_file": "ABD1A03100_A61022_LGT_JDM_2005_5EAT.bin",
        "xmlid": "SUBARU_5EAT_ABD1A03100", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB4434", "caseid": "Q1F", "year": "2005",
        "market": "JDM", "submodel": "ABD1A03100 (JDM Legacy GT 2005)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 142, "PressureB": 144, "PressureC": 144, "ShiftStageD": 144, "PressureThresholdE": 144, "SlipThreshold": 148, "RefSpeedBaseline": 148, "CAN511Threshold": 148, "SignalResponseCurves": 148},
    },
    {
        "id": "91D1207900", "rom_file": "[91D1207900-A61022]_31711AG589.bin",
        "xmlid": "SUBARU_5EAT_91D1207900", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB4373", "caseid": "Q3P", "year": "Unknown",
        "market": "JDM", "submodel": "91D1207900 (Hitachi 31711AG589)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 42, "PressureB": 44, "PressureC": 44, "ShiftStageD": 44, "PressureThresholdE": 44, "SlipThreshold": 48, "RefSpeedBaseline": 48, "CAN511Threshold": 48, "SignalResponseCurves": 48},
    },
    {
        "id": "AAD1A07100", "rom_file": "[AAD1A07100-A61022]_31711AJ782.bin",
        "xmlid": "SUBARU_5EAT_AAD1A07100", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB440X", "caseid": "Q2P", "year": "Unknown",
        "market": "JDM", "submodel": "AAD1A07100 (Hitachi 31711AJ782)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 162, "PressureB": 164, "PressureC": 164, "ShiftStageD": 164, "PressureThresholdE": 164, "SlipThreshold": 168, "RefSpeedBaseline": 168, "CAN511Threshold": 168, "SignalResponseCurves": 168},
    },
    {
        "id": "ABD1207000", "rom_file": "[ABD1207000-A61022].bin",
        "xmlid": "SUBARU_5EAT_ABD1207000", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB5300", "caseid": "Q5L", "year": "2006",
        "market": "JDM", "submodel": "ABD1207000 (06 JDM Legacy GT)", "filesize": "384kb",
        "offsets": {"SpeedTrimA": 142, "PressureB": 144, "PressureC": 144, "ShiftStageD": 144, "PressureThresholdE": 144, "SlipThreshold": 148, "RefSpeedBaseline": 148, "CAN511Threshold": 148, "SignalResponseCurves": 148},
    },
    {
        "id": "ACD1207000", "rom_file": "ACD1207000_MB558D01_LGT06_JDM.bin",
        "xmlid": "SUBARU_5EAT_ACD1207000", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB558D01", "caseid": "Q7W", "year": "2006",
        "market": "JDM", "submodel": "ACD1207000 (LGT06 JDM)", "filesize": "512kb",
        "offsets": {"SpeedTrimA": 142, "PressureB": 144, "PressureC": 144, "ShiftStageD": 96, "PressureThresholdE": 144, "SlipThreshold": 100, "RefSpeedBaseline": 100, "CAN511Threshold": 100, "SignalResponseCurves": 100},
    },
    {
        "id": "ADE0236000", "rom_file": "5EAT_ADE0236000.bin",
        "xmlid": "SUBARU_5EAT_ADE0236000", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB562EH", "caseid": "Q8C", "year": "Unknown",
        "market": "Unknown", "submodel": "ADE0236000", "filesize": "512kb",
        "offsets": {"SpeedTrimA": 592, "PressureB": 592, "PressureC": 592,
                    "ShiftStageD": 544, "PressureThresholdE": 592,
                    "SlipThreshold": 548, "RefSpeedBaseline": 548,
                    "CAN511Threshold": 548, "SignalResponseCurves": 548},
    },
    {
        "id": "ACD1A06000", "rom_file": "ACD1A06000_JDM_5EAT_2007_M32176F4V.bin",
        "xmlid": "SUBARU_5EAT_ACD1A06000", "base": "SUBARU_5EAT_91D1206000",
        "internalidstring": "MB558D20", "caseid": "Q6E", "year": "2007",
        "market": "JDM", "submodel": "ACD1A06000 (JDM 2007)", "filesize": "512kb",
        "offsets": {"SpeedTrimA": 142, "PressureB": 144, "PressureC": 144, "ShiftStageD": 96, "PressureThresholdE": 144, "SlipThreshold": 100, "RefSpeedBaseline": 100, "CAN511Threshold": 100, "SignalResponseCurves": 100},
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
  </romid>"""

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

    return f"""  <table type="2D" name="{name}" category="{category}" storagetype="uint16" endian="big" storageaddress="0x{data_addr:06X}" sizex="{n}" userlevel="1">
   <scaling units="{value_label}" expression="x" to_byte="x" format="0" fineincrement="1" coarseincrement="16" />
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
        delta = profile["offsets"].get(family["id"], 0)
        for base_addr in family["headers"]:
            want = u16(base_addr)                 # count in the BASE rom
            got = u16_at(base_addr + delta)       # count in THIS rom
            checked += 1
            if got != want:
                errors.append(f"{family['id']} @ 0x{base_addr + delta:06X}: "
                              f"count {got} != expected {want}")
    return checked, errors


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

        for family in FAMILIES:
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
            for cname in sorted(curves):
                c = curves[cname]
                parts.append(build_shift_curve_xml(cname, c["addr"], c["rows"]))
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
