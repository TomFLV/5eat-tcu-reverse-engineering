#!/usr/bin/env python3
"""Name the shipped Denso tables through the pointer index that reaches them.

Section 74b established why the previous attempt named nothing useful: it followed
tables that appear as literals in code, and the tables the definition ships are not
reached that way. They are reached through a pointer index - a block of addresses
pointing at table headers - so the code never names a table directly, only the
index.

That gives a different chain, one step longer:

    table header -> the index run that points at it
                 -> the code that loads that run
                 -> the function containing it
                 -> the RAM that function writes
                 -> what those addresses are known to be

It is coarser than naming one table at a time: everything in a run shares the
evidence of the function that walks it. That is a real limitation and is reported
as such - a run of 41 tables all "read by the code that writes line pressure" says
those 41 are part of the pressure calculation, not that each one is line pressure.
Coarse and true beats precise and invented.

    python tools/denso_name_indexed.py
    python tools/denso_name_indexed.py --json out.json
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, REPO_WSL, WORK, WORK_WSL, SH2_WSL  # noqa: E402

import argparse
import bisect
import json
import re
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
ROM = os.path.join(REPO, "rom-denso", "Impreza_STI_3.583_JDM2011.bin")
LISTING = os.path.join(REPO, "disasm-denso", "Impreza_STI_3.583_JDM2011.asm")
INDEXED = os.path.join(HERE, "denso_indexed_tables.json")
XREF = WORK + "/xref.json"
SSM = os.path.join(HERE, "denso_ssm_addresses.json")
CALID = "WQDE2WB1"

ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s+_?(\S+)\s*([^;]*)(?:;(.*))?$")
PROLOGUE = re.compile(r"^(r\d+|pr),@-r15$")
POINTER = re.compile(r"\.pointer\s+([0-9a-f]{6,8})")


def parse_listing():
    """Function starts, and every literal pool entry, in one pass."""
    starts, pool = [], {}
    with open(LISTING, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = ROW.match(line.rstrip("\n"))
            if not m:
                continue
            addr, mnem, ops = int(m.group(1), 16), m.group(2), m.group(3).strip()
            if mnem in ("mov.l", "sts.l") and PROLOGUE.match(ops.split(";")[0].strip()):
                starts.append(addr)
            p = POINTER.search(mnem + " " + ops)
            if p:
                pool[addr] = int(p.group(1), 16)
    starts.sort()
    out = []
    for a in starts:
        if not out or a - out[-1] > 2:
            out.append(a)
    return out, pool


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()

    rom = open(ROM, "rb").read()
    idx = json.load(open(INDEXED, encoding="utf-8"))
    runs = (idx.get(CALID) or list(idx.values())[0])["runs"]
    starts, pool = parse_listing()
    sys.stderr.write("%d functions, %d literal pool entries, %d index runs\n"
                     % (len(starts), len(pool), len(runs)))

    names = {}
    try:
        for k, v in json.load(open(SSM, encoding="utf-8")).items():
            names[int(k, 16)] = v
    except (OSError, ValueError):
        pass

    xr = json.load(open(XREF, encoding="utf-8"))

    def enclosing(a):
        i = bisect.bisect_right(starts, a)
        return starts[i - 1] if i else None

    fn_writes = {}
    for a, sites in xr["writes"].items():
        av = int(a, 16)
        for s in sites:
            f = enclosing(s)
            if f is not None:
                fn_writes.setdefault(f, set()).add(av)

    # A pool entry holding an address inside a run is the code's handle on it.
    result = {}
    for run in runs:
        lo = run["at"]
        hi = lo + run["entries"] * 4
        users = set()
        for pool_addr, val in pool.items():
            if lo <= val < hi:
                f = enclosing(pool_addr)
                if f is not None:
                    users.add(f)
        if not users:
            continue
        known = set()
        for f in users:
            for a in fn_writes.get(f, ()):
                if a in names:
                    known.add(names[a])
        if not known:
            continue
        headers = ["%06X" % struct.unpack_from(">I", rom, lo + 4 * i)[0]
                   for i in range(run["entries"])]
        result["%06X" % lo] = {
            "entries": run["entries"],
            "used_by": ["%08X" % f for f in sorted(users)],
            "writes": sorted(known),
            "headers": headers,
        }

    total = sum(r["entries"] for r in result.values())
    print("\n%d of %d index runs are reached by code that writes something named"
          % (len(result), len(runs)))
    print("covering %d table headers\n" % total)
    for at, v in sorted(result.items(), key=lambda kv: -kv[1]["entries"]):
        print("  run 0x%s  %d tables  used by %s"
              % (at, v["entries"], ", ".join(v["used_by"][:2])))
        print("     writes: %s" % ", ".join(v["writes"])[:130])

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
        print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
