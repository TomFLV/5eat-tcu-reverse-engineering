#!/usr/bin/env python3
"""Build a drive profile for the emulator, from the real vehicle logs.

The logs in logs/ are 568 rows from a car running this exact firmware - unit
A3DE207100, calibration WQDE2WB1 - covering 0 to 173 km/h through all five gears.
Using them as the input profile means the simulated drive follows something that
actually happened rather than a sequence someone made up.

Each row becomes one tick: the inputs for that instant, written to the RAM
addresses the control code reads. The emulator keeps its state between ticks, so
the run is a drive rather than 568 unrelated experiments.

    python tools/denso_make_profile.py --out /home/rust/drive.csv
    python tools/denso_make_profile.py --synthetic --ticks 1800 --out /home/rust/drive.csv

--synthetic generates a sweep instead: every input walked across its range, which
covers states the logged drive never reached.

Note which addresses are used. The Select Monitor names are mostly *published
copies* the firmware writes and never reads (FINDINGS 50), so writing those changes
nothing. The addresses here are the ones probing showed the control code actually
reads (FINDINGS 53 and 54).
"""

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LOGDIR = os.path.join(REPO, "logs")

# Addresses the control code reads, from probing rather than from the Select
# Monitor table. Mapped to the log column that drives each one where a sensible
# mapping exists.
INPUTS = [
    # addr,      size, log column,                        scale to raw
    (0xFFFF9F55, 1, None,                                 None),   # schedule selector
    (0xFFFF8A88, 1, "Engine Speed",                       1 / 32.0),
    (0xFFFF8A89, 1, "Turbine Revolution Speed",           1 / 32.0),
    (0xFFFF8A8A, 1, "Front Wheel Speed",                  1.0),
    (0xFFFF357C, 1, "Accelerator Pedal Travel",           2.55),
    (0xFFFF357A, 1, "Gear Position",                      1.0),
    (0xFFFF33AC, 1, "ATF Temperature",                    1.0),
    (0xFFFF32D0, 1, "Rear Wheel Speed",                   1.0),
    (0xFFFF35E1, 1, None,                                 None),
    (0xFFFF8E62, 1, None,                                 None),
    (0xFFFF8E64, 1, None,                                 None),
    (0xFFFF9152, 1, None,                                 None),
]


# HCAN0 mailbox data, from table 16.6 of the SH7058 hardware manual and confirmed
# by the addresses the firmware's own literal pool carries. The TCU is told torque,
# engine speed and pedal angle over CAN, so feeding these is the difference between
# a firmware that thinks it is idling and one that thinks it is being driven
# (FINDINGS 56).
CAN_MB0 = 0xFFFFD100      # mailbox 0 data
CAN_MB1 = 0xFFFFD108      # mailbox 1 data


def can_410(row, get):
    """The eight bytes of CAN 0x410 as the ECU sends them.

    Layout is rimwall's, from forum topic 20850:
      0 torque out x2.0 Nm   1 max torque x1.6   2 max allowed x1.6
      3 torque loss x1.6     4 pedal x100/255    5,6 engine rpm lo,hi
      7 status bits
    """
    rpm = int(get(row, "Engine Speed", 0))
    torque = int(get(row, "Engine Torque", 0) / 2.0) if get(row, "Engine Torque", 0) else 0
    pedal = int(get(row, "Accelerator Pedal", 0) * 2.55)
    return [
        min(255, max(0, torque)),
        min(255, max(0, torque)),          # max torque, absent from the log
        0xFF,                              # nothing limiting
        0,
        min(255, max(0, pedal)),
        rpm & 0xFF,
        (rpm >> 8) & 0xFF,
        0x01,
    ]


def can_411(row, get):
    """CAN 0x411: throttle, the gear the ECU infers, cruise speed."""
    return [
        0, 0, 0,
        min(255, max(0, int(get(row, "Throttle", 0) * 2.55))),
        int(get(row, "Gear", 0)),
        0, 0, 0,
    ]


def read_log():
    """Rows from the richest log, with the comma decimal separator handled."""
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
                # The logger writes 0,00 rather than 0.00. float() fails silently
                # on that, which once made a fully-populated column read as empty.
                try:
                    clean[k.strip()] = float(v.replace(",", "."))
                except ValueError:
                    pass
            if clean:
                rows.append(clean)
    return rows


def column_for(want, sample):
    if not want:
        return None
    for k in sample:
        if want.lower() in k.lower():
            return k
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--ticks", type=int, default=0)
    args = ap.parse_args()

    lines = ["# tick,addr:size=value,...  generated by denso_make_profile.py"]

    if args.synthetic:
        n = args.ticks or 1800
        for t in range(n):
            parts = ["%d" % t]
            for i, (addr, size, _c, _s) in enumerate(INPUTS):
                # Each input walks its range at a different rate, so every
                # combination gets visited rather than all moving together.
                period = 7 + i * 5
                val = int((t // period) % 256)
                parts.append("%08X:%d=0x%X" % (addr, size, val))
            lines.append(",".join(parts))
        source = "synthetic sweep"
    else:
        rows = read_log()
        if not rows:
            sys.stderr.write("no usable log found in %s\n" % LOGDIR)
            return 1
        if args.ticks:
            rows = rows[:args.ticks]
        sample = rows[0]
        cols = {addr: column_for(c, sample) for addr, _s, c, _sc in INPUTS}
        def get(r, want, default=0.0):
            for k in r:
                if want.lower() in k.lower():
                    return r[k]
            return default

        for t, row in enumerate(rows):
            parts = ["%d" % t]
            for addr, size, _c, scale in INPUTS:
                col = cols.get(addr)
                if col and col in row and scale:
                    val = int(max(0, min(255, row[col] * scale)))
                else:
                    val = 0
                parts.append("%08X:%d=0x%X" % (addr, size, val))
            # The CAN frames, written straight into the mailboxes the same way the
            # controller would deliver them.
            for base, frame in ((CAN_MB0, can_410(row, get)),
                                (CAN_MB1, can_411(row, get))):
                for i, b in enumerate(frame):
                    parts.append("%08X:1=0x%X" % (base + i, b))
            lines.append(",".join(parts))
        source = "%d rows of %s" % (len(rows), "the vehicle log")

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print("%d ticks from %s -> %s" % (len(lines) - 1, source, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
