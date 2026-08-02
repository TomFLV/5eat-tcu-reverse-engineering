#!/usr/bin/env python3
"""Describe every Denso table by what its numbers actually look like.

The Denso definition ships a few hundred tables whose structure is certain and whose
meaning is not. Naming them by eye is impractical, and naming them by guesswork is
worse than leaving them alone.

This produces the evidence a name would have to rest on: axis ranges and step
patterns, value ranges, monotonicity, how many firmwares share the table, and whether
the axis looks like a quantity already confirmed elsewhere in the project - pedal
percent, engine RPM, a -40 temperature, a road speed.

Nothing here proposes a name. It produces the facts; anything that later suggests a
name - a person or a model - has to be checked back against these.

    python tools/profile_denso_tables.py [--json out.json]
"""

import argparse
import glob
import json
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

HEADER_STRIDE = 28


def u16(d, a):
    return struct.unpack(">H", d[a:a + 2])[0]


def u32(d, a):
    return struct.unpack(">I", d[a:a + 4])[0]


def f32(d, a):
    return struct.unpack(">f", d[a:a + 4])[0]


def scan(d):
    """Every self-consistent table header, as in tools/survey_denso_tcu.py."""
    out, n = [], len(d)
    for a in range(0, n - HEADER_STRIDE, 4):
        rows, cols = struct.unpack(">HH", d[a:a + 4])
        if not (2 <= rows <= 64 and 1 <= cols <= 64):
            continue
        xp, yp, dp = struct.unpack(">III", d[a + 4:a + 16])
        if yp != xp + rows * 4 or dp != yp + cols * 4:
            continue
        if not (0x1000 < xp < n and dp + rows * cols * 2 <= n):
            continue
        scale, offset = struct.unpack(">ff", d[a + 20:a + 28])
        if scale != scale or offset != offset or scale == 0:
            continue
        if abs(scale) > 1e6 or abs(offset) > 1e6:
            continue
        out.append((a, rows, cols, xp, yp, dp, scale, offset))
    return out


def describe_axis(vals):
    """What a set of axis numbers resembles, stated as evidence not conclusion."""
    if not vals:
        return {}
    lo, hi = min(vals), max(vals)
    steps = [round(b - a, 4) for a, b in zip(vals, vals[1:])]
    even = len(set(steps)) == 1 if steps else False
    hints = []
    if abs(lo) < 1e-6 and 95 <= hi <= 105:
        hints.append("0..100, consistent with % pedal or % load")
    if hi > 3000 and lo >= 0:
        hints.append("reaches >3000, consistent with engine RPM")
    if -45 <= lo <= -30 and 100 <= hi <= 220:
        hints.append("spans about -40..+150, consistent with a temperature in C")
    if 0 <= lo and 120 <= hi <= 260 and not even:
        hints.append("0..~200, could be road speed in km/h")
    if hi <= 8 and len(vals) <= 8:
        hints.append("small integer ladder, consistent with a gear or mode index")
    return {"min": round(lo, 3), "max": round(hi, 3), "n": len(vals),
            "even_steps": even, "step": steps[0] if even and steps else None,
            "hints": hints}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(HERE, "denso_table_profiles.json"))
    ap.add_argument("--rom", default=None, help="profile one image (default: all)")
    args = ap.parse_args()

    roms = sorted(glob.glob(os.path.join(REPO, "rom-denso", "*.bin")))
    if args.rom:
        roms = [r for r in roms if args.rom in os.path.basename(r)]

    # index by header offset so the same table across firmwares can be matched
    by_key = {}
    for path in roms:
        d = open(path, "rb").read()
        cal = d[0x2000:0x2008].decode("ascii", "replace")
        for (hdr, rows, cols, xp, yp, dp, scale, offset) in scan(d):
            xs = [f32(d, xp + 4 * i) for i in range(rows)]
            ys = [f32(d, yp + 4 * i) for i in range(cols)]
            grid = [u16(d, dp + 2 * i) for i in range(rows * cols)]
            live = [v for v in grid if v != 255]
            key = "%dx%d@%06X" % (rows, cols, hdr)
            rec = by_key.setdefault(key, {
                "shape": "%dx%d" % (rows, cols), "header": hdr,
                "firmwares": [], "x": describe_axis(xs), "y": describe_axis(ys),
            })
            rec["firmwares"].append(cal)
            rec["value"] = {
                "min": min(grid), "max": max(grid),
                "distinct": len(set(grid)),
                "all_255": all(v == 255 for v in grid),
                "unused_rows": sum(1 for r in range(cols)
                                   if all(grid[r * rows + c] == 255 for c in range(rows))),
                "monotonic_rows": sum(1 for r in range(cols)
                                      if all(grid[r * rows + c] <= grid[r * rows + c + 1]
                                             for c in range(rows - 1))),
                "rows_total": cols,
                "live_min": min(live) if live else None,
                "live_max": max(live) if live else None,
            }

    with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(by_key, fh, indent=1, sort_keys=True)

    shapes = {}
    for k, v in by_key.items():
        shapes.setdefault(v["shape"], 0)
        shapes[v["shape"]] += 1
    print("profiled %d distinct tables across %d Denso images" % (len(by_key), len(roms)))
    print("shapes: %s" % ", ".join("%s x%d" % kv for kv in
                                   sorted(shapes.items(), key=lambda kv: -kv[1])[:10]))
    hinted = [k for k, v in by_key.items() if v["x"].get("hints") or v["y"].get("hints")]
    print("%d tables have at least one axis hint" % len(hinted))
    print("wrote %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
