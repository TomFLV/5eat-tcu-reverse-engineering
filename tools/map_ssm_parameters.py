#!/usr/bin/env python3
"""Name the TCU's RAM addresses by joining the ROM's SSM table to FreeSSM's list.

The Select Monitor addresses a parameter by a three-byte SSM address, and the ROM
holds a table that turns that address into the internal RAM address the value
actually lives at. The table is a run of 32-bit big-endian pointers into on-chip
RAM, indexed by SSM address, with a dummy address filling every unsupported slot.

FreeSSM's SSMFlagbyteDefinitions_en.cpp gives the other half: SSM address to
parameter name, unit and conversion. Joining the two names the RAM addresses,
which is what lets a table's purpose be established from the code that reads it
rather than from the shape of its numbers.

The approach, and the location of the table, are rimwall's - forum topic 13725,
post 391. FreeSSM is Comer352L's, GPLv3; nothing from it is redistributed here,
it is downloaded when this runs.

    python tools/map_ssm_parameters.py rom/*.bin rom-denso/*.bin
    python tools/map_ssm_parameters.py --defs /path/to/SSMFlagbyteDefinitions_en.cpp rom/x.bin

Writes tools/ssm_parameters.json and prints a per-ROM summary.
"""

import argparse
import json
import os
import re
import struct
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ssm_parameters.json")

DEFS_URL = ("https://raw.githubusercontent.com/Comer352L/FreeSSM/master/"
            "src/SSMFlagbyteDefinitions_en.cpp")

# The two families put their on-chip RAM in different places - M32R at 0x0080xxxx,
# SH705x high in the address space - so a pointer table is a run of values inside
# one of these, and a value outside every range ends the run.
# 0xFFFFFFFF is excluded deliberately: erased flash is a run of it tens of
# thousands of entries long, which otherwise wins every time.
RAM_RANGES = (
    (0x00800000, 0x0080FFFF),   # Hitachi M32R
    (0xFFFF8000, 0xFFFFEFFF),   # Denso SH705x on-chip RAM
)


def in_ram(v):
    return any(lo <= v <= hi for lo, hi in RAM_RANGES)

# A table shorter than this is a coincidence, not the parameter map.
MIN_ENTRIES = 128


def fetch_defs(path):
    """The FreeSSM definitions, from a local copy or from upstream."""
    if path and os.path.exists(path):
        return open(path, encoding="utf-8", errors="replace").read()
    cached = os.path.join(HERE, "SSMFlagbyteDefinitions_en.cpp")
    if os.path.exists(cached):
        return open(cached, encoding="utf-8", errors="replace").read()
    sys.stderr.write("fetching %s\n" % DEFS_URL)
    req = urllib.request.Request(DEFS_URL, headers={"User-Agent": "Mozilla/5.0"})
    text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    with open(cached, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return text


ENTRY = re.compile(r'<<\s*"([^"]+)"')


def parse_defs(text):
    """SSM address -> parameter description.

    Measuring blocks are flagbyte;bit;type;addr;addr_low;name;unit;conv;prec and
    switches are flagbyte;bit;type;addr;name;states. A 16-bit parameter names two
    addresses; both are recorded, marked with which half they are.
    """
    out = {}
    section = None
    for line in text.splitlines():
        if "_MB_defs_en" in line:
            section = "mb"
        elif "_SW_defs_en" in line:
            section = "sw"
        elif "_defs_en" in line and "QStringList" in line:
            section = None
        if section is None:
            continue
        m = ENTRY.search(line)
        if not m:
            continue
        f = m.group(1).split(";")
        try:
            if section == "mb" and len(f) >= 8:
                hi, lo, name, unit, conv = f[3], f[4], f[5], f[6], f[7]
                out.setdefault(int(hi, 16), {}).update(
                    {"name": name, "unit": unit, "conv": conv, "kind": "mb",
                     "half": "high" if lo else "single"})
                if lo:
                    out.setdefault(int(lo, 16), {}).update(
                        {"name": name, "unit": unit, "conv": conv, "kind": "mb",
                         "half": "low"})
            elif section == "sw" and len(f) >= 6:
                addr, name, states = f[3], f[4], f[5]
                d = out.setdefault(int(addr, 16), {"switches": []})
                d.setdefault("switches", []).append(
                    {"bit": int(f[1]), "name": name, "states": states})
                d.setdefault("kind", "sw")
        except ValueError:
            continue
    return out


def find_table(data):
    """The longest run of plausible RAM pointers, as (start, count).

    Returned as the longest run rather than the first: short runs of values that
    happen to fall in the RAM range occur throughout a calibration region.
    """
    best = (None, 0)
    i, n = 0, len(data) - 4
    while i <= n:
        v = struct.unpack_from(">I", data, i)[0]
        if not in_ram(v):
            i += 4
            continue
        j = i
        while j <= n and in_ram(struct.unpack_from(">I", data, j)[0]):
            j += 4
        count = (j - i) // 4
        if count >= MIN_ENTRIES and count > best[1] and looks_like_map(data, i, count):
            best = (i, count)
        i = j
    return best


def looks_like_map(data, start, count):
    """A parameter map, as distinct from any other run of in-range words.

    The distinguishing shape is one address repeated for every unsupported
    parameter and a modest number of distinct real ones. A block of packed
    pointers has no dominant value; a block of padding has nothing else.
    """
    vals = [struct.unpack_from(">I", data, start + 4 * k)[0] for k in range(count)]
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    filler = max(counts, key=counts.get)
    return counts[filler] >= count * 0.4 and 8 <= len(counts) - 1 <= count * 0.5


ASSIGN = re.compile(r"^\s*DAT_00([0-9a-fA-F]{6})\s*=\s*([^;]+);")
SOURCE = re.compile(r"DAT_00([0-9a-fA-F]{6})")
# Ghidra routes a value through a temporary whenever the copy is range-checked,
# which is most of them: iVar2 = DAT_008046c6 / 100; if (...) DAT_00805173 = iVar2;
TEMP_ASSIGN = re.compile(r"^\s*([iu]Var\d+)\s*=\s*([^;]+);")
TEMP_USE = re.compile(r"\b([iu]Var\d+)\b")


def trace_sources(listing, mirror_addrs):
    """mirror RAM address -> (working variable addresses, expression).

    The parameters the Select Monitor reports are copied into a contiguous block
    just before they are sent. That block is a staging buffer, not where the
    control logic keeps anything - but the copy names its source, so one hop back
    from a named mirror address gives the working variable, scaling and all.
    """
    if not os.path.exists(listing):
        return {}
    out = {}
    temps = {}
    for line in open(listing, encoding="utf-8", errors="replace"):
        t = TEMP_ASSIGN.match(line)
        if t:
            var, val = t.group(1), t.group(2).strip()
            # A saturating clamp reassigns the temporary to a constant between
            # the real assignment and its use - if (iVar2 < 0) iVar2 = 0; - so a
            # constant must not displace the expression that names the source.
            if SOURCE.search(val) or var not in temps:
                temps[var] = val
            continue
        m = ASSIGN.match(line)
        if not m:
            continue
        dest = int(m.group(1), 16)
        if dest not in mirror_addrs:
            continue
        expr = m.group(2).strip()
        # Substitute the temporary's own expression, so the working variable is
        # reported rather than the name Ghidra gave the intermediate.
        for var in set(TEMP_USE.findall(expr)):
            if var in temps:
                expr = expr.replace(var, "(%s)" % temps[var])
        srcs = [int(s, 16) for s in SOURCE.findall(expr) if int(s, 16) != dest]
        # A parameter guarded by a range check is assigned twice, once with the
        # real value and once with a saturation constant. Keep the real one.
        if srcs or dest not in out:
            out[dest] = {"sources": ["%06X" % s for s in srcs], "expr": expr}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roms", nargs="+")
    ap.add_argument("--defs", help="local SSMFlagbyteDefinitions_en.cpp")
    ap.add_argument("--show", type=int, default=12, help="rows to print per ROM")
    ap.add_argument("--decompiled", default=os.path.join(HERE, "..", "decompiled"),
                    help="directory of Ghidra listings, to trace the staging buffer back")
    args = ap.parse_args()

    defs = parse_defs(fetch_defs(args.defs))
    named = sum(1 for d in defs.values() if d.get("name") or d.get("switches"))
    print("FreeSSM: %d SSM addresses described\n" % named)

    result = {}
    for path in args.roms:
        data = open(path, "rb").read()
        start, count = find_table(data)
        name = os.path.basename(path)
        if start is None or count < MIN_ENTRIES:
            print("%-46s no parameter table found" % name)
            continue

        vals = [struct.unpack_from(">I", data, start + 4 * i)[0] for i in range(count)]
        # The dummy address every unsupported parameter points at is whichever
        # value dominates; a real parameter appears once or twice.
        counts = {}
        for v in vals:
            counts[v] = counts.get(v, 0) + 1
        filler = max(counts, key=counts.get)

        mirror = {v for v in vals if v != filler}
        listing = os.path.join(args.decompiled, os.path.splitext(name)[0] + ".c")
        traced = trace_sources(listing, mirror)

        rows = []
        for ssm, ram in enumerate(vals):
            if ram == filler:
                continue
            d = defs.get(ssm)
            t = traced.get(ram)
            rows.append({
                "ssm": ssm,
                "ram": ram,
                "name": (d or {}).get("name"),
                "unit": (d or {}).get("unit"),
                "conv": (d or {}).get("conv"),
                "half": (d or {}).get("half"),
                "switches": (d or {}).get("switches"),
                "sources": (t or {}).get("sources"),
                "expr": (t or {}).get("expr"),
            })

        known = [r for r in rows if r["name"] or r["switches"]]
        with_src = [r for r in known if r["sources"]]
        result[name] = {
            "table": start, "entries": count, "filler": filler,
            "supported": len(rows), "identified": len(known),
            "traced": len(with_src), "rows": rows,
        }
        print("%-46s table 0x%05X  %d supported  %d named  %d traced to a variable"
              % (name, start, len(rows), len(known), len(with_src)))

        for r in known[:args.show]:
            label = r["name"] or "; ".join(s["name"] for s in r["switches"])
            half = " (%s byte)" % r["half"] if r["half"] in ("high", "low") else ""
            src = "  <- %s" % ", ".join(r["sources"]) if r["sources"] else ""
            print("      SSM %03X  %-46s%s%s" % (r["ssm"], label[:46], half, src))
        if len(known) > args.show:
            print("      ... %d more" % (len(known) - args.show))

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    print("\n-> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
