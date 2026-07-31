#!/usr/bin/env python3
"""Build a RomRaider definition for the Denso SH705x 5EAT transmission controllers.

The 5EAT was built with two different controllers. The Hitachi M32R images are what
`generate_romraider_def.py` covers; later JDM and EDM cars, and the 2014 Tribeca, use
a Denso SH705x instead. Nothing about the two is shared - different processor, table
format, checksum and identification - so this is a separate generator rather than
more firmwares in the existing one.

TABLE FORMAT. Denso used the same structure here as in their engine ECUs, which is
the good news: RomRaider already understands it, so no editor patches are needed.

    +0x00 uint16 rows         +0x0C uint32 -> data, uint16
    +0x02 uint16 cols         +0x10 uint32 flags
    +0x04 uint32 -> X axis    +0x14 float  scale
    +0x08 uint32 -> Y axis    +0x18 float  offset

Axes are IEEE-754 floats and lie immediately before the data, X then Y, which is what
makes a header identifiable: a candidate is only accepted when the pointers are
exactly that far apart. The data is stored with the Y index outermost, which is the
order RomRaider's own Table3D reads, so the grid needs no transposition.

WHAT IS AND IS NOT NAMED. Twelve consecutive 15x5 tables hold the shift schedules,
confirmed two ways: the address matches what rimwall reported on the RomRaider forum
(topic 13725, posts 169 and 227), and the contents decode as an accelerator pedal
axis of 0..100 percent against vehicle speeds rising to a little over 200 km/h. Those
are named and carry real units.

The rest are emitted with structural names and no claimed units. There are a few
hundred of them and guessing would produce something that reads as confirmed when it
is not - the same reason tables in the M32R definition still say `raw`.

    python tools/generate_denso_def.py
"""

import glob
import os
import struct
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "definitions", "5eat_tcu_denso_romraider_defs.xml")

DENSO_MAGIC = b"\x00\x00\x0b\xf8"
CALID_AT = 0x2000
CALID_LEN = 8
HEADER_STRIDE = 28
SHIFT_SHAPE = (15, 5)
SHIFT_BLOCK_MIN = 8          # a run this long is the schedule block, not a coincidence

# Where the images live. They are other people's dumps; see the project README.
SOURCES = [
    os.path.join(REPO, "rom-denso", "*.bin"),
]


# --------------------------------------------------------------------------- #
# reading the ROM

def u16(d, a):
    return struct.unpack(">H", d[a:a + 2])[0]


def u32(d, a):
    return struct.unpack(">I", d[a:a + 4])[0]


def f32(d, a):
    return struct.unpack(">f", d[a:a + 4])[0]


def scan_tables(d):
    """Every self-consistent table header in the image."""
    out = []
    n = len(d)
    for a in range(0, n - HEADER_STRIDE, 4):
        rows, cols = struct.unpack(">HH", d[a:a + 4])
        if not (2 <= rows <= 64 and 1 <= cols <= 64):
            continue
        xp, yp, dp = struct.unpack(">III", d[a + 4:a + 16])
        # The axes sit immediately before the data, X then Y. Requiring that exact
        # spacing is what separates real headers from coincidental byte runs.
        if yp != xp + rows * 4 or dp != yp + cols * 4:
            continue
        if not (0x1000 < xp < n and dp + rows * cols * 2 <= n):
            continue
        scale, offset = struct.unpack(">ff", d[a + 20:a + 28])
        if scale != scale or offset != offset or scale == 0:      # NaN or degenerate
            continue
        if abs(scale) > 1e6 or abs(offset) > 1e6:
            continue
        out.append({"hdr": a, "rows": rows, "cols": cols,
                    "x": xp, "y": yp, "data": dp})
    return out


def shift_block(tables):
    """The longest run of consecutive 15x5 headers: the shift schedules."""
    hits = [t for t in tables if (t["rows"], t["cols"]) == SHIFT_SHAPE]
    hits.sort(key=lambda t: t["hdr"])
    best, run = [], []
    for t in hits:
        if run and t["hdr"] - run[-1]["hdr"] != HEADER_STRIDE:
            if len(run) > len(best):
                best = run
            run = []
        run.append(t)
    if len(run) > len(best):
        best = run
    return best if len(best) >= SHIFT_BLOCK_MIN else []


# --------------------------------------------------------------------------- #
# emitting the definition

def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


SHIFT_DESC = """SHIFT SCHEDULE {n} of {total}. Vehicle speed at which this shift
happens, against accelerator pedal angle.

Raise a value to delay the shift and hold the lower gear longer; lower it to shift
earlier. The transmission carries several complete schedules and selects between them
by operating condition - WHICH condition picks WHICH schedule is not established, so
treat them as a set unless you have logged which one is active.

Rows reading 255 throughout are unused in this calibration.

The address of this block matches what rimwall reported for Denso 5EAT TCUs on the
RomRaider forum, and the units are read from the data: the axis runs 0 to 100 percent
pedal, and the values are road speeds in km/h."""

RAW_DESC = """Unidentified {rows}x{cols} table, header at 0x{hdr:06X}.

The structure is certain - the header is self-consistent and the axes are real float
arrays - but the physical quantity is NOT established, so no units are claimed and the
values are shown raw. Changing it without knowing what it does is a bad idea."""


def axis_xml(kind, name, addr, size, units, expr, fmt):
    dim = 'sizex="%d"' % size if kind == "X Axis" else 'sizey="%d"' % size
    return (
        '   <table type="%s" name="%s" storageaddress="0x%06X" storagetype="float"\n'
        '          endian="big" %s>\n'
        '    <scaling units="%s" expression="%s" to_byte="%s" format="%s"\n'
        '             fineincrement="1" coarseincrement="5" />\n'
        '   </table>' % (kind, esc(name), addr, dim, esc(units), expr, expr, fmt))


def table_xml(t, name, category, desc, value_units, value_fmt, level):
    x = axis_xml("X Axis", "Accelerator pedal" if value_units else "X",
                 t["x"], t["rows"],
                 "% pedal" if value_units else "raw", "x", "0")
    y = axis_xml("Y Axis", "Schedule" if value_units else "Y",
                 t["y"], t["cols"],
                 "index" if value_units else "raw", "x", "0")
    return (
        '  <table type="3D" name="%s" category="%s" storageaddress="0x%06X"\n'
        '         storagetype="uint16" endian="big" sizex="%d" sizey="%d"\n'
        '         userlevel="%d">\n'
        '   <scaling units="%s" expression="x" to_byte="x" format="%s"\n'
        '            fineincrement="1" coarseincrement="5" />\n'
        '%s\n%s\n   <description>%s</description>\n  </table>'
        % (esc(name), esc(category), t["data"], t["rows"], t["cols"], level,
           esc(value_units or "raw"), value_fmt, x, y, esc(desc)))


def build_rom(path, d):
    calid = d[CALID_AT:CALID_AT + CALID_LEN].decode("ascii", "replace")
    tables = scan_tables(d)
    shifts = shift_block(tables)
    shift_hdrs = {t["hdr"] for t in shifts}

    parts = [" <rom>",
             "  <romid>",
             "   <xmlid>SUBARU_5EAT_DENSO_%s</xmlid>" % esc(calid),
             # HEX, without a 0x prefix: RomRaider reads this with
             # RomAttributeParser.parseHexString, so a decimal value here is
             # silently reinterpreted as hex and the definition never matches.
             "   <internalidaddress>%X</internalidaddress>" % CALID_AT,
             "   <internalidstring>%s</internalidstring>" % esc(calid),
             "   <ecuid>%s</ecuid>" % esc(calid),
             "   <year>-</year>",
             "   <market>-</market>",
             "   <make>Subaru</make>",
             "   <model>5EAT transmission (Denso SH705x)</model>",
             "   <submodel>%s</submodel>" % esc(os.path.basename(path)),
             "   <transmission>5EAT</transmission>",
             "   <memmodel>SH705x</memmodel>",
             "   <flashmethod>subarutcudenso</flashmethod>",
             "   <filesize>%dkb</filesize>" % (len(d) // 1024),
             "  </romid>",
             "",
             # Must be the DENSO manager. The Hitachi M32R one writes an additive
             # checksum at 0x8000 and a balance at 0x8020, neither of which exists
             # here - pointing this at "subarutcu" would corrupt the image on save.
             '  <checksum type="subarutcudenso" />',
             ""]

    parts.append("  <!-- ============ Shift Schedules ============ -->")
    for i, t in enumerate(shifts, 1):
        parts.append(table_xml(
            t, "Shift Schedule %d" % i, "Transmission - Shift Schedule",
            SHIFT_DESC.format(n=i, total=len(shifts)),
            "km/h", "0", 1))
    parts.append("")

    parts.append("  <!-- ============ Unidentified ============ -->")
    others = [t for t in tables if t["hdr"] not in shift_hdrs]
    for t in others:
        parts.append(table_xml(
            t, "Table %06X (%dx%d)" % (t["hdr"], t["rows"], t["cols"]),
            "Transmission - Unidentified",
            RAW_DESC.format(rows=t["rows"], cols=t["cols"], hdr=t["hdr"]),
            None, "0", 4))

    parts.append(" </rom>")
    return "\n".join(parts), calid, len(shifts), len(others)


def main():
    paths = []
    for pat in SOURCES:
        paths.extend(sorted(glob.glob(pat)))
    if not paths:
        print("No Denso images found in rom-denso/. Nothing to do.")
        return 1

    blocks, summary = [], []
    for p in paths:
        d = open(p, "rb").read()
        if d[:4] != DENSO_MAGIC:
            print("  skipping %s: not a Denso image" % os.path.basename(p))
            continue
        xml, calid, n_shift, n_other = build_rom(p, d)
        blocks.append(xml)
        summary.append((os.path.basename(p), calid, n_shift, n_other))

    doc = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
           "<!--\n"
           "  Subaru 5EAT transmission control unit - Denso SH705x\n\n"
           "  A SEPARATE FAMILY from the Hitachi M32R 5EAT definition in\n"
           "  5eat_tcu_romraider_defs.xml. Different processor, table format and\n"
           "  checksum; the two share nothing but the transmission they control.\n\n"
           "  Generated by tools/generate_denso_def.py - edit that, not this.\n"
           "-->\n<roms>\n" + "\n\n".join(blocks) + "\n</roms>\n")

    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)

    print("Wrote %s" % OUT)
    for name, calid, ns, no in summary:
        print("  %-44s %-9s %2d shift schedules, %3d unidentified"
              % (name[:44], calid, ns, no))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
