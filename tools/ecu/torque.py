#!/usr/bin/env python3
"""Engine torque from pedal and engine speed, out of the real ECU calibration.

This closes the gap that stalled the TCU drive simulation. The TCU is told engine
torque over CAN 0x410 byte 0, and section 19 puts torque at the head of the line
pressure chain - but every log we have is TCU-side and carries no torque column,
so that byte has been fed as zero and the whole chain has sat untouched.

AZ1G502L is the ECU from the same car as the TCU image we work on: 2009 JDM
Impreza STI with the automatic, which is the A-Line, which is the 5EAT car. Its
requested-torque maps are indexed by accelerator pedal angle and engine speed.
The logs carry both. So torque is not missing at all - it is computable from what
we already have, using the calibration that actually shipped rather than a guess.

    python torque.py --at 30 3000              # one point, all three modes
    python torque.py --compare                 # how the SI-DRIVE modes differ
    python torque.py --log                     # torque for every row of the log

The A and B maps: the ECU carries two per mode and the delivered figure sits
between them, so both are reported and A is used unless told otherwise.
"""

import argparse
import csv
import os
import sys

import read_table

HERE = os.path.dirname(os.path.abspath(__file__))


def find_logs():
    """The vehicle logs, whether this runs from the repo or the work directory.

    Walking up looking for a logs/ directory keeps the same file working in
    tools/ecu/ inside the repository and in the external work directory where the
    ROM and definitions live.
    """
    d = HERE
    for _ in range(4):
        cand = os.path.join(d, "logs")
        if os.path.isdir(cand):
            return cand
        d = os.path.dirname(d)
    for cand in (r"C:\Users\Tom\Desktop\5eat-tcu-reverse-engineering\logs",
                 "/mnt/c/Users/Tom/Desktop/5eat-tcu-reverse-engineering/logs"):
        if os.path.isdir(cand):
            return cand
    return os.path.join(HERE, "logs")


LOGDIR = find_logs()

CAL = "AZ1G502L"
MODES = ("Intelligent", "Sport", "Sport Sharp")
NAME = "Requested Torque %s (Accelerator Pedal) SI-DRIVE %s"

# rimwall's decode of CAN 0x410, forum topic 20850: byte 0 is engine torque at
# 2.0 Nm per count. The map tops out at 350 Nm, which lands on 175 - inside a
# byte with room to spare, which is a decent sign the two agree.
NM_PER_COUNT = 2.0


def _interp(axis, v):
    """Fractional index of v along axis, clamped at both ends.

    Clamping matters: the map starts at 800 rpm and the logs start at rest, so
    without it every idle row would extrapolate to nonsense.
    """
    if v <= axis[0]:
        return 0, 0, 0.0
    if v >= axis[-1]:
        return len(axis) - 1, len(axis) - 1, 0.0
    for i in range(len(axis) - 1):
        if axis[i] <= v <= axis[i + 1]:
            span = axis[i + 1] - axis[i]
            return i, i + 1, (v - axis[i]) / span if span else 0.0
    return len(axis) - 1, len(axis) - 1, 0.0


class TorqueMap(object):
    def __init__(self, cal=CAL, variant="A", mode="Intelligent", rom=None):
        self.name = NAME % (variant, mode)
        self.x, self.y, self.grid, self.meta = read_table.load_table(
            cal, self.name, rom=rom)

    def at(self, pedal, rpm):
        """Bilinear lookup: torque in Nm for a pedal angle and engine speed."""
        x0, x1, fx = _interp(self.x, pedal)
        y0, y1, fy = _interp(self.y, rpm)
        a = self.grid[y0][x0] + (self.grid[y0][x1] - self.grid[y0][x0]) * fx
        b = self.grid[y1][x0] + (self.grid[y1][x1] - self.grid[y1][x0]) * fx
        return a + (b - a) * fy

    def byte(self, pedal, rpm):
        """The value the ECU would put in CAN 0x410 byte 0."""
        return max(0, min(255, int(round(self.at(pedal, rpm) / NM_PER_COUNT))))


def read_log():
    """The richest vehicle log, with the comma decimal separator handled."""
    path = None
    for name in sorted(os.listdir(LOGDIR)):
        if name.endswith(".csv") and "133923" in name:
            path = os.path.join(LOGDIR, name)
    if not path:
        return []
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            clean = {}
            for k, v in row.items():
                if k is None or v is None:
                    continue
                try:
                    clean[k.strip()] = float(v.replace(",", "."))
                except ValueError:
                    pass
            if clean:
                rows.append(clean)
    return rows


def col(row, want, default=0.0):
    for k in row:
        if want.lower() in k.lower():
            return row[k]
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", nargs=2, type=float, metavar=("PEDAL", "RPM"))
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--log", action="store_true")
    ap.add_argument("--mode", default="Intelligent", choices=MODES)
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    if args.at:
        pedal, rpm = args.at
        print("pedal %.1f%%  %.0f rpm\n" % (pedal, rpm))
        print("%-14s %8s %8s %8s" % ("SI-DRIVE", "A (Nm)", "B (Nm)", "CAN b0"))
        for m in MODES:
            a = TorqueMap(variant="A", mode=m)
            b = TorqueMap(variant="B", mode=m)
            print("%-14s %8.1f %8.1f %8d"
                  % (m, a.at(pedal, rpm), b.at(pedal, rpm), a.byte(pedal, rpm)))
        return 0

    if args.compare:
        maps = {m: TorqueMap(variant="A", mode=m) for m in MODES}
        ref = maps["Intelligent"]
        print("Torque at full pedal, by mode and engine speed (Nm)\n")
        print("%8s %14s %14s %14s" % ("rpm", "Intelligent", "Sport", "Sport Sharp"))
        for rpm in ref.y:
            vals = [maps[m].at(100.0, rpm) for m in MODES]
            print("%8.0f %14.1f %14.1f %14.1f" % (rpm, vals[0], vals[1], vals[2]))
        print("\nTorque at 20%% pedal (where the modes are meant to differ)\n")
        print("%8s %14s %14s %14s" % ("rpm", "Intelligent", "Sport", "Sport Sharp"))
        for rpm in ref.y:
            vals = [maps[m].at(20.0, rpm) for m in MODES]
            print("%8.0f %14.1f %14.1f %14.1f" % (rpm, vals[0], vals[1], vals[2]))
        return 0

    if args.log:
        rows = read_log()
        if not rows:
            sys.stderr.write("no usable log in %s\n" % LOGDIR)
            return 1
        tm = TorqueMap(variant="A", mode=args.mode)
        out = []
        for i, r in enumerate(rows):
            pedal = col(r, "Accelerator Pedal")
            rpm = col(r, "Engine Speed")
            out.append((i, pedal, rpm, tm.at(pedal, rpm), tm.byte(pedal, rpm)))
        nz = [t for _i, _p, _r, t, _b in out if t > 0]
        print("%d log rows, SI-DRIVE %s" % (len(out), args.mode))
        print("torque: min %.1f  max %.1f  mean %.1f Nm  (%d rows above zero)"
              % (min(nz) if nz else 0, max(nz) if nz else 0,
                 sum(nz) / len(nz) if nz else 0, len(nz)))
        print("\n%6s %8s %8s %10s %8s" % ("tick", "pedal%", "rpm", "torque Nm", "CAN b0"))
        for i, p, r, t, b in out[::40]:
            print("%6d %8.1f %8.0f %10.1f %8d" % (i, p, r, t, b))
        if args.csv:
            with open(args.csv, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("tick,pedal_pct,rpm,torque_nm,can_byte0\n")
                for i, p, r, t, b in out:
                    fh.write("%d,%.2f,%.0f,%.2f,%d\n" % (i, p, r, t, b))
            print("\n-> %s" % args.csv)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
