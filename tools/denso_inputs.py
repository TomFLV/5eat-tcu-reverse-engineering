#!/usr/bin/env python3
"""What RAM a function actually reads, taken from an emulated run.

Static cross-referencing says which addresses a function *could* touch. Running it
says which it did, on the path the inputs actually took - and that is the set worth
setting when simulating a driving state.

The method: emulate, record the executed path, and intersect it with the literal
map from denso_literals.py. Every RAM access on this core loads its address from a
PC-relative literal (FINDINGS 46), so an executed literal load is a RAM access, and
the instruction after it says whether the access was a read or a write.

    python tools/denso_inputs.py 0x00023E72
    python tools/denso_inputs.py 0x00023E72 --reads-only

Reads are candidate inputs. Writes are outputs, and section 50 is the warning about
confusing the two: the Select Monitor names several addresses that the firmware
only ever writes, and setting those changes nothing.
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
VARS = os.path.join(HERE, "denso_working_vars.json")
SSM = os.path.join(HERE, "ssm_parameters.json")

GHIDRA = os.environ.get("GHIDRA_HOME", os.path.expanduser("~/ghidra_12.1.2_PUBLIC"))
PROJECT = os.environ.get("DENSO_PROJECT", os.path.expanduser("~/sh2e_test/w"))
SCRIPTS = os.environ.get("GHIDRA_SCRIPTS", os.path.expanduser("~/my_scripts"))
LISTING = os.path.join(REPO, "disasm-denso", "Impreza_STI_3.583_JDM2011.asm")
ROM = os.path.join(REPO, "rom-denso", "Impreza_STI_3.583_JDM2011.bin")

HEX6 = re.compile(r"\b[0-9A-F]{6}\b")
ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s*_?(\S+)\s*(.*)$")
POOL = re.compile(r"@\(0x([0-9a-f]+),pc\),(\w+)")

# Reads and writes, both plain and displaced.
#
#   mov.b @r6,r2            reads the address in r6
#   mov.b @(0x2,r1),r0      reads r1 + 2  <- this form is why counting bare
#                                            registers undercounts badly
#   mov.b r2,@r6            writes the address in r6
#   mov.b r0,@(0x4,r1)      writes r1 + 4
#
# The displaced form matters more than it looks: several of these addresses are
# structure bases, and the members are what the code actually reads. Treating a
# base as a single address reports one input where there are a dozen, and makes a
# simulation that pokes it look inert.
READ = re.compile(r"^mov\.[bwl]\s+@(\w+)[,+]")
READ_DISP = re.compile(r"^mov\.[bwl]\s+@\(0x([0-9a-f]+),(\w+)\),")
WRITE = re.compile(r"^mov\.[bwl]\s+\w+,@(\w+)$")
WRITE_DISP = re.compile(r"^mov\.[bwl]\s+\w+,@\(0x([0-9a-f]+),(\w+)\)")


def known_names():
    out = {}
    if os.path.exists(VARS):
        v = json.load(open(VARS, encoding="utf-8"))
        for _a, d in v.get("variables", {}).items():
            out[d["working"]] = d["name"]
        for a, n in v.get("direct", {}).items():
            out[int(a, 16)] = n
    if os.path.exists(SSM):
        s = json.load(open(SSM, encoding="utf-8"))
        info = s.get(os.path.basename(ROM))
        for r in (info or {}).get("rows", []):
            if r.get("name"):
                out.setdefault(r["ram"], r["name"] + " (SSM)")
    return out


def emulate(entry, steps):
    cmd = [os.path.join(GHIDRA, "support", "analyzeHeadless"), PROJECT, "p",
           "-process", "t.bin", "-noanalysis", "-scriptPath", SCRIPTS,
           "-postScript", "DensoEmuTable.java", entry, str(steps)]
    env = dict(os.environ)
    env.setdefault("TMPDIR", os.path.expanduser("~/gtmp"))
    env["_JAVA_OPTIONS"] = "-Djava.io.tmpdir=" + env["TMPDIR"]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    for line in (p.stdout + p.stderr).splitlines():
        if "PATH " in line:
            return [int(x, 16) for x in HEX6.findall(line.split("PATH ", 1)[1])]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entry")
    ap.add_argument("--steps", type=int, default=60000)
    ap.add_argument("--reads-only", action="store_true")
    ap.add_argument("--show", type=int, default=40)
    args = ap.parse_args()

    if not os.path.exists(LISTING):
        sys.stderr.write("no listing at %s\n" % LISTING)
        return 1
    data = open(ROM, "rb").read()

    # The listing, indexed by address, so the path can be walked in order.
    rows, order = {}, []
    for line in open(LISTING, encoding="utf-8", errors="replace"):
        m = ROW.match(line.rstrip("\n"))
        if not m or m.group(2).startswith("."):
            continue
        a = int(m.group(1), 16)
        rows[a] = (m.group(2), m.group(3))
        order.append(a)

    path = emulate(args.entry, args.steps)
    if not path:
        sys.stderr.write("no path recorded - did the emulation run?\n")
        return 1

    names = known_names()
    reads, writes = {}, {}
    reg_holds = {}
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
                if size == 4:
                    val = struct.unpack_from(">I", data, pool)[0]
                else:
                    val = struct.unpack_from(">h", data, pool)[0] & 0xFFFFFFFF
                if val >= 0xFFFF0000:
                    reg_holds[p.group(2)] = val
            continue
        full = (mnem + " " + rest).strip()
        m = READ_DISP.match(full)
        if m and m.group(2) in reg_holds:
            addr = reg_holds[m.group(2)] + int(m.group(1), 16)
            reads[addr] = reads.get(addr, 0) + 1
            continue
        m = READ.match(full)
        if m and m.group(1) in reg_holds:
            addr = reg_holds[m.group(1)]
            reads[addr] = reads.get(addr, 0) + 1
            continue
        m = WRITE_DISP.match(full)
        if m and m.group(2) in reg_holds:
            addr = reg_holds[m.group(2)] + int(m.group(1), 16)
            writes[addr] = writes.get(addr, 0) + 1
            continue
        m = WRITE.match(full)
        if m and m.group(1) in reg_holds:
            addr = reg_holds[m.group(1)]
            writes[addr] = writes.get(addr, 0) + 1

    print("%s: %d instructions executed" % (args.entry, len(path)))
    print("%d RAM addresses read, %d written\n" % (len(reads), len(writes)))

    print("READS - candidate inputs")
    for a in sorted(reads, key=lambda x: -reads[x])[:args.show]:
        print("   0x%08X  x%-4d %s" % (a, reads[a], names.get(a, "")))
    if not args.reads_only and writes:
        print("\nWRITES - outputs")
        for a in sorted(writes, key=lambda x: -writes[x])[:args.show]:
            print("   0x%08X  x%-4d %s" % (a, writes[a], names.get(a, "")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
