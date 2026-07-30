#!/usr/bin/env python3
"""Locate the downshift pressure control tables - target pressure and ramp timing.

WHAT THIS IS

Following the line pressure work, a second target lookup turned up in the same RAM
block:

    DAT_00804a94 = FUN_00045070((&PTR_PTR_00012034)[DAT_00804a8e], 0, DAT_008047fe);

Input is vehicle speed, output is a pressure, and the surrounding code is a timed
ramp - a counter that increments every cycle, compared against a per-state duration,
with the output stepping toward the target once the duration elapses:

    if (timer < duration[idx])          out = floor;
    else                                out = min(target, start + step[idx]);

WHY IT IS DOWNSHIFT CONTROL AND NOT LOCK-UP

The state index comes from a 5 x 5 byte matrix at 0x1BB6A, read as [a * 5 + b]:

          b=0    1    2    3    4
    a=0   255  255  255  255  255
    a=1     0  255  255  255  255
    a=2     1    2  255  255  255
    a=3     3    4    5  255  255
    a=4     6    7    8    9  255

Lower triangular: an index exists only when b < a, and 255 means "no entry". With a
as the current gear and b as the target gear, b < a is a DOWNSHIFT, and there are
exactly ten of them among five gears - 2-1, 3-1, 3-2, 4-1, 4-2, 4-3, 5-1, 5-2, 5-3,
5-4. Ten valid indices, ten target maps. That is a gear-transition table, not a
torque converter clutch, so this is NOT the lock-up control.

UNITS

Pressure is /10 = kPa, the same scale confirmed for the line pressure targets in
FINDINGS section 19 - the maps top out at 13720, which is the 1372 kPa the factory
manual specifies for full throttle in D.

Duration is a loop counter with no established period, so it ships raw. Calling it
milliseconds without knowing the task rate would be a guess.

Writes downshift_pressure.json for generate_romraider_def.py.
"""

import glob
import io
import json
import os
import re
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

GEARS = 5
STATES = 10          # the ten downshift combinations


def u16(d, a):
    return struct.unpack(">H", d[a:a + 2])[0]


def u32(d, a):
    return struct.unpack(">I", d[a:a + 4])[0]


def is_downshift_matrix(d, at):
    """Lower triangular, 0..9 below the diagonal, 0xFF on and above it."""
    if at + GEARS * GEARS > len(d):
        return False
    seen = []
    for a in range(GEARS):
        for b in range(GEARS):
            v = d[at + a * GEARS + b]
            if b < a:
                if v > 0xFE:
                    return False
                seen.append(v)
            elif v != 0xFF:
                return False
    return sorted(seen) == list(range(STATES))


def curve(d, at, maxrec=24):
    recs = []
    a = at
    while a + 8 <= len(d) and len(recs) < maxrec:
        f0 = u16(d, a)
        if f0 == 0xFFFF:
            break
        recs.append((f0, u16(d, a + 2)))
        a += 8
    else:
        return None
    if len(recs) < 3:
        return None
    bps = [r[0] for r in recs]
    vals = [r[1] for r in recs]
    if bps != sorted(bps) or bps[0] != 0 or bps[-1] > 400:
        return None
    # Pressures, on the confirmed /10 = kPa scale.
    if not all(2000 <= v <= 20000 for v in vals):
        return None
    return recs


def find_map_array(d):
    """A run of ten pointers to speed-indexed pressure curves."""
    for base in range(0x8000, min(len(d), 0x60000) - 4, 4):
        ok = 0
        rows = []
        for i in range(STATES):
            p = u32(d, base + i * 4)
            if not (0x8000 <= p < len(d)):
                break
            c = curve(d, p)
            if c is None:
                break
            ok += 1
            rows.append({"addr": p, "rows": len(c)})
        if ok == STATES:
            return base, rows
    return None, None


def main():
    out = {}
    for f in sorted(glob.glob(os.path.join(REPO, "rom", "*.bin"))):
        d = open(f, "rb").read()
        m = re.search(r"[0-9A-Z]{10}", os.path.basename(f).upper())
        if not m:
            continue
        cal = m.group(0)

        matrix = None
        for at in range(0x8000, min(len(d), 0x60000)):
            if is_downshift_matrix(d, at):
                matrix = at
                break

        base, maps = find_map_array(d)
        if matrix is None or base is None:
            print("  %-12s matrix=%s maps=%s  (incomplete, skipped)"
                  % (cal, "0x%05X" % matrix if matrix else "none",
                     "0x%05X" % base if base else "none"))
            continue

        # The {step, duration} structs sit immediately before the pointer array.
        ramp = base - STATES * 4
        out[cal] = {"matrix": matrix, "maps_ptr": base, "ramp": ramp, "maps": maps}
        print("  %-12s matrix 0x%05X  maps 0x%05X  ramp 0x%05X  top %.0f kPa"
              % (cal, matrix, base, ramp,
                 max(u16(d, mm["addr"] + r * 8 + 2)
                     for mm in maps for r in range(mm["rows"])) / 10.0))

    dest = os.path.join(HERE, "downshift_pressure.json")
    with io.open(dest, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("\nwrote %s (%d firmwares)" % (dest, len(out)))


if __name__ == "__main__":
    main()
