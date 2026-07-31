#!/usr/bin/env python3
"""Survey Denso SH705x 5EAT TCU images and decode their shift tables.

This project's definition covers the Hitachi M32R TCUs. The 5EAT was also built with
a Denso SH705x controller - later JDM and EDM cars, and the 2014 Tribeca - and those
images are a different family entirely: different processor, different checksum,
different table format. Nothing in `definitions/` applies to them.

They are tractable, though, and this tool is what establishes that. rimwall gave two
addresses on the RomRaider forum (topic 13725, posts 169 and 227): shift table headers
at 0xE9080, data starting at 0xB6354. Both land exactly.

The table format is Denso's own, the same one their ECUs use:

    +0x00  uint16  rows          (15)
    +0x02  uint16  columns       (5)
    +0x04  uint32  pointer to the X axis, IEEE-754 floats
    +0x08  uint32  pointer to the Y axis, IEEE-754 floats
    +0x0C  uint32  pointer to the data, uint16
    +0x10  uint32  flags
    +0x14  float   scale
    +0x18  float   offset
                   (28 bytes; headers repeat at that stride)

Decoded, the first table is plainly a shift schedule: the X axis runs 0,5,10..100
which is accelerator pedal angle in percent, the Y axis 0..4, and the data rises from
about 33 to 224 with pedal, which is vehicle speed in km/h. Two rows read 255
throughout and are unused.

    python tools/survey_denso_tcu.py <image.bin> ...
"""

import argparse
import os
import struct

DENSO_MAGIC = b"\x00\x00\x0b\xf8"
INTEGRITY_TABLE = 0xFFB80
INTEGRITY_TARGET = 0x5AA5A55A
HEADER_STRIDE = 28
SHIFT_SIG = bytes.fromhex("000f0005")     # a 15 x 5 table


def u16(d, a):
    return struct.unpack(">H", d[a:a + 2])[0]


def u32(d, a):
    return struct.unpack(">I", d[a:a + 4])[0]


def f32(d, a):
    return struct.unpack(">f", d[a:a + 4])[0]


def integrity(d):
    """Denso block table: [start][end][balance] triples summing to 0x5AA5A55A."""
    out = []
    for i in range(6):
        a = INTEGRITY_TABLE + i * 12
        if a + 12 > len(d):
            break
        s, e, bal = struct.unpack(">III", d[a:a + 12])
        if not (0 <= s < e <= len(d)):
            break
        n = (e - s + 1) // 4
        tot = sum(struct.unpack(">%dI" % n, d[s:s + n * 4])) & 0xFFFFFFFF
        out.append((s, e, ((tot + bal) & 0xFFFFFFFF) == INTEGRITY_TARGET))
    return out


def shift_headers(d):
    """Consecutive 15x5 headers, which is where the shift schedules live."""
    found, a = [], d.find(SHIFT_SIG, 0xE0000, 0xF0000)
    while a != -1 and (not found or a - found[-1] == HEADER_STRIDE):
        found.append(a)
        a = d.find(SHIFT_SIG, a + 1, 0xF0000)
    return found


def decode(d, hdr):
    rows, cols = u16(d, hdr), u16(d, hdr + 2)
    xp, yp, dp = u32(d, hdr + 4), u32(d, hdr + 8), u32(d, hdr + 12)
    if max(xp, yp, dp) >= len(d):
        return None
    xs = [f32(d, xp + 4 * i) for i in range(rows)]
    ys = [f32(d, yp + 4 * i) for i in range(cols)]
    grid = [[u16(d, dp + 2 * (r * rows + c)) for c in range(rows)] for r in range(cols)]
    return xs, ys, grid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--tables", action="store_true", help="decode the first shift table")
    args = ap.parse_args()

    for path in args.images:
        d = open(path, "rb").read()
        print("\n=== %s (%d KB)" % (os.path.basename(path), len(d) // 1024))
        if d[:4] != DENSO_MAGIC:
            print("  not a Denso image (opens %s)" % d[:4].hex())
            continue

        for s, e, ok in integrity(d):
            print("  integrity 0x%06X-0x%06X  %s" % (s, e, "OK" if ok else "BAD"))

        hdrs = shift_headers(d)
        if not hdrs:
            print("  no 15x5 shift table headers found in 0xE0000-0xF0000")
            continue
        print("  %d shift tables at 0x%06X, stride %d" % (len(hdrs), hdrs[0], HEADER_STRIDE))

        if args.tables:
            got = decode(d, hdrs[0])
            if not got:
                print("    header pointers out of range")
                continue
            xs, ys, grid = got
            print("    pedal %%: %s" % ", ".join("%g" % v for v in xs))
            for y, row in zip(ys, grid):
                mark = "  (unused)" if set(row) == {255} else ""
                print("    y=%-4g %s%s" % (y, row, mark))


if __name__ == "__main__":
    raise SystemExit(main())
