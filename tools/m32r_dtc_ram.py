#!/usr/bin/env python3
"""Resolve the M32R live fault-flag bytes in RAM, and what each bit means.

FINDINGS 16b decompiled the routine that builds the DTC message: twelve status
bytes of eight fault flags each, indexing a 96-entry table of codes stored as the
P-number in hex.

    for (uVar4 = 0; uVar4 < 0xc; uVar4++) {          // 12 status bytes
        bVar1 = (&PTR_DAT_0001cdc4)[uVar4][2];       // 8 fault flags each
        ...
            (&DAT_008047b8)[uVar5] = (&DAT_0001ce18)[uVar4 * 8 + uVar3];

The flags are not at a flat address: `PTR_DAT_0001cdc4` is a table of twelve
POINTERS, and the flag byte is at offset 2 of whatever each one points at. So
reading them means following the pointer table out of the ROM image first, which is
what this does.

    python3 tools/m32r_dtc_ram.py                     # every firmware
    python3 tools/m32r_dtc_ram.py --rom rom/x.bin     # one
    python3 tools/m32r_dtc_ram.py --ssm               # as SSM read addresses

WHY THIS IS USEFUL ON A BENCH. M32R RAM lives at 0x800000-0x81FFFF, which fits the
three-byte address an SSM read command carries with nothing to spare and nothing to
truncate. The Denso equivalent sits at 0xFFFF____ and does not fit, which is the
open question in FINDINGS 83. Here the addressing is not in doubt.

The pointer table address differs per firmware, so it is located rather than
hardcoded: the code table is already known per firmware from tools/dtc_table.json,
and the pointer table sits a fixed distance below it in every image checked.
"""

import argparse
import glob
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DTC_JSON = os.path.join(HERE, "dtc_table.json")

GROUPS = 12          # status bytes
BITS = 8             # flags per byte
FLAG_OFFSET = 2      # the flag byte within each pointed-at structure

# In 91D1206000 the pointer table sits 0x54 below the code table. That is a fact
# about that image and not about the family: assuming it held everywhere resolved
# one firmware out of sixteen. The table is located instead, by its own shape -
# twelve consecutive big-endian words that all point into M32R RAM.
SEARCH_BACK = 0x400


def cal_id(rom):
    return rom[0x8008:0x8018].decode("ascii", "replace").strip()


def find_pointer_table(rom, code_addr):
    """Where the twelve pointers live, found by shape rather than by offset.

    Twelve consecutive 32-bit words that all land in M32R RAM is a specific enough
    pattern that a false match is not a realistic worry, and the evenly spaced
    structures they point at confirm it.
    """
    best = None
    lo = max(0, code_addr - SEARCH_BACK)
    for a in range(lo, code_addr, 4):
        ptrs = []
        for g in range(GROUPS):
            if a + g * 4 + 4 > len(rom):
                break
            ptrs.append(struct.unpack_from(">I", rom, a + g * 4)[0])
        if len(ptrs) != GROUPS:
            continue
        if not all(0x800000 <= p <= 0x81FFFF for p in ptrs):
            continue
        # The structures are evenly spaced in every image examined; that
        # regularity distinguishes the real table from a coincidental run.
        deltas = {ptrs[i + 1] - ptrs[i] for i in range(GROUPS - 1)}
        score = (len(deltas), -a)
        if best is None or score < best[0]:
            best = (score, a)
    return best[1] if best else None


def resolve(rom, code_addr):
    """The twelve RAM addresses holding fault flags, and the codes they map to."""
    ptr_addr = find_pointer_table(rom, code_addr)
    if ptr_addr is None:
        return None, None
    out = []
    for g in range(GROUPS):
        p = struct.unpack_from(">I", rom, ptr_addr + g * 4)[0]
        codes = []
        for b in range(BITS):
            c = struct.unpack_from(">H", rom, code_addr + (g * BITS + b) * 2)[0]
            codes.append(c)
        out.append((p + FLAG_OFFSET, codes))
    return out, ptr_addr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom")
    ap.add_argument("--ssm", action="store_true",
                    help="print the addresses as an SSM read list")
    args = ap.parse_args()

    try:
        known = json.load(open(DTC_JSON, encoding="utf-8"))
    except OSError:
        sys.exit("tools/dtc_table.json not found - run extract_dtc_table.py first")

    roms = [args.rom] if args.rom else sorted(glob.glob(os.path.join(REPO, "rom", "*.bin")))
    ok = 0
    for path in roms:
        rom = open(path, "rb").read()
        name = os.path.basename(path)
        rid = None
        for k, v in known.items():
            if k in name:
                rid = (k, v["addr"])
                break
        if rid is None:
            continue
        groups, ptr_addr = resolve(rom, rid[1])
        if groups is None:
            print("  %-42s no pointer table found below 0x%06X"
                  % (name[:42], rid[1]))
            continue
        ok += 1
        print("=== %s   cal %s" % (name, cal_id(rom)))
        print("    code table   0x%06X" % rid[1])
        print("    pointers     0x%06X" % ptr_addr)
        if args.ssm:
            addrs = " ".join("%06X" % a for a, _ in groups)
            print("    SSM read     %s" % addrs)
        else:
            for i, (addr, codes) in enumerate(groups):
                named = [("P%04X" % (c & 0x3FFF)) if c not in (0, 0x3FFF, 0xFFFF)
                         else "-" for c in codes]
                print("    group %2d  RAM 0x%06X  bit0..7: %s"
                      % (i, addr, " ".join(named)))
        print()

    print("%d of %d firmwares resolved" % (ok, len(roms)))
    if ok:
        print("\nA fault is set when  ram[group_address] & (1 << bit)  and the code")
        print("for that bit is the one listed above it. Read all twelve addresses in")
        print("one SSM request - read-address batches them.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
