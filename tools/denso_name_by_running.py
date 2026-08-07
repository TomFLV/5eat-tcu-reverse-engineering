#!/usr/bin/env python3
"""Name Denso tables by running the code that reads them and watching what it writes.

Three static attempts failed for the same reason. A table is read by a function,
and to know what the table is for you need to know what that function produces -
but the functions write their results through computed pointers, and a
cross-reference that only resolves literal addresses sees nothing at all. Function
0x00027A4E reads a table and, as far as static analysis can tell, writes nowhere.

The emulator does not have that problem. Run the function and record every address
it touches. Intersect that with the 141 addresses the Select Monitor table names
(FINDINGS 74) and the table has evidence attached: not a guess from its shape, but
the observed effect of the code that uses it.

    python tools/denso_name_by_running.py
    python tools/denso_name_by_running.py --json out.json

Each function is one native run of a few hundredths of a second, so the whole set
takes about a minute - which is the only reason this is worth doing at all.
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

SH2 = SH2_WSL
ROM_L = (REPO_WSL + "/rom-denso/"
         "Impreza_STI_3.583_JDM2011.bin")
WIN = WORK + "/naming"
LIN = WORK_WSL + "/naming"

ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s+_?(\S+)\s*([^;]*)")
PRO = re.compile(r"^(r\d+|pr),@-r15$")


def function_starts():
    starts = []
    with open(LISTING, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = ROW.match(line.rstrip("\n"))
            if m and m.group(2) in ("mov.l", "sts.l") and PRO.match(m.group(3).strip()):
                starts.append(int(m.group(1), 16))
    return sorted(set(starts))


def shipped_headers():
    """The tables the definition actually offers, by header address."""
    import xml.etree.ElementTree as ET
    out = []
    t = ET.parse(DEFS)
    for rom in t.getroot().iter("rom"):
        rid = rom.find("romid")
        if rid is None or (rid.findtext("xmlid") or "") != "SUBARU_5EAT_DENSO_WQDE2WB1":
            continue
        for tab in rom.findall("table"):
            m = re.search(r"Table ([0-9A-F]{6})", tab.get("name") or "")
            if m:
                out.append(m.group(1))
        break
    return out


# The controller's own task list, run before the function under test so it starts
# from a state the firmware would recognise rather than from zeroed RAM.
TASKS = WORK_WSL + "/tasks_ctl.txt"
PROFILE = WORK_WSL + "/drive_short.csv"


def write_set(entry, warm=True):
    """Every RAM address the function writes.

    Cold - entered with zeroed registers and no vehicle state - a function that
    begins by checking whether the engine is running takes its early exit and
    writes nothing, which is how the first version of this named five tables out
    of 185. Warm, the controller's tasks run first over a real drive profile, so
    the state the function tests is the state a driven car would have produced.

    The baseline is the same drive without the function appended, so what is
    attributed to it is what it added rather than everything the drive touched.
    """
    tag = "%08X" % entry
    ws = "%s/w_%s.txt" % (WIN, tag)
    entries = open(WORK + "/tasks_ctl.txt").read().strip() if warm else ""
    spec = (entries + "+0x%08X" % entry) if warm else "0x%08X" % entry
    with open("%s/e_%s.txt" % (WIN, tag), "w", newline="\n") as fh:
        fh.write(spec)
    env = dict(os.environ)
    env["WSLENV"] = "SH2_WRITESET/u"
    env["SH2_WRITESET"] = "%s/w_%s.txt" % (LIN, tag)
    subprocess.run(["wsl", SH2, ROM_L,
                    PROFILE if warm else LIN + "/empty.csv",
                    LIN + "/out.csv", "@%s/e_%s.txt" % (LIN, tag), "5000"],
                   capture_output=True, env=env)
    if not os.path.exists(ws) or not os.path.getsize(ws):
        return set()
    lines = open(ws).read().split()
    return {int(x, 16) for x in lines[1:]}


def baseline_set():
    """What the drive writes with no extra function, so it can be subtracted."""
    ws = "%s/w_base.txt" % WIN
    env = dict(os.environ)
    env["WSLENV"] = "SH2_WRITESET/u"
    env["SH2_WRITESET"] = "%s/w_base.txt" % LIN
    subprocess.run(["wsl", SH2, ROM_L, PROFILE, LIN + "/out.csv",
                    "@" + TASKS, "5000"], capture_output=True, env=env)
    if not os.path.exists(ws) or not os.path.getsize(ws):
        return set()
    return {int(x, 16) for x in open(ws).read().split()[1:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()

    os.makedirs(WIN, exist_ok=True)
    with open(WIN + "/empty.csv", "w", newline="\n") as fh:
        fh.write("# nothing injected\n" + "\n".join(str(t) for t in range(3)) + "\n")

    names = {int(k, 16): v
             for k, v in json.load(open(SSM, encoding="utf-8")).items()}
    lit = json.load(open(LITERALS, encoding="utf-8"))["tables"]
    starts = function_starts()

    def enclosing(a):
        i = bisect.bisect_right(starts, a)
        return starts[i - 1] if i else None

    headers = shipped_headers()
    # One run per function, not per table: many tables share a reader.
    fn_tables = {}
    for h in headers:
        for site in lit.get(h, []):
            f = enclosing(site)
            if f is not None:
                fn_tables.setdefault(f, set()).add(h)
    sys.stderr.write("%d shipped tables, %d distinct reading functions\n"
                     % (len(headers), len(fn_tables)))

    base = baseline_set()
    sys.stderr.write("drive baseline writes %d addresses\n" % len(base))
    result, done = {}, 0
    for f, tabs in sorted(fn_tables.items()):
        ws = write_set(f) - base
        known = sorted({names[a] for a in ws if a in names})
        done += 1
        if done % 25 == 0:
            sys.stderr.write("  %d/%d functions run\n" % (done, len(fn_tables)))
        if not known:
            continue
        for h in tabs:
            result.setdefault(h, {"function": "%08X" % f, "writes": known})

    print("\n%d of %d shipped tables have a reader observed writing a named address\n"
          % (len(result), len(headers)))
    by_name = {}
    for h, v in result.items():
        by_name.setdefault(" / ".join(v["writes"][:3]), []).append(h)
    for k, v in sorted(by_name.items(), key=lambda kv: -len(kv[1]))[:18]:
        print("  %-64s %d tables" % (k[:64], len(v)))

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
        print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
