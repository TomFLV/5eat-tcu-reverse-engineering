#!/usr/bin/env python3
"""Build a drive profile for the emulator, from the real vehicle logs.

The logs in logs/ are 568 rows from a car running this exact firmware - unit
A3DE207100, calibration WQDE2WB1 - covering 0 to 173 km/h through all five gears.
Using them as the input profile means the simulated drive follows something that
actually happened rather than a sequence someone made up.

Each row becomes one tick: the inputs for that instant, written to the RAM
addresses the control code reads. The emulator keeps its state between ticks, so
the run is a drive rather than 568 unrelated experiments.

    python tools/denso_make_profile.py --out $FIVEEAT_WORK/drive.csv
    python tools/denso_make_profile.py --synthetic --ticks 1800 --out $FIVEEAT_WORK/drive.csv

--synthetic generates a sweep instead: every input walked across its range, which
covers states the logged drive never reached.

Note which addresses are used. The Select Monitor names are mostly *published
copies* the firmware writes and never reads (FINDINGS 50), so writing those changes
nothing. The addresses here are the ones probing showed the control code actually
reads (FINDINGS 53 and 54).
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, REPO_WSL, WORK, WORK_WSL, SH2_WSL  # noqa: E402

import argparse
import csv

HERE = os.path.dirname(os.path.abspath(__file__))
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


# Where the decoded CAN frames go, from the firmware's own receive table at
# 0x08600E - see tools/denso_can_map.py.
#
# Writing the HCAN mailboxes was the obvious thing to do and it accomplished
# nothing, twice. Two reasons, both now settled by reading rather than guessing.
# The mailbox accessor at 0x0000A8E6 lays out the hardware as 32 bytes per
# mailbox, header at 0xFFFFD100 + N*32 and data at 0xFFFFD108 + N*32, so the old
# constants below were writing one frame into mailbox 0's header and the next into
# its data. And more to the point, no consumer reads a mailbox at all: a receive
# task copies each frame into a fixed buffer and every consumer reads the buffer.
# So the frame has to be delivered where the firmware will look for it.
CAN_RX = {
    0x410: 0xFFFF300C,    # torque, pedal, engine speed from the ECU
    0x411: 0xFFFF3014,    # throttle, inferred gear, cruise
    0x412: 0xFFFF301C,
}

# Delivering the frame is still not enough on its own. The receive task at
# 0x00012BA4 asks a gate at 0x0000A2E2 whether anything arrived; the gate reads the
# receive-pending register, masks the bit for that mailbox, and reports nothing if
# it is clear. On real hardware the CAN controller sets that bit. Nothing sets it
# here, so the task skipped the decode every tick and the frame sat in its buffer
# untouched - which is why writing the buffer alone changed as little as writing
# the mailbox did.
#
# Which register, exactly, comes from the two helpers the gate calls rather than
# from the channel offset - and guessing at the offset got it wrong once already.
# The address helper at 0x0000AC96 takes the base 0xFFFFD040 and the mailbox number
# and adjusts: below 16 it adds 2, 32 to 47 adds 0x802, 48 and up adds 0x800. So
# the mailbox numbering is global - 0 to 31 is channel 0, 32 to 63 is channel 1 -
# and byte 4 of the table entry is not a channel index at all. The mask helper at
# 0x0000AD00 indexes a plain 1<<n table at 0x0000ADA4 by mailbox & 15.
#
# Frames 0x410 and 0x411 are mailboxes 4 and 5, both below 16, so the register is
# 0xFFFFD040 + 2 and the bits are 0x0010 and 0x0020.
CAN_RXPR = 0xFFFFD042
CAN_RXPR_BITS = 0x0030

# The decode routine at 0x00012BD2 was read instruction by instruction, so what it
# does to frame 0x410 is known exactly:
#
#   mov.b  @r4,r6          byte 0        -> 0xFFFF30F0   engine torque
#   mov.b  @(0x4,r4),r0    byte 4        -> 0xFFFF30F1   pedal angle
#   mov.b  @(0x6,r4),r0    byte 6 << 8   \
#   mov.b  @(0x5,r4),r0    byte 5        -> 0xFFFF30F2   engine speed, u16
#   mov.b  @(0x7,r4),r0    byte 7        -> 0xFFFF30F4   status bits
#
# Writing those four directly performs the transformation the firmware performs.
# It still moves nothing, and the reason is worth stating plainly rather than
# working around: a register-aware cross-reference of the whole image finds
# 0xFFFF30F0 written three times and read nowhere. Engine torque from 0x410 is a
# published copy, not a control input - the pattern of FINDINGS 50 again.
DECODED = {
    "torque": (0xFFFF30F0, 1),
    "pedal": (0xFFFF30F1, 1),
    "rpm": (0xFFFF30F2, 2),
    "status": (0xFFFF30F4, 1),
}

# CAN 0x412 byte 0 is the one that is actually consumed: seven readers against
# torque's zero, and the Select Monitor table names it Accelerator Pedal Travel.
# See can_412 for why this is the frame section 19's line pressure chain hangs off.
PEDAL_TRAVEL = 0xFFFF30FB


def load_torque(path):
    """Torque per tick, as CAN 0x410 byte 0, from the ECU calibration.

    The logs are TCU-side and have no torque column, so byte 0 was fed as zero
    for a long time - and since torque is at the head of the line pressure chain
    (FINDINGS 19), that left the chain untouched no matter how well the frames
    were delivered. It was never really missing: the ECU derives torque from
    pedal angle and engine speed, and the logs carry both. Reading the
    requested-torque map out of AZ1G502L - the ECU from the same car as this TCU -
    turns those two columns into the torque the ECU would actually have sent.

    Produced by ecu/torque.py --log --csv. Absent, the byte stays zero and the
    chain stays cold, which is worth saying out loud rather than discovering later.
    """
    if not path or not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out[int(row["tick"])] = int(row["can_byte0"])
            except (KeyError, ValueError):
                continue
    return out


def can_410(row, get, torque=0):
    """The eight bytes of CAN 0x410 as the ECU sends them.

    Layout is rimwall's, from forum topic 20850:
      0 torque out x2.0 Nm   1 max torque x1.6   2 max allowed x1.6
      3 torque loss x1.6     4 pedal x100/255    5,6 engine rpm lo,hi
      7 status bits
    """
    rpm = int(get(row, "Engine Speed", 0))
    pedal = int(get(row, "Accelerator Pedal", 0) * 2.55)
    # Bytes 0 and 1 are the same torque on different scales - 2.0 Nm per count
    # against 1.6 - so the raw value has to be converted, not copied. Copying it
    # understates max torque by a fifth, which is exactly the sort of quiet error
    # that survives a run and shows up as a plausible wrong answer.
    nm = torque * 2.0
    return [
        min(255, max(0, torque)),
        min(255, max(0, int(nm / 1.6))),
        0xFF,                              # nothing limiting
        0,
        min(255, max(0, pedal)),
        rpm & 0xFF,
        (rpm >> 8) & 0xFF,
        0x01,
    ]


def can_412(row, get):
    """CAN 0x412. Byte 0 is the pedal figure the control code actually uses.

    This is the frame that matters, and it took a while to see. Section 19 traced
    line pressure from 0x412, not 0x410, and the cross-reference bears it out: the
    0x410 decode writes engine torque to 0xFFFF30F0, which nothing in the image
    reads, while the 0x412 decode writes byte 0 to 0xFFFF30FB, which seven sites
    read. 0xFFFF30FB is the address the Select Monitor table names Accelerator
    Pedal Travel - so the pedal the control path uses arrives over CAN from the
    ECU, not from a sensor of its own and not from byte 4 of 0x410.

    The remaining fields decode to 0xFFFF30FC, 0xFFFF30FE, 0xFFFF3100 and
    0xFFFF3101, none of them named yet, so they are left at zero rather than
    filled with invented values.
    """
    pedal = int(get(row, "Accelerator Pedal", 0) * 2.55)
    return [min(255, max(0, pedal)), 0, 0, 0, 0, 0, 0, 0]


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
    ap.add_argument("--torque", default=None,
                    help="torque per tick from ecu/torque.py --log --csv")
    ap.add_argument("--zero-pedal", action="store_true",
                    help="hold CAN 0x412 pedal at zero, as a control")
    args = ap.parse_args()

    # The work directory is outside the repo because the ECU ROM and the
    # RomRaider definition file are other people's, and this project does not
    # redistribute them. The tools are here; the inputs are fetched.
    torque_csv = args.torque
    if not torque_csv:
        for cand in (os.path.join(REPO, "ecu", "torque_from_log.csv"),
                     WORK_WSL + "/ecu/torque_from_log.csv",
                     WORK + r"\ecu\torque_from_log.csv"):
            if os.path.exists(cand):
                torque_csv = cand
                break
    torque = load_torque(torque_csv)

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
            frame410 = can_410(row, get, torque.get(t, 0))
            frame412 = [0] * 8 if args.zero_pedal else can_412(row, get)

            # The CAN frames, delivered to the buffers the receive table names.
            for base, frame in ((CAN_RX[0x410], frame410),
                                (CAN_RX[0x411], can_411(row, get)),
                                (CAN_RX[0x412], frame412)):
                for i, b in enumerate(frame):
                    parts.append("%08X:1=0x%X" % (base + i, b))
            # Tell the receive task a frame arrived, the way the controller would.
            parts.append("%08X:2=0x%X" % (CAN_RXPR, CAN_RXPR_BITS))

            # And perform the decode the receive task would have performed.
            for name, value in (("torque", frame410[0]),
                                ("pedal", frame410[4]),
                                ("rpm", frame410[5] | (frame410[6] << 8)),
                                ("status", frame410[7])):
                addr, size = DECODED[name]
                parts.append("%08X:%d=0x%X" % (addr, size, value))
            # And the one from 0x412 that the control code demonstrably reads.
            parts.append("%08X:1=0x%X" % (PEDAL_TRAVEL, frame412[0]))
            lines.append(",".join(parts))
        source = "%d rows of %s" % (len(rows), "the vehicle log")

    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print("%d ticks from %s -> %s" % (len(lines) - 1, source, args.out))
    if torque:
        moving = sum(1 for v in torque.values() if v)
        print("torque from %s: %d ticks, %d under load, peak %d (%.0f Nm)"
              % (os.path.basename(torque_csv), len(torque), moving,
                 max(torque.values()), max(torque.values()) * 2.0))
    else:
        print("no torque source found - CAN 0x410 byte 0 stays zero, so the "
              "line pressure chain will not be exercised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
