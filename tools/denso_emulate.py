#!/usr/bin/env python3
"""Run a Denso TCU function under emulation and report the tables it reads.

Static analysis says what a table is read *near*. This says what a routine actually
does: set the inputs, execute the real instructions, and see which calibration
tables the path touches and what comes back.

Ghidra ships a p-code emulator that works against whatever language a program was
loaded with, so this runs on the SH-2E definition this project added rather than an
approximation. `tools/ghidra/DensoEmuTable.java` does the stepping and prints the
executed path; this drives it and joins that path against the literal map from
denso_literals.py, since every calibration access on this core goes through a
PC-relative literal (section 46).

    python tools/denso_emulate.py 0x0002C3DA
    python tools/denso_emulate.py 0x0002C3DA --regs r4=0x40 r5=0x1000
    python tools/denso_emulate.py 0x0002C3DA --sweep r4=0,255,16

--sweep runs the function repeatedly over a range of one argument, which is how a
table's role shows itself: an input that changes which rows are read is an axis.

Requires GHIDRA_HOME and a project built by tools/ghidra/decompile_all_denso.sh.
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

GHIDRA = os.environ.get("GHIDRA_HOME", os.path.expanduser("~/ghidra_12.1.2_PUBLIC"))
PROJECT = os.environ.get("DENSO_PROJECT", os.path.expanduser("~/sh2e_test/w"))
SCRIPTS = os.environ.get("GHIDRA_SCRIPTS", os.path.expanduser("~/my_scripts"))

HEX6 = re.compile(r"\b[0-9A-F]{6}\b")


def site_map():
    if not os.path.exists(LITERALS):
        sys.stderr.write("run tools/denso_literals.py first\n")
        return None
    lit = json.load(open(LITERALS, encoding="utf-8"))
    out = {}
    for table, sites in lit["tables"].items():
        for s in sites:
            out[s] = int(table, 16)
    return out


def emulate(entry, regs, steps):
    cmd = [os.path.join(GHIDRA, "support", "analyzeHeadless"), PROJECT, "p",
           "-process", "t.bin", "-noanalysis",
           "-scriptPath", SCRIPTS,
           "-postScript", "DensoEmuTable.java", entry, str(steps)] + regs
    env = dict(os.environ)
    env.setdefault("TMPDIR", os.path.expanduser("~/gtmp"))
    env["_JAVA_OPTIONS"] = "-Djava.io.tmpdir=" + env["TMPDIR"]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    path, result = [], ""
    for line in (p.stdout + p.stderr).splitlines():
        if "PATH " in line:
            path = [int(x, 16) for x in HEX6.findall(line.split("PATH ", 1)[1])]
        elif "RESULT " in line:
            result = line.split("RESULT ", 1)[1].replace("(GhidraScript)", "").strip()
    return path, result


def report(path, result, sites, label=""):
    hits = [(p, sites[p]) for p in path if p in sites]
    tables = {}
    for p, t in hits:
        tables.setdefault(t, 0)
        tables[t] += 1
    print("%s%s" % (label, result))
    print("   %d instructions, %d table loads, %d distinct tables"
          % (len(path), len(hits), len(tables)))
    for t in sorted(tables):
        print("      0x%06X  x%d" % (t, tables[t]))
    return tables


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entry")
    ap.add_argument("--regs", nargs="*", default=[])
    ap.add_argument("--steps", type=int, default=20000)
    ap.add_argument("--sweep", help="reg=start,stop,step - run once per value")
    args = ap.parse_args()

    sites = site_map()
    if sites is None:
        return 1

    if args.sweep:
        reg, rng = args.sweep.split("=", 1)
        start, stop, step = (int(x, 0) for x in rng.split(","))
        seen = {}
        for v in range(start, stop + 1, step):
            regs = list(args.regs) + ["%s=0x%X" % (reg, v)]
            path, result = emulate(args.entry, regs, args.steps)
            tables = report(path, result, sites, label="%s=0x%02X  " % (reg, v))
            for t in tables:
                seen.setdefault(t, []).append(v)
            print()
        print("tables by which %s values reach them:" % reg)
        for t in sorted(seen):
            vals = seen[t]
            print("   0x%06X  %d of %d runs" % (t, len(vals),
                                                len(range(start, stop + 1, step))))
    else:
        path, result = emulate(args.entry, args.regs, args.steps)
        report(path, result, sites)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
