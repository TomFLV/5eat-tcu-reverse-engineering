#!/usr/bin/env python3
"""Work out which bytes of a Denso image are calibration data, not code.

Full disassembly needs to know what NOT to disassemble. Decoding a table as
instructions destroys it and, worse, manufactures cross-references that look real - a
sweep that ignored this produced 77 referrers to the shift-schedule array, every one
of them the sweep reading its own mis-decoded pointers.

Each table header describes exactly which bytes belong to it:

    header      28 bytes at the header address
    X axis      rows * 4 bytes of float
    Y axis      cols * 4 bytes of float
    data        rows * cols * 2 bytes of uint16

The axes and data are contiguous and immediately follow each other, so a table
occupies one run from the X axis pointer to the end of its data, plus the header
itself wherever that sits.

Emits one "start end" pair per line, merged and sorted, for the Ghidra sweep to skip.

    python tools/denso_data_ranges.py <image.bin> > ranges.txt
"""

import struct
import sys

HEADER_STRIDE = 28


def headers(d):
    out = []
    n = len(d)
    for a in range(0, n - HEADER_STRIDE, 4):
        rows, cols = struct.unpack(">HH", d[a:a + 4])
        if not (2 <= rows <= 64 and 1 <= cols <= 64):
            continue
        xp, yp, dp = struct.unpack(">III", d[a + 4:a + 16])
        if yp != xp + rows * 4 or dp != yp + cols * 4:
            continue
        if not (0x1000 < xp < n and dp + rows * cols * 2 <= n):
            continue
        scale, offset = struct.unpack(">ff", d[a + 20:a + 28])
        if scale != scale or offset != offset or scale == 0:
            continue
        if abs(scale) > 1e6 or abs(offset) > 1e6:
            continue
        out.append((a, rows, cols, xp, dp))
    return out


def main():
    d = open(sys.argv[1], "rb").read()
    spans = []
    for a, rows, cols, xp, dp in headers(d):
        spans.append((a, a + HEADER_STRIDE))                 # the header
        spans.append((xp, dp + rows * cols * 2))             # axes then data
    # the pointer arrays that index the headers are data too
    for i in range(0x1000, len(d) - 4, 4):
        v = struct.unpack(">I", d[i:i + 4])[0]
        if 0x1000 < v < len(d) - HEADER_STRIDE:
            rows, cols = struct.unpack(">HH", d[v:v + 2] + d[v + 2:v + 4])
            if 2 <= rows <= 64 and 1 <= cols <= 64:
                xp, yp, dp = struct.unpack(">III", d[v + 4:v + 16])
                if yp == xp + rows * 4 and dp == yp + cols * 4:
                    spans.append((i, i + 4))

    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    covered = sum(e - s for s, e in merged)
    for s, e in merged:
        print("%X %X" % (s, e))
    sys.stderr.write("%d data spans, %d bytes (%.1f%% of image)\n"
                     % (len(merged), covered, 100.0 * covered / len(d)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
