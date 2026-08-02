#!/usr/bin/env python3
"""Find the Denso tables the firmware actually indexes, not merely the ones that parse.

The header scan in survey_denso_tcu.py finds about 1770 self-consistent headers per
image. Self-consistent is not the same as used: a 28-byte structure whose pointers
happen to sit the right distance apart will pass that filter by chance, and in a 1 MB
image plenty do.

The firmware settles it. Tables are reached through arrays of pointers to their
headers, so a run of consecutive words that all point at valid headers is a real
index, and everything it names is a real table. Disassembling one image with Ghidra
confirmed the shape: the shift-schedule headers at 0xE9080 are referenced from a
pointer run at 0x242E0, and the data blocks they point to have no direct references
at all, exactly as that indirection implies.

Requiring at least MIN_RUN consecutive valid pointers is what makes this trustworthy.
A single word that looks like a header pointer proves nothing; eleven in a row do.

    python tools/find_denso_pointer_tables.py [--min-run 4]
"""

import argparse
import glob
import json
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "denso_indexed_tables.json")


def header_shape(d, a):
    """(rows, cols) if a valid table header sits at a, else None."""
    if not (0 < a < len(d) - 28):
        return None
    rows, cols = struct.unpack(">HH", d[a:a + 4])
    if not (2 <= rows <= 64 and 1 <= cols <= 64):
        return None
    xp, yp, dp = struct.unpack(">III", d[a + 4:a + 16])
    if yp != xp + rows * 4 or dp != yp + cols * 4:
        return None
    if not (0x1000 < xp < len(d) and dp + rows * cols * 2 <= len(d)):
        return None
    return rows, cols


def runs_of_pointers(d, min_run):
    """Maximal runs of consecutive words that all point at valid headers."""
    out, cur, i = [], [], 0x1000
    while i + 4 <= len(d):
        p = struct.unpack(">I", d[i:i + 4])[0]
        if header_shape(d, p):
            cur.append((i, p))
        else:
            if len(cur) >= min_run:
                out.append(cur)
            cur = []
        i += 4
    if len(cur) >= min_run:
        out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-run", type=int, default=4)
    args = ap.parse_args()

    result = {}
    for path in sorted(glob.glob(os.path.join(REPO, "rom-denso", "*.bin"))):
        d = open(path, "rb").read()
        cal = d[0x2000:0x2008].decode("ascii", "replace")
        runs = runs_of_pointers(d, args.min_run)
        tables = []
        for r in runs:
            for _off, p in r:
                rows, cols = header_shape(d, p)
                tables.append({"header": p, "rows": rows, "cols": cols})
        # a table can be indexed from more than one run
        uniq = {t["header"]: t for t in tables}
        result[cal] = {
            "runs": [{"at": r[0][0], "entries": len(r)} for r in runs],
            "tables": sorted(uniq.values(), key=lambda t: t["header"]),
        }
        shapes = {}
        for t in uniq.values():
            k = "%dx%d" % (t["rows"], t["cols"])
            shapes[k] = shapes.get(k, 0) + 1
        top = ", ".join("%s x%d" % kv for kv in
                        sorted(shapes.items(), key=lambda kv: -kv[1])[:5])
        print("%-10s %3d runs, %4d indexed tables   %s"
              % (cal, len(runs), len(uniq), top))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    print("\nwrote %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
