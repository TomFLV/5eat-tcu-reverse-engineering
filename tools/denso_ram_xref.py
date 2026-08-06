#!/usr/bin/env python3
"""Cross-reference every RAM address in a Denso disassembly against the code.

For any on-chip RAM address, which instructions touch it - and, where the Select
Monitor table names that address, what it is.

This is what section 45c said was needed and section 46 made possible. It needs a
listing from tools/ghidra/DensoDisasmAll.java, not the decompiled C: the decompiler
discards literal pools, which is where every RAM address in this family lives.

    python tools/denso_ram_xref.py disasm-denso/Impreza_STI_3.583_JDM2011.asm
    python tools/denso_ram_xref.py <listing> --near 0xFFFFAA3A
    python tools/denso_ram_xref.py <listing> --named

Writes tools/denso_ram_xref.json.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SSM_JSON = os.path.join(HERE, "ssm_parameters.json")
OUT = os.path.join(HERE, "denso_ram_xref.json")

# 000164D0  D5 93   mov.l @(0x16720,pc),r5   ; [00016720] = 0xFFFFAA3A -> RAM 0xFFFFAA3A
LINE = re.compile(
    r"^([0-9A-F]{8})\s+((?:[0-9A-F]{2} )+)\s*(.*?)\s*(?:;\s*(.*))?$")
RAMREF = re.compile(r"->\s*RAM\s*0x([0-9A-F]{8})")
POOL = re.compile(r"\[([0-9A-F]{8})\]")


def ssm_names(listing):
    """RAM address -> Select Monitor name, for the image this listing came from."""
    stem = os.path.splitext(os.path.basename(listing))[0]
    if not os.path.exists(SSM_JSON):
        return {}
    data = json.load(open(SSM_JSON, encoding="utf-8"))
    info = data.get(stem + ".bin")
    if not info:
        return {}
    out = {}
    for r in info["rows"]:
        label = r.get("name")
        if not label and r.get("switches"):
            label = "; ".join(s["name"] for s in r["switches"])
        if label:
            out[r["ram"]] = label
    return out


def parse(path):
    """RAM address -> list of (rom_addr, mnemonic). Instructions only.

    A literal pool entry also carries a RAM annotation, but it is the datum, not a
    use of it, so it is skipped: counting it would double every reference.
    """
    xref = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        m = LINE.match(line.rstrip("\n"))
        if not m:
            continue
        rom, _bytes, body, comment = m.group(1), m.group(2), m.group(3), m.group(4)
        if not body or body.startswith("."):
            continue
        text = (comment or "")
        r = RAMREF.search(text)
        if not r:
            continue
        addr = int(r.group(1), 16)
        pool = POOL.search(text)
        xref.setdefault(addr, []).append({
            "rom": int(rom, 16),
            "insn": body.strip(),
            "pool": int(pool.group(1), 16) if pool else None,
        })
    return xref


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listing")
    ap.add_argument("--near", help="show sites touching this RAM address")
    ap.add_argument("--named", action="store_true",
                    help="only addresses the Select Monitor names")
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args()

    if not os.path.exists(args.listing):
        sys.stderr.write("no such listing: %s\n" % args.listing)
        return 1

    xref = parse(args.listing)
    names = ssm_names(args.listing)

    total_sites = sum(len(v) for v in xref.values())
    named_addrs = [a for a in xref if a in names]
    print("%d distinct RAM addresses, %d code sites" % (len(xref), total_sites))
    print("%d of those addresses are named by the Select Monitor table\n"
          % len(named_addrs))

    if args.near:
        target = int(args.near, 16)
        sites = xref.get(target, [])
        label = names.get(target, "(unnamed)")
        print("RAM 0x%08X  %s  - %d sites" % (target, label, len(sites)))
        for s in sites[:args.show]:
            print("   ROM %06X  %s" % (s["rom"], s["insn"]))
    elif args.named:
        for a in sorted(named_addrs, key=lambda x: -len(xref[x])):
            print("RAM 0x%08X  x%-4d %s" % (a, len(xref[a]), names[a]))
    else:
        busiest = sorted(xref, key=lambda a: -len(xref[a]))[:args.show]
        print("busiest RAM addresses:")
        for a in busiest:
            print("   0x%08X  x%-5d %s" % (a, len(xref[a]), names.get(a, "")))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({
            "listing": os.path.basename(args.listing),
            "addresses": len(xref),
            "sites": total_sites,
            "named": {("%08X" % a): names[a] for a in named_addrs},
            "xref": {("%08X" % a): v for a, v in xref.items()},
        }, fh, indent=1, sort_keys=True)
    print("\n-> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
