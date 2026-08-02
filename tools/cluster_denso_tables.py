#!/usr/bin/env python3
"""Group the Denso tables into families, so naming is a few dozen decisions not 1770.

Tables that share a shape and an axis signature are the same table in different
firmwares, or the same quantity indexed slightly differently. Grouping them first
means a name is argued once per family and inherited by its members, and it makes the
evidence stronger: a signature that recurs across nine independent images is a real
structure, one that appears once is probably a coincidence that survived the header
filter.

Reads tools/denso_table_profiles.json from profile_denso_tables.py.

    python tools/cluster_denso_tables.py [--min-firmwares 2]
"""

import argparse
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
IN = os.path.join(HERE, "denso_table_profiles.json")
OUT = os.path.join(HERE, "denso_table_clusters.json")


def axis_sig(a):
    """A coarse fingerprint: shape of the axis, not its exact numbers."""
    if not a:
        return "none"
    return "%s|%s|%s" % (
        a.get("n"),
        ("even%s" % a.get("step")) if a.get("even_steps") else "uneven",
        ";".join(sorted(a.get("hints", []))) or "-",
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-firmwares", type=int, default=2)
    args = ap.parse_args()

    profiles = json.load(open(IN, encoding="utf-8"))

    groups = defaultdict(list)
    for key, p in profiles.items():
        sig = (p["shape"], axis_sig(p.get("x")), axis_sig(p.get("y")))
        groups[sig].append((key, p))

    out = []
    for sig, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        fws = set()
        for _k, p in members:
            fws.update(p["firmwares"])
        if len(fws) < args.min_firmwares:
            continue
        # monotonicity is the fact that separates a schedule (rises with the axis)
        # from a duty or a flat threshold, so carry it into the family record
        mono = sum(p["value"]["monotonic_rows"] for _k, p in members)
        rows = sum(p["value"]["rows_total"] for _k, p in members)
        unused = sum(p["value"]["unused_rows"] for _k, p in members)
        vmins = [p["value"]["min"] for _k, p in members]
        vmaxs = [p["value"]["max"] for _k, p in members]
        live = [p["value"]["live_max"] for _k, p in members if p["value"]["live_max"]]
        sample = members[0][1]
        out.append({
            "shape": sig[0],
            "x_signature": sig[1],
            "y_signature": sig[2],
            "members": len(members),
            "firmwares": len(fws),
            "x": sample.get("x"),
            "y": sample.get("y"),
            "value_min": min(vmins),
            "value_max": max(vmaxs),
            "live_max": max(live) if live else None,
            "mostly_unused": all(p["value"]["all_255"] for _k, p in members),
            "rows_monotonic_pct": round(100.0 * mono / rows, 1) if rows else 0,
            "rows_unused_pct": round(100.0 * unused / rows, 1) if rows else 0,
            "example_header": "0x%06X" % sample["header"],
        })

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1)

    print("%d families from %d tables (>= %d firmwares each)"
          % (len(out), len(profiles), args.min_firmwares))
    print()
    print("%-8s %7s %5s  %-40s %s" % ("shape", "members", "fw", "x axis", "values"))
    print("-" * 100)
    for g in out[:25]:
        xh = ", ".join(g["x"].get("hints", []))[:38] if g["x"] else ""
        print("%-8s %7d %5d  %-40s %d..%d%s"
              % (g["shape"], g["members"], g["firmwares"], xh,
                 g["value_min"], g["value_max"],
                 "  (all unused)" if g["mostly_unused"] else ""))
    print("\nwrote %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
