#!/usr/bin/env python3
"""Drive a Denso TCU under emulation and watch what it computes.

Set a vehicle state - road speed, pedal, gear, ATF temperature - run the control
code against it, and read back the RAM the firmware left behind. Then change one
input and do it again. What moves is what that input controls.

This is the same question the vehicle logs answer, except it costs seconds instead
of a drive, it works on all nine Denso images rather than the one car that was
available, and inputs can be set to values a car would never reach.

    python tools/denso_drive.py --entry 0x00023E72 --sweep pedal=0,255,64
    python tools/denso_drive.py --entry 0x00023E72 --state speed=60,pedal=128,gear=3
    python tools/denso_drive.py --cycle          # a whole drive, idle to redline

Inputs are written by name where the name is known. The names come from FINDINGS
section 47, and the caution in section 50 applies: several of these addresses are
what the firmware *publishes* rather than what it acts on, so writing them may
change nothing. That is a finding in itself and the tool reports it rather than
hiding it.

Requires a Ghidra project with the image loaded and an on-chip RAM block
(DensoAddRam.java), plus tools/denso_literals.json.
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LITERALS = os.path.join(HERE, "denso_literals.json")
VARS = os.path.join(HERE, "denso_working_vars.json")

GHIDRA = os.environ.get("GHIDRA_HOME", os.path.expanduser("~/ghidra_12.1.2_PUBLIC"))
PROJECT = os.environ.get("DENSO_PROJECT", os.path.expanduser("~/sh2e_test/w"))
SCRIPTS = os.environ.get("GHIDRA_SCRIPTS", os.path.expanduser("~/my_scripts"))

# The inputs a driving state is made of, and where they live. Sizes are what the
# copy routine reads, so a byte unless the parameter is a 16-bit quantity.
INPUTS = {
    "pedal":     (0xFFFF30FB, 1, "Accelerator Pedal Travel"),
    "gear":      (0xFFFFA015, 1, "Gear Position"),
    "front":     (0xFFFF3B16, 1, "Front Wheel Speed"),
    "rear":      (0xFFFF3B17, 1, "Rear Wheel Speed"),
    "atf":       (0xFFFF3B6C, 1, "ATF Temperature"),
    "battery":   (0xFFFF8A38, 2, "Battery Voltage"),
    "lateral":   (0xFFFF8A3C, 2, "Lateral G"),
    "sidrive":   (0xFFFFA6D8, 1, "SI-Drive Mode"),
}

# The block the Select Monitor staging buffer sits in, which is where computed
# results show up. Dumping it is how an output is observed.
WATCH = (0xFFFFA9F0, 0xFFFFAA20)

HEX6 = re.compile(r"\b[0-9A-F]{6}\b")


def run(entry, writes, dump, steps):
    args = [entry, str(steps)]
    for addr, size, value in writes:
        args.append("@%08X:%d=0x%X" % (addr, size, value))
    args.append("dump@%08X-%08X" % dump)
    cmd = [os.path.join(GHIDRA, "support", "analyzeHeadless"), PROJECT, "p",
           "-process", "t.bin", "-noanalysis", "-scriptPath", SCRIPTS,
           "-postScript", "DensoEmuTable.java"] + args
    env = dict(os.environ)
    env.setdefault("TMPDIR", os.path.expanduser("~/gtmp"))
    env["_JAVA_OPTIONS"] = "-Djava.io.tmpdir=" + env["TMPDIR"]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)

    path, result, mem = [], "", ""
    for line in (p.stdout + p.stderr).splitlines():
        if "PATH " in line:
            path = HEX6.findall(line.split("PATH ", 1)[1])
        elif "RESULT " in line:
            result = line.split("RESULT ", 1)[1].replace("(GhidraScript)", "").strip()
        elif "DUMP " in line:
            mem = line.split("DUMP ", 1)[1].replace("(GhidraScript)", "").strip()
    return path, result, mem


def site_map():
    if not os.path.exists(LITERALS):
        return {}
    lit = json.load(open(LITERALS, encoding="utf-8"))
    out = {}
    for table, sites in lit["tables"].items():
        for s in sites:
            out["%06X" % s] = int(table, 16)
    return out


def parse_state(text):
    writes = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        k, _, v = part.partition("=")
        if k not in INPUTS:
            sys.stderr.write("unknown input %r; known: %s\n"
                             % (k, ", ".join(sorted(INPUTS))))
            continue
        addr, size, _label = INPUTS[k]
        writes.append((addr, size, int(v, 0)))
    return writes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", default="0x00023E72",
                    help="function to run (default: the shift schedule selector)")
    ap.add_argument("--state", help="speed=60,pedal=128,gear=3")
    ap.add_argument("--sweep", help="pedal=0,255,64")
    ap.add_argument("--steps", type=int, default=60000)
    args = ap.parse_args()

    sites = site_map()

    def report(label, writes):
        path, result, mem = run(args.entry, writes, WATCH, args.steps)
        tables = sorted({sites[p] for p in path if p in sites})
        print("%-22s %s" % (label, result))
        print("   %d instructions, %d tables, buffer %s"
              % (len(path), len(tables), mem[:32] or "(not read)"))
        return path, mem, tables

    if args.sweep:
        name, rng = args.sweep.split("=", 1)
        lo, hi, step = (int(x, 0) for x in rng.split(","))
        base = parse_state(args.state)
        seen = {}
        for v in range(lo, hi + 1, step):
            writes = [w for w in base if w[0] != INPUTS[name][0]]
            addr, size, _l = INPUTS[name]
            writes.append((addr, size, v))
            path, mem, tables = report("%s=0x%02X" % (name, v), writes)
            seen[v] = (len(path), mem, tuple(tables))
        print()
        distinct_paths = {v[0] for v in seen.values()}
        distinct_mem = {v[1] for v in seen.values()}
        print("across %d runs: %d distinct path lengths, %d distinct buffer states"
              % (len(seen), len(distinct_paths), len(distinct_mem)))
        if len(distinct_paths) == 1 and len(distinct_mem) == 1:
            print("%s changed nothing. Either this function does not read it, or "
                  "the address is an output rather than an input (FINDINGS 50)."
                  % name)
    else:
        report("state", parse_state(args.state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
