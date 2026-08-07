#!/usr/bin/env python3
"""Call graph for a Denso listing, and the climb from a leaf to whatever runs it.

Section 62 established the problem: this project has been running one function,
0x00023E72, and treating the results as the controller's behaviour. Most of the
firmware's input surface is read by code that has never been executed here. To run
the controller rather than a piece of it, the entry points have to come from the
firmware's own structure.

The first guess was a table of function pointers at 0x00D98C. It is not a task
table - the code before it is a run of small stubs that each bump a fault counter
and jump away, and the pointers are their literal pool. Guessing at tables by shape
found the wrong thing twice now; the call graph is the thing that is actually true.

    python tools/denso_callgraph.py <listing> --callers 0x0002CF80
    python tools/denso_callgraph.py <listing> --chain 0x0002CF80
    python tools/denso_callgraph.py <listing> --roots
    python tools/denso_callgraph.py <listing> --reaches 0x0002CF80 --json tasks.json

A root is a function nothing calls. On a controller these are the scheduler, the
interrupt handlers, and whatever the reset vector runs - which is exactly the set
worth feeding to the emulator.
"""

import argparse
import json
import re
import sys

ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s+(_?)([a-z][a-z0-9./]*)\s*([^;]*?)\s*(?:;.*)?$")
PROLOGUE = re.compile(r"^(r\d+|pr),@-r15$")
CALL_TARGET = re.compile(r"0x([0-9a-f]{6,8})")


def parse(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = ROW.match(line.rstrip("\n"))
            if m:
                rows.append((int(m.group(1), 16), m.group(3), m.group(4).strip()))
    return rows


def build(rows):
    """Function starts, and who calls whom.

    A function start is either a register-save prologue or the target of a call -
    the second matters because not every function saves anything, and a leaf that
    only uses scratch registers would otherwise be invisible.
    """
    starts = set()
    calls = []
    for addr, mnem, ops in rows:
        if mnem in ("mov.l", "sts.l") and PROLOGUE.match(ops):
            starts.add(addr)
        if mnem in ("bsr", "jsr", "bsrf"):
            m = CALL_TARGET.search(ops)
            if m:
                t = int(m.group(1), 16)
                calls.append((addr, t))
                starts.add(t)

    ordered = sorted(starts)

    def enclosing(a):
        lo, hi = 0, len(ordered)
        while lo < hi:
            mid = (lo + hi) // 2
            if ordered[mid] <= a:
                lo = mid + 1
            else:
                hi = mid
        return ordered[lo - 1] if lo else None

    callers, callees = {}, {}
    for site, target in calls:
        fn = enclosing(site)
        if fn is None:
            continue
        callers.setdefault(target, set()).add(fn)
        callees.setdefault(fn, set()).add(target)
    return ordered, callers, callees


def chain(callers, target, depth=0, seen=None, out=None):
    """Climb from a function to everything that can reach it."""
    seen = seen if seen is not None else set()
    out = out if out is not None else []
    if target in seen or depth > 12:
        return out
    seen.add(target)
    out.append((depth, target, sorted(callers.get(target, ()))))
    for c in sorted(callers.get(target, ())):
        chain(callers, c, depth + 1, seen, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing")
    ap.add_argument("--callers")
    ap.add_argument("--chain")
    ap.add_argument("--reaches")
    ap.add_argument("--roots", action="store_true")
    ap.add_argument("--json")
    args = ap.parse_args()

    rows = parse(args.listing)
    starts, callers, callees = build(rows)
    sys.stderr.write("%d instructions, %d functions, %d called\n"
                     % (len(rows), len(starts), len(callers)))

    if args.callers:
        t = int(args.callers, 16)
        c = sorted(callers.get(t, ()))
        print("0x%08X is called by %d: %s"
              % (t, len(c), ", ".join("0x%08X" % x for x in c) or "nothing"))

    if args.chain:
        t = int(args.chain, 16)
        print("climb from 0x%08X:\n" % t)
        for depth, fn, up in chain(callers, t):
            tag = "  ROOT - nothing calls this" if not up else ""
            print("  %s0x%08X%s" % ("  " * depth, fn, tag))

    if args.roots:
        called = set(callers)
        roots = [f for f in starts if f not in called and f in callees]
        roots.sort(key=lambda f: -len(callees.get(f, ())))
        print("%d functions are never called but do call others:\n" % len(roots))
        print("  %-12s %s" % ("address", "calls"))
        for f in roots[:30]:
            print("  0x%08X   %d" % (f, len(callees.get(f, ()))))
        if args.json:
            with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(["0x%08X" % f for f in roots], fh, indent=1)
            print("\n-> %s" % args.json)

    if args.reaches:
        t = int(args.reaches, 16)
        seen = {x for _d, x, _u in chain(callers, t)}
        called = set(callers)
        roots = sorted(f for f in seen if f not in called)
        print("%d functions can reach 0x%08X; %d of them are roots"
              % (len(seen), t, len(roots)))
        for f in roots:
            print("  root 0x%08X" % f)
        if args.json:
            with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(["0x%08X" % f for f in roots], fh, indent=1)
            print("-> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
