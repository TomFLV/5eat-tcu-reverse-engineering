#!/usr/bin/env python3
"""Find which raw tables are stored as fixed-point, from the stored bits alone.

A table whose every value is an exact multiple of 2^k across every firmware has k
unused low bits. That does not happen by accident in a hand-entered calibration: it
means the quantity was entered in whole units and stored with k fractional bits, and
the value the tuner should see is raw / 2^k.

This says nothing about WHAT the quantity is. It is a statement about the storage
format, provable from the ROM, and it is worth shipping on its own - a table reading
19456 where the calibrator typed 76 is unusable, whichever unit 76 is in.

The test is deliberately strict:
  * every value in every firmware must be a multiple of 2^k
  * the table must not be constant, or the result is vacuous
  * at least one value must have bit k set, or a larger k would fit and the
    divisor being reported is not the real one

    python tools/detect_fixed_point.py [--min-values 20]
"""

import argparse
import glob
import os
import struct
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFS = os.path.join(REPO, "definitions", "5eat_tcu_romraider_defs.xml")

RAW_UNITS = ("raw", "", "x")


def cells(t, rom):
    addr = int(t.get("storageaddress"), 16)
    stype = t.get("storagetype", "uint16")
    size = 1 if "8" in stype else 2
    n = int(t.get("sizey") or t.get("sizex") or 1)
    stride = (1 + int(t.get("skipCells") or 0)) * size
    out = []
    for i in range(n):
        a = addr + i * stride
        if a + size > len(rom):
            return []
        out.append(rom[a] if size == 1 else struct.unpack(">H", rom[a:a + 2])[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-values", type=int, default=20,
                    help="skip tables with fewer stored values than this in total")
    args = ap.parse_args()

    root = ET.parse(DEFS).getroot()
    roms = {os.path.basename(f): open(f, "rb").read()
            for f in glob.glob(os.path.join(REPO, "rom", "*.bin"))}

    # gather every value of every raw table, keyed by table name
    acc = {}
    for romnode in root.iter("rom"):
        xid = romnode.find("romid").find("xmlid").text.replace("SUBARU_5EAT_", "")
        rom = None
        for name, data in roms.items():
            if xid in name.replace("[", "").replace("]", ""):
                rom = data
                break
        if rom is None:
            continue
        for t in romnode.iter("table"):
            name = t.get("name") or ""
            cat = t.get("category") or ""
            if not cat:
                continue
            # Trouble-code switches store a P-number, not a measurement. They pass
            # the multiple-of-2^k test by accident and mean nothing scaled.
            if "Diagnostic Codes" in cat or t.get("type") == "Switch":
                continue
            sc = t.find("scaling")
            units = (sc.get("units") if sc is not None else "") or ""
            if units.strip().lower() not in RAW_UNITS:
                continue
            v = cells(t, rom)
            if v:
                acc.setdefault((cat, name), []).extend(v)

    print("%-46s %7s %6s  %s" % ("table", "values", "scale", "range once scaled"))
    print("-" * 96)
    found = 0
    for (cat, name), vals in sorted(acc.items()):
        if len(vals) < args.min_values:
            continue
        if len(set(vals)) < 2:
            continue                       # constant: nothing to conclude
        nz = [v for v in vals if v]
        if not nz:
            continue
        # largest k where every value is a multiple of 2^k
        k = 0
        while k < 12 and all(v % (1 << (k + 1)) == 0 for v in nz):
            k += 1
        if k < 3:
            continue                       # too weak to mean anything
        div = 1 << k
        scaled = [v / float(div) for v in vals]
        print("%-46s %7d  /%-5d %g .. %g"
              % (name[:46], len(vals), div, min(scaled), max(scaled)))
        found += 1

    print("\n%d raw table(s) are stored as fixed point and can be shown scaled" % found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
