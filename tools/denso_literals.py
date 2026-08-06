#!/usr/bin/env python3
"""Resolve every PC-relative literal load in a Denso listing, from the ROM.

SH-2 cannot build a 32-bit constant in an instruction, so every address the code
uses - RAM variables, calibration table bases, jump targets - is fetched from a
literal pool with mov.l or mov.w @(disp,pc). Reading those pools is how you find
out what any piece of code actually touches.

Ghidra annotates a load only when it has typed the pool entry as data, which on
this image is 21,979 of 34,644 loads. The other 12,665 are not unresolvable - the
listing already carries the absolute pool address in the operand, so the value can
be read straight out of the ROM image. That is what this does, and it covers all of
them.

Each literal is classified by where it points:

    ram     0xFFFF0000 and up          a variable
    table   inside the calibration region  a map the code reads
    code    below the calibration region   a function or jump table
    const   anything else                  a plain number

mov.w literals are sign-extended, because that is how a RAM address in 0xFFFFxxxx
is held in two bytes (section 46).

    python tools/denso_literals.py disasm-denso/Impreza_STI_3.583_JDM2011.asm
    python tools/denso_literals.py <listing> --tables
    python tools/denso_literals.py <listing> --touching 0xFFFF30FB

Writes tools/denso_literals.json.
"""

import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "denso_literals.json")

LOAD = re.compile(
    r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s*_?(mov\.[lw])\s+@\(0x([0-9a-f]+),pc\),(\w+)")

RAM_LO = 0xFFFF0000


def classify(value, romsize, cal_start):
    if value >= RAM_LO:
        return "ram"
    if cal_start <= value < romsize:
        return "table"
    if value < cal_start and value % 2 == 0 and value != 0:
        return "code"
    return "const"


def rom_for(listing):
    stem = os.path.splitext(os.path.basename(listing))[0]
    for folder in ("rom-denso", "rom"):
        p = os.path.join(REPO, folder, stem + ".bin")
        if os.path.exists(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing")
    ap.add_argument("--cal-start", default="0xA0000",
                    help="where calibration data begins (default 0xA0000)")
    ap.add_argument("--tables", action="store_true",
                    help="list calibration tables by how often they are read")
    ap.add_argument("--touching", help="code sites near uses of this RAM address")
    ap.add_argument("--show", type=int, default=25)
    args = ap.parse_args()

    rom_path = rom_for(args.listing)
    if not rom_path:
        sys.stderr.write("no ROM image for %s\n" % args.listing)
        return 1
    data = open(rom_path, "rb").read()
    cal = int(args.cal_start, 16)

    loads = []
    for line in open(args.listing, encoding="utf-8", errors="replace"):
        m = LOAD.match(line.rstrip("\n"))
        if not m:
            continue
        rom = int(m.group(1), 16)
        size = 4 if m.group(2) == "mov.l" else 2
        pool = int(m.group(3), 16)
        if pool + size > len(data):
            continue
        if size == 4:
            val = struct.unpack_from(">I", data, pool)[0]
        else:
            val = struct.unpack_from(">h", data, pool)[0] & 0xFFFFFFFF
        loads.append({"rom": rom, "reg": m.group(4), "pool": pool,
                      "value": val, "kind": classify(val, len(data), cal)})

    kinds = {}
    for l in loads:
        kinds[l["kind"]] = kinds.get(l["kind"], 0) + 1
    print("%d PC-relative literal loads resolved" % len(loads))
    print("   " + ",  ".join("%s %d" % (k, kinds[k]) for k in sorted(kinds)))

    tables = {}
    for l in loads:
        if l["kind"] == "table":
            tables.setdefault(l["value"], []).append(l["rom"])

    if args.tables:
        print("\n%d distinct calibration addresses referenced by code:" % len(tables))
        for v in sorted(tables, key=lambda x: -len(tables[x]))[:args.show]:
            sites = ", ".join("%06X" % s for s in tables[v][:4])
            print("   0x%06X  read from %-3d site(s)   %s" % (v, len(tables[v]), sites))
    elif args.touching:
        target = int(args.touching, 16)
        near = [l for l in loads if l["value"] == target]
        print("\n%d loads of 0x%08X" % (len(near), target))
        for l in near[:args.show]:
            print("   ROM %06X  -> %s" % (l["rom"], l["reg"]))
    else:
        print("\n%d distinct calibration addresses referenced by code" % len(tables))
        print("%d distinct RAM addresses"
              % len({l["value"] for l in loads if l["kind"] == "ram"}))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({
            "listing": os.path.basename(args.listing),
            "rom": os.path.basename(rom_path),
            "loads": len(loads),
            "kinds": kinds,
            "tables": {("%06X" % v): tables[v] for v in tables},
        }, fh, indent=1, sort_keys=True)
    print("\n-> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
