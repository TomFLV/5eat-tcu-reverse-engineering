#!/usr/bin/env python3
"""Name a calibration table by changing it and seeing what moves.

EVERY PREVIOUS ATTEMPT WAS INDIRECT. Follow the table to the function that reads
it, that function to the addresses it writes, those to whatever consumes them, and
ask whether any of it is named. Four routes like that are recorded in FINDINGS 74,
78 and 84, and all end the same way: the controller is densely connected, three
functions publish 48 named values each, everything reaches everything. A graph
cannot distinguish what it cannot separate.

This asks the question directly. Change the table in the ROM image, run the same
drive, compare the whole of RAM against an unmodified run. What differs is what
that table AFFECTS - not what it might be connected to. A table whose perturbation
moves the lock-up solenoid current controls lock-up, whatever the call graph says.

    python3 tools/denso_perturb.py --table 0E5208
    python3 tools/denso_perturb.py --all --json out.json --resume

WHY THIS SHOULD HAVE BEEN FIRST. It is the method that produced the CAN signal map
in FINDINGS 77c - hold an input at two values, diff whole RAM images - applied to a
table instead of a frame byte. That map found real signals where a swept input had
produced 1,118 false positives.

WHAT IT CANNOT SHOW. A table read only under conditions a drive never reaches moves
nothing, and that is reported as no effect rather than as no meaning. So several
drives are run: idle, cruise, acceleration, kickdown, and one with the ATF hot.
"""

import argparse
import json
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, WORK, WORK_WSL, SH2_WSL, wsl  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROM = os.path.join(REPO, "rom-denso", "Impreza_STI_3.583_JDM2011.bin")
SSM = os.path.join(HERE, "denso_ssm_addresses.json")
OUT = os.path.join(WORK, "perturb")
TASKS = WORK_WSL + "/tasks_ctl.txt"

# Values go into the CAN receive buffers the signal map established, which is where
# the control code looks. Writing to the 0xFFFFA0xx block injects into the
# controller's OUTPUT mirror and is overwritten on the same tick - a mistake that
# cost a day (FINDINGS 80).
IN_PEDAL, IN_RPM = 0xFFFF301C, 0xFFFF3011
IN_SPEED_A, IN_SPEED_B = 0xFFFF301F, 0xFFFF3020
IN_GEAR, IN_TORQUE = 0xFFFF30A6, 0xFFFF3010
IN_ATF = 0xFFFFA025

PROFILES = {
    "idle":       [(0, 0x20, 0, 1, 0x10)] * 30,
    "cruise":     [(0x28, 0x5A, 0x78, 5, 0x3C)] * 30,
    "accelerate": [(p, min(255, 0x20 + p), min(255, p), 1 + p // 40,
                    min(255, p)) for p in range(0, 240, 8)],
    "kickdown":   ([(0x1E, 0x50, 0x8C, 5, 0x32)] * 10
                   + [(0xDC, 0xC8, 0x96, 3, 0xDC)] * 20),
    "hot":        [(0x28, 0x5A, 0x78, 5, 0x3C)] * 30,
    "coast":      [(0, max(0x20, 200 - t * 8), max(0, 200 - t * 8),
                    max(1, 5 - t // 6), 5) for t in range(30)],
}


def names():
    return {int(k, 16): v
            for k, v in json.load(open(SSM, encoding="utf-8")).items()}


def make_profile(name, path):
    hot = name == "hot"
    with open(path, "w", newline="\n") as fh:
        for t, (pedal, rpm, speed, gear, torque) in enumerate(PROFILES[name]):
            cells = [
                "%08X:1=%d" % (IN_PEDAL, pedal),
                "%08X:1=%d" % (IN_RPM, rpm),
                "%08X:1=%d" % (IN_SPEED_A, speed),
                "%08X:1=%d" % (IN_SPEED_B, speed),
                "%08X:1=%d" % (IN_GEAR, (gear & 0xF) << 4),
                "%08X:1=%d" % (IN_TORQUE, torque),
                "%08X:1=%d" % (IN_ATF, 0x96 if hot else 0x50),
            ]
            fh.write("%d,%s\n" % (t, ",".join(cells)))
    return path


def table_shape(rom, hdr):
    """rows, cols and the data offset, read out of the table header."""
    try:
        rows = struct.unpack_from(">H", rom, hdr)[0]
        cols = struct.unpack_from(">H", rom, hdr + 2)[0]
    except struct.error:
        return None
    if not (1 <= rows <= 64 and 1 <= cols <= 64):
        return None
    data = hdr + 4 + rows * 2 + cols * 2
    if data + rows * cols * 2 > len(rom):
        return None
    return rows, cols, data


def perturb(rom, hdr, factor):
    """A copy of the ROM with one table's cells scaled.

    Scaling rather than zeroing: a table of zeros can send the firmware down a
    different branch, and then what moved is the branch and not the table. A factor
    keeps the shape of the calibration and changes only its magnitude.
    """
    shape = table_shape(rom, hdr)
    if shape is None:
        return None
    rows, cols, data = shape
    out = bytearray(rom)
    changed = 0
    for i in range(rows * cols):
        off = data + i * 2
        v = struct.unpack_from(">H", out, off)[0]
        nv = min(0xFFFF, max(0, int(v * factor)))
        if nv != v:
            struct.pack_into(">H", out, off, nv)
            changed += 1
    return (bytes(out), changed) if changed else None


def run(rom_path, dump_path, profile):
    env = dict(os.environ)
    env["SH2_DUMP"] = wsl(dump_path)
    env["WSLENV"] = "SH2_DUMP/u"
    subprocess.run(["wsl", SH2_WSL, wsl(rom_path), wsl(profile),
                    WORK_WSL + "/perturb/out.csv", "@" + TASKS, "400000"],
                   capture_output=True, env=env)
    return open(dump_path, "rb").read() if os.path.exists(dump_path) else b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--factor", type=float, action="append",
                    help="scale factor, repeatable. Two catch a table whose effect "
                         "saturates one way: in a controller full of limits, "
                         "halving and doubling are not mirror images.")
    ap.add_argument("--profile", action="append", choices=sorted(PROFILES))
    ap.add_argument("--json")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    rom = open(ROM, "rb").read()
    nm = names()

    if args.table:
        targets = [int(args.table, 16)]
    else:
        import denso_name_by_task as M
        targets = [int(h, 16) for h in M.shipped_headers()]
        if args.limit:
            targets = targets[:args.limit]

    profiles = args.profile or ["cruise", "accelerate", "kickdown", "hot"]
    factors = args.factor or [2.0, 0.5]

    result = {}
    if args.resume and args.json and os.path.exists(args.json):
        result = json.load(open(args.json, encoding="utf-8"))
        sys.stderr.write("resuming: %d tables already recorded\n" % len(result))

    bases = {}
    for pname in profiles:
        pf = make_profile(pname, os.path.join(OUT, "p_%s.csv" % pname))
        b = run(ROM, os.path.join(OUT, "base_%s.bin" % pname), pf)
        if not b:
            sys.exit("the %s baseline produced no RAM image" % pname)
        bases[pname] = (b, pf)
        sys.stderr.write("baseline %-11s %d bytes\n" % (pname, len(b)))

    total = len(targets) * len(profiles) * len(factors)
    done = 0
    for hdr in targets:
        key = "%06X" % hdr
        entry = result.setdefault(key, {"conditions": {}})
        entry.setdefault("conditions", {})
        for pname in profiles:
            base, pf = bases[pname]
            for factor in factors:
                done += 1
                ckey = "%s_x%g" % (pname, factor)
                if args.resume and ckey in entry["conditions"]:
                    continue
                p = perturb(rom, hdr, factor)
                if p is None:
                    continue
                mod, ncells = p
                mod_path = os.path.join(OUT, "mod.bin")
                open(mod_path, "wb").write(mod)
                dump = run(mod_path, os.path.join(OUT, "mod_dump.bin"), pf)
                if len(dump) != len(base):
                    continue
                diff = [0xFFFF0000 + i for i in range(len(base))
                        if base[i] != dump[i]]
                hit = sorted({nm[a] for a in diff if a in nm})
                entry["conditions"][ckey] = {"cells": ncells,
                                             "moved": len(diff), "named": hit}
                sys.stderr.write("  %d/%d  %s %-14s %d cells -> %d addr%s\n"
                                 % (done, total, key, ckey, ncells, len(diff),
                                    ("  " + ", ".join(hit[:2])) if hit else ""))
                sys.stderr.flush()
                # Written as it goes, so a long run can be read while running.
                if args.json:
                    with open(args.json, "w", encoding="utf-8",
                              newline="\n") as fh:
                        json.dump(result, fh, indent=1, sort_keys=True)

    for v in result.values():
        allnames, moved = set(), 0
        for c in v.get("conditions", {}).values():
            allnames |= set(c["named"])
            moved = max(moved, c["moved"])
        v["named"] = sorted(allnames)
        v["moved"] = moved

    named = {k: v for k, v in result.items() if v.get("named")}
    print("\n%d tables perturbed, %d moved a named address\n"
          % (len(result), len(named)))
    count = {}
    for v in named.values():
        for x in v["named"]:
            count[x] = count.get(x, 0) + 1
    print("  name reach - a name most tables move is a hub, not a finding:")
    for x, c in sorted(count.items(), key=lambda kv: -kv[1])[:8]:
        print("    %-46s %d tables" % (x[:46], c))
    print()
    for k, v in sorted(named.items(), key=lambda kv: len(kv[1]["named"])):
        specific = [x for x in v["named"] if count[x] <= max(3, len(named) // 6)]
        if specific:
            print("  %s  ->  %s" % (k, ", ".join(specific)))

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
        print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
