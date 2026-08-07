#!/usr/bin/env python3
"""Recover the gather that assembles the TCU's control block.

The shift logic does not read the CAN buffers, the sensor staging areas or the
Select Monitor copies. It reads one contiguous block, and a routine fills that
block by copying from all over RAM just before the block is used. Finding it took
five failed attempts at making a CAN value propagate (FINDINGS 56 to 60); the
route is in section 61.

The routine is an unrolled sequence of load-store pairs rather than a loop over a
table, so it has no table to read. What it does have is a literal pool, and the
pool holds the addresses in source, destination order - which amounts to the same
thing and is just as recoverable:

    0002CF9C  mov.l ...,r6     ; 0xFFFF30FB    source
    0002CF9E  mov.b @r6,r2
    0002CFA0  mov.l ...,r6     ; 0xFFFF8E47    destination
    0002CFA2  mov.b r2,@r6

Anchoring on the shape - a run of paired RAM addresses whose second element climbs
steadily through one block - finds it without knowing where it is, so this works on
the other firmwares too.

    python tools/denso_gather_map.py rom-denso/Impreza_STI_3.583_JDM2011.bin
    python tools/denso_gather_map.py <rom> --json gather.json
"""

import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = os.path.join(HERE, "denso_working_vars.json")

RAM_LO, RAM_HI = 0xFFFF2000, 0xFFFFBFFF
MIN_PAIRS = 8


def u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


def is_ram(v):
    return RAM_LO <= v <= RAM_HI


def find_gathers(d):
    """Runs of source,destination pairs that look like a gather rather than a pool.

    Two things have to be got right here, and the first attempt got both wrong.

    Alignment. A run of RAM addresses can be paired two ways, and starting on the
    wrong one pairs each destination with the next source - which turns a real
    gather into noise. Both alignments are scored and the better one kept.

    Discrimination. A literal pool full of consecutive RAM addresses also has a
    rising second column, so "destinations rise" matches almost any pool and finds
    the wrong thing everywhere. What actually marks a gather is the contrast: it
    collects from all over RAM into one small block, so the sources are scattered
    across a wide span while the destinations sit inside a narrow one. Requiring
    that contrast is what separates the routine from the pools around it.
    """
    runs, o = [], 0
    while o + 4 <= len(d):
        if not is_ram(u32(d, o)):
            o += 4
            continue
        start = o
        while o + 4 <= len(d) and is_ram(u32(d, o)):
            o += 4
        if (o - start) >= MIN_PAIRS * 8:
            runs.append((start, o))

    out = []
    for start, end in runs:
        best = None
        for align in (0, 4):
            base = start + align
            pairs = [(u32(d, p), u32(d, p + 4))
                     for p in range(base, end - 4, 8)]
            if len(pairs) < MIN_PAIRS:
                continue
            src = [s for s, _t in pairs]
            dst = [t for _s, t in pairs]
            # Requiring every destination inside one narrow span was too strict and
            # missed the gather at 0x0002D1A8: most of its slots are in
            # 0xFFFF8E44-0xFFFF8E8C but a handful sit well outside. What holds is
            # that a clear majority cluster together, so score the modal cluster
            # rather than the full range.
            mid = sorted(dst)[len(dst) // 2]
            inband = [t for t in dst if abs(t - mid) <= 0x100]
            if len(inband) < 0.6 * len(dst):
                continue
            sspan = max(src) - min(src)
            # A gather collects from all over RAM into one block; a plain literal
            # pool of consecutive addresses does not.
            if sspan < 0x1000:
                continue
            rising = sum(1 for a, b in zip(inband, inband[1:]) if b > a)
            if rising < 0.7 * max(1, len(inband) - 1):
                continue
            score = (len(inband), sspan)
            if best is None or score > best[0]:
                best = (score, base, pairs)
        if best:
            out.append((best[1], best[2]))
    return out


def pool_loaders(listing):
    """Every pc-relative load in the listing, as code address -> pool address.

    Needed because the pair-shape test on its own is only a heuristic: plenty of
    ordinary literal pools hold scattered RAM addresses and pass it. A real gather
    has something a pool does not - a tight run of instructions that loads it. The
    listing resolves each load's target in its comment, which makes the check cheap.
    """
    import re
    row = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s+_?mov\.l\s+@\(0x([0-9a-f]+),pc\)")
    out = {}
    with open(listing, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = row.match(line.rstrip("\n"))
            if m:
                out[int(m.group(1), 16)] = int(m.group(2), 16)
    return out


def verify(candidate, loaders):
    """Is this pool loaded by one tight run of code, as a gather must be?

    Returns the code span that loads it and how many of the pool's slots that run
    touches. A literal pool serving a whole function is loaded from all over that
    function; a gather's pool is consumed by a dense unrolled sequence.
    """
    start, pairs = candidate
    end = start + len(pairs) * 8
    sites = sorted(pc for pc, target in loaders.items() if start <= target < end)
    if len(sites) < len(pairs):
        return None
    span = sites[-1] - sites[0]
    # Two instructions per copy, four bytes of code per pair at the very least;
    # allow generous slack but reject a pool referenced across a whole subsystem.
    if span > max(0x200, len(pairs) * 0x20):
        return None
    return (sites[0], sites[-1], len(sites))


def load_names():
    try:
        with open(NAMES, encoding="utf-8") as fh:
            n = json.load(fh)
    except (OSError, ValueError):
        return {}
    if isinstance(n, dict) and not any(k.startswith("FFFF") for k in n):
        for v in n.values():
            if isinstance(v, dict) and any(k.startswith("FFFF") for k in v):
                return v
        return {}
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--json")
    ap.add_argument("--verify", metavar="LISTING",
                    help="keep only pools loaded by one tight run of code")
    args = ap.parse_args()

    d = open(args.rom, "rb").read()
    names = load_names()
    gathers = find_gathers(d)
    if args.verify:
        loaders = pool_loaders(args.verify)
        kept = []
        for cand in gathers:
            v = verify(cand, loaders)
            if v:
                kept.append((cand, v))
        print("%d of %d candidates are loaded by a tight run of code\n"
              % (len(kept), len(gathers)))
        gathers = [c for c, _v in kept]
        spans = {c[0]: v for c, v in kept}
    else:
        spans = {}
    if not gathers:
        sys.stderr.write("no gather found in %s\n" % args.rom)
        return 1

    result = []
    for start, pairs in gathers:
        dests = [t for _s, t in pairs]
        print("gather at 0x%06X : %d pairs, filling 0x%08X - 0x%08X\n"
              % (start, len(pairs), min(dests), max(dests)))
        print("  %-12s %-12s %s" % ("source", "slot", "what the source is"))
        for s, t in pairs:
            print("  0x%08X   0x%08X   %s"
                  % (s, t, names.get("%08X" % s, "")))
            result.append({"source": "%08X" % s, "dest": "%08X" % t,
                           "name": names.get("%08X" % s, "")})
        print()

    named = sum(1 for r in result if r["name"])
    print("%d pairs across %d gather(s), %d sources already named"
          % (len(result), len(gathers), named))

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=1)
        print("-> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
