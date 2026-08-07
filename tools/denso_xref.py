#!/usr/bin/env python3
"""Which code reads, and which writes, each RAM address - tracking registers.

The naive version of this got it wrong and said so confidently. It found a
function loading a base address into a register, found a displacement read off
that register further down, and reported the two as connected. They were not: the
register had been reloaded in between. Two reported reads of engine torque were
both false, and the mistake was only caught by opening the listing.

So this one carries register state. Within a function it tracks what each register
holds - a resolved literal, a copy of another register, a small adjustment - and
invalidates on anything it cannot follow. A read is only attributed to an address
when the base register provably holds that address at that instruction.

Being wrong in the safe direction matters more than coverage here. Register state
is dropped at every branch target, because a value that arrived along one path
cannot be assumed on another, and any instruction whose effect on a register is not
modelled clears it. The result under-reports rather than inventing links.

    python tools/denso_xref.py <listing> --addr 0xFFFF30F0
    python tools/denso_xref.py <listing> --range 0xFFFF30EC 0xFFFF30FF
    python tools/denso_xref.py <listing> --json out.json

SH-2 note: a 32-bit constant cannot be built inline, so addresses arrive as
pc-relative loads from a literal pool. The listing already resolves those in its
comment, which is what makes this tractable at all - see FINDINGS 45 and 46.
"""

import argparse
import json
import re
import sys

# 00012BD2  D4 60      mov.l @(0x12d54,pc),r4   ; [00012D54] = 0xFFFF300C -> RAM 0xFFFF300C
ROW = re.compile(
    r"^([0-9A-F]{8})\s+((?:[0-9A-F]{2} )+)\s+_?([a-z][a-z0-9./]*)\s*([^;]*?)\s*(?:;(.*))?$")

POOL_RAM = re.compile(r"->\s*RAM\s+0x([0-9A-Fa-f]{8})")
POOL_VAL = re.compile(r"=\s*0x([0-9A-Fa-f]+)")

MOV_PC = re.compile(r"^@\(0x[0-9a-f]+,pc\),(r\d+)$")
MOV_REG = re.compile(r"^(r\d+),(r\d+)$")
MOV_IMM = re.compile(r"^#(-?0x[0-9a-f]+|-?\d+),(r\d+)$")
ADD_IMM = re.compile(r"^(-?0x[0-9a-f]+|-?\d+),(r\d+)$")

READ_PLAIN = re.compile(r"^@(r\d+)(\+?),(r\d+)$")
READ_DISP = re.compile(r"^@\(0x([0-9a-f]+),(r\d+)\),(r\d+)$")
WRITE_PLAIN = re.compile(r"^(r\d+),@(-?)(r\d+)$")
WRITE_DISP = re.compile(r"^(r\d+),@\(0x([0-9a-f]+),(r\d+)\)$")

BRANCH = re.compile(r"^(bra|bsr|bt|bf|bt/s|bf/s|bra/s|jmp|jsr|rts|rte)$")
TARGET = re.compile(r"0x([0-9a-f]{6,8})")

SIZE = {"mov.b": 1, "mov.w": 2, "mov.l": 4}


def parse(path):
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = ROW.match(line.rstrip("\n"))
        if not m:
            continue
        addr = int(m.group(1), 16)
        mnem = m.group(3)
        ops = m.group(4).strip()
        comment = m.group(5) or ""
        rows.append((addr, mnem, ops, comment))
    return rows


def literal_from(comment, mnem):
    """The value a pc-relative load brings in, as the listing already resolved it."""
    m = POOL_RAM.search(comment)
    if m:
        return int(m.group(1), 16)
    m = POOL_VAL.search(comment)
    if not m:
        return None
    v = int(m.group(1), 16)
    # mov.w sign-extends its 16-bit literal, which is how a RAM address in the
    # 0xFFFF... range is produced from two bytes (FINDINGS 45).
    if mnem == "mov.w" and v & 0x8000:
        v |= 0xFFFF0000
    return v


def branch_targets(rows):
    out = set()
    for _a, mnem, ops, _c in rows:
        if BRANCH.match(mnem):
            m = TARGET.search(ops)
            if m:
                out.add(int(m.group(1), 16))
    return out


def analyse(rows, verbose=False):
    """Walk the listing, tracking register contents, recording RAM access."""
    targets = branch_targets(rows)
    reads, writes = {}, {}
    reg = {}
    dropped = 0

    for addr, mnem, ops, comment in rows:
        # A value proved on one path cannot be assumed on another.
        if addr in targets:
            reg = {}

        size = SIZE.get(mnem, 0)

        if size:
            m = READ_DISP.match(ops)
            if m:
                base = reg.get(m.group(2))
                if base is not None:
                    reads.setdefault(base + int(m.group(1), 16), []).append(addr)
                else:
                    dropped += 1
            else:
                m = READ_PLAIN.match(ops)
                if m:
                    base = reg.get(m.group(1))
                    if base is not None:
                        reads.setdefault(base, []).append(addr)
                    else:
                        dropped += 1
                else:
                    m = WRITE_DISP.match(ops)
                    if m:
                        base = reg.get(m.group(3))
                        if base is not None:
                            writes.setdefault(base + int(m.group(2), 16), []).append(addr)
                        else:
                            dropped += 1
                    else:
                        m = WRITE_PLAIN.match(ops)
                        if m:
                            base = reg.get(m.group(3))
                            if base is not None and not m.group(2):
                                writes.setdefault(base, []).append(addr)
                            elif base is None:
                                dropped += 1

        # Now update register state for this instruction.
        dest = None
        if mnem in SIZE:
            m = MOV_PC.match(ops)
            if m:
                v = literal_from(comment, mnem)
                if v is None:
                    reg.pop(m.group(1), None)
                else:
                    reg[m.group(1)] = v
                continue
            for rx in (READ_DISP, READ_PLAIN):
                m = rx.match(ops)
                if m:
                    dest = m.group(3)
                    break
        elif mnem == "mov":
            m = MOV_IMM.match(ops)
            if m:
                reg[m.group(2)] = int(m.group(1), 0)
                continue
            m = MOV_REG.match(ops)
            if m:
                src = reg.get(m.group(1))
                if src is None:
                    reg.pop(m.group(2), None)
                else:
                    reg[m.group(2)] = src
                continue
        elif mnem == "add":
            m = ADD_IMM.match(ops)
            if m:
                cur = reg.get(m.group(2))
                if cur is not None:
                    reg[m.group(2)] = (cur + int(m.group(1), 0)) & 0xFFFFFFFF
                continue
            m = MOV_REG.match(ops)
            if m:
                dest = m.group(2)
        else:
            # Anything not modelled that plainly names a destination register
            # clears it, rather than letting a stale value be trusted.
            m = re.search(r"(r\d+)$", ops)
            if m:
                dest = m.group(1)

        if dest:
            reg.pop(dest, None)

    if verbose:
        sys.stderr.write("%d accesses had an unknown base and were dropped\n" % dropped)
    return reads, writes


def report(reads, writes, lo, hi):
    hits = sorted(set(list(reads) + list(writes)))
    hits = [h for h in hits if lo <= h <= hi]
    if not hits:
        print("no tracked access in 0x%08X - 0x%08X" % (lo, hi))
        return
    print("  %-12s %-7s %-7s  %s" % ("address", "reads", "writes", "sites"))
    for h in hits:
        r, w = reads.get(h, []), writes.get(h, [])
        sites = ", ".join("0x%08X" % x for x in sorted(set(r))[:4])
        if len(set(r)) > 4:
            sites += ", ..."
        print("  0x%08X   %-7d %-7d  %s" % (h, len(set(r)), len(set(w)), sites or "-"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing")
    ap.add_argument("--addr")
    ap.add_argument("--range", nargs=2)
    ap.add_argument("--json")
    args = ap.parse_args()

    rows = parse(args.listing)
    sys.stderr.write("%d instructions parsed\n" % len(rows))
    reads, writes = analyse(rows, verbose=True)
    sys.stderr.write("%d addresses read, %d written\n" % (len(reads), len(writes)))

    if args.addr:
        a = int(args.addr, 16)
        r, w = sorted(set(reads.get(a, []))), sorted(set(writes.get(a, [])))
        print("\n0x%08X" % a)
        print("  read by %d sites : %s"
              % (len(r), ", ".join("0x%08X" % x for x in r) or "none"))
        print("  written by %d    : %s"
              % (len(w), ", ".join("0x%08X" % x for x in w) or "none"))
    elif args.range:
        report(reads, writes, int(args.range[0], 16), int(args.range[1], 16))

    if args.json:
        out = {"reads": {"%08X" % k: sorted(set(v)) for k, v in reads.items()},
               "writes": {"%08X" % k: sorted(set(v)) for k, v in writes.items()}}
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
        print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
