#!/usr/bin/env python3
"""Name the shipped Denso tables from what each individual task writes.

Three earlier routes failed and one nearly worked. The one that nearly worked ran
each table's reading function on its own and looked at what it wrote; it named
five tables out of 185, because a function entered directly starts from a state no
running controller would be in, and most of them take an early exit and write
nothing.

Running the whole controller fixes the state and breaks the attribution: the
combined write set of 395 tasks touches nine thousand addresses, and every table
looks identical against it. What was missing is which *task* wrote what.

SH2_TASKSETS records that - one write set per entry, from a single warm run. The
chain then closes:

    table -> the function that reads it -> the task that calls that function
          -> the addresses that task writes -> what those addresses are known to be

    python tools/denso_name_by_task.py
    python tools/denso_name_by_task.py --json out.json

Tables whose task writes nothing named stay unnamed. That is the honest answer and
the one this project has had to relearn at every step.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, REPO_WSL, WORK, WORK_WSL, SH2_WSL  # noqa: E402

import argparse
import bisect
import json
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
LISTING = os.path.join(REPO, "disasm-denso", "Impreza_STI_3.583_JDM2011.asm")
LITERALS = os.path.join(HERE, "denso_literals.json")
SSM = os.path.join(HERE, "denso_ssm_addresses.json")
DEFS = os.path.join(REPO, "definitions", "5eat_tcu_denso_romraider_defs.xml")
CALLGRAPH = os.path.join(HERE, "denso_callgraph.json")

SH2 = SH2_WSL
ROM_L = (REPO_WSL + "/rom-denso/"
         "Impreza_STI_3.583_JDM2011.bin")
WIN, LIN = WORK + "/naming", WORK_WSL + "/naming"
TASKS = WORK_WSL + "/tasks_ctl.txt"
PROFILE = WORK_WSL + "/drive_short.csv"

ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s+_?(\S+)\s*(.*)$")
PROLOGUE = re.compile(r"^(r\d+|pr),@-r15$")


def function_starts():
    starts = []
    with open(LISTING, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = ROW.match(line.rstrip("\n"))
            if m and m.group(2) in ("mov.l", "sts.l") \
               and PROLOGUE.match(m.group(3).split(";")[0].strip()):
                starts.append(int(m.group(1), 16))
    starts.sort()
    out = []
    for a in starts:
        if not out or a - out[-1] > 2:
            out.append(a)
    return out


def shipped_headers():
    import xml.etree.ElementTree as ET
    out = []
    for rom in ET.parse(DEFS).getroot().iter("rom"):
        rid = rom.find("romid")
        if rid is None or (rid.findtext("xmlid") or "") != "SUBARU_5EAT_DENSO_WQDE2WB1":
            continue
        for tab in rom.findall("table"):
            m = re.search(r"Table ([0-9A-F]{6})", tab.get("name") or "")
            if m:
                out.append(m.group(1))
        break
    return out


def one_warm_run():
    """One warm run recording, per task, both what it writes and what it executes.

    Both halves come from the same run so they describe the same execution. The
    executed set is what replaces the static call graph: that graph resolves the
    callees of 1,322 functions and cannot follow indirect dispatch, which put all
    twenty of the functions reading shipped tables outside the reach of all 395
    tasks - an overlap of exactly zero, and a fact about the graph rather than
    about the firmware.
    """
    os.makedirs(WIN, exist_ok=True)
    env = dict(os.environ)
    env["SH2_TASKSETS"] = "%s/tasksets.txt" % LIN
    env["SH2_TASKPCS"] = "%s/taskpcs.txt" % LIN
    env["SH2_FNSETS"] = "%s/fnsets.txt" % LIN
    # Tell the core which addresses are function starts, so it can name the
    # function that is running however that function was reached. The call stack
    # only sees jsr and bsr, and the readers of the shipped tables are dispatched
    # to - they arrive by jmp and were never on it.
    env["SH2_FNENTRIES"] = "%s/fn_entries.txt" % LIN
    # Reads as well as writes. The second hop of the naming chain needs to know who
    # CONSUMES what a table's reader produced, and the static cross-reference sees
    # none of it: the readers write 280 addresses around 0xFFFF98xx and not one
    # appears there as ever being read, because they are reached by computed
    # address.
    env["SH2_FNREADS"] = "%s/fnreads.txt" % LIN
    env["WSLENV"] = ("SH2_TASKSETS/u:SH2_TASKPCS/u:SH2_FNSETS/u:"
                     "SH2_FNENTRIES/u:SH2_FNREADS/u")
    r = subprocess.run(["wsl", SH2, ROM_L, PROFILE, LIN + "/out.csv",
                        "@" + TASKS, "400000"],
                       capture_output=True, text=True, env=env)
    sys.stderr.write(r.stdout.strip() + "\n")

    def load(path, base):
        if not os.path.exists(path):
            sys.stderr.write("missing %s - is this build current?\n" % path)
            return {}
        out = {}
        for line in open(path):
            parts = line.split()
            if len(parts) >= 2:
                out[int(parts[0], 16)] = {int(x, 16) for x in parts[2:]}
        return out

    fns = {}
    fp = "%s/fnsets.txt" % WIN
    if os.path.exists(fp):
        for line in open(fp):
            p = line.split()
            if len(p) == 2:
                fns.setdefault(int(p[0], 16), set()).add(int(p[1], 16))
    return (load("%s/tasksets.txt" % WIN, 0), load("%s/taskpcs.txt" % WIN, 0), fns)


def reachable_from(callgraph, roots):
    """Which functions each task can reach, so a table read three calls deep
    still attaches to the task that ultimately caused the read."""
    out = {}
    for root in roots:
        seen, stack = set(), [root]
        while stack:
            f = stack.pop()
            if f in seen:
                continue
            seen.add(f)
            stack.extend(callgraph.get("%08X" % f, ()))
        out[root] = seen
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()

    names = {int(k, 16): v
             for k, v in json.load(open(SSM, encoding="utf-8")).items()}
    lit = json.load(open(LITERALS, encoding="utf-8"))["tables"]
    starts = function_starts()
    headers = shipped_headers()

    def enclosing(a):
        i = bisect.bisect_right(starts, a)
        return starts[i - 1] if i else None

    sets, pcs, fnsets = one_warm_run()
    if not sets or not pcs:
        return 1
    sys.stderr.write("%d tasks, %d write addresses, %d executed addresses, "
                     "%d functions with writes\n"
                     % (len(sets), len(set().union(*sets.values())),
                        len(set().union(*pcs.values())), len(fnsets)))

    # The listing's idea of a function start and the emulator's disagree. The
    # parser collapses a run of prologue saves and reports 0x00010C20, which is
    # the `mov.l r14,@-r15` in the middle of one; the emulator pushes whatever
    # address was actually branched to. Looking one up in the other found nothing
    # for all twenty readers. The observed call targets are the ground truth here,
    # so the lookup uses those.
    observed = sorted(fnsets)

    def enclosing_observed(a):
        i = bisect.bisect_right(observed, a)
        return observed[i - 1] if i else None

    # A table's reference sites are code addresses. Its owner is the function
    # containing them, and the evidence is what THAT function wrote - not what
    # its whole task wrote. Per task, 76 tables came back sharing one write set,
    # so all 76 carried identical evidence: a subsystem, not a name.
    result = {}
    for h in headers:
        sites = set(lit.get(h, []))
        if not sites:
            continue
        fns = {enclosing_observed(s) for s in sites}
        fns.discard(None)
        ran = [t for t in pcs if pcs[t] & sites]
        # Function-level evidence where the function wrote something; the task it
        # ran under as the fallback, marked so the two are never confused.
        known = sorted({names[a] for f in fns for a in fnsets.get(f, ())
                        if a in names})
        level = "function"
        if not known:
            known = sorted({names[a] for t in ran for a in sets.get(t, ())
                            if a in names})
            level = "task"
        if not known:
            continue
        result[h] = {"functions": ["%08X" % f for f in sorted(fns)],
                     "tasks": ["%08X" % t for t in sorted(ran)],
                     "evidence": level,
                     "writes": known}

    byfn = sum(1 for v in result.values() if v["evidence"] == "function")
    print("\n%d of %d shipped tables have evidence: %d from the reading function "
          "itself, %d only from its task\n"
          % (len(result), len(headers), byfn, len(result) - byfn))
    groups = {}
    for h, v in result.items():
        groups.setdefault((v["evidence"], " / ".join(v["writes"][:3])), []).append(h)
    print("  %-9s %-58s %s" % ("evidence", "writes", "tables"))
    for (lvl, k), v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:24]:
        print("  %-9s %-58s %d" % (lvl, k[:58], len(v)))

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
        print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
