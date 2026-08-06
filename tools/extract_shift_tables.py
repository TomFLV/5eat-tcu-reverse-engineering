#!/usr/bin/env python3
"""Extract every shift schedule table in an M32R image, named by what reaches it.

The firmware selects a schedule with

    index = drive mode offset * 50 + shift lever offset * 10 + gear * 2

reading the upshift curve from one pointer array and the downshift from a second
four bytes later. The formula, both mappings and the naming convention are
rimwall's, from forum topic 13725 post 393; FINDINGS section 51 verifies them
against `FUN_0004bcd8`.

The definition previously carried eight curves per firmware - drive mode 0 with the
lever in D, found by pattern scanning. Walking the whole index finds around 200 per
image. Everything reached through Sport#, I-Mode, Slope, Kickdown, ATF Temp Low or
Manual was simply never looked at.

The pointer array moves between firmwares, so it is located rather than assumed:
the eight curves already known for an image must all appear in it, which pins it
uniquely.

    python tools/extract_shift_tables.py rom/ACD1A06000_JDM_5EAT_2007_M32176F4V.bin
    python tools/extract_shift_tables.py --all

Writes tools/shift_tables.json, keyed by calibration id, in the same shape as
shift_curves.json so the generator can consume it.
"""

import argparse
import glob
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
KNOWN = os.path.join(HERE, "shift_curves.json")
OUT = os.path.join(HERE, "shift_tables.json")

# Internal drive mode value -> mapped offset, and the name to use. Manual Mode maps
# to 4 or 8 depending on bit 7 of 0x8055FC, so both offsets carry it.
DRIVE = [(0, "Normal"), (1, "Sport#"), (2, "Slope"), (3, "Mode3"), (4, "Manual"),
         (5, "Mode6"), (6, "Kickdown"), (7, "ATFTempLow"), (8, "Manual"),
         (9, "IMode")]
LEVER = {0: "D5", 1: "4", 2: "3", 3: "2", 4: "1"}
LEVER_ORDER = "D5432"
GEARS = ["1st", "2nd", "3rd", "4th", "5th"]

RECORD = 8          # four uint16 per record
MAX_ROWS = 40       # a curve longer than this is a misread, not a calibration


def calid(data):
    """The unit identifier at 0x802A, which is how shift_curves.json is keyed.

    Not the calibration string at 0x8008 - that is a different identifier and
    keying on it silently matches nothing.
    """
    return "".join("%02X" % b for b in data[0x802A:0x802F])


def find_arrays(data, known_addrs):
    """(up_array, down_array), located by requiring the known curves to be in it.

    The array relocates between firmwares - 0x17714 on the base ROM, 0x180E8 on
    ACD1A06000 - so it is found rather than assumed. Every address the definition
    already knows for this image has to appear at an even index, four bytes apart
    from its downshift partner.
    """
    want = set(known_addrs)
    if not want:
        return None, None

    # Index 0 is drive mode 0, lever in D, first gear, upshift - the first curve
    # the definition already knows. Anchoring on that is what distinguishes the
    # real base from a window part-way into the same array: the known addresses
    # appear at both, just at different offsets, and only one has them at the
    # start.
    best = None
    for base in range(0x10000, min(len(data) - 4000, 0x40000), 4):
        first = struct.unpack_from(">I", data, base)[0] & 0xFFFFFF
        if first not in want:
            continue
        hits = 0
        for k in range(0, 100):
            at = base + 4 * k
            if at + 4 > len(data):
                break
            if (struct.unpack_from(">I", data, at)[0] & 0xFFFFFF) in want:
                hits += 1
        if best is None or hits > best[1]:
            best = (base, hits)
    if best is None:
        return None, None
    return best[0], best[0] + 4


def rows_at(data, addr):
    """How many 8-byte records the curve at addr holds.

    A curve is a polyline of [speed, pedal, speed, pedal] records. It ends where
    the speed stops advancing, which is what the terminator amounts to.
    """
    n, prev = 0, -1
    while n < MAX_ROWS:
        at = addr + n * RECORD
        if at + RECORD > len(data):
            break
        a, b, c, _d = struct.unpack_from(">HHHH", data, at)
        if a == 0xFFFF or (a == 0 and b == 0 and c == 0):
            break
        if a < prev:
            break
        prev = a
        n += 1
    return n


def extract(path, known):
    data = open(path, "rb").read()
    cid = calid(data)
    seed = [v["addr"] for v in known.get(cid, {}).values()]
    up, down = find_arrays(data, seed)
    if up is None:
        return cid, None, {}

    tables = {}
    for dm_off, dm_name in DRIVE:
        for lev in range(5):
            for gear in range(5):
                index = dm_off * 50 + lev * 10 + gear * 2
                for array, direction in ((up, "Up"), (down, "Down")):
                    at = array + 4 * index
                    if at + 4 > len(data):
                        continue
                    addr = struct.unpack_from(">I", data, at)[0] & 0xFFFFFF
                    if not (0x10000 <= addr < len(data)):
                        continue
                    e = tables.setdefault(addr, {"drive": set(), "levers": set(),
                                                 "gear": gear, "dir": direction})
                    e["drive"].add(dm_name)
                    e["levers"].add(LEVER[lev])

    out = {}
    for addr, e in tables.items():
        rows = rows_at(data, addr)
        if rows < 2:
            continue
        levers = "".join(c for c in LEVER_ORDER if c in "".join(e["levers"]))
        name = "Shift %s %s %s %s" % ("+".join(sorted(e["drive"])),
                                      levers or "?", GEARS[e["gear"]], e["dir"])
        out[name] = {"addr": addr, "rows": rows}
    return cid, up, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roms", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    known = json.load(open(KNOWN, encoding="utf-8")) if os.path.exists(KNOWN) else {}
    paths = args.roms or sorted(glob.glob(os.path.join(REPO, "rom", "*.bin")))

    result = {}
    print("%-40s %-10s %8s %8s" % ("calibration", "array", "known", "found"))
    print("-" * 70)
    for p in paths:
        cid, up, tables = extract(p, known)
        have = len(known.get(cid, {}))
        if not tables:
            print("%-40s %-10s %8d %8s" % (cid, "-", have, "none"))
            continue
        result[cid] = tables
        print("%-40s 0x%06X %8d %8d" % (cid, up, have, len(tables)))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    total = sum(len(v) for v in result.values())
    print("\n%d tables across %d firmwares -> %s" % (total, len(result), OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
