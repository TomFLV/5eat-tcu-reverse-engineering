#!/usr/bin/env python3
"""Check the perturbation method against a table whose purpose is already known.

The method names a table by changing it and seeing what moves. That is only worth
trusting if it gives the right answer where the answer is already known - so this
runs it on the shift schedules, which were identified independently, in real units,
and verified against rimwall's published chart.

A shift schedule holds the road speed at which each shift happens. Change it and
the controller should shift at different times, so gear position and whatever
depends on gear should move. If they do not, the method is measuring something
other than what it claims and nothing else it produces can be relied on.

    python3 tools/denso_perturb_check.py

This is the same discipline as the checksum round-trip test and the offset
self-test: run the instrument against a known answer before believing it on an
unknown one.
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, WORK, WORK_WSL, SH2_WSL, wsl  # noqa: E402
import denso_perturb as P  # noqa: E402

# Shift Schedule 1 through 4, upshift, from the shipped definition. Data address
# and shape rather than a header, because these are the tables the project already
# identified and they are quoted that way.
KNOWN = [
    ("Shift Schedule 1 - Upshift", 0x0B63A4, 15, 5),
    ("Shift Schedule 2 - Upshift", 0x0B6574, 15, 5),
    ("Shift Schedule 3 - Upshift", 0x0B6744, 15, 5),
    ("Shift Schedule 4 - Upshift", 0x0B6914, 15, 5),
]

# A shift schedule holds road speeds. Halving them makes every upshift happen
# earlier, which a drive that accelerates through the range will certainly reach.
FACTOR = 0.5
PROFILE = "accelerate"


def perturb_data(rom, addr, rows, cols, factor):
    out = bytearray(rom)
    n = 0
    for i in range(rows * cols):
        off = addr + i * 2
        v = struct.unpack_from(">H", out, off)[0]
        nv = min(0xFFFF, max(0, int(v * factor)))
        if nv != v:
            struct.pack_into(">H", out, off, nv)
            n += 1
    return bytes(out), n


def main():
    argparse.ArgumentParser(
        description="Check the perturbation method against tables whose purpose "
                    "is already known.",
        epilog="Takes no arguments: it runs a fixed check against four shift "
               "schedules established independently and verified against a "
               "published chart.").parse_args()

    os.makedirs(P.OUT, exist_ok=True)
    # The sweep builds its task list in main(); this uses the same one, so the
    # check exercises exactly what the sweep will.
    P.TASKS = P.task_list()
    rom = open(P.ROM, "rb").read()
    nm = P.names()

    pf = P.make_profile(PROFILE, os.path.join(P.OUT, "chk_%s.csv" % PROFILE))
    base = P.run(P.ROM, os.path.join(P.OUT, "chk_base.bin"), pf)
    if not base:
        sys.exit("baseline produced no RAM image")
    print("checking the method on tables whose purpose is already established\n")

    ok = 0
    for label, addr, rows, cols in KNOWN:
        mod, n = perturb_data(rom, addr, rows, cols, FACTOR)
        mp = os.path.join(P.OUT, "chk_mod.bin")
        open(mp, "wb").write(mod)
        dump = P.run(mp, os.path.join(P.OUT, "chk_dump.bin"), pf)
        if len(dump) != len(base):
            print("  %-32s run failed" % label)
            continue
        diff = [0xFFFF0000 + i for i in range(len(base)) if base[i] != dump[i]]
        hit = sorted({nm[a] for a in diff if a in nm})
        gear = [h for h in hit if "Gear" in h or "Turbine" in h or "Speed" in h]
        verdict = "as expected" if gear else "NOTHING gear-related moved"
        if gear:
            ok += 1
        print("  %-32s %d cells -> %d addresses  %s"
              % (label, n, len(diff), verdict))
        if hit:
            print("      %s" % ", ".join(hit[:6]))

    print("\n%d of %d known shift schedules moved something gear or speed related."
          % (ok, len(KNOWN)))
    if ok == len(KNOWN):
        print("The method gives the right answer where the answer is known.")
    else:
        print("It does not. Treat every result from the sweep as unproven until")
        print("this passes - a method that misses a table it should catch will")
        print("also miss ones nobody can check.")
    return 0 if ok == len(KNOWN) else 1


if __name__ == "__main__":
    sys.exit(main())
