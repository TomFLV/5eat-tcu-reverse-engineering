#!/usr/bin/env python3
"""Recover the TCU's CAN receive map: identifier, mailbox, destination buffer.

Writing CAN frames straight into the HCAN mailboxes changed nothing in the
simulated drive, and the reason turns out to be simple: the firmware does not
read a mailbox where the control code needs the data. A receive task copies each
frame into a fixed RAM buffer, and every consumer reads the buffer. Run the
control function without running that task and the mailbox might as well be empty.

This finds the configuration table that drives the copy. Each entry is 16 bytes:

    +0  u16  CAN identifier            0x0410
    +2  u16  channel and mailbox       0x0104 - channel 1, mailbox 4
    +4  u16  0x0800, the payload length in the high byte
    +6  u16  0xFFFF, high half of the destination
    +8  u16  low half of the destination      0x300C -> 0xFFFF300C
    +10 u16  0x0100 flags
    +12 u32  zero

The destinations are eight bytes apart, one CAN payload each, which is the
strongest single confirmation that the reading is right.

    python tools/denso_can_map.py rom-denso/Impreza_STI_3.583_JDM2011.bin
    python tools/denso_can_map.py <rom> --profile 0x410=7E,9D,FF,00,FE,DE,15,01

The --profile form emits drive-profile lines that write a decoded frame to the
buffer the firmware actually reads, which is what feeding torque requires.
"""

import argparse
import struct
import sys

ENTRY = 16
# A receive entry is recognisable without knowing where the table starts: the
# length word and the high half of the destination are fixed, and the identifier
# is a valid 11-bit CAN id. Anchoring on the shape rather than an address means
# this still works on the other firmwares, where the table has moved.
LEN_WORD = 0x0800
DEST_HI = 0xFFFF


def be16(d, o):
    return struct.unpack_from(">H", d, o)[0]


def looks_like_entry(d, o):
    if o + ENTRY > len(d):
        return False
    cid = be16(d, o)
    return (0 < cid <= 0x7FF
            and be16(d, o + 4) == LEN_WORD
            and be16(d, o + 6) == DEST_HI
            and be16(d, o + 8) >= 0x2000)


def find_table(d):
    """The longest run of consecutive receive entries in the image."""
    best = (0, 0)
    o = 0
    while o + ENTRY <= len(d):
        if looks_like_entry(d, o):
            start, n = o, 0
            while looks_like_entry(d, o):
                n += 1
                o += ENTRY
            if n > best[1]:
                best = (start, n)
        else:
            o += 2
    return best


def entries(d, start, count):
    for i in range(count):
        o = start + i * ENTRY
        cid = be16(d, o)
        mbx = be16(d, o + 2)
        yield {
            "offset": o,
            "id": cid,
            "channel": mbx >> 8,
            "mailbox": mbx & 0xFF,
            "length": be16(d, o + 4) >> 8,
            "dest": 0xFFFF0000 | be16(d, o + 8),
            "flags": be16(d, o + 10),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--profile", action="append", default=[],
                    metavar="ID=B0,B1,...",
                    help="emit profile writes for a decoded frame")
    args = ap.parse_args()

    d = open(args.rom, "rb").read()
    start, count = find_table(d)
    if not count:
        sys.stderr.write("no receive table found in %s\n" % args.rom)
        return 1

    print("receive table at 0x%06X, %d entries\n" % (start, count))
    print("  %-8s %-7s %-4s %-8s %-6s %-12s %s"
          % ("offset", "CAN id", "ch", "mailbox", "len", "destination", "flags"))
    by_id = {}
    for e in entries(d, start, count):
        by_id.setdefault(e["id"], e)
        print("  %06X   0x%03X   %-4d %-8d %-6d 0x%08X   %04X"
              % (e["offset"], e["id"], e["channel"], e["mailbox"],
                 e["length"], e["dest"], e["flags"]))

    if args.profile:
        print("\nprofile writes - the firmware reads these, not the mailboxes:")
        for spec in args.profile:
            key, _, blob = spec.partition("=")
            cid = int(key, 16)
            if cid not in by_id:
                sys.stderr.write("id 0x%X is not in the receive table\n" % cid)
                continue
            dest = by_id[cid]["dest"]
            parts = []
            for i, b in enumerate(blob.split(",")):
                parts.append("%08X:1=0x%s" % (dest + i, b.strip().lstrip("0x")))
            print("  0x%03X -> 0x%08X" % (cid, dest))
            print("    " + ",".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
