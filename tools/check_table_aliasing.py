#!/usr/bin/env python3
"""Find tables that share ROM bytes, so editing one silently changes another.

The Hitachi shift maps are sparse: each declares a cellIndices list naming the
exact offset of every cell, which is why several tables legitimately share one
storage address. The existing validator checks that a table does not alias itself
- no index twice in one cellIndices - but nothing checks aliasing BETWEEN tables.

That gap matters to whoever is tuning. "Shift Map - Normal, 3" and
"Shift Map - Normal, 4" begin with identical index lists; if they overlap, an
edit to one changes the other, and a tuner who does not know that will chase a
change they did not make.

This does not assume overlap is a bug. Two gears sharing a schedule may be
exactly what the firmware does. The point is to state it, so that it is a
documented property rather than a surprise.

    python tools/check_table_aliasing.py
    python tools/check_table_aliasing.py --definition <path> --verbose

Exit status is non-zero only if a table aliases ITSELF, which is never right.
"""

import argparse
import collections
import os
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WIDTH = {"uint8": 1, "int8": 1, "uint16": 2, "int16": 2,
         "uint32": 4, "int32": 4, "float": 4}


def cells_of(tab):
    """Every ROM byte offset this table's cells occupy."""
    addr = tab.get("storageaddress")
    if not addr:
        return set()
    base = int(addr, 16)
    w = WIDTH.get(tab.get("storagetype") or "uint16", 2)
    ci = tab.get("cellIndices")
    out = set()
    if ci:
        for v in (int(x) for x in ci.split(",")):
            if v >= 0:
                out.update(range(base + v * 2, base + v * 2 + w))
        return out
    # A Switch table's sizey is a BYTE count, not a row count, and it has no
    # storagetype. Treating it as rows of uint16 doubles its extent, so each
    # two-byte code ran into the next one and 387 imaginary alias pairs appeared
    # the moment the DTC switches were added - a checker inventing the very fault
    # it exists to detect.
    if (tab.get("type") or "") == "Switch":
        return set(range(base, base + int(tab.get("sizey") or 1)))
    sx = int(tab.get("sizex") or 1)
    sy = int(tab.get("sizey") or 1)
    return set(range(base, base + sx * sy * w))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--definition", action="append", default=[])
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    defs = args.definition or [
        os.path.join(REPO, "definitions", "5eat_tcu_romraider_defs.xml"),
        os.path.join(REPO, "definitions", "5eat_tcu_denso_romraider_defs.xml"),
    ]

    self_alias, shared_total, firmwares = 0, 0, 0
    for path in defs:
        print("=== %s" % os.path.basename(path))
        for rom_el in ET.parse(path).getroot().iter("rom"):
            rid = rom_el.find("romid")
            ident = (rid.findtext("internalidstring") or "?").strip() if rid is not None else "?"
            firmwares += 1
            tabs = [(t.get("name") or "?", t) for t in rom_el.findall("table")]

            # A cell index repeated inside one table means two of its own cells
            # edit the same bytes. That is never intentional.
            for name, t in tabs:
                ci = t.get("cellIndices")
                if not ci:
                    continue
                real = [int(x) for x in ci.split(",") if int(x) >= 0]
                if len(set(real)) != len(real):
                    self_alias += 1
                    print("  %-10s %s aliases itself: %d duplicate cell(s)"
                          % (ident, name, len(real) - len(set(real))))

            owners = collections.defaultdict(list)
            for name, t in tabs:
                for b in cells_of(t):
                    owners[b].append(name)
            pairs = collections.Counter()
            for b, ns in owners.items():
                if len(ns) > 1:
                    for i in range(len(ns)):
                        for j in range(i + 1, len(ns)):
                            pairs[tuple(sorted((ns[i], ns[j])))] += 1
            # Two kinds of sharing, and lumping them together says nothing useful.
            # A strided 2D curve stores its breakpoints and its values in
            # alternating fields of one record array, so the two tables MUST
            # overlap - that is the format, not a fault. Two different shift maps
            # overlapping is a real statement about the calibration: edit one gear
            # and another changes with it.
            # Comparing only the stem before the last " - " is not enough, and
            # failing quietly: "Shift Map - Normal, 3" has the stem "Shift Map",
            # so every shift map matched every other one and the cross-gear
            # sharing this check exists to find disappeared from the report.
            #
            # The suffix has to be a ROLE - the axis or the values of one curve -
            # and not a variant name. Roles are a short closed list; a variant is
            # anything else, and treating an unrecognised suffix as a variant errs
            # toward reporting a pair rather than hiding it.
            ROLES = {"breakpoint", "breakpoints", "value", "values", "adc",
                     "°c", "c", "kpa", "km/h", "rpm", "%", "ms"}

            def same_curve(a, b):
                if " - " not in a or " - " not in b:
                    return False
                sa, ra = a.rsplit(" - ", 1)
                sb, rb = b.rsplit(" - ", 1)
                return (sa == sb and ra != rb
                        and ra.strip().lower() in ROLES
                        and rb.strip().lower() in ROLES)

            by_format = {p: n for p, n in pairs.items() if same_curve(*p)}
            real = {p: n for p, n in pairs.items() if not same_curve(*p)}
            if pairs:
                shared_total += len(real)
                print("  %-10s %d pair(s) share bytes: %d are one curve's "
                      "breakpoints and values, %d are distinct tables"
                      % (ident, len(pairs), len(by_format), len(real)))
                for (a, b), n in collections.Counter(real).most_common(
                        None if args.verbose else 5):
                    print("       %-30s <-> %-30s %d bytes" % (a[:30], b[:30], n))
                if not args.verbose and len(real) > 5:
                    print("       ... and %d more, use --verbose" % (len(real) - 5))
            else:
                print("  %-10s no shared bytes" % ident)

    print("\n%d firmwares examined." % firmwares)
    print("%d table pair(s) share ROM bytes - editing one changes the other."
          % shared_total)
    if self_alias:
        print("%d table(s) alias themselves, which is always wrong." % self_alias)
        return 1
    print("No table aliases itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
