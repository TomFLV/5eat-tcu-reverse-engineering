#!/usr/bin/env python3
"""Locate the DTC code table in the Denso firmwares.

The M32R family's diagnostics are fully worked out: twelve status bytes of eight
fault flags each, indexing a 96-entry table of codes stored as the P-number in
hex, so 0x0705 is P0705. Fifty-three codes per firmware, and the definition ships
them.

The Denso family ships none, which means a fault provoked in the simulator can be
seen to perturb the controller but cannot be named. That is the difference between
"six addresses changed" and "this sets P0722", and it is the whole point of fault
testing.

The encoding is a strong signature - a dense run of uint16 values that all decode
to plausible powertrain P-codes and none of which decode to nonsense - so the same
scoring the M32R extractor uses applies here. What is NOT assumed is the geometry:
the 12x8 arrangement is a fact about the M32R firmware, and looking for exactly 96
entries in a different controller would find nothing and prove nothing. This scans
for runs of any length and reports what it finds.

    python tools/denso_find_dtc.py
    python tools/denso_find_dtc.py --min 12 --json tools/denso_dtc_table.json
"""

import argparse
import glob
import json
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROM_DIR = os.path.join(REPO, "rom-denso")

# Powertrain code ranges, as the M32R extractor established them.
VALID_RANGES = ((0x0700, 0x0999), (0x1600, 0x1899))
EMPTY = (0x0000, 0x3FFF, 0xFFFF)


def plausible(code):
    if code in EMPTY:
        return None
    for lo, hi in VALID_RANGES:
        if lo <= code <= hi:
            # A real P-code reads as decimal in hex: 0x705, never 0x7AF.
            if (code & 0x0F) <= 9 and ((code >> 4) & 0x0F) <= 9:
                return True
    return False


def runs(data, min_len):
    """Every maximal run of plausible codes, allowing empty slots inside it."""
    out = []
    i, n = 0, len(data) - 1
    while i < n:
        good, gaps, j = 0, 0, i
        while j < n:
            v = plausible(struct.unpack_from(">H", data, j)[0])
            if v is True:
                good += 1
                gaps = 0
            elif v is None:
                gaps += 1
                if gaps > 4:            # a long gap ends the table
                    break
            else:
                break                   # a non-code ends it outright
            j += 2
        if good >= min_len:
            out.append((i, good, (j - i) // 2))
            i = j
        else:
            i += 2
    return out


def as_pcode(v):
    return "P%04X" % v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=12,
                    help="fewest codes a run must hold to be reported")
    ap.add_argument("--json")
    args = ap.parse_args()

    result = {}
    for path in sorted(glob.glob(os.path.join(ROM_DIR, "*.bin"))):
        data = open(path, "rb").read()
        found = runs(data, args.min)
        name = os.path.basename(path)
        if not found:
            print("  %-44s no run of %d+ codes" % (name[:44], args.min))
            continue
        found.sort(key=lambda r: -r[1])
        base, good, span = found[0]
        codes = []
        for k in range(span):
            v = struct.unpack_from(">H", data, base + k * 2)[0]
            if plausible(v):
                codes.append(v)
        print("  %-44s 0x%06X  %d codes in %d slots%s"
              % (name[:44], base, good, span,
                 "   (%d other runs)" % (len(found) - 1) if len(found) > 1 else ""))
        print("       %s" % " ".join(as_pcode(c) for c in codes[:14]))
        if len(codes) > 14:
            print("       ... and %d more" % (len(codes) - 14))
        result[name] = {"addr": base, "count": good, "span": span,
                        "codes": [as_pcode(c) for c in codes]}

    print("\n%d of %d firmwares have a DTC code table"
          % (len(result), len(glob.glob(os.path.join(ROM_DIR, "*.bin")))))
    if args.json and result:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
        print("-> %s" % args.json)
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
