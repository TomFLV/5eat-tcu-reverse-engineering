#!/usr/bin/env python3
"""Propose a real scale for tables that currently ship as `raw`.

Most remaining raw tables are not unknowable - they are fixed-point numbers whose
divisor nobody has pinned down. This tests each one against the divisors this ROM
family is already known to use and reports where the decoded values land in a
sensible engineering range.

The strongest lead comes from the forum thread (post 184, rimwall), which describes
the line pressure chain:

    CET arrives on CAN 0x412 bytes 3-4. Slip is the ratio of turbine to engine
    speed. A factor is looked up from a table based on slip - about 1.4 at high
    slip (~0.5), about 1.0 at low slip. CET is multiplied by that factor, smoothed,
    then factored again by a lookup on ATF temperature, and the result looks up a
    Line Pressure target.

A multiplier that runs from 1.0 to about 1.4 is a very specific signature. In
fixed point that is 1024..1434 at /1024, or 256..358 at /256. A table whose whole
range sits in one of those windows, ascending, is almost certainly that factor.

This prints CANDIDATES. Nothing here goes into the definition without checking the
consuming code, because a plausible scale that is wrong reads as confirmed - which
is the mistake this project has already made once with pressure units.

    python tools/classify_raw_tables.py
"""

import io
import json
import os
import struct
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
XML = os.path.join(REPO, "definitions", "5eat_tcu_romraider_defs.xml")

# Divisors this family is already known to use, plus the obvious neighbours.
SCALES = [
    ("/1024 (as gear ratio)", 1024.0),
    ("/512", 512.0),
    ("/256", 256.0),
    ("/128", 128.0),
    ("/64", 64.0),
    ("/8 (as engine speed)", 8.0),
]

# What a decoded range has to look like to be worth reporting.
PROFILES = [
    ("multiplier near 1.0-1.5  (slip / ATF-temp factor, post 184)",
     lambda lo, hi: 0.90 <= lo <= 1.10 and 1.10 <= hi <= 2.20),
    ("fraction 0..1            (duty, ratio, blend)",
     lambda lo, hi: 0.0 <= lo <= 0.10 and 0.60 <= hi <= 1.05),
    ("percent 0..100",
     lambda lo, hi: 0.0 <= lo <= 5.0 and 60.0 <= hi <= 105.0),
]


def u16(d, a):
    return struct.unpack(">H", d[a:a + 2])[0]


def s16(d, a):
    return struct.unpack(">h", d[a:a + 2])[0]


def load_rom(cal):
    import glob
    import re
    for f in glob.glob(os.path.join(REPO, "rom", "*.bin")):
        m = re.search(r"[0-9A-Z]{10}", os.path.basename(f).upper())
        if m and m.group(0) == cal:
            return open(f, "rb").read()
    return None


def cells_of(t, d):
    """Every stored value of a table, honouring stride and sparse maps."""
    addr = int(t.get("storageaddress"), 16)
    signed = "int16" in (t.get("storagetype") or "")
    read = (lambda a: s16(d, a)) if signed else (lambda a: u16(d, a))
    out = []

    cm = t.get("cellIndices")
    if cm:
        for v in (int(x) for x in cm.split(",")):
            if v >= 0 and addr + v * 2 + 2 <= len(d):
                out.append(read(addr + v * 2))
        return out

    sx = int(t.get("sizex") or 1)
    sy = int(t.get("sizey") or 1)
    skip = int(t.get("skipCells", "0"))
    n = sx * sy
    if skip:
        for i in range(n):
            a = addr + i * (1 + skip) * 2
            if a + 2 <= len(d):
                out.append(read(a))
    else:
        for i in range(n):
            a = addr + i * 2
            if a + 2 <= len(d):
                out.append(read(a))
    return out


def main():
    root = ET.parse(XML).getroot()
    reported = 0

    for rom_el in root.findall("rom"):
        cal = (rom_el.find("romid").findtext("ecuid") or "").strip()
        d = load_rom(cal)
        if d is None:
            continue
        # One firmware is enough to find candidates; they are checked across the
        # rest before anything is adopted.
        if cal != "91D1206000":
            continue

        print("candidates in %s\n%s" % (cal, "-" * 76))
        for t in rom_el.findall("table"):
            scaling = t.find("scaling")
            if scaling is None or "raw" not in (scaling.get("units") or ""):
                continue
            vals = [v for v in cells_of(t, d) if v not in (0xFFFF,)]
            if len(vals) < 4:
                continue
            lo, hi = min(vals), max(vals)
            if lo == hi:
                continue

            for sname, div in SCALES:
                dlo, dhi = lo / div, hi / div
                for pname, ok in PROFILES:
                    if ok(dlo, dhi):
                        print("  %-46s %s" % (t.get("name")[:46], t.get("category")))
                        print("      raw %d..%d   %s -> %.3f..%.3f   %s"
                              % (lo, hi, sname, dlo, dhi, pname))
                        reported += 1
                        break
                else:
                    continue
                break

    print("\n%d candidate scalings. None adopted - each needs the consuming code\n"
          "checked before it goes in the definition." % reported)


if __name__ == "__main__":
    main()
