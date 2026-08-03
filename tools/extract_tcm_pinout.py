#!/usr/bin/env python3
"""Reconstruct the 5EAT TCM connector pinout from the service manual's diagnostics.

There is no single terminal table for connectors B54 and B55 in the manual, but the
fault-finding procedures reference individual pins constantly - "measure between
(B54) No. 23 and chassis ground" inside the lock-up solenoid procedure, and so on.
Each reference sits under a DTC heading that names the circuit, so collecting them
reconstructs the pinout.

This matters because a bench rig cannot be wired without it, and the pinout that
circulates on the forum is for a different unit (FINDINGS section 18d).

    python tools/extract_tcm_pinout.py <TRANSMISSION_SECTION.txt> [more.txt ...]

Prints a pin table and writes tools/tcm_pinout.json.
"""

import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "tcm_pinout.json")

PIN = re.compile(r"\(B(5[45])\)\s*No\.\s*(\d+)")
# a DTC heading names the circuit the following pins belong to
DTC = re.compile(r"\bDTC\s+(P[0-9]{4}|U[0-9]{4})\s+(.{6,70})")
# so does a bare component heading in the fault-finding index
COMP = re.compile(r"^\s*(?:[0-9]+\.\s*)?([A-Z][A-Za-z/ &\-]{8,60}(?:SENSOR|SOLENOID|SWITCH|"
                  r"CIRCUIT|SIGNAL|POWER SUPPLY|GROUND|LINE))\s*$")


def circuits(lines):
    """Index -> the circuit heading in force at that line."""
    cur, out = "", []
    for line in lines:
        m = DTC.search(line)
        if m:
            cur = "%s %s" % (m.group(1), m.group(2).strip().rstrip(":"))
        else:
            c = COMP.match(line)
            if c:
                cur = c.group(1).strip()
        out.append(cur)
    return out


def main():
    paths = sys.argv[1:] or ["/home/rust/fsm/TRANSMISSION_SECTION.txt"]
    hits = defaultdict(lambda: defaultdict(int))

    for p in paths:
        if not os.path.exists(p):
            sys.stderr.write("missing: %s\n" % p)
            continue
        lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
        ctx = circuits(lines)
        for i, line in enumerate(lines):
            for conn, pin in PIN.findall(line):
                if ctx[i]:
                    hits[("B" + conn, int(pin))][ctx[i]] += 1

    table = {}
    print("%-6s %-4s %s" % ("conn", "pin", "circuit (from the DTC or component heading)"))
    print("-" * 88)
    for key in sorted(hits, key=lambda k: (k[0], k[1])):
        best = max(hits[key], key=hits[key].get)
        n = hits[key][best]
        table.setdefault(key[0], {})[key[1]] = {"circuit": best, "mentions": n}
        print("%-6s %-4d %s" % (key[0], key[1], best[:66]))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(table, fh, indent=1, sort_keys=True)
    print("\n%d pins across %d connectors -> %s"
          % (sum(len(v) for v in table.values()), len(table), OUT))
    print("\nReconstructed from diagnostics, not read off a terminal table. Verify any")
    print("pin against the manual before connecting power to it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
