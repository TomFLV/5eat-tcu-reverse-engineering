#!/usr/bin/env python3
"""Draw a ROM's shift schedule as a chart, in the same form as the factory one.

WHY THIS EXISTS, and why the RomRaider tables are not a 3D surface
------------------------------------------------------------------
A shift map is usually pictured as a grid: speed across, load up, a gear or a
value in every cell. The 5EAT does not store one. Each shift point is a POLYLINE
of seven or eight vertices in (vehicle speed, accelerator angle) space, and the
TCU shifts when the operating point crosses that line.

That has a real consequence: there is no matrix in the ROM to put on a grid. A
"3D map" of the shift schedule could only be produced by sampling the polylines
onto a grid we invented, and every cell of it would be fabricated - editable in
appearance, connected to nothing. Which is why the RomRaider tables are what they
are: the vertex list, in real units, exactly as many numbers as the ROM holds.

So to actually SEE the map, plot the lines. That is what the factory chart does
(docs/shift-curves-reference.png), and it is what this produces - from any ROM,
so you can see what your own calibration does and diff it against stock.

Output is a PNG written with nothing but the standard library.

    python tools/plot_shift_map.py rom/91D1206000_5EAT.bin -o shift_map.png
"""

import argparse
import json
import os
import re
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

W, H = 900, 620
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 78, 210, 46, 56
PLOT_W = W - MARGIN_L - MARGIN_R
PLOT_H = H - MARGIN_T - MARGIN_B
SPEED_MAX = 140          # km/h across
PEDAL_MAX = 100          # % accelerator up

BG = (24, 26, 30)
GRID = (52, 56, 64)
AXIS = (150, 156, 168)
TEXT = (226, 230, 238)

# Upshifts warm, downshifts cool, so a pair is easy to tell apart at a glance.
COLOURS = {
    "1-2": (255, 92, 92), "2-3": (255, 158, 66),
    "3-4": (255, 214, 74), "4-5": (140, 220, 96),
    "2-1": (96, 190, 255), "3-2": (120, 150, 255),
    "4-3": (168, 128, 255), "5-4": (226, 120, 226),
}

# A 5x7 bitmap font, enough for the labels used here. Each glyph is 7 rows of 5
# bits. Drawing text is not worth a dependency for this.
FONT = {
    "0": (0x1E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E), "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F), "3": (0x1F, 0x02, 0x04, 0x02, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02), "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E), "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E), "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x1C),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00), "%": (0x11, 0x12, 0x02, 0x04, 0x08, 0x09, 0x11),
    "/": (0x01, 0x02, 0x02, 0x04, 0x08, 0x08, 0x10), " ": (0, 0, 0, 0, 0, 0, 0),
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11), "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E), "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10), "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0E),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11), "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11), "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11), "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E), "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11), "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04), "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04), "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11),
    "Y": (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04), "h": (0x10, 0x10, 0x16, 0x19, 0x11, 0x11, 0x11),
    "k": (0x10, 0x10, 0x12, 0x14, 0x18, 0x14, 0x12), "m": (0x00, 0x00, 0x1A, 0x15, 0x15, 0x15, 0x15),
    "p": (0x00, 0x00, 0x1E, 0x11, 0x1E, 0x10, 0x10), "e": (0x00, 0x0E, 0x11, 0x1F, 0x10, 0x11, 0x0E),
    "d": (0x01, 0x01, 0x0D, 0x13, 0x11, 0x11, 0x0F), "a": (0x00, 0x0E, 0x01, 0x0F, 0x11, 0x11, 0x0F),
    "l": (0x0C, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E), "s": (0x00, 0x0F, 0x10, 0x0E, 0x01, 0x11, 0x0E),
    "n": (0x00, 0x00, 0x16, 0x19, 0x11, 0x11, 0x11), "i": (0x04, 0x00, 0x04, 0x04, 0x04, 0x04, 0x04),
    "o": (0x00, 0x00, 0x0E, 0x11, 0x11, 0x11, 0x0E), "t": (0x04, 0x04, 0x1F, 0x04, 0x04, 0x04, 0x03),
    "u": (0x00, 0x00, 0x11, 0x11, 0x11, 0x11, 0x0F), "r": (0x00, 0x00, 0x16, 0x19, 0x10, 0x10, 0x10),
    "c": (0x00, 0x00, 0x0E, 0x11, 0x10, 0x11, 0x0E), "g": (0x00, 0x0F, 0x11, 0x0F, 0x01, 0x01, 0x0E),
    "(": (0x02, 0x04, 0x08, 0x08, 0x08, 0x04, 0x02), ")": (0x08, 0x04, 0x02, 0x02, 0x02, 0x04, 0x08),
    ":": (0x00, 0x04, 0x00, 0x00, 0x00, 0x04, 0x00), ".": (0, 0, 0, 0, 0, 0, 0x04),
    "f": (0x06, 0x08, 0x1C, 0x08, 0x08, 0x08, 0x08), "w": (0x00, 0x00, 0x11, 0x11, 0x15, 0x15, 0x0A),
    "b": (0x10, 0x10, 0x1E, 0x11, 0x11, 0x11, 0x1E), "h": (0x10, 0x10, 0x16, 0x19, 0x11, 0x11, 0x11),
    "y": (0x00, 0x00, 0x11, 0x11, 0x0F, 0x01, 0x0E), "v": (0x00, 0x00, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "x": (0x00, 0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11), "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
}


class Canvas:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.px = bytearray(bg * (w * h))

    def set(self, x, y, c):
        x, y = int(x), int(y)
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(c)

    def hline(self, x0, x1, y, c):
        for x in range(int(x0), int(x1) + 1):
            self.set(x, int(y), c)

    def vline(self, x, y0, y1, c):
        for y in range(int(y0), int(y1) + 1):
            self.set(int(x), y, c)

    def line(self, x0, y0, x1, y1, c, width=2):
        """Bresenham, thickened by stamping a small square at each step."""
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx - dy
        r = width // 2
        while True:
            for ox in range(-r, r + 1):
                for oy in range(-r, r + 1):
                    self.set(x0 + ox, y0 + oy, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def text(self, x, y, s, c, scale=1):
        cx = x
        for ch in s:
            g = FONT.get(ch)
            if g is None:
                cx += 6 * scale
                continue
            for row, bits in enumerate(g):
                for col in range(5):
                    if bits & (1 << (4 - col)):
                        for sx in range(scale):
                            for sy in range(scale):
                                self.set(cx + col * scale + sx,
                                         y + row * scale + sy, c)
            cx += 6 * scale
        return cx

    def png(self, path):
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)                                  # filter type 0
            raw += self.px[y * self.w * 3:(y + 1) * self.w * 3]

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
            fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)))
            fh.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
            fh.write(chunk(b"IEND", b""))


def read_curves(rom_path):
    """Read the shift curves for this ROM out of the extracted address table."""
    curves = json.load(open(os.path.join(HERE, "shift_curves.json")))
    m = re.search(r"[0-9A-Z]{10}", os.path.basename(rom_path).upper())
    key = m.group(0) if m else None
    if key not in curves:
        raise SystemExit(
            f"no shift curve addresses for {os.path.basename(rom_path)}.\n"
            f"known: {', '.join(sorted(curves))}")
    data = open(rom_path, "rb").read()

    def u16(a):
        return (data[a] << 8) | data[a + 1]

    out = {}
    for name, c in curves[key].items():
        pts = []
        for r in range(c["rows"]):
            o = c["addr"] + r * 8
            s0, p0, s1, p1 = u16(o), u16(o + 2), u16(o + 4), u16(o + 6)
            # The final record clamps with 255 in both slots; it is a sentinel
            # meaning "beyond here, unchanged", not a point at 255 km/h.
            pts.append((s0, p0 * 100.0 / 255.0))
            if s1 != 0xFF and s1 < 0xFF00 and s1 != 255:
                pts.append((s1, p1 * 100.0 / 255.0))
        out[name] = pts
    return out, key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()
    out = args.out or os.path.splitext(os.path.basename(args.rom))[0] + "_shift_map.png"

    curves, key = read_curves(args.rom)
    cv = Canvas(W, H, BG)

    def sx(speed):
        return MARGIN_L + speed / SPEED_MAX * PLOT_W

    def sy(pedal):
        return MARGIN_T + PLOT_H - pedal / PEDAL_MAX * PLOT_H

    # grid
    for s in range(0, SPEED_MAX + 1, 20):
        cv.vline(sx(s), MARGIN_T, MARGIN_T + PLOT_H, GRID)
        cv.text(sx(s) - 6, MARGIN_T + PLOT_H + 10, str(s), AXIS)
    for p in range(0, PEDAL_MAX + 1, 10):
        cv.hline(MARGIN_L, MARGIN_L + PLOT_W, sy(p), GRID)
        cv.text(MARGIN_L - 26, sy(p) - 3, str(p), AXIS)

    cv.hline(MARGIN_L, MARGIN_L + PLOT_W, MARGIN_T + PLOT_H, AXIS)
    cv.vline(MARGIN_L, MARGIN_T, MARGIN_T + PLOT_H, AXIS)
    cv.text(MARGIN_L + PLOT_W // 2 - 52, MARGIN_T + PLOT_H + 30, "Vehicle speed km/h", TEXT)
    cv.text(6, MARGIN_T - 22, "Pedal %", TEXT)
    cv.text(MARGIN_L, 14, f"5EAT shift schedule  {key}", TEXT)

    # curves
    for name, pts in sorted(curves.items()):
        m = re.search(r"(\d-\d)", name)
        colour = COLOURS.get(m.group(1) if m else "", (200, 200, 200))
        for i in range(len(pts) - 1):
            (s0, p0), (s1, p1) = pts[i], pts[i + 1]
            if s0 > SPEED_MAX or s1 > SPEED_MAX:
                continue
            cv.line(sx(s0), sy(p0), sx(s1), sy(p1), colour, 2)

    # legend
    ly = MARGIN_T + 4
    cv.text(MARGIN_L + PLOT_W + 18, ly, "Upshift", TEXT)
    ly += 14
    for name in sorted(curves):
        m = re.search(r"(\d-\d)", name)
        tag = m.group(1) if m else name
        if "Down" in name:
            continue
        colour = COLOURS.get(tag, (200, 200, 200))
        cv.line(MARGIN_L + PLOT_W + 18, ly + 3, MARGIN_L + PLOT_W + 44, ly + 3, colour, 3)
        cv.text(MARGIN_L + PLOT_W + 50, ly, tag, TEXT)
        ly += 14
    ly += 8
    cv.text(MARGIN_L + PLOT_W + 18, ly, "Downshift", TEXT)
    ly += 14
    for name in sorted(curves):
        m = re.search(r"(\d-\d)", name)
        tag = m.group(1) if m else name
        if "Down" not in name:
            continue
        colour = COLOURS.get(tag, (200, 200, 200))
        cv.line(MARGIN_L + PLOT_W + 18, ly + 3, MARGIN_L + PLOT_W + 44, ly + 3, colour, 3)
        cv.text(MARGIN_L + PLOT_W + 50, ly, tag, TEXT)
        ly += 14

    cv.png(out)
    n = sum(len(v) for v in curves.values())
    print(f"wrote {out}  ({len(curves)} curves, {n} vertices)")


if __name__ == "__main__":
    main()
