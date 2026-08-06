#!/usr/bin/env python3
"""Resolve a RomRaider ECU definition, following the base-definition chain.

RomRaider splits an ECU definition in two. A base entry - 32BITBASE and friends -
carries the shape of every table: type, axes, scaling, units. Each real
calibration then inherits from it and overrides only the addresses, because the
same table lives somewhere different in every ROM. Reading one half alone tells
you either what a table means or where it is, never both.

    python ecu_def.py AZ1G502L                    # summary + base chain
    python ecu_def.py AZ1G502L --grep torque      # matching tables, resolved
    python ecu_def.py --list-bases

Output for a table is the merged view: the name and scaling from the base, the
address from the calibration.
"""

import argparse
import xml.etree.ElementTree as ET


def load(path):
    """Every <rom> in the file, keyed by xmlid, with its declared base."""
    tree = ET.parse(path)
    roms = {}
    for rom in tree.getroot().iter("rom"):
        rid = rom.find("romid")
        if rid is None:
            continue
        xmlid = (rid.findtext("xmlid") or "").strip()
        if xmlid:
            roms[xmlid] = rom
    return roms


def chain(roms, xmlid):
    """The inheritance chain, most-derived first."""
    out, seen = [], set()
    cur = xmlid
    while cur and cur in roms and cur not in seen:
        seen.add(cur)
        out.append(cur)
        cur = roms[cur].get("base")
    return out


def merged_tables(roms, xmlid):
    """Tables for a calibration, base shape merged with derived addresses.

    Walked from the base outward so a derived entry overwrites what it
    redefines - which is the whole point of the split.
    """
    tables = {}
    for name in reversed(chain(roms, xmlid)):
        for t in roms[name].findall("table"):
            key = t.get("name")
            if key is None:
                continue
            cur = dict(tables.get(key, {}).get("attrib", {}))
            cur.update(t.attrib)
            axes = tables.get(key, {}).get("axes", {})
            axes = dict(axes)
            for sub in t.findall("table"):
                sk = sub.get("type") or sub.get("name")
                merged = dict(axes.get(sk, {}))
                merged.update(sub.attrib)
                axes[sk] = merged
            tables[key] = {"attrib": cur, "axes": axes, "from": name}
    return tables


def show(name, info):
    a = info["attrib"]
    print("\n%s" % name)
    print("   defined in : %s" % info["from"])
    for k in ("type", "storageaddress", "storagetype", "endian", "sizex",
              "sizey", "scaling", "category", "level", "swapxy"):
        if a.get(k):
            print("   %-11s: %s" % (k, a[k]))
    for ax, at in sorted(info["axes"].items()):
        bits = " ".join("%s=%s" % (k, v) for k, v in sorted(at.items())
                        if k in ("name", "storageaddress", "storagetype",
                                 "sizex", "sizey", "scaling", "elements"))
        print("   axis %-6s: %s" % (ax, bits))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xmlid", nargs="?")
    ap.add_argument("--xml", default="ecu_defs.xml")
    ap.add_argument("--grep", default="")
    ap.add_argument("--list-bases", action="store_true")
    ap.add_argument("--names-only", action="store_true")
    args = ap.parse_args()

    roms = load(args.xml)

    if args.list_bases:
        bases = {}
        for x, r in roms.items():
            bases[r.get("base") or "(none)"] = bases.get(r.get("base") or "(none)", 0) + 1
        for b, n in sorted(bases.items(), key=lambda kv: -kv[1]):
            print("%-14s %d calibrations inherit from this" % (b, n))
        return

    if not args.xmlid:
        ap.error("need an xmlid")
    if args.xmlid not in roms:
        print("no such calibration: %s" % args.xmlid)
        return

    rid = roms[args.xmlid].find("romid")
    print("=== %s ===" % args.xmlid)
    for f in ("year", "market", "model", "submodel", "transmission", "memmodel",
              "filesize", "ecuid", "internalidaddress", "internalidstring",
              "flashmethod", "caseid"):
        v = (rid.findtext(f) or "").strip()
        if v:
            print("   %-18s %s" % (f, v))
    print("   %-18s %s" % ("base chain", " -> ".join(chain(roms, args.xmlid))))

    tables = merged_tables(roms, args.xmlid)
    print("\n%d tables resolved" % len(tables))

    hits = [n for n in sorted(tables) if args.grep.lower() in n.lower()]
    if args.grep:
        print("%d match %r" % (len(hits), args.grep))
    if args.names_only:
        for n in hits:
            print("   %s" % n)
        return
    for n in hits:
        show(n, tables[n])


if __name__ == "__main__":
    main()
