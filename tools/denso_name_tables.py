#!/usr/bin/env python3
"""Name Denso tables from what the code that reads them goes on to write.

The Denso definition ships 133 tables worth opening and names 12 of them. Grouping
by axes (FINDINGS 68) made the rest navigable but says nothing about what any of
them does. This is the step that can: a table is read by a function, that function
writes RAM addresses, and some of those addresses are ones the dependency map and
the Select Monitor table have already identified.

    table -> reading function -> addresses it writes -> what those are known to be

Nothing here guesses from shape. A table whose reader writes the address the SSM
table calls Accelerator Pedal Travel is evidence; a 11x5 table indexed by pedal and
gear is not. Where the chain produces nothing the table stays unnamed, which is the
honest answer and the one this project keeps having to relearn.

    python tools/denso_name_tables.py            # what can be named, and how
    python tools/denso_name_tables.py --json out.json
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, REPO_WSL, WORK, WORK_WSL, SH2_WSL  # noqa: E402

import argparse
import bisect
import json
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LISTING = os.path.join(REPO, "disasm-denso", "Impreza_STI_3.583_JDM2011.asm")
LITERALS = os.path.join(HERE, "denso_literals.json")
XREF = WORK + "/xref.json"
DEPMAP = os.path.join(HERE, "denso_depmap.json")
WORKING = os.path.join(HERE, "denso_working_vars.json")

ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s+_?(\S+)\s*(.*)$")
PROLOGUE = re.compile(r"^(r\d+|pr),@-r15$")


def function_starts():
    """Where each function begins, so a code address can be attributed to one."""
    starts = []
    with open(LISTING, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = ROW.match(line.rstrip("\n"))
            if not m:
                continue
            mnem, ops = m.group(2), m.group(3).split(";")[0].strip()
            if mnem in ("mov.l", "sts.l") and PROLOGUE.match(ops):
                starts.append(int(m.group(1), 16))
    starts.sort()
    # Collapse a prologue's consecutive saves into one entry.
    out = []
    for a in starts:
        if not out or a - out[-1] > 2:
            out.append(a)
    return out


def load_names():
    """Every RAM address this project has a name for, from any source."""
    names = {}
    try:
        w = json.load(open(WORKING, encoding="utf-8"))
        for k, v in w.get("direct", {}).items():
            names[int(k, 16)] = v
        for k, v in w.get("variables", {}).items():
            if isinstance(v, dict) and v.get("name"):
                names[int(k, 16)] = v["name"]
                if isinstance(v.get("working"), int):
                    names.setdefault(v["working"], v["name"] + " (working copy)")
    except (OSError, ValueError):
        pass
    # The Select Monitor table is the large source and was going unused: the
    # addresses are in it under "ram", and reading the wrong key made it look as
    # though only a couple of dozen addresses had names. There are 141, including
    # every solenoid current channel, which is what turns this from a curiosity
    # into something that can name control tables.
    try:
        ssm = json.load(open(os.path.join(HERE, "denso_ssm_addresses.json"),
                             encoding="utf-8"))
        for k, v in ssm.items():
            names.setdefault(int(k, 16), v)
    except (OSError, ValueError):
        pass
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--min-evidence", type=int, default=1)
    args = ap.parse_args()

    lit = json.load(open(LITERALS, encoding="utf-8"))
    tables = {int(k, 16): v for k, v in lit["tables"].items()}
    xr = json.load(open(XREF, encoding="utf-8"))
    writes = {}
    for a, sites in xr["writes"].items():
        for s in sites:
            writes.setdefault(s, []).append(int(a, 16))
    names = load_names()

    # Addresses the dependency map showed responding to a known input.
    driven = {}
    if os.path.exists(DEPMAP):
        dm = json.load(open(DEPMAP, encoding="utf-8"))
        for inp, outs in dm.items():
            for o in outs:
                driven.setdefault(int(o, 16), []).append(inp)

    starts = function_starts()
    sys.stderr.write("%d functions, %d tables referenced, %d named addresses\n"
                     % (len(starts), len(tables), len(names)))

    def enclosing(addr):
        i = bisect.bisect_right(starts, addr)
        return starts[i - 1] if i else None

    # Which RAM each function writes.
    fn_writes = {}
    for site, addrs in writes.items():
        f = enclosing(site)
        if f is not None:
            fn_writes.setdefault(f, set()).update(addrs)

    result = {}
    for tbl, sites in sorted(tables.items()):
        fns = {enclosing(s) for s in sites}
        fns.discard(None)
        evidence = {}
        for f in fns:
            for a in fn_writes.get(f, ()):
                if a in names:
                    evidence.setdefault("named", set()).add(names[a])
                if a in driven:
                    for inp in driven[a]:
                        evidence.setdefault("responds_to", set()).add(inp)
        if evidence:
            result["%06X" % tbl] = {
                "functions": ["%08X" % f for f in sorted(fns)],
                "named": sorted(evidence.get("named", ())),
                "responds_to": sorted(evidence.get("responds_to", ())),
            }

    print("\n%d of %d referenced tables have a reader that writes something known\n"
          % (len(result), len(tables)))
    shown = 0
    for t, v in sorted(result.items(), key=lambda kv: -len(kv[1]["named"])):
        if not v["named"]:
            continue
        print("  table 0x%s  read by %s" % (t, ", ".join(v["functions"][:2])))
        print("     writes: %s" % ", ".join(v["named"][:4]))
        shown += 1
        if shown >= 25:
            break

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
        print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
