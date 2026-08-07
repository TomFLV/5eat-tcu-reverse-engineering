#!/usr/bin/env python3
"""The isolation campaign, run on the native core instead of p-code.

Section 62 swept forty inputs against one entry point and took about half an hour
across twelve parallel emulators. The native core of section 67 does the same work
in the time it takes to write the profiles, which makes it worth sweeping all 119
inputs the cross-reference found rather than the forty that fitted in a coffee
break.

The entry point matters for trust. The native core is exact against the p-code
emulator for a single function - 358 of 358 cells - and only diverges once a long
task list lets some task wander into the vector table. A single-function sweep is
therefore inside the regime where the two agree exactly, which is why this is a
safe place to use the fast core and the full-controller drives are not.

    python tools/denso_campaign_native.py --run
    python tools/denso_campaign_native.py --analyse
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
OUT = os.path.join(HERE, "denso_campaign_native.json")

SH2 = os.environ.get("SH2_BIN", SH2_WSL)
ROM = os.environ.get("SH2_ROM",
    REPO_WSL + "/rom-denso/Impreza_STI_3.583_JDM2011.bin")
WORK = os.environ.get("SH2_WORK", WORK_WSL + "/campaign")
WIN_WORK = os.environ.get("SH2_WORK_WIN", WORK + "/campaign")
XREF = os.environ.get("SH2_XREF", WORK + "/xref.json")
ENTRY = os.environ.get("SH2_ENTRY", "0x00023E72")

HOLD = 0x40
TICKS = 256


def inputs_from_xref(path, min_reads=4):
    """Addresses read often and written by nothing - FINDINGS 60 and 61c."""
    with open(path, encoding="utf-8") as fh:
        x = json.load(fh)
    reads = {int(k, 16): v for k, v in x["reads"].items()}
    writes = {int(k, 16) for k in x["writes"]}
    return sorted(a for a, s in reads.items()
                  if a not in writes and 0xFFFF2000 <= a <= 0xFFFFBFFF
                  and len(s) >= min_reads)


def write_profile(path, sweep, addrs):
    lines = ["# isolation sweep of %08X" % sweep]
    for t in range(TICKS):
        parts = ["%d" % t]
        for a in addrs:
            parts.append("%08X:1=0x%X" % (a, (t % 256) if a == sweep else HOLD))
        lines.append(",".join(parts))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def responders(csv_path, sweep):
    """Addresses that moved, and whether they track the swept input.

    Correlation was the wrong test in section 54 - shift decisions are thresholds,
    so a value can depend entirely on an input while correlating weakly with it.
    Movement is the test; correlation is reported alongside as a hint, not a filter.
    """
    if not os.path.exists(csv_path) or not os.path.getsize(csv_path):
        return {}
    rows = list(csv.DictReader(open(csv_path)))
    if not rows:
        return {}
    cols = [c for c in rows[0] if c != "tick"]
    key = "%08X" % sweep

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
        if len(set(s)) <= 1:
            continue
        ms = sum(s) / n
        vs = sum((y - ms) ** 2 for y in s)
        r = (sum((x - md) * (y - ms) for x, y in zip(drive, s)) / (vd * vs) ** 0.5
             if vd and vs else 0.0)
        out[c] = round(r, 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--analyse", action="store_true")
    ap.add_argument("--entry", default=ENTRY)
    ap.add_argument("--min-reads", type=int, default=4)
    args = ap.parse_args()

    os.makedirs(WIN_WORK, exist_ok=True)
    results = {}
    if os.path.exists(OUT):
        results = json.load(open(OUT, encoding="utf-8"))

    if args.run:
        addrs = inputs_from_xref(XREF, args.min_reads)
        print("%d inputs derived from the cross-reference, entry %s\n"
              % (len(addrs), args.entry))
        for i, a in enumerate(addrs):
            key = "%08X" % a
            prof_win = os.path.join(WIN_WORK, "p_%s.csv" % key)
            log_win = os.path.join(WIN_WORK, "l_%s.csv" % key)
            write_profile(prof_win, a, addrs)
            cmd = ["wsl", SH2, ROM,
                   "%s/p_%s.csv" % (WORK, key), "%s/l_%s.csv" % (WORK, key),
                   args.entry, "200000"]
            p = subprocess.run(cmd, capture_output=True, text=True)
            resp = responders(log_win, a)
            results[key] = {"moved": len(resp),
                            "responders": {k: v for k, v in resp.items()
                                           if abs(v) >= 0.9}}
            print("  %3d/%d  %s  %4d moved, %3d track it closely"
                  % (i + 1, len(addrs), key, len(resp),
                     len(results[key]["responders"])))
            sys.stdout.flush()
        with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(results, fh, indent=1, sort_keys=True)
        print("\n-> %s" % OUT)

    if args.analyse or not args.run:
        if not results:
            sys.stderr.write("nothing to analyse; --run first\n")
            return 1
        owners = {}
        for inp, d in results.items():
            for a in d.get("responders", {}):
                owners.setdefault(a, []).append(inp)
        unique = {a: v[0] for a, v in owners.items() if len(v) == 1}
        print("%d computed addresses answer to exactly one input\n" % len(unique))
        by_input = {}
        for a, inp in unique.items():
            by_input.setdefault(inp, []).append(a)
        for inp in sorted(by_input, key=lambda k: -len(by_input[k])):
            print("  0x%s drives %d addresses" % (inp, len(by_input[inp])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
