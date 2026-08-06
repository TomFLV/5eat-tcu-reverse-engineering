#!/usr/bin/env python3
"""Isolate every input in turn and record what the firmware computes from it.

The drive of FINDINGS 55 moved all the inputs at once, which shows that a
dependency exists but cannot separate one input's effect from another's. This runs
each input on its own: everything else is held at a plausible constant while one
address is walked across its full range, and the whole of RAM is watched.

An address that moves only when input X moves is computed from X. An address that
moves in every run is internal state on a timer. An address that never moves is not
reached on this path.

Nothing here needs a name for the input, so the result does not inherit the
assumption that sank the naming in section 55c - the graph is true regardless of
what the input turns out to be.

    python tools/denso_campaign.py --run          # every input, full range
    python tools/denso_campaign.py --analyse      # read the results back

Each run is one emulator session of 256 ticks, which takes well under a minute.
"""

import argparse
import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(HERE, "denso_campaign.json")
WORK = os.environ.get("DENSO_WORK_DIR", os.path.expanduser("~/campaign"))

GHIDRA = os.environ.get("GHIDRA_HOME", os.path.expanduser("~/ghidra_12.1.2_PUBLIC"))
PROJECT = os.environ.get("DENSO_PROJECT", os.path.expanduser("~/sh2e_test/w"))
SCRIPTS = os.environ.get("GHIDRA_SCRIPTS", os.path.expanduser("~/my_scripts"))
ENTRY = "0x00023E72"

# Every address probing showed the control code reads (FINDINGS 53, 54), plus the
# schedule selector. These are the levers; everything else is watched.
INPUTS = [
    0xFFFF9F55, 0xFFFF8A88, 0xFFFF8A89, 0xFFFF8A8A, 0xFFFF357C, 0xFFFF357A,
    0xFFFF33AC, 0xFFFF32D0, 0xFFFF35E1, 0xFFFF8E60, 0xFFFF8E62, 0xFFFF8E64,
    0xFFFF9152, 0xFFFF99C9, 0xFFFF99CF, 0xFFFF86ED, 0xFFFF86D7, 0xFFFF8EA0,
    0xFFFF34A8, 0xFFFF3332, 0xFFFF35E1, 0xFFFF9F55,
]

# A mid-scale hold for the inputs not being swept, so comparisons are not all
# against zero. All-zero RAM makes every branch take its default and hides the
# dependency entirely - that is what made the first sweeps look flat (FINDINGS 53a).
HOLD = 0x40


def write_profile(path, sweep_addr, ticks=256):
    lines = ["# isolation sweep of %08X" % sweep_addr]
    for t in range(ticks):
        parts = ["%d" % t]
        for a in sorted(set(INPUTS)):
            v = (t % 256) if a == sweep_addr else HOLD
            parts.append("%08X:1=0x%X" % (a, v))
        lines.append(",".join(parts))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def run_drive(profile, out_csv):
    cmd = [os.path.join(GHIDRA, "support", "analyzeHeadless"), PROJECT, "p",
           "-process", "t.bin", "-noanalysis", "-scriptPath", SCRIPTS,
           "-postScript", "DensoDriveLog.java", ENTRY, profile, out_csv, "200000"]
    env = dict(os.environ)
    env.setdefault("TMPDIR", os.path.expanduser("~/gtmp"))
    env["_JAVA_OPTIONS"] = "-Djava.io.tmpdir=" + env["TMPDIR"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=1800)
    except subprocess.TimeoutExpired:
        return None
    for line in (p.stdout + p.stderr).splitlines():
        if "RESULT " in line:
            return line.split("RESULT ", 1)[1].replace("(GhidraScript)", "").strip()
    return None


def responders(csv_path, sweep_addr):
    """Addresses that moved, and how strongly they follow the swept input."""
    if not os.path.exists(csv_path):
        return {}
    rows = list(csv.DictReader(open(csv_path)))
    if not rows:
        return {}
    cols = [c for c in rows[0] if c != "tick"]
    key = "%08X" % sweep_addr

    def series(c):
        out, last = [], 0
        for r in rows:
            v = r.get(c)
            if v not in ("", None):
                last = int(v)
            out.append(last)
        return out

    if key not in cols:
        return {}
    drive = series(key)
    n = len(drive)
    md = sum(drive) / n
    vd = sum((x - md) ** 2 for x in drive)
    out = {}
    for c in cols:
        if c == key:
            continue
        s = series(c)
        ms = sum(s) / n
        vs = sum((y - ms) ** 2 for y in s)
        if vs == 0 or vd == 0:
            continue
        r = sum((x - md) * (y - ms) for x, y in zip(drive, s)) / (vd * vs) ** 0.5
        out[c] = round(r, 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--analyse", action="store_true")
    ap.add_argument("--ticks", type=int, default=256)
    args = ap.parse_args()

    os.makedirs(WORK, exist_ok=True)
    results = {}
    if os.path.exists(OUT):
        results = json.load(open(OUT, encoding="utf-8"))

    if args.run:
        for addr in sorted(set(INPUTS)):
            key = "%08X" % addr
            if key in results:
                print("%s  already done (%d responders)"
                      % (key, len(results[key].get("responders", {}))))
                continue
            prof = os.path.join(WORK, "prof_%s.csv" % key)
            log = os.path.join(WORK, "log_%s.csv" % key)
            write_profile(prof, addr, args.ticks)
            res = run_drive(prof, log)
            if res is None:
                print("%s  FAILED or timed out" % key)
                continue
            resp = responders(log, addr)
            strong = {k: v for k, v in resp.items() if abs(v) >= 0.9}
            results[key] = {"result": res, "responders": strong,
                            "moved": len(resp)}
            print("%s  %-46s  %d moved, %d follow it closely"
                  % (key, res, len(resp), len(strong)))
            with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(results, fh, indent=1, sort_keys=True)

    if args.analyse or not args.run:
        if not results:
            sys.stderr.write("nothing to analyse; run with --run first\n")
            return 1
        # Which computed addresses answer to exactly one input.
        owners = {}
        for inp, d in results.items():
            for addr in d.get("responders", {}):
                owners.setdefault(addr, []).append(inp)
        unique = {a: v[0] for a, v in owners.items() if len(v) == 1}
        print("\n%d computed addresses follow exactly one input:" % len(unique))
        for a in sorted(unique):
            print("   0x%s  <-  0x%s  (r=%.3f)"
                  % (a, unique[a], results[unique[a]]["responders"][a]))
        shared = {a: v for a, v in owners.items() if len(v) > 1}
        print("\n%d follow more than one, so they are downstream of several"
              % len(shared))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
