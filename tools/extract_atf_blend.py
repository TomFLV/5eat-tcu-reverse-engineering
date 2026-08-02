#!/usr/bin/env python3
"""Locate the ATF temperature blend window in every firmware.

All seven solenoid channels compute their target pressure by interpolating between a
cold calibration and a warm one across a temperature window. The two breakpoints are
single bytes at consecutive addresses, in the -40 encoding this family uses
throughout, and they relocate between firmwares like every other constant.

Rather than derive the relocation, read each firmware's own decompiler output. The
interpolation has a distinctive shape and names both addresses directly:

    uVar7 = (uint)DAT_0001c3bd;          <- low breakpoint
    uVar3 = (uint)DAT_008047fb;          <- the ATF reading
    if (uVar7 < uVar3) {
      if ((uVar7 < uVar3) && (uVar8 = (uint)DAT_0001c3be, uVar3 < uVar8)) {

The pattern occurs exactly seven times per firmware - once per solenoid channel - and
all seven agree, which is what makes the answer trustworthy rather than a lucky
regex match.

Writes tools/atf_blend.json for the generator.
"""

import glob
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "atf_blend.json")

PATTERN = re.compile(
    r"=\s*\(uint\)DAT_([0-9a-f]{8});\s*"
    r"\w+\s*=\s*\(uint\)DAT_([0-9a-f]{8});\s*"
    r"if\s*\([^)]*\)\s*\{\s*"
    r"if\s*\(\([^)]*\)\s*&&\s*\(\w+\s*=\s*\(uint\)DAT_([0-9a-f]{8}),",
    re.S)

EXPECT_CHANNELS = 7


# One image is named for a different reading of its calibration id in the decompiler
# output than in the ROM file. Same bytes; see FINDINGS section 24.
ALIASES = {"AC91207000": "ACD1207000"}


def cal_id(path):
    """The 10-character calibration id embedded in a file name."""
    m = re.search(r"([0-9A-Z]{10})", os.path.basename(path))
    if not m:
        return None
    return ALIASES.get(m.group(1), m.group(1))


def main():
    roms = {}
    for f in glob.glob(os.path.join(REPO, "rom", "*.bin")):
        cid = cal_id(f)
        if cid:
            roms[cid] = f

    out = {}
    problems = []
    for src in sorted(glob.glob(os.path.join(REPO, "decompiled", "*.c"))):
        cid = cal_id(src)
        if not cid:
            continue
        text = open(src, encoding="utf-8", errors="replace").read()
        hits = PATTERN.findall(text)
        if not hits:
            problems.append("%s: interpolation not found" % os.path.basename(src))
            continue

        counts = Counter((lo, hi, atf) for lo, atf, hi in hits)
        (lo, hi, atf), n = counts.most_common(1)[0]
        lo_a, hi_a = int(lo, 16), int(hi, 16)

        if hi_a - lo_a != 1:
            problems.append("%s: breakpoints not adjacent (0x%X, 0x%X)" % (cid, lo_a, hi_a))
            continue
        if n != EXPECT_CHANNELS:
            problems.append("%s: %d of %d channels agree" % (cid, n, len(hits)))

        entry = {"lo_addr": lo_a, "hi_addr": hi_a, "atf_addr": int(atf, 16),
                 "channels": n}

        if cid in roms:
            d = open(roms[cid], "rb").read()
            lo_v, hi_v = d[lo_a], d[hi_a]
            if not lo_v < hi_v:
                problems.append("%s: window not ascending (%d, %d)" % (cid, lo_v, hi_v))
                continue
            entry.update(lo_value=lo_v, hi_value=hi_v,
                         lo_c=lo_v - 40, hi_c=hi_v - 40)
        out[cid] = entry

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)

    print("%-14s %-10s %-10s %s" % ("firmware", "lo", "hi", "window"))
    print("-" * 62)
    for cid in sorted(out):
        e = out[cid]
        w = ("%4d C .. %4d C" % (e["lo_c"], e["hi_c"])) if "lo_c" in e else "(no rom)"
        print("%-14s 0x%-8X 0x%-8X %s" % (cid, e["lo_addr"], e["hi_addr"], w))

    windows = {(e.get("lo_c"), e.get("hi_c")) for e in out.values() if "lo_c" in e}
    print("\ndistinct windows across firmwares: %s" % sorted(windows))
    for p in problems:
        print("  NOTE %s" % p)
    print("\nwrote %s (%d firmwares)" % (OUT, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
