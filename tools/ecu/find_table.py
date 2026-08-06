#!/usr/bin/env python3
"""Which calibrations actually locate a given table?

The base definition says what a table is; only a calibration says where it lives.
A table can be perfectly well defined and still be unusable for a particular ROM
because nobody ever found it in that one. This answers the question that matters
before hunting for a ROM: which calibrations carry an address for this table, and
of those, which are the cars we care about.

    python find_table.py "Requested Torque (Accelerator Pedal)"
    python find_table.py "Requested Torque" --at
"""

import argparse
import xml.etree.ElementTree as ET

FIELDS = ("year", "market", "model", "submodel", "transmission", "memmodel")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--xml", default="ecu_defs.xml")
    ap.add_argument("--at", action="store_true")
    ap.add_argument("--exact", action="store_true")
    args = ap.parse_args()

    tree = ET.parse(args.xml)
    hits = []
    for rom in tree.getroot().iter("rom"):
        rid = rom.find("romid")
        if rid is None:
            continue
        xmlid = (rid.findtext("xmlid") or "").strip()
        meta = {f: (rid.findtext(f) or "").strip() for f in FIELDS}
        if args.at and "AT" not in meta["transmission"].upper():
            continue
        for t in rom.findall("table"):
            name = t.get("name") or ""
            ok = (name == args.table) if args.exact else (
                args.table.lower() in name.lower())
            if ok and t.get("storageaddress"):
                hits.append((xmlid, meta, name, t.get("storageaddress")))

    by_cal = {}
    for xmlid, meta, name, addr in hits:
        by_cal.setdefault(xmlid, (meta, []))[1].append((name, addr))

    print("%d calibrations locate a table matching %r\n" % (len(by_cal), args.table))
    for xmlid in sorted(by_cal, key=lambda x: (by_cal[x][0]["year"], x)):
        meta, tabs = by_cal[xmlid]
        print("%-10s %-3s %-6s %-22s %-14s %-6s %-8s  %d table(s)"
              % (xmlid, meta["year"], meta["market"], meta["model"],
                 meta["submodel"], meta["transmission"], meta["memmodel"],
                 len(tabs)))
        for n, a in sorted(tabs):
            print("        0x%-8s %s" % (a, n))


if __name__ == "__main__":
    main()
