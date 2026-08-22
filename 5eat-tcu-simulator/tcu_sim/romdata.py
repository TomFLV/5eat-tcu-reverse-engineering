"""Per-ROM firmware parameters. Each TCU ROM carries its own calibration; the
simulator loads real values from the selected .bin so it reflects that firmware,
not a hardcoded constant. Today: gear ratios (extracted, verified). Shift maps
are stored as packed polylines and are the next extraction (see notes in chat).

Bring your own ROMs: firmware is not distributed with this tool. Point it at a
folder of .bin files with the TCUSIM_ROM_DIR environment variable, or drop them in
a `roms/` folder next to the app / in the working directory. The selector shows a
year/model name parsed from the file name + part number. With no ROMs found the
simulator falls back to built-in model defaults.
"""
from __future__ import annotations
import os
import re
import struct

from .paths import app_base

_CANDIDATE_DIRS = [
    os.environ.get("TCUSIM_ROM_DIR", ""),
    os.path.join(app_base(), "roms"),
    os.path.join(os.path.dirname(__file__), "roms"),
    os.path.join(os.getcwd(), "roms"),
]

GEAR_RATIO_ADDR = 0x01234C     # uint16 x5, value/1024


def rom_dir() -> str | None:
    for d in _CANDIDATE_DIRS:
        if d and os.path.isdir(d):
            return d
    return None


def _friendly(fname: str) -> str:
    base = fname.rsplit(".", 1)[0]
    low = base.lower()
    model = ("Tribeca" if "tribeca" in low else
             "Forester" if "forester" in low else
             "Impreza STI" if ("impreza" in low or "sti" in low) else
             "Legacy GT" if ("lgt" in low or "legas" in low or "legase" in low or "legacy" in low) else
             "Outback" if "obk" in low else "5EAT")
    region = ("USDM" if "usdm" in low else "JDM" if "jdm" in low else
              "EDM" if "edm" in low else "")
    # a real model year (2003-2015), not a fragment of the part number
    ym = re.search(r"(?<!\d)(20(?:0[3-9]|1[0-5]))(?!\d)", base)
    year = ym.group(1) if ym else ""
    part = base.split("_")[0]
    bits = [model, region, year]
    label = " ".join(b for b in bits if b).strip()
    return "%s  [%s]" % (label, part) if label else part


def has_si_drive(name_or_id: str) -> bool:
    """Heuristic: SI-DRIVE (I / S / S#) shipped on Legacy GT / spec.B / Outback
    XT / turbo models, NOT on the Tribeca 5EAT or plain base units. Filename-based
    and conservative - defaults to False when the model is unclear."""
    low = name_or_id.lower()
    if "tribeca" in low:
        return False
    return any(k in low for k in ("lgt", "legacy", "legas", "legase",
                                  "outback", "obk", "spec", "sti", "forester"))


def list_roms() -> list[dict]:
    d = rom_dir()
    if not d:
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if not fn.lower().endswith(".bin"):
            continue
        try:
            gr = gear_ratios(_read(fn))
        except Exception:
            gr = None
        out.append({"id": fn, "name": _friendly(fn),
                    "ratios": [gr[i] for i in range(1, 6)] if gr else None,
                    "valid_5eat": gr is not None,
                    "si_drive": has_si_drive(fn)})
    return out


def _read(rom_id: str) -> bytes:
    d = rom_dir()
    if not d:
        raise FileNotFoundError("no ROM directory")
    path = os.path.join(d, os.path.basename(rom_id))
    with open(path, "rb") as f:
        return f.read()


def _ratios_at(rom: bytes, addr: int) -> list[float]:
    return [struct.unpack(">H", rom[addr + 2*i: addr + 2*i + 2])[0] / 1024.0 for i in range(5)]


def _plausible(v: list[float]) -> bool:
    # a 5EAT ratio set: descending, 1st ~2.5-4.5, 5th ~0.5-0.95, 4th ~1.0 (direct)
    return (len(v) == 5 and 2.5 < v[0] < 4.6 and 0.5 < v[4] < 0.95
            and 0.90 < v[3] < 1.12 and all(v[i] > v[i+1] for i in range(4)))


def gear_ratios(rom: bytes):
    """Per-ROM gear ratios, or None if this ROM has no recognizable 5EAT ratio
    set (e.g. SH7058 STI / different platform). Tries the known address, then
    signature-scans the cal region for 5 values that actually look like a 5EAT
    set (descending, 1st ~2.5-4.5, 4th = direct ~1.0, 5th ~0.5-0.95)."""
    v = _ratios_at(rom, GEAR_RATIO_ADDR)
    if _plausible(v):
        return {i + 1: round(v[i], 3) for i in range(5)}
    for addr in range(0x10000, min(len(rom) - 10, 0x1E000), 2):
        cand = _ratios_at(rom, addr)
        if _plausible(cand):
            return {i + 1: round(cand[i], 3) for i in range(5)}
    return None                     # not a recognizable 5EAT ratio table


def rom_params(rom_id: str) -> dict:
    rom = _read(rom_id)
    gr = gear_ratios(rom)
    return {"id": rom_id, "name": _friendly(rom_id),
            "gear_ratios": gr, "ratios_valid": gr is not None,
            "si_drive": has_si_drive(rom_id), "size": len(rom)}


def apply_rom(vehicle, rom_id: str) -> dict:
    """Load the selected ROM's real parameters into the vehicle model. If the ROM
    has no recognizable 5EAT ratio table, RESET to the model default (rather than
    leaving whatever the previously-selected ROM set)."""
    from .vehicle import GEAR_RATIOS as DEFAULT
    p = rom_params(rom_id)
    if p["ratios_valid"]:
        vehicle.gear_ratios = dict(p["gear_ratios"])
    else:
        vehicle.gear_ratios = dict(DEFAULT)
    return p
