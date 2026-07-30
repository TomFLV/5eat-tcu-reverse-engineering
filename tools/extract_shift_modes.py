#!/usr/bin/env python3
"""Extract every shift schedule, not just the one the definition has shipped so far.

STRUCTURE

The shift curves are reached through a pointer array. Each entry is a curve, indexed
as gear * 2 + direction, ten entries per mode - five gears by (upshift, downshift).
Slot 1 and slot 8 are always placeholders, because first gear has no downshift and
fifth has no upshift, which is what confirms the indexing.

Walking the array past the first ten entries shows forty modes, and they are
organised as EIGHT GROUPS OF FIVE. Within every group the number of live upshifts
steps down 4, 3, 2, 1, 0 as the mode increases, with the highest upshift replaced by
the placeholder each time:

    limit 0   1-2, 2-3, 3-4, 4-5 all live      D, all gears
    limit 1   4-5 disabled                     hold 4th
    limit 2   3-4 and 4-5 disabled             hold 3rd
    limit 3   only 1-2 live                    hold 2nd
    limit 4   no upshifts at all               hold 1st

That is manual gear limiting, and it is read off the data rather than assumed - a
fuelling or temperature state would not progressively disable upshifts from the top
down. The eight GROUPS are then eight different operating conditions, each with its
own base curve set.

WHAT THIS EXTRACTS

One complete schedule per group, at the D limit, since the limited variants mostly
reuse the same curves with upshifts removed and add little to tune. That turns the
single shift map in the definition into eight.

The conditions themselves are NOT named. Sasha_A80 listed candidates in the forum
thread - cold and warm engine, cold and warm ATF, catalyst preheat, quick shift,
hill assist - and rimwall never pinned them down either, so they are numbered.
Naming them on the strength of that list would be a guess wearing a confident label.

Writes shift_modes.json for generate_romraider_def.py.
"""

import glob
import io
import json
import os
import re
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

PER_MODE = 10          # 5 gears x (up, down)
LIMITS = 5             # gear-limit variants per group
SLOT_NAMES = {0: "Shift 1-2 Upshift Curve", 2: "Shift 2-3 Upshift Curve",
              4: "Shift 3-4 Upshift Curve", 6: "Shift 4-5 Upshift Curve",
              3: "Shift 2-1 Downshift Curve", 5: "Shift 3-2 Downshift Curve",
              7: "Shift 4-3 Downshift Curve", 9: "Shift 5-4 Downshift Curve"}


def u16(d, a):
    return struct.unpack(">H", d[a:a + 2])[0]


def u32(d, a):
    return struct.unpack(">I", d[a:a + 4])[0]


def curve_rows(d, at):
    n, a, prev = 0, at, -1
    while a + 8 <= len(d) and n < 40:
        x = u16(d, a)
        if x == 0xFFFF:
            return n if n >= 2 else None
        y = u16(d, a + 2)
        if x < prev or y > 255 or x > 400:
            return None
        prev = x
        n += 1
        a += 8
    return None


def find_array(d):
    """The pointer array: ten in-ROM pointers where slots 1 and 8 are placeholders
    and the rest are curves. That shape is specific enough to locate it directly."""
    for base in range(0x10000, min(len(d), 0x40000) - PER_MODE * 4, 4):
        ptrs = [u32(d, base + i * 4) for i in range(PER_MODE)]
        if not all(0x8000 <= p < len(d) for p in ptrs):
            continue
        rows = [curve_rows(d, p) for p in ptrs]
        if rows[1] is not None or rows[8] is not None:
            continue                      # slots 1 and 8 must be placeholders
        if sum(1 for i, r in enumerate(rows) if r and i not in (1, 8)) != 8:
            continue
        return base
    return None


def main():
    out = {}
    for f in sorted(glob.glob(os.path.join(REPO, "rom", "*.bin"))):
        d = open(f, "rb").read()
        m = re.search(r"[0-9A-Z]{10}", os.path.basename(f).upper())
        if not m:
            continue
        cal = m.group(0)

        base = find_array(d)
        if base is None:
            print("  %-12s pointer array not found" % cal)
            continue

        groups = []
        mode = 0
        while mode < 64:
            mb = base + mode * PER_MODE * 4
            if mb + PER_MODE * 4 > len(d):
                break
            ptrs = [u32(d, mb + i * 4) for i in range(PER_MODE)]
            rows = [curve_rows(d, p) if 0x8000 <= p < len(d) else None for p in ptrs]
            if not any(rows):
                break
            if mode % LIMITS == 0:            # the D-limit mode of each group
                curves = {}
                for slot, nm in SLOT_NAMES.items():
                    if rows[slot]:
                        curves[nm] = {"addr": ptrs[slot], "rows": rows[slot]}
                if len(curves) == 8:
                    groups.append({"mode": mode, "curves": curves})
            mode += 1

        if not groups:
            print("  %-12s no complete schedules" % cal)
            continue
        out[cal] = {"array": base, "modes": mode, "groups": groups}
        print("  %-12s array 0x%05X  %d modes  %d complete schedules"
              % (cal, base, mode, len(groups)))

    dest = os.path.join(HERE, "shift_modes.json")
    with io.open(dest, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("\nwrote %s (%d firmwares)" % (dest, len(out)))


if __name__ == "__main__":
    main()
