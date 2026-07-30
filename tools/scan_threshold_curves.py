#!/usr/bin/env python3
"""Find every speed/pedal threshold polyline in the ROM, mapped or not.

The definition currently exposes eight shift curves. This scan says how many
curves of that exact shape are actually in the image, which turns out to be far
more: the eight are one slice of a much larger family.

A curve qualifies only if it has the full shape of a known shift curve, which is
what keeps the false-positive rate near zero:

  * 8-byte records of 4 x uint16, terminated by a leading 0xFFFF
  * field 0 ascending and starting at 0 - vehicle speed in km/h
  * field 1 ascending and within 0..255 - accelerator angle
  * segments chain: each record's field 2 equals the next record's field 0

Run it to see what is unmapped:

    python tools/scan_threshold_curves.py rom/91D1206000_5EAT.bin
"""

import argparse
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def load_known(cal):
    """Addresses already carried by the definition, so leftovers stand out."""
    known = {}
    try:
        sc = json.load(io.open(os.path.join(HERE, "shift_curves.json")))
        for name, v in sc.get(cal, {}).items():
            known[v["addr"]] = name
    except (IOError, ValueError):
        pass
    try:
        for c in json.load(io.open(os.path.join(HERE, "hysteresis_curves.json"))):
            known.setdefault(c["addr"], c["name"])
    except (IOError, ValueError):
        pass
    try:
        pc = json.load(io.open(os.path.join(HERE, "pressure_curves.json")))
        for c in pc.get(cal, []):
            known.setdefault(c["addr"], "line pressure")
    except (IOError, ValueError):
        pass
    return known


def scan(d, lo=0x8000, hi=0x60000, max_rows=40):
    def u16(a):
        return (d[a] << 8) | d[a + 1]

    def at(start):
        a, recs = start, []
        while a + 8 <= len(d):
            f0 = u16(a)
            if f0 == 0xFFFF:
                break
            recs.append((f0, u16(a + 2), u16(a + 4), u16(a + 6)))
            a += 8
            if len(recs) > max_rows:
                return None
        if not (3 <= len(recs) <= max_rows):
            return None
        if a + 2 > len(d) or u16(a) != 0xFFFF:
            return None
        f0s = [r[0] for r in recs]
        f1s = [r[1] for r in recs]
        if f0s != sorted(f0s) or f0s[0] != 0 or max(f0s) > 400:
            return None
        if f1s != sorted(f1s) or max(f1s) > 255:
            return None
        # Segment chaining is the strongest single filter: a coincidental run of
        # ascending uint16 pairs almost never chains end-to-start as well.
        for i in range(len(recs) - 1):
            if recs[i][2] != recs[i + 1][0]:
                return None
        return recs

    out, a, end = [], lo, min(len(d), hi) - 8
    while a < end:
        recs = at(a)
        if recs:
            out.append((a, recs))
            a += len(recs) * 8 + 2
        else:
            a += 2
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", nargs="?",
                    default=os.path.join(REPO, "rom", "91D1206000_5EAT.bin"))
    ap.add_argument("--unmapped-only", action="store_true")
    args = ap.parse_args()

    d = open(args.rom, "rb").read()
    m = re.search(r"[0-9A-Z]{10}", os.path.basename(args.rom).upper())
    known = load_known(m.group(0) if m else "")

    found = scan(d)
    for addr, recs in found:
        tag = known.get(addr)
        if args.unmapped_only and tag:
            continue
        speeds = [r[0] for r in recs]
        pedals = [round(r[1] * 100.0 / 255.0) for r in recs]
        label = ("mapped: " + tag) if tag else "UNMAPPED"
        print(f"0x{addr:06X}  rows={len(recs):2d}  {label}")
        print(f"            km/h  {speeds}")
        print(f"            pedal {pedals}")

    n_un = sum(1 for a, _ in found if a not in known)
    print(f"\n{len(found)} threshold curves, {n_un} not in the definition")


if __name__ == "__main__":
    main()
