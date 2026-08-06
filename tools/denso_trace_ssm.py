#!/usr/bin/env python3
"""Name Denso working variables by tracing the Select Monitor buffer fill.

The Select Monitor does not read the control variables directly. A routine copies
each one into a contiguous staging buffer just before the reply is sent, so the
table of section 42 names buffer slots rather than the variables the transmission
logic actually uses.

The copy is what bridges them, and on this family it is a run of very small
functions, each of the same shape:

    mov.l  @(0x7fcf0,pc),r6    ; = 0xFFFF3B17     the working variable
    mov.b  @r6,r2                                 read it
    mov.l  @(0x7fcf4,pc),r6    ; = 0xFFFFA9F7     the buffer slot
    rts
    mov.b  r2,@r6                                 write it

So: for each write into the buffer, the nearest preceding RAM literal that is not
itself a buffer address is the source. Where the copy scales or clamps the value,
the arithmetic in between is reported too, because that is the scaling.

This is the Denso equivalent of what map_ssm_parameters.py does for the M32R, and
it needs a listing from DensoDisasmAll.java - the decompiled C does not contain the
literal pools these addresses live in (section 46).

    python tools/denso_trace_ssm.py disasm-denso/Impreza_STI_3.583_JDM2011.asm

Writes tools/denso_working_vars.json.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SSM_JSON = os.path.join(HERE, "ssm_parameters.json")
OUT = os.path.join(HERE, "denso_working_vars.json")

LINE = re.compile(r"^([0-9A-F]{8})\s+((?:[0-9A-F]{2} )+)\s*(\S.*?)\s*(?:;\s*(.*))?$")
RAMREF = re.compile(r"->\s*RAM\s*0x([0-9A-F]{8})")

# How far back to look for the source. The copy routines are a handful of
# instructions; a wider window starts crossing into unrelated code.
WINDOW = 12


def ssm_names(listing):
    stem = os.path.splitext(os.path.basename(listing))[0]
    if not os.path.exists(SSM_JSON):
        return {}, set()
    data = json.load(open(SSM_JSON, encoding="utf-8"))
    info = data.get(stem + ".bin")
    if not info:
        return {}, set()
    names, targets = {}, set()
    for r in info["rows"]:
        targets.add(r["ram"])
        label = r.get("name")
        if not label and r.get("switches"):
            label = "; ".join(s["name"] for s in r["switches"])
        if label:
            names[r["ram"]] = label
    return names, targets


def load(path):
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = LINE.match(line.rstrip("\n"))
        if not m:
            continue
        body = m.group(3)
        if body.startswith("."):
            continue
        ram = RAMREF.search(m.group(4) or "")
        rows.append({
            "rom": int(m.group(1), 16),
            "insn": body.strip().lstrip("_"),
            "ram": int(ram.group(1), 16) if ram else None,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing")
    ap.add_argument("--show", type=int, default=40)
    args = ap.parse_args()

    if not os.path.exists(args.listing):
        sys.stderr.write("no such listing: %s\n" % args.listing)
        return 1

    names, buffer_addrs = ssm_names(args.listing)
    if not names:
        sys.stderr.write("no Select Monitor names for this image; "
                         "run tools/map_ssm_parameters.py first\n")
        return 1

    rows = load(args.listing)
    hits = {}
    for i, r in enumerate(rows):
        if r["ram"] in buffer_addrs:
            hits.setdefault(r["ram"], []).append(i)

    # Not every address the table names is a staging slot. Some parameters are
    # pointed straight at the working variable - pedal travel is one - and those
    # must not be traced: there is nothing behind them, so walking back just picks
    # up whatever literal happens to be near and invents a wrong answer. The first
    # version of this did exactly that and reported pedal travel as 0xFFFF301C,
    # which is a different variable entirely.
    #
    # The staging buffer is the long contiguous run of named addresses, each
    # touched exactly once. Anything outside that run, or used more than once, is
    # already the working variable.
    single = sorted(a for a in hits if a in names and len(hits[a]) == 1)
    buffer_run = set()
    if single:
        run = [single[0]]
        for a in single[1:]:
            if a - run[-1] <= 2:
                run.append(a)
            else:
                if len(run) > len(buffer_run):
                    buffer_run = set(run)
                run = [a]
        if len(run) > len(buffer_run):
            buffer_run = set(run)

    direct = {a: names[a] for a in hits if a in names and a not in buffer_run}

    traced = {}
    for addr, idxs in hits.items():
        if addr not in names or addr not in buffer_run:
            continue
        for i in idxs:
            source, ops = None, []
            for j in range(i - 1, max(-1, i - WINDOW), -1):
                r = rows[j]
                if r["ram"] is not None and r["ram"] not in buffer_addrs:
                    source = r["ram"]
                    break
                if r["ram"] is None:
                    ops.append(r["insn"])
            if source is not None:
                traced[addr] = {
                    "name": names[addr],
                    "working": source,
                    "at": rows[i]["rom"],
                    "ops": list(reversed(ops))[:6],
                }
                break

    print("%d addresses named by the Select Monitor table" % len(names))
    print("%d are staging slots; %d traced back to a working variable"
          % (len(buffer_run), len(traced)))
    if direct:
        print("\n%d point straight at the working variable, no trace needed:"
              % len(direct))
        for a in sorted(direct):
            print("   0x%08X  %s" % (a, direct[a][:58]))
    print()
    print("%-42s %-12s %s" % ("parameter", "working var", "scaling seen"))
    print("-" * 92)
    for addr in sorted(traced, key=lambda a: traced[a]["name"]):
        t = traced[addr]
        ops = " ".join(o for o in t["ops"]
                       if not o.startswith(("mov.b @", "mov.w @", "mov.l @", "mov ",
                                            "rts", "nop", "mov.b r", "mov.w r")))
        print("%-42s 0x%08X   %s" % (t["name"][:42], t["working"], ops[:34]))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({
            "listing": os.path.basename(args.listing),
            "slots": len(buffer_run),
            "direct": {("%08X" % a): direct[a] for a in direct},
            "traced": len(traced),
            "variables": {("%08X" % a): traced[a] for a in traced},
        }, fh, indent=1, sort_keys=True)
    print("\n-> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
