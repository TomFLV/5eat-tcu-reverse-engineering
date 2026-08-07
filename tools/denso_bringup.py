#!/usr/bin/env python3
"""Find the next peripheral register the firmware boot is waiting on.

Booting either controller from its reset vector stops in a short loop polling a
status bit that no hardware exists to set. Clearing one wait reveals the next, so
the work is a cycle - boot, find the loop, read what it polls, model it, repeat -
and doing it by hand costs three tool calls and a listing hunt each time.

This does the cycle in one pass:

    boot with the PC histogram on   -> the hot loop's address
    trace from that address         -> the register values at that instant
    read the listing around it      -> which register, which bit, what width

The output is the line to add to periph_or() in sh2.c. What it cannot tell you is
whether returning "ready" for that bit is *right* - that is a claim about the
simulated hardware, and it belongs in the source with a comment saying which
instruction demanded it, not in a default that quietly satisfies every wait.

    python tools/denso_bringup.py                     # TCU
    python tools/denso_bringup.py --rom <path> --entry 0x00000C0C
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, REPO_WSL, WORK, WORK_WSL, SH2_WSL  # noqa: E402

import argparse
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))

SH2 = SH2_WSL
WORK = WORK_WSL
ROMS = {
    "tcu": (REPO_WSL + "/rom-denso/"
            "Impreza_STI_3.583_JDM2011.bin", "0x00000BF8",
            "disasm-denso/Impreza_STI_3.583_JDM2011.asm"),
    "ecu": (REPO_WSL + "/rom-ecu/"
            "AZ1G502L.bin", "0x00000C0C", "disasm-ecu/AZ1G502L.asm"),
}

ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s+_?(\S+)\s*(.*?)\s*$")
# The poll itself: tst #imm,r0 tests a bit of whatever was just loaded.
TST = re.compile(r"^tst\s+(?:#)?(?:0x)?([0-9a-fx]+),r0$", re.I)
# The load feeding it, in the three widths the firmware uses.
LOAD = re.compile(r"^mov\.([bwl])\s+@(?:\(0x([0-9a-f]+),)?r(\d+)\)?,r(\d+)$", re.I)


def run(cmd, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
        e["WSLENV"] = ":".join(k + "/u" for k in env)
    return subprocess.run(["wsl"] + cmd, capture_output=True, text=True, env=e)


def hot_pc(rom, entry, steps):
    """The address the boot spends most of its time at."""
    r = run([SH2, rom, WORK + "/naming/empty.csv", WORK + "/scratch/bring.csv",
             entry, str(steps)], {"SH2_HOT": "1"})
    best = None
    for line in r.stderr.splitlines():
        m = re.match(r"^\s+([0-9A-F]{8})\s+(\d+)$", line)
        if m and best is None:
            best = (int(m.group(1), 16), int(m.group(2)))
    return best


def regs_at(rom, entry, pc, steps):
    """Register values the first time execution reaches pc."""
    r = run([SH2, rom, WORK + "/naming/empty.csv", WORK + "/scratch/bring.csv",
             entry, str(steps)],
            {"SH2_TRACE_FROM": "%08X" % pc, "SH2_TRACE": "1"})
    out = {}
    for line in r.stderr.splitlines():
        for k, v in re.findall(r"\b(r\d+)=([0-9A-F]{8})", line):
            out[k] = int(v, 16)
        if out:
            break
    return out


def listing(path, lo, hi):
    rows = {}
    with open(os.path.join(REPO, path), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = ROW.match(line.rstrip("\n"))
            if not m:
                continue
            a = int(m.group(1), 16)
            if lo <= a <= hi:
                rows[a] = (m.group(2), m.group(3))
    return rows


SRC = WORK + "/sh2/sh2.c"
MARK = "    default:         return 0;"


def apply_case(addr, bit, pc):
    """Insert one entry into periph_or() and rebuild."""
    s = open(SRC, encoding="utf-8").read()
    line = ("    case 0x%08X: return 0x%04X;   /* polled at 0x%08X */\n"
            % (addr, bit, pc))
    if "case 0x%08X:" % addr in s:
        return False, "already modelled - the boot is stuck for another reason"
    s = s.replace(MARK, line + MARK, 1)
    open(SRC, "w", encoding="utf-8", newline="\n").write(s)
    r = subprocess.run(["wsl", "bash", "-c",
                        "cd %s/sh2 && gcc -O2 -o sh2 sh2.c" % WORK_WSL],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr.strip()[:200]


def one_pass(rom, entry, asm, steps, verbose=True):
    """Return (pc, addr, bit) for the next wait, or (pc, None, None)."""
    hp = hot_pc(rom, entry, steps)
    if not hp:
        return None, None, None
    pc, count = hp
    rows = listing(asm, pc - 0x14, pc + 0xC)
    if verbose:
        print("hot at %08X (%d executions)" % (pc, count))
    bit, tst_at = None, None
    for a in sorted(rows):
        m = TST.match((rows[a][0] + " " + rows[a][1]).strip())
        if m and a >= pc and bit is None:
            bit, tst_at = int(m.group(1), 16), a
    if bit is None:
        return pc, None, None
    regs = regs_at(rom, entry, pc, steps)
    for a in sorted((a for a in rows if a <= tst_at), reverse=True):
        m = LOAD.match((rows[a][0] + " " + rows[a][1]).strip())
        if not m or m.group(4) != "0":
            continue
        rv = regs.get("r%d" % int(m.group(3)))
        if rv is None:
            continue
        return pc, rv + (int(m.group(2), 16) if m.group(2) else 0), bit
    return pc, None, None


def auto(rom, entry, asm, steps, rounds):
    """Model wait after wait until the boot stops stalling on status bits.

    Each round is a claim that a piece of hardware works, so every entry lands in
    the source with the instruction that demanded it. The loop stops on anything
    it cannot read as a status poll rather than guessing - a long loop is
    sometimes honest work, and the checksum at 0x00008D28 proved it.
    """
    added = []
    for i in range(rounds):
        pc, addr, bit = one_pass(rom, entry, asm, steps)
        if pc is None:
            print("round %d: no histogram - the core stopped" % (i + 1))
            break
        if addr is None:
            print("round %d: %08X is not a status poll - read it by hand" % (i + 1, pc))
            break
        ok, msg = apply_case(addr, bit, pc)
        if not ok:
            print("round %d: %s" % (i + 1, msg))
            break
        added.append((pc, addr, bit))
        print("round %d: %08X waits on %08X bit mask 0x%X - modelled"
              % (i + 1, pc, addr, bit))
    print("\n%d registers modelled this run:" % len(added))
    for pc, addr, bit in added:
        print("  %08X  polled at %08X  mask 0x%X" % (addr, pc, bit))
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", choices=sorted(ROMS), default="tcu")
    ap.add_argument("--steps", type=int, default=8000000)
    ap.add_argument("--auto", type=int, metavar="ROUNDS",
                    help="model each wait and continue, up to ROUNDS times")
    args = ap.parse_args()

    rom, entry, asm = ROMS[args.which]
    if args.auto:
        auto(rom, entry, asm, args.steps, args.auto)
        return 0
    hp = hot_pc(rom, entry, args.steps)
    if not hp:
        print("no histogram - the core may have crashed or SH2_HOT is unsupported")
        return 1
    pc, count = hp
    print("boot spends its time at %08X (%d executions of %d steps)"
          % (pc, count, args.steps))

    rows = listing(asm, pc - 0x14, pc + 0xC)
    print("\n--- the loop ---")
    for a in sorted(rows):
        print("  %08X  %-8s %s" % (a, rows[a][0], rows[a][1]))

    # Walk back from the hot address for the tst, then for the load feeding it.
    # The test is the one right after the hot address, and its operand is hex.
    # Deciding the base from whether the digits look decimal turns "tst 0x80"
    # into 80 decimal, which is 0x50 - a mask the firmware never mentions.
    bit, tst_at = None, None
    for a in sorted(rows):
        m = TST.match((rows[a][0] + " " + rows[a][1]).strip())
        if m and a >= pc and bit is None:
            bit, tst_at = int(m.group(1), 16), a
    if bit is None:
        print("\nno 'tst #imm,r0' here - this may not be a status poll at all.")
        print("A long loop can be honest work: the checksum at 0x00008D28 looked")
        print("exactly like a stall until its instructions were read.")
        return 0

    regs = regs_at(rom, entry, pc, args.steps)
    # The load that feeds the test is the last one into r0 before it, not the
    # first one in the window - the setup code above a wait writes the same
    # registers repeatedly, so "first match" lands several instructions early
    # and names a neighbouring address with conviction.
    for a in sorted((a for a in rows if a <= tst_at), reverse=True):
        m = LOAD.match((rows[a][0] + " " + rows[a][1]).strip())
        if not m or m.group(4) != "0":
            continue
        width, disp, base = m.group(1), m.group(2), int(m.group(3))
        rv = regs.get("r%d" % base)
        if rv is None:
            continue
        addr = rv + (int(disp, 16) if disp else 0)
        print("\n--- what it polls ---")
        print("  %08X  reads r%d+0x%s as mov.%s -> %08X, waiting for bit mask 0x%X"
              % (a, base, disp or "0", width, addr, bit))
        print("\nadd to periph_or() in sh2.c:")
        print("    case 0x%08X: return 0x%04X;   /* polled at 0x%08X */"
              % (addr, bit, pc))
        return 0

    print("\nfound the test but not the load - registers: %s"
          % ", ".join("%s=%08X" % kv for kv in sorted(regs.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
