#!/usr/bin/env python3
"""Read a table out of a Subaru ECU ROM using its RomRaider definition.

Why this exists. Our TCU is told engine torque over CAN 0x410 byte 0, and the
vehicle logs are TCU-side so that byte has always been fed as zero - which leaves
the whole line-pressure chain untouched in every simulated drive so far. The ECU
that sends it is AZ1G502L, and its requested-torque maps are pedal angle by engine
speed. Both of those ARE in the logs. So reading these maps turns the logs into
the torque signal they were missing, from the actual calibration rather than a
guess.

Two details bite if assumed rather than read. The scaling is an inline expression
on the table rather than a named reference. And the definitions tag the float axes
little-endian when the ROM stores them big-endian like everything else on an
SH7058 - believe the tag and the data comes out perfect while the axes come out as
denormals around 1e-41, so the table still prints and is still wrong.

    python read_table.py AZ1G502L "Requested Torque A (Accelerator Pedal) SI-DRIVE Intelligent"
    python read_table.py AZ1G502L --grep "Requested Torque" --list
    python read_table.py AZ1G502L "..." --csv out.csv
"""

import argparse
import os
import struct
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))


def work_dir():
    """Where the ECU ROM and the RomRaider definition file live.

    Deliberately outside the repository: neither is ours. The ROMs come from a
    community collection and the definitions are the RomRaider project's, so this
    keeps the tools versioned and the inputs fetched. Set ECU_WORK_DIR to move it;
    the defaults cover the mirrored working copy from both sides of WSL.
    """
    for c in (os.environ.get("ECU_WORK_DIR"), HERE,
              "/mnt/d/5eat-work/ecu", r"D:\5eat-work\ecu"):
        if c and os.path.exists(os.path.join(c, "ecu_defs.xml")):
            return c
    return HERE


FMT = {
    ("uint8", "big"): (">B", 1), ("uint8", "little"): ("<B", 1),
    ("int8", "big"): (">b", 1), ("int8", "little"): ("<b", 1),
    ("uint16", "big"): (">H", 2), ("uint16", "little"): ("<H", 2),
    ("int16", "big"): (">h", 2), ("int16", "little"): ("<h", 2),
    ("uint32", "big"): (">I", 4), ("uint32", "little"): ("<I", 4),
    ("float", "big"): (">f", 4), ("float", "little"): ("<f", 4),
}


def load_roms(path):
    roms = {}
    for rom in ET.parse(path).getroot().iter("rom"):
        rid = rom.find("romid")
        if rid is not None:
            x = (rid.findtext("xmlid") or "").strip()
            if x:
                roms[x] = rom
    return roms


def resolve(roms, xmlid, want):
    """Merge base shape with calibration addresses for one named table.

    Returns the merged attributes plus the axis sub-tables, each carrying its own
    scaling. The base is applied first so the calibration wins where they differ.
    """
    order, cur, seen = [], xmlid, set()
    while cur and cur in roms and cur not in seen:
        seen.add(cur)
        order.append(cur)
        cur = roms[cur].get("base")

    attrib, axes, scaling, desc = {}, {}, None, None
    for name in reversed(order):
        for t in roms[name].findall("table"):
            if t.get("name") != want:
                continue
            attrib.update(t.attrib)
            s = t.find("scaling")
            if s is not None:
                scaling = s.attrib
            d = t.findtext("description")
            if d:
                desc = d.strip()
            for sub in t.findall("table"):
                key = sub.get("type") or sub.get("name")
                a = dict(axes.get(key, {}).get("attrib", {}))
                a.update(sub.attrib)
                sc = axes.get(key, {}).get("scaling")
                ss = sub.find("scaling")
                if ss is not None:
                    sc = ss.attrib
                axes[key] = {"attrib": a, "scaling": sc}
    if not attrib:
        return None
    return {"attrib": attrib, "axes": axes, "scaling": scaling,
            "description": desc}


def apply_expr(expr, x):
    if not expr:
        return x
    try:
        return eval(expr, {"__builtins__": {}}, {"x": float(x)})
    except Exception:
        return x


def plausible(vals):
    """Does this endianness produce values a real axis could hold?

    A big-endian float read as little-endian turns 800.0 - stored 44 48 00 00 -
    into 0x00004844, a denormal near 1e-41. No calibration axis holds denormals,
    infinities or values in the billions, so any of those is a reliable sign the
    declared endianness is wrong. It is wrong often: these definitions tag the
    float axes little-endian while the ROM stores them big-endian like everything
    else on an SH7058. Trusting the tag yields a table with perfect data and
    nonsense axes, which is worse than an obvious failure because it still prints.
    """
    for v in vals:
        if v != v or v in (float("inf"), float("-inf")):
            return False
        if v != 0 and abs(v) < 1e-20:
            return False
        if abs(v) > 1e9:
            return False
    return True


def read_series(data, addr, count, stype, endian, expr):
    key = (stype, endian)
    if key not in FMT:
        raise ValueError("unhandled storage %s/%s" % (stype, endian))
    fmt, size = FMT[key]
    out = []
    for i in range(count):
        off = addr + i * size
        raw = struct.unpack_from(fmt, data, off)[0]
        out.append(apply_expr(expr, raw))
    return out


def load_table(xmlid, want, rom=None, xml=None):
    """Read one table and return (x axis, y axis, grid, meta).

    The single entry point for anything that needs ROM values rather than a
    printout - the torque lookup that feeds the TCU drive profile uses this.
    Axes come back as None when the table does not define them.
    """
    xml = xml or os.path.join(work_dir(), "ecu_defs.xml")
    rom = rom or os.path.join(work_dir(), "rom", xmlid + ".bin")
    roms = load_roms(xml)
    if xmlid not in roms:
        raise KeyError("no such calibration: %s" % xmlid)
    info = resolve(roms, xmlid, want)
    if not info:
        raise KeyError("table not found: %s" % want)
    a = info["attrib"]
    if not a.get("storageaddress"):
        raise KeyError("%s is not located in %s" % (want, xmlid))

    data = open(rom, "rb").read()
    addr = int(a["storageaddress"], 16)
    stype = a.get("storagetype", "uint16")
    endian = a.get("endian", "big")
    expr = (info["scaling"] or {}).get("expression")
    nx = int(a.get("sizex") or 1)
    ny = int(a.get("sizey") or 1)
    _fmt, size = FMT[(stype, endian)]

    def axis(spec, n):
        if not spec or not spec["attrib"].get("storageaddress"):
            return None
        at = spec["attrib"]
        sc = spec["scaling"] or {}
        st = at.get("storagetype", "float")
        dec = at.get("endian", "little")
        v = read_series(data, int(at["storageaddress"], 16), n, st, dec,
                        sc.get("expression"))
        if not plausible(v):
            alt = read_series(data, int(at["storageaddress"], 16), n, st,
                              "big" if dec == "little" else "little",
                              sc.get("expression"))
            if plausible(alt):
                v = alt
        return v

    grid = [read_series(data, addr + r * nx * size, nx, stype, endian, expr)
            for r in range(ny)]
    meta = {"address": addr, "sizex": nx, "sizey": ny, "expression": expr,
            "units": (info["scaling"] or {}).get("units", ""),
            "description": info["description"]}
    return axis(info["axes"].get("X Axis"), nx), \
        axis(info["axes"].get("Y Axis"), ny), grid, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xmlid")
    ap.add_argument("table", nargs="?")
    ap.add_argument("--xml", default=os.path.join(work_dir(), "ecu_defs.xml"))
    ap.add_argument("--rom", default=None)
    ap.add_argument("--grep", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    roms = load_roms(args.xml)
    if args.xmlid not in roms:
        print("no such calibration: %s" % args.xmlid)
        return 1

    if args.list:
        names = []
        cur, seen = args.xmlid, set()
        while cur and cur in roms and cur not in seen:
            seen.add(cur)
            for t in roms[cur].findall("table"):
                n = t.get("name") or ""
                if t.get("storageaddress") and args.grep.lower() in n.lower():
                    names.append((n, t.get("storageaddress")))
            cur = roms[cur].get("base")
        for n, a in sorted(set(names)):
            print("  %-10s %s" % (a, n))
        print("\n%d located tables match %r" % (len(set(names)), args.grep))
        return 0

    rom = args.rom or os.path.join(work_dir(), "rom", args.xmlid + ".bin")
    data = open(rom, "rb").read()

    info = resolve(roms, args.xmlid, args.table)
    if not info:
        print("table not found: %s" % args.table)
        return 1
    a = info["attrib"]
    if not a.get("storageaddress"):
        print("table has no address in %s - not located for this calibration"
              % args.xmlid)
        return 1

    addr = int(a["storageaddress"], 16)
    stype = a.get("storagetype", "uint16")
    endian = a.get("endian", "big")
    expr = (info["scaling"] or {}).get("expression")
    units = (info["scaling"] or {}).get("units", "")
    nx = int(a.get("sizex") or 1)
    ny = int(a.get("sizey") or 1)

    print("=== %s ===" % args.table)
    print("ROM        %s" % os.path.basename(rom))
    print("address    0x%X   %s %s   %dx%d" % (addr, stype, endian, nx, ny))
    print("scaling    %s      units: %s" % (expr, units))
    if info["description"]:
        print("\n%s\n" % info["description"])

    ax = info["axes"].get("X Axis")
    ay = info["axes"].get("Y Axis")

    def axis_vals(spec, n):
        if not spec or not spec["attrib"].get("storageaddress"):
            return None, ""
        at = spec["attrib"]
        sc = spec["scaling"] or {}
        stype_ax = at.get("storagetype", "float")
        declared = at.get("endian", "little")
        vals = read_series(data, int(at["storageaddress"], 16), n, stype_ax,
                           declared, sc.get("expression"))
        if not plausible(vals):
            other = "big" if declared == "little" else "little"
            flipped = read_series(data, int(at["storageaddress"], 16), n,
                                  stype_ax, other, sc.get("expression"))
            if plausible(flipped):
                vals = flipped
        return vals, sc.get("units", "")

    xv, xu = axis_vals(ax, nx)
    yv, yu = axis_vals(ay, ny)

    fmt, size = FMT[(stype, endian)]
    grid = []
    for r in range(ny):
        row = read_series(data, addr + r * nx * size, nx, stype, endian, expr)
        grid.append(row)

    xname = (ax or {}).get("attrib", {}).get("name", "X")
    yname = (ay or {}).get("attrib", {}).get("name", "Y")
    print("%s ->  %s" % (xname, xu))
    hdr = "%9s" % (yname[:9])
    for j in range(nx):
        hdr += "%8s" % (("%.5g" % xv[j]) if xv else j)
    print(hdr)
    for r in range(ny):
        line = "%9s" % (("%.5g" % yv[r]) if yv else r)
        for v in grid[r]:
            line += "%8.1f" % v
        print(line)
    print("\n(%s in %s)" % (yname, yu))

    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("," + ",".join("%.6g" % v for v in (xv or range(nx))) + "\n")
            for r in range(ny):
                fh.write("%.6g," % (yv[r] if yv else r))
                fh.write(",".join("%.6g" % v for v in grid[r]) + "\n")
        print("-> %s" % args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
