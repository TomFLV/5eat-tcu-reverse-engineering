#!/usr/bin/env python3
"""Locate the table that decides which shift schedule GROUP applies.

Section 33 established the selection: the schedule index is
DAT_0080485A * 2 + sVar1 * 10, and sVar1 comes from a selector byte that holds
0x80..0x85 or 0x8C. That byte is not read from a sensor. It comes from a lookup:

    cVar1 = *(char *)(DAT_0080486E * 4 + 0x10108 + ((DAT_008052B3 ^ 0xFF) & 7) - 3);
    if (cVar1 != 0 && cVar1 != -1) use cVar1;

So the mapping is calibration data, and it decides which group of ten schedules the
transmission uses. The stored bytes are the selector codes themselves - 0x81, 0x82,
0x83, 0x85 - with 0xFF meaning "no override, keep the current position" and 0x00
meaning the entry is unused.

Located per firmware from each image's own decompiler output rather than by assuming
the base ROM offset holds; it does not, the same as every other constant here.

Writes tools/selector_table.json for the generator.
"""

import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "selector_table.json")

# the lookup, as the decompiler renders it
PATTERN = re.compile(
    r"\*\(char \*\)\(\(uint\)DAT_([0-9a-f]{8}) \* 4 \+ (0x[0-9a-f]+) \+ "
    r"\(\(\(DAT_([0-9a-f]{8}) \^ 0xff\) & 7\) - 3 & 0xff\)\)")

SELECTOR_CODES = {0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x8C}
ROWS, COLS = 5, 4          # 0x10108..0x1011C in the base ROM

ALIASES = {"AC91207000": "ACD1207000"}


def cal_id(path):
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

    out, problems = {}, []
    for src in sorted(glob.glob(os.path.join(REPO, "decompiled", "*.c"))):
        cid = cal_id(src)
        if not cid:
            continue
        text = open(src, encoding="utf-8", errors="replace").read()
        m = PATTERN.search(text)
        if not m:
            problems.append("%s: lookup not found" % cid)
            continue
        idx_var, base, sub_var = m.group(1), int(m.group(2), 16), m.group(3)

        entry = {"addr": base, "index_var": "0x" + idx_var, "sub_var": "0x" + sub_var,
                 "rows": ROWS, "cols": COLS}

        if cid in roms:
            d = open(roms[cid], "rb").read()
            body = d[base:base + ROWS * COLS]
            codes = [b for b in body if b in SELECTOR_CODES]
            entry["selector_bytes"] = len(codes)
            entry["sample"] = " ".join("%02X" % b for b in body[:16])
            # a table that decides gear limits must actually contain selector codes
            if len(codes) < 3:
                problems.append("%s: only %d selector codes at 0x%X - not shipping"
                                % (cid, len(codes), base))
                continue
        out[cid] = entry

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)

    print("%-12s %-9s %-7s %s" % ("firmware", "addr", "codes", "first 16 bytes"))
    print("-" * 76)
    for cid in sorted(out):
        e = out[cid]
        print("%-12s 0x%-7X %-7s %s"
              % (cid, e["addr"], e.get("selector_bytes", "?"), e.get("sample", "")))
    for p in problems:
        print("  NOTE %s" % p)
    print("\nwrote %s (%d firmwares)" % (OUT, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
