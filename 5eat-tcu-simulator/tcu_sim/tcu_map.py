"""Live-watch map of TCU RAM — symbol -> address -> meaning, from the decoded
8AF0237300 firmware. This is what turns SSM raw reads into a readable dashboard.

Each entry: name, addr, size (bytes), fmt, and src (firmware provenance). fmt is
how to render the raw value:
  u8/u16/s8/s16  integer (optionally scaled: value*scale + off, with unit)
  hex8/hex16     hex
  bits8          bit-flag byte (labels give bit meanings, LSB first)

CONFIDENCE: addresses and roles come straight from the firmware trace and are
solid; absolute engineering SCALES (°C, kPa, rpm) for a few analog shadows are
best-effort until cross-checked against a live TCU / SSM param defs, and are
marked unit="raw" where unproven. Nothing here is guessed from thin air.

M32R is big-endian: a 16-bit value at addr is (mem[addr]<<8)|mem[addr+1].
"""
from __future__ import annotations
from typing import List, Dict

# bit-flag label sets (LSB=bit0 first), from the dtc_inputs_grp* collectors
_GEAR_RANGE_BITS = ["gear1 ratio", "gear2 ratio", "gear3 ratio", "gear4 ratio",
                    "gear5 ratio", "", "shift-complete", ""]
_MEMBOX_BITS = ["mbox b0", "mbox b1", "mbox b2", "mbox b3",
                "mbox b4", "mbox b5", "mbox b6", "MEMORY-BOX COMM FAULT"]

WATCH: List[Dict] = [
    # ---- Range & gear ---------------------------------------------------------
    dict(name="Range / selector code", addr=0x8047F3, size=1, fmt="hex8",
         group="Range & gear", src="reflash gate: 0x84=Park"),
    dict(name="Park interlock flag", addr=0x804955, size=1, fmt="u8",
         group="Range & gear", src="reflash gate DAT_00804955==1 in Park"),
    dict(name="Gear index (derived)", addr=0x8050F8, size=1, fmt="u8",
         group="Range & gear", src="ratio monitor FUN@0x21241"),

    # ---- Speeds ---------------------------------------------------------------
    dict(name="Input/turbine speed", addr=0x80468C, size=2, fmt="u16", unit="raw",
         group="Speeds", src="FUN_00028f88(0x0b)"),
    dict(name="Output shaft speed", addr=0x80468E, size=2, fmt="u16", unit="raw",
         group="Speeds", src="FUN_00028f88(0x0d)"),
    dict(name="Engine RPM shadow", addr=0x8047C6, size=2, fmt="u16", unit="raw",
         group="Speeds", src="CAN 0x410 decode; failsafe 0x131"),

    # ---- ATF & thermal (raw A/D shadows: RAM = 0x804C18 + 2*channel) ----------
    dict(name="ATF sensor 1 (A/D ch11)", addr=0x804C2E, size=2, fmt="u16", unit="raw",
         group="ATF & thermal", src="ADC_CHANNEL_MAP ch11"),
    dict(name="ATF sensor 2 (A/D ch13)", addr=0x804C32, size=2, fmt="u16", unit="raw",
         group="ATF & thermal", src="ADC_CHANNEL_MAP ch13"),
    dict(name="Supply / ignition V (ch14)", addr=0x804C34, size=2, fmt="u16", unit="raw",
         group="ATF & thermal", src="ADC_CHANNEL_MAP ch14"),
    dict(name="ATF temp (ctrl index)", addr=0x804813, size=1, fmt="u8", unit="raw",
         group="ATF & thermal", src="pressure-loop temp index"),
    dict(name="ATF temp (DTC)", addr=0x804816, size=1, fmt="u8", unit="raw",
         group="ATF & thermal", src="ATF DTC 0x13/0x14 monitor"),

    # ---- Line pressure & solenoid feedback -----------------------------------
    dict(name="Line-press solenoid duty", addr=0x80504C, size=1, fmt="u8", unit="raw",
         group="Line pressure", src="pressure_ctrl_loop clamp out"),
    dict(name="Duty stage", addr=0x80505A, size=1, fmt="u8", unit="raw",
         group="Line pressure", src="pressure_ctrl_loop duty stage"),
    dict(name="Press feedback A (ch)", addr=0x804A9A, size=2, fmt="u16", unit="raw",
         group="Line pressure", src="solenoid pressure A/D"),
    dict(name="Press feedback B (ch)", addr=0x804A9C, size=2, fmt="u16", unit="raw",
         group="Line pressure", src="solenoid pressure A/D"),

    # ---- Memory box (control-valve-body serial link; DTC P1601 = index 0x34) --
    dict(name="Mbox read state", addr=0x804D6B, size=1, fmt="u8",
         group="Memory box", src="state machine (5-8 read, 0x18 fault)"),
    dict(name="Mbox retry counter", addr=0x804D6C, size=1, fmt="u8",
         group="Memory box", src="vs cal 0x130e4 before fault"),
    dict(name="Mbox frame step", addr=0x804D6E, size=1, fmt="u8",
         group="Memory box", src="0..0x3a bitbang step index"),
    dict(name="Mbox last word in", addr=0x804D70, size=2, fmt="hex16",
         group="Memory box", src="P1.2 readback accumulator"),
    dict(name="Mbox signature", addr=0x804DAE, size=2, fmt="hex16",
         group="Memory box", src="expect 0x5555"),
    dict(name="Mbox/learned validity", addr=0x8053C2, size=2, fmt="hex16",
         group="Memory box", src="0xFFFF init, set on valid read"),
    dict(name="Mbox comm flags", addr=0x8050EA, size=1, fmt="bits8",
         group="Memory box", labels=_MEMBOX_BITS,
         src="bit7 = P1601 comm fault (grp11)"),

    # ---- DTC condition flags (dtc_inputs_grp* sources) ------------------------
    dict(name="Elec fault flags A", addr=0x804118, size=1, fmt="bits8",
         group="DTC flags", src="dtc_inputs grp0/1/5/8/9"),
    dict(name="Elec fault flags B", addr=0x80411C, size=1, fmt="bits8",
         group="DTC flags", src="dtc_inputs grp1/5/6/7/9"),
    dict(name="Elec fault flags C", addr=0x804120, size=1, fmt="bits8",
         group="DTC flags", src="dtc_inputs grp0/1/6/11"),
    dict(name="Elec fault flags D", addr=0x804124, size=1, fmt="bits8",
         group="DTC flags", src="dtc_inputs grp7/10"),
    dict(name="Gear/shift DTC flags", addr=0x8050EB, size=1, fmt="bits8",
         group="DTC flags", labels=_GEAR_RANGE_BITS,
         src="ratio/shift monitor grp1/2/7"),

    # ---- Diagnostics summary --------------------------------------------------
    dict(name="Active DTC count", addr=0x8052D8, size=1, fmt="u8",
         group="Diagnostics", src="dtc_count_active_stored"),
    dict(name="Stored DTC count", addr=0x8052D5, size=1, fmt="u8",
         group="Diagnostics", src="dtc_count_active_stored"),
    dict(name="SSM/reflash status", addr=0x805261, size=1, fmt="bits8",
         group="Diagnostics",
         labels=["rx busy", "req pending", "write ok", "reflash mode",
                 "special cmd", "", "", "power-ok"],
         src="diag flags DAT_00805261"),

    # ---- SSM-index reads: firmware-portable. The TCU routes indices < 0x200
    # through its own Select Monitor translation table, so these resolve correctly
    # on any supported image without per-firmware RAM addresses. ATF conversion is
    # x-50 C (community RE + RomRaider logger, cross-checked vs CAN 0x422). --------
    dict(name="ATF Sensor 1 (SSM 0x56)", addr=0x56, size=1, fmt="u8",
         scale=1.0, off=-50.0, unit="°C",
         group="SSM diagnostics", src="SSM idx 0x56, x-50 (oil pan)"),
    dict(name="ATF Sensor 2 (SSM 0x5A)", addr=0x5A, size=1, fmt="u8",
         scale=1.0, off=-50.0, unit="°C",
         group="SSM diagnostics", src="SSM idx 0x5A, x-50 (TC outlet)"),
]

# DTC status bitfields over SSM. Firmware-portable indices, verified against the
# in-ROM SSM table (FINDINGS 91): index -> DTC status block current/confirmed byte.
_DTC_SSM = [  # (group, current_idx, confirmed_idx)
    (0, 0x9C, 0xBC), (1, 0x9D, 0xBD), (2, 0x9E, 0xBE), (3, 0xA6, 0xC6),
    (4, 0xF0, 0xF4), (5, 0xF1, 0xF5), (6, 0xF2, 0xF6), (7, 0xF3, 0xF7),
    (8, 0x123, 0x12B), (9, 0x124, 0x12C), (10, 0x125, 0x12D), (11, 0x162, 0x167),
]
for _g, _cur, _conf in _DTC_SSM:
    WATCH.append(dict(name="DTC Group %d Current" % _g, addr=_cur, size=1, fmt="bits8",
                      group="SSM diagnostics", src="SSM DTC status (current bits)"))
    WATCH.append(dict(name="DTC Group %d Confirmed" % _g, addr=_conf, size=1, fmt="bits8",
                      group="SSM diagnostics", src="SSM DTC status (confirmed bits)"))

GROUP_ORDER = ["Range & gear", "Speeds", "ATF & thermal", "Line pressure",
               "Memory box", "DTC flags", "Diagnostics", "SSM diagnostics"]


def all_byte_addrs(watch: List[Dict] = WATCH) -> List[int]:
    """Every distinct byte address the watch-list needs, in a stable order, so the
    monitor can pull them in one 0xA8 request and slice results back per symbol."""
    seen: Dict[int, None] = {}
    for e in watch:
        for a in range(e["addr"], e["addr"] + e["size"]):
            seen.setdefault(a, None)
    return list(seen.keys())


def _raw_value(e: Dict, mem: Dict[int, int]) -> int | None:
    v = 0
    for k in range(e["size"]):
        b = mem.get(e["addr"] + k)
        if b is None:
            return None
        v = (v << 8) | b            # big-endian
    if e["fmt"].startswith("s"):    # sign-extend
        bits = e["size"] * 8
        if v >= (1 << (bits - 1)):
            v -= (1 << bits)
    return v


def decode(e: Dict, mem: Dict[int, int]) -> Dict:
    """Render one watch entry from a {addr: byte} memory dict. Returns raw value,
    a display string, and (for bit fields) the set flags."""
    v = _raw_value(e, mem)
    out = {"name": e["name"], "group": e["group"], "addr": e["addr"],
           "size": e["size"], "src": e.get("src", ""), "raw": v}
    if v is None:
        out["display"] = "—"
        return out
    fmt = e["fmt"]
    if fmt in ("hex8", "hex16"):
        out["display"] = "0x%0*X" % (e["size"] * 2, v)
    elif fmt == "bits8":
        labels = e.get("labels")
        on = [i for i in range(8) if v & (1 << i)]
        out["display"] = "0x%02X" % v
        out["bits"] = on
        if labels:
            named = [labels[i] for i in on if i < len(labels) and labels[i]]
            if named:
                out["display"] += "  [" + ", ".join(named) + "]"
    else:  # integer, optional scale
        scale = e.get("scale")
        if scale is not None:
            val = v * scale + e.get("off", 0.0)
            out["display"] = "%.1f %s" % (val, e.get("unit", ""))
            out["value"] = round(val, 2)
        else:
            unit = e.get("unit")
            out["display"] = "%d%s" % (v, (" (%s)" % unit if unit and unit != "raw" else ""))
    return out
