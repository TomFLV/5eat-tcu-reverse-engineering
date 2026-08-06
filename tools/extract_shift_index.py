#!/usr/bin/env python3
"""Walk the M32R shift table index and name every table it reaches.

The firmware picks a shift schedule with

    index = drive mode offset * 50 + shift lever offset * 10 + gear * 2

and reads the upshift table from one pointer array and the downshift from a second
four bytes after it. That formula, the two mappings it needs, and the naming
convention below are rimwall's, from forum topic 13725 post 393; FINDINGS section 51
verifies all three against the code in `FUN_0004bcd8`.

The definition previously carried eight shift tables, found by pattern scanning.
Walking the index finds **202** in `ACD1A06000`: everything reached through a drive
mode other than the default was invisible to a scan.

Many index slots share the same data - a table used for D and for Manual 5 down to
2 appears at five slots - so each table is named once, listing every state that
reaches it:

    Table_Normal_D5432_1st_Up

    python tools/extract_shift_index.py rom/ACD1A06000_JDM_5EAT_2007_M32176F4V.bin
    python tools/extract_shift_index.py <rom> --json

Writes tools/shift_index.json.
"""

import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "shift_index.json")

# Upshift pointers, then downshift four bytes on. Both are arrays of ROM addresses.
UP_ARRAY = 0x000180E8
DOWN_ARRAY = 0x000180EC

# Internal drive mode value -> (mapped offset, name). From FUN_0004bcd8. Manual
# Mode maps to 4 or 8 depending on bit 7 of 0x8055FC, so it occupies both.
DRIVE_MODES = {
    0x0: (0, "Normal"),
    0x1: (1, "Sport#"),
    0x3: (3, "Unknown3"),
    0x4: (4, "Manual"),
    0x5: (1, "Unknown5"),
    0x6: (5, "Unknown6"),
    0x8: (7, "ATFTempLow"),
    0x9: (8, "Unknown9"),
    0xB: (9, "IMode"),
    0xC: (2, "Slope"),
    0xD: (6, "Kickdown"),
}
MANUAL_ALT = 8  # the other offset Manual Mode can take

# Shift lever offset -> the states that reach it. Offset 0 covers P, N, D *and*
# Manual 5, which is why the first table is D5432 and not D432: one slot serves two
# lever positions. Getting this wrong is easy and shows up immediately against
# rimwall's published example, Table_Normal_D5432_1st_Up.
LEVER_LABEL = {0: "D5", 1: "4", 2: "3", 3: "2", 4: "1"}
LEVER_ORDER = "D5432"

GEARS = ["1st", "2nd", "3rd", "4th", "5th"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args()

    data = open(args.rom, "rb").read()

    # address -> the states that reach it
    tables = {}
    offsets = sorted({o for o, _n in DRIVE_MODES.values()} | {MANUAL_ALT})
    names_for_offset = {}
    for _v, (o, n) in DRIVE_MODES.items():
        names_for_offset.setdefault(o, n)
    names_for_offset.setdefault(MANUAL_ALT, "Manual")

    for dm_off in offsets:
        for lev_off in range(5):
            for gear in range(5):
                index = dm_off * 50 + lev_off * 10 + gear * 2
                for array, direction in ((UP_ARRAY, "Up"), (DOWN_ARRAY, "Down")):
                    at = array + 4 * index
                    if at + 4 > len(data):
                        continue
                    addr = struct.unpack_from(">I", data, at)[0] & 0xFFFFFF
                    if not (0x10000 <= addr < len(data)):
                        continue
                    e = tables.setdefault(addr, {
                        "drive": set(), "levers": set(), "gear": gear,
                        "dir": direction,
                    })
                    e["drive"].add(names_for_offset[dm_off])
                    e["levers"].add(LEVER_LABEL[lev_off])

    named = {}
    for addr, e in tables.items():
        drive = "+".join(sorted(e["drive"]))
        levers = "".join(c for c in LEVER_ORDER if c in "".join(e["levers"]))
        named[addr] = "Table_%s_%s_%s_%s" % (drive, levers or "?",
                                             GEARS[e["gear"]], e["dir"])

    print("%s" % os.path.basename(args.rom))
    print("%d distinct shift tables reached through the index\n" % len(named))
    for addr in sorted(named)[:args.show]:
        print("   0x%06X  %s" % (addr, named[addr]))
    if len(named) > args.show:
        print("   ... %d more" % (len(named) - args.show))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"rom": os.path.basename(args.rom),
                   "tables": {("%06X" % a): named[a] for a in named}},
                  fh, indent=1, sort_keys=True)
    print("\n-> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
