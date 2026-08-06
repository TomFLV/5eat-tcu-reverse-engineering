#!/usr/bin/env python3
"""Find the functions that actually decide on a variable, not just touch it.

Reading a variable and acting on it are different things. An initialisation routine
loads pedal position once and stores it; the routine that decides a shift loads it
and then *compares* it. The second is what you want, and telling them apart is a
matter of looking at what follows the load.

For each function - segmented on `rts`, which is where SH-2 ends one - this records:

    reads       loads the address
    compares    a cmp against the loaded value follows within a few instructions
    branches    a conditional branch follows the compare

A function that reads, compares and branches on pedal is making a decision with it.
One that only reads is moving it around.

    python tools/denso_find_users.py <listing> 0xFFFF30FB
    python tools/denso_find_users.py <listing> 0xFFFF30FB --deciding

Combine with tools/denso_emulate.py: this narrows thousands of functions to a
handful, and the emulator then says what each one does.
"""

import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LITERALS = os.path.join(HERE, "denso_literals.json")
OUT = os.path.join(HERE, "denso_users.json")

ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s*_?(\S+)(.*)$")
LOAD = re.compile(r"^mov\.[lw]$")
POOL = re.compile(r"@\(0x([0-9a-f]+),pc\)")

# How far after the load a comparison still counts as acting on it.
REACH = 10


def rom_for(listing):
    stem = os.path.splitext(os.path.basename(listing))[0]
    p = os.path.join(REPO, "rom-denso", stem + ".bin")
    return p if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing")
    ap.add_argument("address", help="RAM address, e.g. 0xFFFF30FB")
    ap.add_argument("--deciding", action="store_true",
                    help="only functions that compare and branch on it")
    ap.add_argument("--show", type=int, default=25)
    args = ap.parse_args()

    rom_path = rom_for(args.listing)
    if not rom_path:
        sys.stderr.write("no ROM image for %s\n" % args.listing)
        return 1
    data = open(rom_path, "rb").read()
    target = int(args.address, 16)

    rows = []
    for line in open(args.listing, encoding="utf-8", errors="replace"):
        m = ROW.match(line.rstrip("\n"))
        if not m or m.group(2).startswith("."):
            continue
        rows.append((int(m.group(1), 16), m.group(2), m.group(3)))

    # Split into functions on rts, keeping the delay slot with the function.
    funcs, start, pending = [], None, False
    bounds = []
    for i, (addr, mnem, _rest) in enumerate(rows):
        if start is None:
            start = i
        if pending:
            bounds.append((start, i))
            start, pending = None, False
        elif mnem == "rts":
            pending = True
    if start is not None:
        bounds.append((start, len(rows) - 1))

    hits = []
    for lo, hi in bounds:
        loads = []
        for i in range(lo, hi + 1):
            addr, mnem, rest = rows[i]
            if not LOAD.match(mnem):
                continue
            p = POOL.search(rest)
            if not p:
                continue
            pool = int(p.group(1), 16)
            size = 4 if mnem == "mov.l" else 2
            if pool + size > len(data):
                continue
            if size == 4:
                val = struct.unpack_from(">I", data, pool)[0]
            else:
                val = struct.unpack_from(">h", data, pool)[0] & 0xFFFFFFFF
            if val == target:
                loads.append(i)
        if not loads:
            continue

        compares = branches = 0
        for i in loads:
            window = rows[i:min(hi + 1, i + REACH)]
            saw_cmp = False
            for _a, mnem, _r in window:
                if mnem.startswith("cmp") or mnem in ("tst", "tst.b"):
                    saw_cmp = True
                    compares += 1
                elif saw_cmp and mnem in ("bt", "bf", "bt/s", "bf/s"):
                    branches += 1
                    break
        hits.append({
            "start": rows[lo][0], "end": rows[hi][0],
            "loads": len(loads), "compares": compares, "branches": branches,
        })

    deciding = [h for h in hits if h["branches"] > 0]
    print("0x%08X is loaded in %d functions; %d compare and branch on it\n"
          % (target, len(hits), len(deciding)))

    show = deciding if args.deciding else hits
    show = sorted(show, key=lambda h: (-h["branches"], -h["loads"]))
    print("%-12s %-12s %6s %8s %8s" % ("function", "ends", "loads", "compares",
                                       "branches"))
    print("-" * 54)
    for h in show[:args.show]:
        print("0x%08X   0x%08X   %5d %8d %8d"
              % (h["start"], h["end"], h["loads"], h["compares"], h["branches"]))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"listing": os.path.basename(args.listing),
                   "address": "%08X" % target,
                   "functions": hits}, fh, indent=1, sort_keys=True)
    print("\n-> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
