#!/usr/bin/env python3
"""Locate the line-pressure target curves and emit their per-firmware addresses.

These are the first tables in this project with a pressure unit that is not a
guess. Earlier attempts to put a real unit on the "Pressure Control" families
failed because those tables hold small correction values (flat 20, or 6/6/6/10/10
by gear) that are plainly not a pressure in any unit. The mistake was looking for
the conversion inside the ROM. There isn't one to find: the TCU already works in
kPa, because the factory service manual has it reporting "P/L Solenoid Target
Pressure" to the Subaru Select Monitor in kPa.

The FSM line-pressure test (5AT-35) documents the targets:

    D range, throttle full closed   490 kPa
    D range, throttle full open    1370 kPa
    R range, throttle full closed  1370 kPa

Searching for 1370 as a big-endian uint16 finds it seven times at a 4-byte
stride, in every firmware, at an address that relocates between them - the
signature of a real calibration table rather than a coincidence.

The layout is an array of 4-byte records, 2 x uint16:

    [engine speed x 8, pressure in kPa]

The engine-speed column uses the same /8 scaling already confirmed for the
SpeedTrim and SlipThreshold axes, and its terminating breakpoint is 0xFF00 =
65280 = 8160 RPM, the same near-ceiling sentinel that appears in those axes.
So both columns carry a confirmed real unit.

What is NOT confirmed: which hydraulic circuit each table governs. The value
column is constant within a table (1370 in one, 953 in the other), so these are
flat limits against engine speed rather than shaped curves, and the consuming
function has not been traced. The tables are therefore named for what they
demonstrably contain - a pressure target in kPa against engine speed - and not
for a circuit we would be guessing at.

Writes pressure_curves.json for generate_romraider_def.py.
"""

import glob
import re
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

END_BREAKPOINT = 0xFF00   # 65280 raw = 8160 RPM, the max sentinel
FSM_TARGET_KPA = 1370     # from the FSM line pressure test, used as the fingerprint


def u16(d, a):
    return (d[a] << 8) | d[a + 1]


def walk(d, start, max_tables=8):
    """Walk consecutive 4-byte [breakpoint, value] tables from `start`."""
    tables, a, end = [], start, min(len(d) - 4, start + 0x400)
    while a < end and len(tables) < max_tables:
        recs, first = [], a
        while a < end:
            bp, val = u16(d, a), u16(d, a + 2)
            recs.append((bp, val))
            a += 4
            if bp == END_BREAKPOINT:
                break
        if len(recs) < 2 or recs[-1][0] != END_BREAKPOINT:
            break
        # A real table's breakpoints ascend to the sentinel.
        bps = [b for b, _ in recs[:-1]]
        if bps != sorted(bps) or len(set(v for _, v in recs)) != 1:
            break
        tables.append({"addr": first, "rows": len(recs),
                       "kpa": recs[0][1],
                       "rpm": [round(b / 8) for b, _ in recs]})
    return tables


def find(d):
    """Find the run of pressure tables by the FSM-documented 1370 kPa value."""
    hit = None
    for a in range(0x010000, min(len(d), 0x020000), 2):
        if u16(d, a + 2) == FSM_TARGET_KPA and 0x2000 <= u16(d, a) <= END_BREAKPOINT:
            hit = a
            break
    if hit is None:
        return []
    s = hit
    while s > 0x010000 and u16(d, s - 4) != END_BREAKPOINT:
        s -= 4
    return walk(d, s)


def main():
    out = {}
    for f in sorted(glob.glob(os.path.join(REPO, "rom", "*.bin"))):
        d = open(f, "rb").read()
        # Key by the ten-character part number, which is what the generator's
        # profile ids use. Splitting the filename on "_" or "-" does not work:
        # "5EAT_ADE0236000.bin" would key as "5EAT" and silently fail to match.
        m = re.search(r"[0-9A-Z]{10}", os.path.basename(f).upper())
        if not m:
            print(f"  {os.path.basename(f)}: no part number in filename, skipped")
            continue
        cal = m.group(0)
        tables = find(d)
        if not tables:
            print(f"  {cal:12s} no pressure curves found")
            continue
        out[cal] = tables
        print(f"  {cal:12s} {len(tables)} curves  "
              + "  ".join(f"0x{t['addr']:06X}={t['kpa']}kPa/{t['rows']}r"
                          for t in tables))

    dest = os.path.join(HERE, "pressure_curves.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"\nwrote {dest} ({len(out)} firmwares)")

    # Consistency is the only check available without a traced call site: every
    # firmware should agree on how many curves there are and what they hold.
    counts = {len(v) for v in out.values()}
    kpas = {tuple(t["kpa"] for t in v) for v in out.values()}
    print(f"curve counts across firmwares: {counts}")
    print(f"kPa value sets across firmwares: {kpas}")
    if len(counts) == 1 and len(kpas) == 1:
        print("consistent: same structure and same targets in every firmware")
    else:
        print("INCONSISTENT - do not ship until this is understood")


if __name__ == "__main__":
    main()
