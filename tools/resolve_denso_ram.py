#!/usr/bin/env python3
"""Resolve the RAM addresses behind Ghidra's DAT_ symbols in a Denso listing.

Section 42e claimed Denso working variables could not be traced without resolving
GBR at every access site. That was wrong, and the mistake was assuming rather than
reading the code.

SH-2 has no instruction that loads a 32-bit constant, so the compiler puts the
constant in a literal pool near the code and loads it PC-relative. For RAM
addresses it uses the 16-bit form:

    mov.w  @(disp,pc), Rn        loads a signed 16-bit literal

and **sign-extends** it. On-chip RAM sits at 0xFFFF0000 and up, so an address like
0xFFFF81C0 is stored as the two bytes 0x81C0 and sign-extension does the rest.
That is why a search for 0xFFFFxxxx across the image finds almost nothing: the
addresses are not stored in full anywhere.

Ghidra labels the literal itself - `DAT_000099e0` is the *ROM* address of the
literal, not the RAM address it denotes - and the decompiled body reads

    pbVar4 = (byte *)(int)DAT_000099e0;

So resolving a listing means: for every DAT_ symbol below the ROM ceiling, read
two bytes there, sign-extend, and if the result lands in RAM that is the address
the code is really touching. Joined against the Select Monitor names from
map_ssm_parameters.py, that puts a real-world name on the variable.

This is rimwall's method from forum topic 13725 post 391, arrived at by following
what he described rather than by anything clever here.

    python tools/resolve_denso_ram.py decompiled-denso/Impreza_STI_3.583_JDM2011.c
    python tools/resolve_denso_ram.py --all

Writes tools/denso_ram_names.json.
"""

import argparse
import glob
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SSM_JSON = os.path.join(HERE, "ssm_parameters.json")
OUT = os.path.join(HERE, "denso_ram_names.json")

DAT = re.compile(r"\bDAT_00([0-9a-fA-F]{6})\b")
RAM_LO, RAM_HI = 0xFFFF0000, 0xFFFFFFFE


def rom_for(listing):
    """The ROM image a listing was produced from."""
    stem = os.path.splitext(os.path.basename(listing))[0]
    for folder in ("rom-denso", "rom"):
        p = os.path.join(REPO, folder, stem + ".bin")
        if os.path.exists(p):
            return p
    return None


def ssm_names(rom_name):
    """RAM address -> Select Monitor parameter name, for one image."""
    if not os.path.exists(SSM_JSON):
        return {}
    data = json.load(open(SSM_JSON, encoding="utf-8"))
    info = data.get(rom_name)
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


def resolve(listing, verbose=False):
    rom_path = rom_for(listing)
    if not rom_path:
        sys.stderr.write("no ROM image found for %s\n" % listing)
        return None
    data = open(rom_path, "rb").read()
    names = ssm_names(os.path.basename(rom_path))

    text = open(listing, encoding="utf-8", errors="replace").read()
    symbols = {}
    for m in DAT.finditer(text):
        rom = int(m.group(1), 16)
        symbols[rom] = symbols.get(rom, 0) + 1

    resolved, named = {}, {}
    for rom, uses in symbols.items():
        if rom + 2 > len(data):
            continue
        # The literal is a signed 16-bit word; sign extension is what turns it
        # into an on-chip RAM address.
        addr = struct.unpack_from(">h", data, rom)[0] & 0xFFFFFFFF
        if not (RAM_LO <= addr <= RAM_HI):
            continue
        resolved[rom] = {"ram": addr, "uses": uses}
        if addr in names:
            resolved[rom]["name"] = names[addr]
            named[rom] = names[addr]

    return {
        "listing": os.path.basename(listing),
        "rom": os.path.basename(rom_path),
        "symbols": len(symbols),
        "resolved": len(resolved),
        "named": len(named),
        "uses_named": sum(resolved[r]["uses"] for r in named),
        "entries": resolved,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("listings", nargs="*")
    ap.add_argument("--all", action="store_true",
                    help="every listing in decompiled-denso/")
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    paths = args.listings
    if args.all or not paths:
        paths = sorted(glob.glob(os.path.join(REPO, "decompiled-denso", "*.c")))

    out = {}
    print("%-44s %8s %9s %7s" % ("listing", "DAT_ syms", "-> RAM", "named"))
    print("-" * 74)
    for p in paths:
        r = resolve(p)
        if not r:
            continue
        out[r["listing"]] = {k: v for k, v in r.items() if k != "entries"}
        out[r["listing"]]["entries"] = {
            "%06X" % k: v for k, v in r["entries"].items()}
        print("%-44s %8d %9d %7d" % (r["listing"][:44], r["symbols"],
                                     r["resolved"], r["named"]))

    if len(paths) == 1 and out:
        r = list(out.values())[0]
        rows = [(int(k, 16), v) for k, v in r["entries"].items() if "name" in v]
        rows.sort(key=lambda x: -x[1]["uses"])
        print("\nmost-used named variables:")
        for rom, v in rows[:args.show]:
            print("   ROM %06X -> RAM %08X  x%-4d %s"
                  % (rom, v["ram"], v["uses"], v["name"]))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print("\n-> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
