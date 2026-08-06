#!/usr/bin/env python3
"""Probe a Denso function by experiment: find its inputs and what they select.

The procedure of FINDINGS section 53, automated:

  1. Emulate the function and record the RAM its executed path reads.
  2. Run once with all of those set to zero, once with all set high. If the result
     is identical, the function is genuinely input-independent on this path.
  3. If it moved, set one address high at a time against the zero baseline to find
     which one carries the effect.
  4. Sweep that address and print the mapping from value to result.

Step 2 matters. With RAM zeroed every comparison takes its default branch, so a
function can look inert to any single input while responding perfectly well to a
plausible state. Probing one variable at a time is the wrong experiment and it cost
this project several wrong conclusions before section 53.

    python tools/denso_probe.py 0x00023E72
    python tools/denso_probe.py --top 10          # the biggest table consumers
    python tools/denso_probe.py --batch funcs.txt

Results are appended to tools/denso_probe_results.json so a long run can be stopped
and resumed.
"""

import argparse
import json
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LITERALS = os.path.join(HERE, "denso_literals.json")
RESULTS = os.path.join(HERE, "denso_probe_results.json")

GHIDRA = os.environ.get("GHIDRA_HOME", os.path.expanduser("~/ghidra_12.1.2_PUBLIC"))
PROJECT = os.environ.get("DENSO_PROJECT", os.path.expanduser("~/sh2e_test/w"))
SCRIPTS = os.environ.get("GHIDRA_SCRIPTS", os.path.expanduser("~/my_scripts"))
LISTING = os.path.join(REPO, "disasm-denso", "Impreza_STI_3.583_JDM2011.asm")
ROM = os.path.join(REPO, "rom-denso", "Impreza_STI_3.583_JDM2011.bin")

HEX6 = re.compile(r"\b[0-9A-F]{6}\b")
ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s*_?(\S+)\s*(.*)$")
POOL = re.compile(r"@\(0x([0-9a-f]+),pc\),(\w+)")
READ = re.compile(r"^mov\.[bwl]\s+@(\w+)[,+]")
READ_DISP = re.compile(r"^mov\.[bwl]\s+@\(0x([0-9a-f]+),(\w+)\),")
RESULT = re.compile(r"steps=(\d+).*?r0=0x([0-9a-f]+) r1=0x([0-9a-f]+)")

# More than this and the probe is guessing rather than bisecting; the function is
# reading a structure and needs looking at rather than poking.
MAX_INPUTS = 24


def load_listing():
    rows = {}
    for line in open(LISTING, encoding="utf-8", errors="replace"):
        m = ROW.match(line.rstrip("\n"))
        if m and not m.group(2).startswith("."):
            rows[int(m.group(1), 16)] = (m.group(2), m.group(3))
    return rows


def emulate(entry, writes, steps=60000):
    args = ["0x%08X" % entry, str(steps)]
    for addr, val in writes:
        args.append("@%08X:1=0x%X" % (addr, val))
    cmd = [os.path.join(GHIDRA, "support", "analyzeHeadless"), PROJECT, "p",
           "-process", "t.bin", "-noanalysis", "-scriptPath", SCRIPTS,
           "-postScript", "DensoEmuTable.java"] + args
    env = dict(os.environ)
    env.setdefault("TMPDIR", os.path.expanduser("~/gtmp"))
    env["_JAVA_OPTIONS"] = "-Djava.io.tmpdir=" + env["TMPDIR"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    except subprocess.TimeoutExpired:
        return None, None
    path, res = [], None
    for line in (p.stdout + p.stderr).splitlines():
        if "PATH " in line:
            path = [int(x, 16) for x in HEX6.findall(line.split("PATH ", 1)[1])]
        elif "RESULT " in line:
            m = RESULT.search(line)
            if m:
                res = (int(m.group(1)), m.group(2), m.group(3))
    return path, res


def reads_on_path(path, rows, data):
    """RAM addresses the taken path read, displacement forms included."""
    holds, reads = {}, {}
    for a in path:
        ins = rows.get(a)
        if not ins:
            continue
        mnem, rest = ins
        p = POOL.search(rest)
        if p and mnem.startswith("mov."):
            pool = int(p.group(1), 16)
            size = 4 if mnem == "mov.l" else 2
            if pool + size <= len(data):
                v = (struct.unpack_from(">I", data, pool)[0] if size == 4
                     else struct.unpack_from(">h", data, pool)[0] & 0xFFFFFFFF)
                if v >= 0xFFFF0000:
                    holds[p.group(2)] = v
            continue
        full = (mnem + " " + rest).strip()
        m = READ_DISP.match(full)
        if m and m.group(2) in holds:
            a2 = holds[m.group(2)] + int(m.group(1), 16)
            reads[a2] = reads.get(a2, 0) + 1
            continue
        m = READ.match(full)
        if m and m.group(1) in holds:
            reads[holds[m.group(1)]] = reads.get(holds[m.group(1)], 0) + 1
    return reads


def probe(entry, rows, data, verbose=True):
    path, base = emulate(entry, [])
    if not path or not base:
        return {"entry": "0x%08X" % entry, "status": "no run"}
    reads = reads_on_path(path, rows, data)
    if not reads:
        return {"entry": "0x%08X" % entry, "status": "reads no RAM",
                "steps": base[0]}
    inputs = sorted(reads, key=lambda a: -reads[a])[:MAX_INPUTS]

    _p, high = emulate(entry, [(a, 0x40) for a in inputs])
    if high is None:
        return {"entry": "0x%08X" % entry, "status": "timeout"}
    if high == base:
        return {"entry": "0x%08X" % entry, "status": "input-independent",
                "steps": base[0], "inputs": len(inputs)}

    # Something moved. Which one?
    carriers = []
    for a in inputs:
        _p, one = emulate(entry, [(a, 0x40)])
        if one and one[2] != base[2]:
            carriers.append("%08X" % a)

    out = {"entry": "0x%08X" % entry, "status": "responds",
           "steps": base[0], "inputs": len(inputs),
           "baseline_r1": base[2], "all_high_r1": high[2],
           "carriers": carriers}

    # Sweep the first carrier and read the mapping off r1.
    if carriers:
        a = int(carriers[0], 16)
        mapping = {}
        for v in range(0, 9):
            _p, r = emulate(entry, [(a, v)])
            if r:
                mapping[v] = r[2]
        out["sweep"] = {"address": carriers[0], "r1_by_value": mapping}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entries", nargs="*")
    ap.add_argument("--top", type=int, help="probe the N biggest table consumers")
    args = ap.parse_args()

    rows = load_listing()
    data = open(ROM, "rb").read()

    targets = [int(e, 16) for e in args.entries]
    if args.top:
        lit = json.load(open(LITERALS, encoding="utf-8"))["tables"]
        site2tab = {}
        for t, sites in lit.items():
            for s in sites:
                site2tab[s] = int(t, 16)
        addrs = sorted(rows)
        funcs, start, pend = [], None, False
        for a in addrs:
            if start is None:
                start = a
            if pend:
                funcs.append((start, a))
                start, pend = None, False
            elif rows[a][0] == "rts":
                pend = True
        scored = []
        for lo, hi in funcs:
            n = len({site2tab[s] for s in site2tab if lo <= s <= hi})
            if n:
                scored.append((n, lo))
        scored.sort(reverse=True)
        targets = [lo for _n, lo in scored[:args.top]]

    done = {}
    if os.path.exists(RESULTS):
        done = json.load(open(RESULTS, encoding="utf-8"))

    for entry in targets:
        key = "0x%08X" % entry
        if key in done:
            print("%s  (already probed: %s)" % (key, done[key]["status"]))
            continue
        r = probe(entry, rows, data)
        done[key] = r
        line = "%s  %-18s" % (key, r["status"])
        if r.get("carriers"):
            line += "  carriers: " + ", ".join(r["carriers"][:4])
        if r.get("sweep"):
            vals = r["sweep"]["r1_by_value"]
            line += "  distinct r1: %d" % len(set(vals.values()))
        print(line)
        with open(RESULTS, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(done, fh, indent=1, sort_keys=True)

    print("\n-> %s" % RESULTS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
