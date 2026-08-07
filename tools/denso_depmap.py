#!/usr/bin/env python3
"""The input-to-output dependency map of the whole controller.

Section 62 could only sweep inputs against a single function, because a drive of
the full task list took ten minutes and 119 inputs would have been twenty hours.
The native core makes each drive about a third of a second, so the sweep that was
out of reach is now a minute and a half.

WHY THIS IS SOUND DESPITE SECTION 67b. The native core agrees with the p-code
emulator exactly for a single function but only to 92.7 percent over a long task
list, and the cause is still open. That would matter if the question were "what
value does this address hold". It is not. The question is "which addresses move
when this input moves", and that is answered by comparing two native runs against
each other - swept against held - so whatever makes the native core diverge from
p-code is present in both arms and cancels. The map is a statement about the
firmware's dependency structure, not about absolute values.

    python tools/denso_depmap.py --run
    python tools/denso_depmap.py --report
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, REPO_WSL, WORK, WORK_WSL, SH2_WSL  # noqa: E402

import argparse
import csv
import json
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "denso_depmap.json")

SH2 = os.environ.get("SH2_BIN", SH2_WSL)
ROM = os.environ.get("SH2_ROM",
    REPO_WSL + "/rom-denso/Impreza_STI_3.583_JDM2011.bin")
WORK = WORK_WSL + "/depmap"
WIN = WORK + "/depmap"
XREF = WORK + "/xref.json"
TASKS = WORK + "/tasks_ctl.txt"

TICKS = 8
HOLD = 0x40
PROBE = 0x80

# Two constants, not a sweep against a hold. Sweeping the input while the
# control holds it means the two runs differ at every tick from the first, and
# with 399 tasks sharing state that separates the trajectories completely - the
# first attempt reported every input driving all 2,265 moving addresses, which
# is the experiment failing rather than the firmware being coupled. Holding the
# input at one constant against another isolates it: the schedule selector then
# drives 15 addresses and an inert input drives none, and the answer is stable
# from the second tick on.


def inputs_from_xref(path, min_reads=4):
    with open(path, encoding="utf-8") as fh:
        x = json.load(fh)
    reads = {int(k, 16): v for k, v in x["reads"].items()}
    writes = {int(k, 16) for k in x["writes"]}
    return sorted(a for a, s in reads.items()
                  if a not in writes and 0xFFFF2000 <= a <= 0xFFFFBFFF
                  and not (0xFFFF9000 <= a <= 0xFFFF97FF)
                  and not (0xFFFF2000 <= a <= 0xFFFF27FF)
                  and len(s) >= min_reads)


def profile(path, addrs, sweep=None):
    """One profile. sweep=None holds every input, which is the control."""
    lines = ["# depmap"]
    for t in range(TICKS):
        parts = ["%d" % t]
        for a in addrs:
            v = PROBE if a == sweep else HOLD
            parts.append("%08X:1=0x%X" % (a, v))
        lines.append(",".join(parts))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def series(path):
    if not os.path.exists(path) or not os.path.getsize(path):
        return {}
    rows = list(csv.DictReader(open(path)))
    if not rows:
        return {}
    out = {}
    for c in [c for c in rows[0] if c != "tick"]:
        vals, last = [], 0
        for r in rows:
            v = r.get(c)
            if v not in ("", None):
                last = int(v)
            vals.append(last)
        out[c] = vals
    return out


def run(prof_win, out_win, entry):
    subprocess.run(["wsl", SH2, ROM,
                    prof_win.replace(WORK , WORK_WSL ),
                    out_win.replace(WORK , WORK_WSL ),
                    entry, "5000"],
                   capture_output=True, text=True)
    return series(out_win)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--min-reads", type=int, default=4)
    args = ap.parse_args()

    os.makedirs(WIN, exist_ok=True)
    results = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}

    if args.run:
        addrs = inputs_from_xref(XREF, args.min_reads)
        entry = "@" + WORK_WSL + "/tasks_ctl.txt"
        ntasks_txt = open(TASKS).read().strip()
        ntasks = ntasks_txt.count("+") + 1
        print("%d inputs, %d tasks per tick, %d ticks\n" % (len(addrs), ntasks, TICKS))

        base_prof = WIN + "/hold.csv"
        profile(base_prof, addrs, None)
        base = run(base_prof, WIN + "/hold_out.csv", entry)
        print("control run: %d addresses move on their own\n" % len(base))

        for i, a in enumerate(addrs):
            key = "%08X" % a
            p = WIN + "/p_%s.csv" % key
            o = WIN + "/o_%s.csv" % key
            profile(p, addrs, a)
            got = run(p, o, entry)
            driven = []
            for c in set(got) | set(base):
                if c == key:
                    continue
                x, y = got.get(c), base.get(c)
                if x is None or y is None or x != y:
                    driven.append(c)
            results[key] = sorted(driven)
            print("  %3d/%d  %s  drives %d addresses"
                  % (i + 1, len(addrs), key, len(driven)))
            sys.stdout.flush()
        with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(results, fh, indent=1, sort_keys=True)
        print("\n-> %s" % OUT)

    if args.report or not args.run:
        if not results:
            sys.stderr.write("nothing to report; --run first\n")
            return 1
        print("inputs that drive anything:\n")
        for k in sorted(results, key=lambda k: -len(results[k])):
            if results[k]:
                print("  0x%s  %4d addresses" % (k, len(results[k])))
        owners = {}
        for inp, outs in results.items():
            for o in outs:
                owners.setdefault(o, []).append(inp)
        unique = {o: v[0] for o, v in owners.items() if len(v) == 1}
        print("\n%d addresses are driven by exactly one input" % len(unique))
        print("%d are driven by more than one" % (len(owners) - len(unique)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
