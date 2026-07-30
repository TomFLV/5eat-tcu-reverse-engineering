#!/usr/bin/env python3
"""Locate the DTC code table in each firmware and emit its per-ROM address.

HOW THIS WAS FOUND, and why the earlier attempt was wrong
---------------------------------------------------------
An early version of this project shipped 19 "DTC" switch tables read from 0x4090.
That was wrong: 0x4090 is M32R instruction stream - port initialisation misread as
records - and the tables would have let a user zero out boot code. They were
removed, and DTCs went down as not located.

The CAN decoding from the forum thread is what cracked it. CAN 0x422 bytes 3 and 4
carry a 16-bit word whose top two bits are a rotating DTC index and whose low 14
bits are the DTC number. That is a distinctive thing to search the decompilation
for, and FUN_00032cac builds exactly it:

    DAT_008047b6 = (ushort)DAT_008049b5 * 0x4000
                 + ((&DAT_008047b8)[DAT_008049b5] & 0x3fff);

`* 0x4000` is the index shifted into the top two bits and `& 0x3fff` is the 14-bit
code, matching the thread's description precisely. The four RAM slots are filled
just above it:

    for (uVar4 = 0; uVar4 < 0xc; uVar4++) {                  // 12 status bytes
        bVar1 = (&PTR_DAT_0001cdc4)[uVar4][2];               // 8 fault flags each
        for (uVar3 = 0; uVar3 < 8; uVar3++) {
            if ((bVar1 & bVar2) != 0 && uVar5 < 4) {
                (&DAT_008047b8)[uVar5] = (&DAT_0001ce18)[uVar4 * 8 + uVar3];
                uVar5++;
            }
            bVar2 <<= 1;
        }
    }

So `DAT_0001ce18` is a table of 12 x 8 = 96 uint16 DTC codes, indexed by
status-byte number times eight plus bit position. That is the DTC table.

THE ENCODING: codes are stored as the P-number in hex, not decimal. 0x705 is
P0705 - the one code the factory manual happens to name - and the rest follow:
0x720 P0720, 0x731..0x736 P0731..P0736, 0x741 P0741, 0x1706 P1706, and so on.

The address is NOT the same between firmwares, so it is located per image by
signature rather than assumed: a 96-entry uint16 window where a large majority of
the non-zero entries decode to a plausible powertrain P-code, and nothing decodes
to something impossible.

Writes dtc_table.json for generate_romraider_def.py.
"""

import glob
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

GROUPS = 12          # status bytes walked by the loop
BITS = 8             # flags per status byte
N = GROUPS * BITS    # 96 entries

# A stored code is the P-number in hex. Powertrain codes live in these ranges;
# anything outside them is not a P-code and disqualifies the window.
VALID_RANGES = ((0x0700, 0x0999), (0x1600, 0x1899))
EMPTY = (0x0000, 0x3FFF, 0xFFFF)


def u16(d, a):
    return (d[a] << 8) | d[a + 1]


def plausible(code):
    if code in EMPTY:
        return None                      # empty slot, neither good nor bad
    for lo, hi in VALID_RANGES:
        if lo <= code <= hi:
            # A real P-code's low two hex digits are decimal-looking: 0x705 not 0x7AF.
            if (code & 0x0F) <= 9 and ((code >> 4) & 0x0F) <= 9:
                return True
    return False


def score(d, base):
    """Return (good, bad, filled) for a candidate window."""
    if base + N * 2 > len(d):
        return 0, 999, 0
    good = bad = filled = 0
    for i in range(N):
        v = plausible(u16(d, base + i * 2))
        if v is None:
            continue
        filled += 1
        if v:
            good += 1
        else:
            bad += 1
    return good, bad, filled


def find(d):
    """Best-scoring window. Requires many valid codes and no invalid ones."""
    best = None
    for base in range(0x8000, min(len(d), 0x60000) - N * 2, 2):
        good, bad, filled = score(d, base)
        if good < 30 or bad > 0:
            continue
        if best is None or good > best[1]:
            best = (base, good, filled)
    return best


def as_pcode(v):
    """0x705 -> P0705. The stored value IS the hex of the P-number."""
    return "P%04X" % v


def main():
    out = {}
    for f in sorted(glob.glob(os.path.join(REPO, "rom", "*.bin"))):
        d = open(f, "rb").read()
        m = re.search(r"[0-9A-Z]{10}", os.path.basename(f).upper())
        cal = m.group(0) if m else None
        if not cal:
            continue
        best = find(d)
        if not best:
            print("  %-12s no DTC table found" % cal)
            continue
        base, good, filled = best
        out[cal] = {"addr": base, "codes": good}
        sample = [as_pcode(u16(d, base + i * 2)) for i in range(N)
                  if u16(d, base + i * 2) not in EMPTY][:6]
        print("  %-12s 0x%06X  %2d codes  e.g. %s"
              % (cal, base, good, ", ".join(sample)))

    dest = os.path.join(HERE, "dtc_table.json")
    with io.open(dest, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("\nwrote %s (%d firmwares)" % (dest, len(out)))


if __name__ == "__main__":
    main()
