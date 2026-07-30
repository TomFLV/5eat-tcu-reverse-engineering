#!/usr/bin/env python3
"""Locate the line pressure TARGET maps - engine torque in, line pressure out.

These are the end of the chain rimwall describes in post 184 of the forum thread:
engine torque from CAN 0x412 is multiplied by a slip factor, smoothed, multiplied
again by an ATF temperature factor, and the result looks up a line pressure target.
The two multipliers were scaled in FINDINGS section 18; this is the lookup itself.

Found by following the code rather than by scanning. The twice-factored torque lands
in DAT_008042fa, and the only consumers are:

    DAT_00804a82 = FUN_00045070((&PTR_DAT_00012478)[uVar2 & 0xff], 0, DAT_008042fa);
    DAT_00804a82 = FUN_00045070((&PTR_PTR_00012314)[DAT_0080485f], 0, DAT_008042fa);

so 0x12478 and 0x12314 are arrays of pointers to the target maps, selected by
operating state, and DAT_00804a82 is the resulting target.

BOTH AXES ARE CONFIRMED, against sources outside this project:

  input  /10 = Nm.  The community CAN decoding has 0x412 bytes 3-4 as Engine Torque
         Output. The breakpoints then read 0, 50, 100, 150, 200, 250, 300, 350, 400,
         600, 800, 1000 Nm - round numbers and a sensible range for this engine.

  output /10 = kPa. The factory manual line pressure test (5AT-35) gives two
         numbers, and both land: 5240 decodes to 524 kPa where the manual specifies
         385-555 (nominal 490) at closed throttle, and 13720 at 400 Nm decodes to
         1372 kPa where the manual specifies 1235-1475 (nominal 1370) at full
         throttle in D.

Two independent documents agreeing on both axes is why these are shipped with real
units rather than as raw.

Writes line_pressure_targets.json for generate_romraider_def.py.
"""

import glob
import io
import json
import os
import re
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# The torque axis is the fingerprint: these breakpoints, in tenths of a Nm.
AXIS_TAIL = (4000, 6000, 8000, 10000)
MIN_RECORDS = 8
MAX_RECORDS = 24


def u16(d, a):
    return struct.unpack(">H", d[a:a + 2])[0]


def u32(d, a):
    return struct.unpack(">I", d[a:a + 4])[0]


def read_curve(d, at):
    """8-byte records, 4 x uint16, terminated by a leading 0xFFFF."""
    recs = []
    a = at
    while a + 8 <= len(d) and len(recs) <= MAX_RECORDS:
        f0 = u16(d, a)
        if f0 == 0xFFFF:
            break
        recs.append((f0, u16(d, a + 2)))
        a += 8
    else:
        return None
    if len(recs) < MIN_RECORDS:
        return None
    bps = [r[0] for r in recs]
    vals = [r[1] for r in recs]
    if bps != sorted(bps) or vals != sorted(vals):
        return None
    if tuple(bps[-4:]) != AXIS_TAIL:
        return None
    # A pressure target should be a plausible pressure once decoded.
    if not (200 <= vals[0] / 10.0 <= 1200 and 1000 <= vals[-1] / 10.0 <= 4000):
        return None
    return recs


def find_arrays(d):
    """Pointer runs whose targets are torque/pressure maps."""
    found = {}
    for base in range(0x8000, min(len(d), 0x60000) - 4, 4):
        targets = []
        for i in range(12):
            o = base + i * 4
            if o + 4 > len(d):
                break
            p = u32(d, o)
            if not (0x8000 <= p < len(d)):
                break
            c = read_curve(d, p)
            if c is None:
                break
            targets.append((p, c))
        if len(targets) >= 4:
            found[base] = targets
    # Drop runs that are just a later slice of an earlier one.
    keep = {}
    for base in sorted(found):
        if any(base > b and base < b + len(found[b]) * 4 for b in keep):
            continue
        keep[base] = found[base]
    return keep


def main():
    out = {}
    for f in sorted(glob.glob(os.path.join(REPO, "rom", "*.bin"))):
        d = open(f, "rb").read()
        m = re.search(r"[0-9A-Z]{10}", os.path.basename(f).upper())
        if not m:
            continue
        cal = m.group(0)

        arrays = find_arrays(d)
        # Unique target maps, in address order, so each is emitted once.
        maps = {}
        for base, targets in arrays.items():
            for addr, recs in targets:
                maps.setdefault(addr, len(recs))

        if not maps:
            print("  %-12s none found" % cal)
            continue

        out[cal] = {
            "arrays": sorted(arrays.keys()),
            "maps": [{"addr": a, "rows": n} for a, n in sorted(maps.items())],
        }
        sample = sorted(maps)[0]
        recs = read_curve(d, sample)
        print("  %-12s %d array(s), %2d map(s); e.g. 0x%06X %d Nm -> %.0f kPa"
              % (cal, len(arrays), len(maps), sample,
                 recs[-1][0] // 10, recs[-1][1] / 10.0))

    dest = os.path.join(HERE, "line_pressure_targets.json")
    with io.open(dest, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("\nwrote %s (%d firmwares)" % (dest, len(out)))


if __name__ == "__main__":
    main()
