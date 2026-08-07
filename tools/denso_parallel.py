#!/usr/bin/env python3
"""Run many emulator drives at once, one per core.

A drive of the full task list takes about ten minutes and pins exactly one core
while the other fifteen sit idle. Nothing about the work requires that: each drive
is independent, so the machine can do fifteen more of them for free.

Not a job for the GPU, incidentally. The p-code emulator interprets one
instruction at a time with a data dependency between every step and a branch in
most of them, which is the shape CUDA is worst at - it wants thousands of threads
doing identical arithmetic on independent data. There is no CUDA backend for
p-code either. The parallelism worth having is across whole drives, and that is
process-level.

The one obstacle is that Ghidra locks a project while it is open, so concurrent
runs need a project each. They are 39 MB, so the workers get a copy apiece, made
once and reused.

    python tools/denso_parallel.py --jobs jobs.json --workers 12

jobs.json is a list of objects:

    [{"name": "a", "entry": "0x...+0x...", "profile": "/path/p.csv",
      "out": "/path/log.csv", "steps": 5000}, ...]

Results come back as a dict keyed by name, each with the RESULT line parsed out.
Run it under WSL, where Ghidra lives.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

GHIDRA = os.environ.get("GHIDRA_HOME", os.path.expanduser("~/ghidra_12.1.2_PUBLIC"))
PROJECT = os.environ.get("DENSO_PROJECT", os.path.expanduser("~/sh2e_test/w"))
SCRIPTS = os.environ.get("GHIDRA_SCRIPTS", os.path.expanduser("~/my_scripts"))
POOL = os.environ.get("DENSO_WORKER_DIR", os.path.expanduser("~/workers"))

RESULT = re.compile(
    r"RESULT ticks=(\d+) instructions=(\d+) changed=(\d+)(?: failed=(\d+))?")


def worker_project(i):
    """A private copy of the project for worker i, made once and kept.

    Ghidra holds a lock on an open project, so concurrent runs against one copy
    serialise at best and corrupt it at worst.
    """
    path = os.path.join(POOL, "w%d" % i)
    if not os.path.isdir(path):
        os.makedirs(POOL, exist_ok=True)
        shutil.copytree(PROJECT, path)
        # A copied project can carry a stale lock from whenever it was taken.
        for root, _dirs, files in os.walk(path):
            for f in files:
                if f.endswith(".lock") or f.startswith("~"):
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass
    return path


def run_one(i, job):
    proj = worker_project(i)
    log = job["out"] + ".log"
    cmd = [os.path.join(GHIDRA, "support", "analyzeHeadless"), proj, "p",
           "-process", "t.bin", "-noanalysis", "-scriptPath", SCRIPTS,
           "-postScript", "DensoDriveLog.java",
           job["entry"], job["profile"], job["out"],
           str(job.get("steps", 5000))]
    env = dict(os.environ)
    tmp = os.path.join(POOL, "tmp%d" % i)
    os.makedirs(tmp, exist_ok=True)
    env["TMPDIR"] = tmp
    env["_JAVA_OPTIONS"] = "-Djava.io.tmpdir=" + tmp
    with open(log, "w") as fh:
        subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env)
    out = {"name": job["name"], "log": log}
    with open(log, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    m = RESULT.search(text)
    if m:
        out.update(ticks=int(m.group(1)), instructions=int(m.group(2)),
                   changed=int(m.group(3)),
                   failed=int(m.group(4)) if m.group(4) else 0)
    else:
        out["error"] = "no RESULT line"
    out["decode_errors"] = text.count("Emulation failure")
    return out


def run_all(jobs, workers):
    slots = list(range(workers))
    results = {}

    def task(job_index):
        job = jobs[job_index]
        slot = slots[job_index % workers]
        r = run_one(slot, job)
        print("  %-22s changed=%-6s instr=%-10s %s"
              % (r["name"], r.get("changed", "-"),
                 r.get("instructions", "-"), r.get("error", "")))
        sys.stdout.flush()
        return r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(task, range(len(jobs))):
            results[r["name"]] = r
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out")
    args = ap.parse_args()

    with open(args.jobs, encoding="utf-8") as fh:
        jobs = json.load(fh)
    print("%d jobs on %d workers\n" % (len(jobs), args.workers))
    results = run_all(jobs, args.workers)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(results, fh, indent=1, sort_keys=True)
        print("\n-> %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
