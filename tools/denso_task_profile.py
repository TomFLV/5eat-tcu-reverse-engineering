#!/usr/bin/env python3
"""Characterise each task by what it does to RAM, and find the ones that must not
run periodically.

The task list of section 63 is the call-graph roots - functions nothing calls by
name, which on a table-dispatched controller is a good approximation of the task
set. It is only an approximation, and one member of it turned out to be a RAM self
test: task 0x00008D58 copies 0xFFFF2000-0xFFFF27FF into 0xFFFF9000-0xFFFF97FF and
fills the source with 0x5AA5A55A, the classic memory test pattern. On the car that
runs once at startup. In the harness it ran on every one of 568 ticks.

That is worth catching for two reasons beyond the obvious corruption. The block it
saves into, 0xFFFF9000-0xFFFF97FF, is where section 61c found "the hottest block in
the firmware, 476 read sites and no writer" - those reads are the test's own verify
loop, not control code, which is why sweeping every one of them changed nothing.
And a destructive routine running every tick is a strong candidate for the seven
percent the native core and the p-code emulator disagree by.

A task that writes a large contiguous span in one pass is an initialiser or a self
test. A control task touches a handful of scattered bytes. That separates them
without needing to understand any of them.

    python tools/denso_task_profile.py --run
    python tools/denso_task_profile.py --list-suspect
"""

import argparse
import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "denso_task_profile.json")
SH2 = "/mnt/d/5eat-work/sh2/sh2"
ROM = ("/mnt/c/Users/Tom/Desktop/5eat-tcu-reverse-engineering/rom-denso/"
       "Impreza_STI_3.583_JDM2011.bin")
WIN = "D:/5eat-work/taskprof"
LIN = "/mnt/d/5eat-work/taskprof"
TASKS = "D:/5eat-work/tasks_trace.txt"

# More than this many bytes touched in two ticks and it is not a control task.
SUSPECT_BYTES = 256


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--list-suspect", action="store_true")
    ap.add_argument("--threshold", type=int, default=SUSPECT_BYTES)
    args = ap.parse_args()

    os.makedirs(WIN, exist_ok=True)
    prof = WIN + "/empty.csv"
    with open(prof, "w", newline="\n") as fh:
        fh.write("# nothing injected\n" + "\n".join(str(t) for t in range(3)) + "\n")

    results = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}

    if args.run:
        tasks = open(TASKS).read().strip().split("+")
        print("%d tasks, each run alone for 3 ticks\n" % len(tasks))
        for i, t in enumerate(tasks):
            out = WIN + "/t_%s.csv" % t.replace("0x", "")
            ws = WIN + "/w_%s.txt" % t.replace("0x", "")
            env = dict(os.environ)
            env["WSLENV"] = "SH2_WRITESET/u"
            env["SH2_WRITESET"] = ws.replace("D:/5eat-work", "/mnt/d/5eat-work")
            subprocess.run(["wsl", SH2, ROM, LIN + "/empty.csv",
                            out.replace("D:/5eat-work", "/mnt/d/5eat-work"),
                            t, "20000"], capture_output=True, env=env)
            # The write set, not the tick-to-tick diff. A routine that writes the
            # same value every tick is invisible to the diff, which is how a RAM
            # self test ran on every tick of every drive without being noticed.
            n, span = 0, 0
            if os.path.exists(ws) and os.path.getsize(ws):
                lines = open(ws).read().split()
                n = int(lines[0])
                if n:
                    a = [int(x, 16) for x in lines[1:]]
                    span = max(a) - min(a)
            results[t] = {"touched": n, "span": span}
            if n >= args.threshold:
                print("  %-12s touches %5d bytes over a span of 0x%X  <-- suspect"
                      % (t, n, span))
            sys.stdout.flush()
        with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(results, fh, indent=1, sort_keys=True)
        print("\n-> %s" % OUT)

    if args.list_suspect or not args.run:
        if not results:
            sys.stderr.write("nothing yet; --run first\n")
            return 1
        sus = sorted((k for k, v in results.items() if v["touched"] >= args.threshold),
                     key=lambda k: -results[k]["touched"])
        print("%d of %d tasks touch %d+ bytes and should not run every tick:\n"
              % (len(sus), len(results), args.threshold))
        for k in sus:
            print("  %-12s %5d bytes, span 0x%X"
                  % (k, results[k]["touched"], results[k]["span"]))
        keep = [k for k in results if k not in set(sus)]
        with open("D:/5eat-work/tasks_control.txt", "w", newline="\n") as fh:
            fh.write("+".join(sorted(keep, key=lambda k: int(k, 16))))
        print("\n%d control tasks -> D:/5eat-work/tasks_control.txt" % len(keep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
