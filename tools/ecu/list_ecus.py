#!/usr/bin/env python3
"""List every ECU calibration in the RomRaider definition file.

We need the ECU that sits on the other end of the CAN bus from our TCU. The TCU
image is Impreza_STI_3.583_JDM2011 - a JDM STI A-Line, which is the 5EAT car -
so the match is a JDM automatic, not the 6MT the STI name usually implies.

    python list_ecus.py                 # everything
    python list_ecus.py --at            # automatics only
    python list_ecus.py --grep impreza
"""

import argparse
import xml.etree.ElementTree as ET

FIELDS = ("xmlid", "year", "market", "make", "model", "submodel",
          "transmission", "memmodel", "flashmethod", "internalidstring")


def roms(path):
    for _ev, el in ET.iterparse(path, events=("end",)):
        if el.tag != "romid":
            continue
        d = {f: (el.findtext(f) or "").strip() for f in FIELDS}
        # A base definition carries the tables; the per-car entries inherit from
        # it and only override addresses. Both are listed - the base is what to
        # read table shapes from, the child is what identifies a real ROM.
        d["base"] = "yes" if not d["internalidstring"] else ""
        yield d
        el.clear()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", default="ecu_defs.xml")
    ap.add_argument("--at", action="store_true", help="automatics only")
    ap.add_argument("--grep", default="")
    ap.add_argument("--year", default="")
    args = ap.parse_args()

    rows = []
    for d in roms(args.xml):
        if args.at and "AT" not in d["transmission"].upper():
            continue
        if args.year and args.year not in d["year"]:
            continue
        if args.grep:
            blob = " ".join(d[f] for f in FIELDS).lower()
            if args.grep.lower() not in blob:
                continue
        rows.append(d)

    rows.sort(key=lambda d: (d["year"], d["model"], d["xmlid"]))
    print("%-12s %-5s %-7s %-26s %-16s %-6s %s"
          % ("XMLID", "YEAR", "MARKET", "MODEL", "SUBMODEL", "TRANS", "MEM"))
    for d in rows:
        print("%-12s %-5s %-7s %-26s %-16s %-6s %s"
              % (d["xmlid"][:12], d["year"], d["market"][:7], d["model"][:26],
                 d["submodel"][:16], d["transmission"][:6], d["memmodel"]))
    print("\n%d calibrations" % len(rows))


if __name__ == "__main__":
    main()
