#!/usr/bin/env python3
"""Pull every transmission-side definition out of a FreeSSM checkout.

FreeSSM knows what a Subaru TCU's SSM parameters MEAN. This project knows, from the
firmware, where each SSM parameter READS FROM. Neither half is much use alone and
together they name RAM addresses, so the first step is getting FreeSSM's half out in
a form that can be joined - which is what this does. See freessm_crosscheck.py.

    python3 tools/freessm_defs.py --src <path to FreeSSM clone>
    python3 tools/freessm_defs.py --src <clone> --json <out.json>

FreeSSM is GPLv3, by Comer352L: https://github.com/Comer352L/FreeSSM
It is not vendored here and nothing is copied out of it into this repository. This
reads a clone you provide and writes a summary of the facts it states.

THE FILE HOLDS FOUR RECORD LAYOUTS AND THEY DISAGREE ABOUT WHERE THE CONTROL UNIT IS

    measuring blocks  flagbyte;flagbit;CUmask;addrLow;addrHigh;title;unit;formula;prec
    switches          flagbyte;flagbit;CUmask;addr;title;unit
    trouble codes     currentAddr;historicAddr;bit;code;description
    adjustments       flagbyte-flagbit|SYSID;CU;addrLow;addrHigh;title;unit;min;max;def;formula;prec
    actuator tests    flagbyte;flagbit;addr;bit;title

CUmask is a BITMASK - bit 0 engine, bit 1 transmission - so 3 means the definition
serves both. The adjustments list uses the same column for a plain INDEX instead, 0
engine and 1 transmission. Reading that as a mask turns every engine adjustment into
a transmission one. The actuator list has no control-unit column at all, and the
answer there is that FreeSSM ships no transmission actuator tests: all 21 are engine.

The trouble code lists have no control-unit column either. They are separated by
which address pair they sit on, so this groups by address and leaves the judgement
about which blocks are transmission to the caller.

WHY THESE ADDRESSES ARE NOT FIRMWARE ADDRESSES. An SSM address is a LOGICAL one that
Subaru keeps stable across control units and model years - 0x00000F is engine speed
on everything. Where that lands in RAM is per-CPU, 0x0080xxxx on M32R and 0xFFFFxxxx
on Denso SH. Never read an address out of this file as a memory location.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import WORK  # noqa: E402

DEFAULT_REL = os.path.join("src", "SSMFlagbyteDefinitions_en.cpp")

LIST = re.compile(r"_(\w+?)_defs_en\s*=\s*QStringList\(\)(.*?);\s*$", re.S | re.M)
LINE = re.compile(r'<<\s*"([^"]*)"')


def lists(text):
    """Each QStringList literal in the file, keyed by its list name."""
    return {m.group(1): LINE.findall(m.group(2)) for m in LIST.finditer(text)}


def extract(text, report=print):
    L = lists(text)
    report("lists found: %s" % ", ".join("%s(%d)" % (k, len(v))
                                         for k, v in sorted(L.items())))
    out = {}

    # Measuring blocks and switches: the control-unit column is a mask.
    for name, key, nfields in (("MB", "measuring_blocks", 9), ("SW", "switches", 6)):
        rows = []
        for ln in L.get(name, []):
            f = ln.split(";")
            if len(f) < nfields - 1 or not f[0].isdigit() or not (int(f[2]) & 0x02):
                continue
            common = dict(flagbyte=int(f[0]), flagbit=int(f[1]),
                          both_cu=bool(int(f[2]) & 1))
            if name == "MB":
                rows.append(dict(common, addr_low=f[3], addr_high=f[4] or None,
                                 title=f[5], unit=f[6], formula=f[7]))
            else:
                rows.append(dict(common, addr=f[3], title=f[4], unit=f[5]))
        out[key] = rows
        report("%-18s %3d transmission entries" % (key, len(rows)))

    # Adjustments: the same column is an index, not a mask.
    adj = []
    for ln in L.get("adjustment", []):
        f = ln.split(";")
        if len(f) < 11 or f[1] != "1":
            continue
        adj.append(dict(gate=f[0], addr_low=f[2], addr_high=f[3] or None,
                        title=f[4], unit=f[5], raw_min=int(f[6]),
                        raw_max=int(f[7]), raw_default=int(f[8]), formula=f[9]))
    out["adjustments"] = adj
    report("%-18s %3d transmission entries  (writable)" % ("adjustments", len(adj)))

    # Actuator tests have no control-unit column because none of them are
    # transmission. Recording the count keeps that from looking like a parse bug.
    out["actuators_engine_only"] = len(L.get("actuator", []))
    report("%-18s %3d, all engine - FreeSSM ships no TCU actuator tests"
           % ("actuators", out["actuators_engine_only"]))

    # Trouble codes: grouped by address pair, classification left to the caller.
    for name, key in (("DTC_SUBARU", "dtc_subaru"), ("DTC_OBD", "dtc_obd")):
        groups = {}
        for ln in L.get(name, []):
            f = ln.split(";")
            if len(f) < 5:
                continue
            groups.setdefault("%s/%s" % (f[0], f[1]), []).append(
                dict(bit=int(f[2]), code=f[3], desc=f[4]))
        out[key] = groups
        report("%-18s %3d address pairs" % (key, len(groups)))
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Extract transmission definitions from a FreeSSM checkout.")
    ap.add_argument("--src", required=True,
                    help="a FreeSSM clone, or the flagbyte definitions .cpp itself")
    ap.add_argument("--json", default=os.path.join(WORK, "freessm_tcu.json"))
    args = ap.parse_args()

    src = args.src
    if os.path.isdir(src):
        src = os.path.join(src, DEFAULT_REL)
    if not os.path.isfile(src):
        sys.exit("not found: %s\nPoint --src at a FreeSSM clone "
                 "(https://github.com/Comer352L/FreeSSM)." % src)

    data = extract(open(src, encoding="utf-8", errors="replace").read())
    d = os.path.dirname(os.path.abspath(args.json))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
