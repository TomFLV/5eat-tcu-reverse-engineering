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
import json
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


INDEXED = {}
_idx = os.path.join(HERE, "denso_indexed_tables.json")
if os.path.exists(_idx):
    with open(_idx, encoding="utf-8") as _fh:
        INDEXED = json.load(_fh)


def indexed_headers(calid):
    """Header addresses the firmware actually indexes, per find_denso_pointer_tables.

    A header that parses is not necessarily a table. Tables are reached through arrays
    of pointers to their headers, so anything named by such an array is real and
    anything else is a candidate that survived a structural filter by chance. Where
    the index is available, the definition ships only what it names.
    """
    e = INDEXED.get(calid)
    return {t["header"] for t in e["tables"]} if e else None


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
                    "x": xp, "y": yp, "data": dp,
                    "scale": scale, "offset": offset})
    return out


def scaling_expr(scale, offset):
    """(expression, to_byte) for a header's scale and offset.

    The header carries the conversion from stored counts to the real quantity, and
    it was being read only to validate the header and then discarded - so every
    Denso table shipped as raw counts while the firmware itself knew better. It
    matters for about half of them: of 196 headers in one image, 98 are scale 1
    offset 0 and the rest are not, with forms like 1/256 fixed point, 0.01, and
    0.001 with a -30 offset.
    """
    # A denormal scale is not a conversion, it is three bytes of something else that
    # happened to sit where the header keeps one. Treat anything below a millionth
    # as unscaled rather than multiplying the table into nothing.
    if (not scale or scale != scale or offset != offset
            or abs(scale) < 1e-6 or abs(offset) >= 1e6):
        return "x", "x"

    def trim(v):
        """Shortest decimal that still round-trips through the stored float32.

        The header holds IEEE-754 single precision, and 0.01 is not exactly
        representable there, so printing the full value gives 0.009999999776 in
        the definition. That is correct and unreadable. Taking the shortest form
        that reads back as the same float32 gives 0.01 while keeping exact values
        like 1/256 intact as 0.00390625.
        """
        for digits in range(1, 10):
            s = "%.*g" % (digits, v)
            if struct.unpack(">f", struct.pack(">f", float(s)))[0] == v:
                break
        else:
            s = "%.10g" % v
        # RomRaider parses these expressions itself, so keep them to plain decimal
        # rather than handing it 1e+04 and hoping.
        if "e" in s or "E" in s:
            s = ("%.10f" % v).rstrip("0").rstrip(".")
        return s

    expr = "x" if scale == 1.0 else "x*%s" % trim(scale)
    if offset:
        expr += ("+" if offset > 0 else "-") + trim(abs(offset))

    inv = "x" if not offset else "(x%s%s)" % ("-" if offset > 0 else "+",
                                              trim(abs(offset)))
    if scale != 1.0:
        inv += "/%s" % trim(scale)
    return expr, inv


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


SHIFT_DESC = """{kind} SCHEDULE {pair} of {pairs}. Road speed at which each shift
happens, against accelerator angle.

Each row is one shift:

    1-2, 2-3, 3-4, 4-5   in that order, top to bottom

A row reading 255 throughout is unused in this calibration.

ABOVE ROUGHLY 35% PEDAL THIS TABLE STOPS DECIDING. Every row flattens into the same
tail, ending at a speed the car cannot reach - 224 km/h on upshift schedules, 205 on
downshift. That entry means "do not shift on road speed", and above it the shift is
governed by an engine speed limit instead. Full-throttle shifts in a logged car occur
at 6278 to 7300 turbine rpm against a 6944 rpm maximum: they are redline shifts.

So changing the high-pedal end of these curves will NOT move a full-throttle shift
point. Only the part-throttle region does anything.

Below that, the threshold here is necessary but not sufficient. A logged car sat 25 to
45 km/h above every 4-5 threshold it has, in the right gear at steady speed, and held
fourth for four seconds before shifting - so something inhibits the change beyond this
comparison. Raising a value will delay a shift; lowering one does not guarantee it
happens sooner.

Confirmed against a log from WQDE2WB1, the calibration these tables were read from.
See FINDINGS.md sections 36 and 37."""

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


def read_axis(d, addr, n):
    """An axis as the firmware stores it: n big-endian floats."""
    try:
        return list(struct.unpack(">%df" % n, d[addr:addr + n * 4]))
    except (struct.error, TypeError):
        return []


def describe_axis(vals):
    """What an axis is, from what is in it.

    Naming a table's FUNCTION from its shape would be guessing, and this project
    has been burned by that often enough to have a rule against it. Naming its
    AXES is a different claim: the values are in the ROM, and a run from 800 to
    6800 in even steps is an engine speed whatever the table does with it. So this
    reports only what the numbers show and falls back to a plain range otherwise.

    The point is navigability. "Table 0E5280 (8x8)" tells a tuner nothing.
    "8x8, engine speed by pedal" tells them what moves along each edge, which is
    enough to find the right table and see what it does to the car.
    """
    if not vals:
        return "axis", "raw"
    lo, hi = min(vals), max(vals)
    n = len(vals)
    rising = all(b >= a for a, b in zip(vals, vals[1:]))
    ints = all(abs(v - round(v)) < 1e-3 for v in vals)
    if not rising:
        return "%g-%g" % (lo, hi), "raw"
    if hi >= 2000 and lo >= 0:
        return "Engine speed %g-%g" % (lo, hi), "RPM"
    if ints and 0 <= lo and hi <= 8 and n <= 9:
        return "Gear or mode %g-%g" % (lo, hi), "index"
    if 90 <= hi <= 110 and lo >= 0:
        return "Pedal or load %g-%g" % (lo, hi), "%"
    if lo < 0 and hi <= 200:
        return "Temperature %g-%g" % (lo, hi), "C"
    if 8 < hi <= 260 and lo >= 0:
        return "Speed %g-%g" % (lo, hi), "km/h"
    return "%g-%g" % (lo, hi), "raw"


def axis_kind(units):
    """A short word for the category, so tables group by what indexes them."""
    return {"RPM": "engine speed", "%": "pedal", "index": "gear",
            "C": "temperature", "km/h": "speed"}.get(units, "")


def table_xml(t, name, category, desc, value_units, value_fmt, level, rom=None):
    if value_units:
        xname, xunits = "Accelerator pedal", "% pedal"
        yname, yunits = "Shift", "0=unused, 1=1-2, 2=2-3, 3=3-4, 4=4-5"
    else:
        # An unidentified table still has real axes. Reading them costs nothing and
        # turns an undifferentiated heap into something a person can navigate.
        xname, xunits = describe_axis(read_axis(rom, t["x"], t["rows"]))
        yname, yunits = describe_axis(read_axis(rom, t["y"], t["cols"]))
    x = axis_xml("X Axis", xname, t["x"], t["rows"], xunits, "x", "0")
    y = axis_xml("Y Axis", yname, t["y"], t["cols"], yunits, "x", "0")
    # The header's own conversion, so the table reads in whatever quantity the
    # firmware works in rather than in stored counts.
    expr, to_byte = scaling_expr(t.get("scale", 1.0), t.get("offset", 0.0))
    fmt = value_fmt
    if expr != "x" and fmt == "0":
        fmt = "0.000"          # a scaled value needs somewhere to put the decimals
    units = value_units or ("raw" if expr == "x" else "scaled")
    return (
        '  <table type="3D" name="%s" category="%s" storageaddress="0x%06X"\n'
        '         storagetype="uint16" endian="big" sizex="%d" sizey="%d"\n'
        '         userlevel="%d">\n'
        '   <scaling units="%s" expression="%s" to_byte="%s" format="%s"\n'
        '            fineincrement="1" coarseincrement="5" />\n'
        '%s\n%s\n   <description>%s</description>\n  </table>'
        % (esc(name), esc(category), t["data"], t["rows"], t["cols"], level,
           esc(units), expr, to_byte, fmt, x, y, esc(desc)))


def build_rom(path, d):
    calid = d[CALID_AT:CALID_AT + CALID_LEN].decode("ascii", "replace")
    tables = scan_tables(d)
    # The shift block is found on the FULL scan. It is identified by a run of
    # consecutive headers at a known address, which is independent evidence and
    # stronger than the pointer index; filtering first breaks the run and silently
    # drops schedules that are certainly real.
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
            t,
            "Shift Schedule %d - %s" % ((i + 1) // 2,
                                        "Upshift" if i % 2 else "Downshift"),
            "Transmission - Shift Schedule",
            SHIFT_DESC.format(kind="UPSHIFT" if i % 2 else "DOWNSHIFT",
                              pair=(i + 1) // 2, pairs=(len(shifts) + 1) // 2),
            "km/h", "0", 1))
    parts.append("")

    dtc_at = dtc_table(d)
    if dtc_at is not None:
        parts.append("  <!-- ============ Diagnostic Codes ============ -->")
        for i in range(DTC_COUNT):
            code = struct.unpack_from(">H", d, dtc_at + i * 2)[0] & 0x3FFF
            if code:
                parts.append(dtc_xml(dtc_at + i * 2, "P%04X" % code))
        parts.append("")

    parts.append("  <!-- ============ Unidentified ============ -->")
    # Everything else IS filtered by the index: an unidentified table is only worth
    # shipping if the firmware demonstrably reaches it.
    keep = indexed_headers(calid)
    others = [t for t in tables if t["hdr"] not in shift_hdrs
              and (keep is None or t["hdr"] in keep)]
    for t in others:
        # Group and name by what the axes are. The function is still unknown - the
        # description says so - but "engine speed by pedal" is a fact read out of
        # the ROM, and it is the difference between 185 identical entries and a
        # dozen groups a person can work through.
        _xn, xu = describe_axis(read_axis(d, t["x"], t["rows"]))
        _yn, yu = describe_axis(read_axis(d, t["y"], t["cols"]))
        kx, ky = axis_kind(xu), axis_kind(yu)
        # A table whose cells are all the same value has nothing to tune. Of 185
        # unidentified tables in one image, 64 are like this. They are real tables
        # and worth keeping - a constant is a fact about the calibration - but
        # mixing them in with the rest is most of what makes the list feel like
        # noise, so they go in their own category and stay out of the way.
        n = t["rows"] * t["cols"]
        try:
            vals = struct.unpack(">%dH" % n, d[t["data"]:t["data"] + n * 2])
        except struct.error:
            vals = ()
        if vals and len(set(vals)) == 1:
            parts.append(table_xml(
                t, "Table %06X - %dx%d constant %d"
                   % (t["hdr"], t["rows"], t["cols"], vals[0]),
                "Transmission - Constant (nothing to tune)",
                RAW_DESC.format(rows=t["rows"], cols=t["cols"], hdr=t["hdr"]),
                None, "0", 4, rom=d))
            continue
        if kx and ky:
            cat = "Transmission - Unidentified (%s by %s)" % (kx, ky)
            label = "%dx%d %s by %s" % (t["rows"], t["cols"], kx, ky)
        elif kx or ky:
            cat = "Transmission - Unidentified (%s)" % (kx or ky)
            label = "%dx%d %s" % (t["rows"], t["cols"], kx or ky)
        else:
            cat = "Transmission - Unidentified (unclassified axes)"
            label = "%dx%d" % (t["rows"], t["cols"])
        parts.append(table_xml(
            t, "Table %06X - %s" % (t["hdr"], label), cat,
            RAW_DESC.format(rows=t["rows"], cols=t["cols"], hdr=t["hdr"]),
            None, "0", 4, rom=d))

    parts.append(" </rom>")
    return "\n".join(parts), calid, len(shifts), len(others)


"""Diagnostic trouble codes.

The table is 44 uint16 slots, each the P-number in hex; the firmware masks the
value with 0x3FFF when it reports it. Its address differs per firmware, so it is
located by searching for the code sequence rather than hardcoded - and the
sequence is identical in all nine images, with the Impreza's base landing on
0x0008624C exactly where the instruction at 0x0007D51C indexes it.

Zeroing a slot is what the switch does, and it is worth being precise about what
that achieves: the fault bit still sets, the controller still behaves however it
behaves, and only the code number goes away. That is the same mechanism the M32R
definition offers and the same caveat applies.

What is NOT offered here is any claim about which fault sets which code. The
monitors were located - 0x00087654, 0x000882DC and 0x0008DA0A, debounced to a
thousand counts against a threshold at 0x000A2DF0 - but no simulated fault has
been made to latch one, so the mapping from condition to code is unverified.
"""
DTC_COUNT = 44
# The first eight codes, used as the search key. Eight uint16 in a fixed order is
# sixteen bytes of very specific data; a false match is not a realistic worry.
DTC_SEQUENCE = (0x0720, 0x0705, 0x0741, 0x0753, 0x0758, 0x1706, 0x0748, 0x0743)

DTC_DESC = """{code} - enable or disable this diagnostic trouble code.

DISABLED writes zero to this code's slot, which makes it identical to the slots \
the factory already leaves empty. The fault bit still sets internally, but no \
code number is attached to it, so nothing is reported.

Know what that does and does not do. It suppresses the CODE, not the FAULT - \
whatever limp-home, pressure or shift behaviour the TCU applies when that bit \
sets will still happen. You have only stopped it telling you why.

Which condition sets this code is not established for this controller family."""


def dtc_table(d):
    """Where the code table starts in this image, or None."""
    key = struct.pack(">" + "H" * len(DTC_SEQUENCE), *DTC_SEQUENCE)
    i = d.find(key)
    return i if i >= 0 else None


def dtc_xml(addr, code):
    return (
        '  <table type="Switch" name="%s" category="Transmission - Diagnostic Codes"\n'
        '         storageaddress="0x%06X" sizey="2" userlevel="4">\n'
        '   <description>%s</description>\n'
        '   <state name="ENABLED"  data="%02X%02X" />\n'
        '   <state name="DISABLED" data="0000" />\n'
        '  </table>' % (code, addr, esc(DTC_DESC.format(code=code)),
                        int(code[1:], 16) >> 8, int(code[1:], 16) & 0xFF))


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
