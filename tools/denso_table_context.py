#!/usr/bin/env python3
"""What each Denso calibration table is read alongside.

A table's shape says nothing about its purpose. What it is read *with* says a great
deal: a table looked up in a routine that also reads pedal position and gear is a
shift or pressure map indexed by those, and one read beside ATF temperature is a
temperature compensation.

This walks the disassembly function by function - SH-2 marks the end of one with
`rts`, so segmenting on that is reliable - and records, for each function, which
table headers it reads and which named working variables it touches. The join is
the context.

Needs:
  * a listing from tools/ghidra/DensoDisasmAll.java (section 46)
  * tools/denso_indexed_tables.json for the real headers (section 48)
  * tools/denso_working_vars.json for the named variables (section 47)

    python tools/denso_table_context.py disasm-denso/Impreza_STI_3.583_JDM2011.asm

Writes tools/denso_table_context.json. Nothing here renames a table on its own -
it produces candidates, and a candidate still has to survive being checked against
the data and the logs.
"""

import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
IDX = os.path.join(HERE, "denso_indexed_tables.json")
VARS = os.path.join(HERE, "denso_working_vars.json")
SSM = os.path.join(HERE, "ssm_parameters.json")
OUT = os.path.join(HERE, "denso_table_context.json")

LOAD = re.compile(
    r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s*_?(mov\.[lw])\s+@\(0x([0-9a-f]+),pc\),(\w+)")
ANY = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s*_?(\S+)")


def rom_for(listing):
    stem = os.path.splitext(os.path.basename(listing))[0]
    p = os.path.join(REPO, "rom-denso", stem + ".bin")
    return p if os.path.exists(p) else None


def calid_for(data):
    if not os.path.exists(IDX):
        return None, {}
    idx = json.load(open(IDX, encoding="utf-8"))
    for cid, v in idx.items():
        if cid.encode() in data:
            return cid, v
    return None, {}


def named_vars(listing):
    """RAM address -> name, from the traced working variables and direct hits."""
    out = {}
    if os.path.exists(VARS):
        v = json.load(open(VARS, encoding="utf-8"))
        if v.get("listing") == os.path.basename(listing):
            for a, d in v.get("variables", {}).items():
                out[int(d["working"] if isinstance(d, dict) else a, 16)
                    if False else d["working"]] = d["name"]
            for a, n in v.get("direct", {}).items():
                out[int(a, 16)] = n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing")
    ap.add_argument("--show", type=int, default=30)
    ap.add_argument("--var", help="only tables read alongside this RAM address")
    args = ap.parse_args()

    rom_path = rom_for(args.listing)
    if not rom_path:
        sys.stderr.write("no ROM image for %s\n" % args.listing)
        return 1
    data = open(rom_path, "rb").read()
    calid, idx = calid_for(data)
    if not idx:
        sys.stderr.write("no pointer index for this image\n")
        return 1
    headers = {t["header"]: t for t in idx["tables"]}
    variables = named_vars(args.listing)

    # Walk the listing, splitting on rts. The delay slot after rts belongs to the
    # function it terminates, so the split happens one instruction later.
    funcs, cur = [], {"start": None, "tables": set(), "rams": set()}
    pending_end = False
    for line in open(args.listing, encoding="utf-8", errors="replace"):
        m = ANY.match(line.rstrip("\n"))
        if not m:
            continue
        addr, mnem = int(m.group(1), 16), m.group(2)
        if mnem.startswith("."):
            continue
        if cur["start"] is None:
            cur["start"] = addr

        ld = LOAD.match(line.rstrip("\n"))
        if ld:
            pool = int(ld.group(3), 16)
            size = 4 if ld.group(2) == "mov.l" else 2
            if pool + size <= len(data):
                if size == 4:
                    val = struct.unpack_from(">I", data, pool)[0]
                else:
                    val = struct.unpack_from(">h", data, pool)[0] & 0xFFFFFFFF
                if val in headers:
                    cur["tables"].add(val)
                elif val >= 0xFFFF0000:
                    cur["rams"].add(val)

        if pending_end:
            funcs.append(cur)
            cur = {"start": None, "tables": set(), "rams": set()}
            pending_end = False
        elif mnem == "rts":
            pending_end = True
    if cur["start"] is not None:
        funcs.append(cur)

    # Context per table: the named variables it shares a function with.
    ctx = {}
    for f in funcs:
        if not f["tables"]:
            continue
        names = sorted({variables[r] for r in f["rams"] if r in variables})
        for t in f["tables"]:
            e = ctx.setdefault(t, {"funcs": 0, "with": {}, "rams": set()})
            e["funcs"] += 1
            e["rams"].update(f["rams"])
            for n in names:
                e["with"][n] = e["with"].get(n, 0) + 1

    withctx = {t: e for t, e in ctx.items() if e["with"]}
    print("%s  calid %s" % (os.path.basename(args.listing), calid))
    print("%d functions, %d indexed tables, %d tables read in a function that also "
          "touches a named variable\n" % (len(funcs), len(headers), len(withctx)))

    if args.var:
        want = int(args.var, 16)
        sel = {t: e for t, e in ctx.items() if want in e["rams"]}
        print("%d tables read alongside 0x%08X:" % (len(sel), want))
        for t in sorted(sel):
            h = headers[t]
            print("   header 0x%06X  %dx%d" % (t, h["rows"], h["cols"]))
    else:
        print("%-16s %-8s %s" % ("header", "size", "read alongside"))
        print("-" * 88)
        for t in sorted(withctx, key=lambda x: -len(withctx[x]["with"]))[:args.show]:
            h, e = headers[t], withctx[t]
            tags = ", ".join("%s" % n for n in sorted(e["with"]))
            print("0x%06X       %-8s %s" % (t, "%dx%d" % (h["rows"], h["cols"]),
                                            tags[:60]))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({
            "listing": os.path.basename(args.listing),
            "calid": calid,
            "functions": len(funcs),
            "tables": len(headers),
            "with_context": len(withctx),
            "context": {("%06X" % t): {
                "rows": headers[t]["rows"], "cols": headers[t]["cols"],
                "funcs": e["funcs"], "with": e["with"],
            } for t, e in ctx.items()},
        }, fh, indent=1, sort_keys=True)
    print("\n-> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
