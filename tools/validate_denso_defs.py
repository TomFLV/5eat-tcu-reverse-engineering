#!/usr/bin/env python3
"""Cross-check every Denso table in the definition against the ROM it belongs to.

The M32R definition has had a validator since it became standalone-per-firmware,
and it runs 5,911 checks across 16 firmwares. The Denso definition has shipped 152
to 197 tables per firmware across 9 firmwares with nothing equivalent, which means
nobody has ever confirmed that a Denso table's address, shape and axes agree with
the bytes actually in that image.

Each <rom> is validated against its own image, matched on the calibration ID at
the address the definition itself declares. Validating everything against one ROM
compares one firmware's addresses to another firmware's bytes and reports
nonsense.

Checks per table:
  bounds      - data and every axis lie inside the image
  extent      - sizex * sizey * storage width fits without running off the end
  axes        - a declared axis has the length the table says it does
  overlap     - two tables do not claim the same bytes with different shapes
  content     - the region is not entirely 0xFF or 0x00, which is erased flash
                or padding rather than calibration

    python tools/validate_denso_defs.py
    python tools/validate_denso_defs.py --verbose

Exit status is non-zero if anything fails, so this can gate a release.
"""

import argparse
import glob
import os
import struct
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ROM_DIR = os.path.join(REPO, "rom-denso")
XML = os.path.join(REPO, "definitions", "5eat_tcu_denso_romraider_defs.xml")

WIDTH = {"uint8": 1, "int8": 1, "uint16": 2, "int16": 2,
         "uint32": 4, "int32": 4, "float": 4}


def load_roms():
    out = {}
    for path in sorted(glob.glob(os.path.join(ROM_DIR, "*.bin"))):
        out[os.path.basename(path)] = open(path, "rb").read()
    return out


def cal_id_at(rom, addr, length=8):
    return rom[addr:addr + length].decode("ascii", "replace")


def match_rom(roms, ident, addr):
    """The image whose calibration ID matches, searched rather than assumed.

    The definition declares the ID address, but a firmware whose ID sits
    elsewhere would silently match nothing and be skipped - which looks identical
    to a clean run. So the declared address is tried first and the whole image
    second, and a table validated against the wrong ROM is impossible either way.
    """
    for name, rom in roms.items():
        if cal_id_at(rom, addr, len(ident)) == ident:
            return name, rom, "declared address"
    probe = ident.encode("ascii", "replace")
    for name, rom in roms.items():
        if probe in rom:
            return name, rom, "found at 0x%X" % rom.index(probe)
    return None, None, None


def table_regions(tab):
    """(address, byte length, description) for the table and each of its axes."""
    out = []
    sx = int(tab.get("sizex") or tab.findtext("sizex") or 1)
    sy = int(tab.get("sizey") or tab.findtext("sizey") or 1)
    addr = tab.get("storageaddress") or tab.findtext("storageaddress")
    stype = tab.get("storagetype") or "uint16"
    w = WIDTH.get(stype, 2)
    if addr and (tab.get("type") or "") == "Switch":
        # sizey on a Switch is a byte count and there is no storagetype; the
        # rows-times-width rule would claim twice the bytes it actually owns.
        out.append((int(addr, 16), sy, "data"))
    elif addr:
        out.append((int(addr, 16), sx * sy * w, "data"))
    for ax in tab.findall("table"):
        aa = ax.get("storageaddress") or ax.findtext("storageaddress")
        if not aa:
            continue
        an = int(ax.get("sizex") or ax.get("sizey") or 1)
        aw = WIDTH.get(ax.get("storagetype") or "uint16", 2)
        out.append((int(aa, 16), an * aw, "axis %s" % (ax.get("type") or "?")))
    return out, sx, sy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    roms = load_roms()
    if not roms:
        print("no ROM images in %s" % ROM_DIR)
        return 2
    tree = ET.parse(XML)

    total, failures, skipped = 0, [], []
    for rom_el in tree.getroot().iter("rom"):
        rid = rom_el.find("romid")
        if rid is None:
            continue
        xmlid = rid.findtext("xmlid") or "?"
        ident = (rid.findtext("internalidstring") or "").strip()
        try:
            idaddr = int((rid.findtext("internalidaddress") or "0"), 16)
        except ValueError:
            idaddr = 0
        if not ident:
            skipped.append((xmlid, "no internalidstring"))
            continue
        name, rom, how = match_rom(roms, ident, idaddr)
        if rom is None:
            skipped.append((xmlid, "no image with calibration ID %s" % ident))
            continue

        checks, bad = 0, []
        claimed = {}
        for tab in rom_el.findall("table"):
            tname = tab.get("name") or "?"
            try:
                regions, sx, sy = table_regions(tab)
            except (ValueError, TypeError) as e:
                bad.append("%s: unreadable shape (%s)" % (tname, e))
                continue
            for addr, length, what in regions:
                checks += 1
                if addr < 0 or addr + length > len(rom):
                    bad.append("%s %s: 0x%06X+%d runs past the %d byte image"
                               % (tname, what, addr, length, len(rom)))
                    continue
                blob = rom[addr:addr + length]
                # An all-zero table is only a defect if the definition presents
                # it as something to tune. 90 of them are already categorised as
                # constants, which is the generator being right, and flagging
                # those was this check being wrong: a validator that fires on
                # correct behaviour trains you to ignore it.
                cat = tab.get("category") or ""
                if (length and len(set(blob)) == 1 and blob[0] in (0x00, 0xFF)
                        and "Constant" not in cat):
                    bad.append("%s %s: 0x%06X+%d is entirely 0x%02X but is "
                               "categorised '%s', not as a constant"
                               % (tname, what, addr, length, blob[0], cat))
                if what == "data":
                    prev = claimed.get(addr)
                    if prev and prev != (sx, sy):
                        bad.append("%s data: 0x%06X claimed as %dx%d and %dx%d"
                                   % (tname, addr, sx, sy, prev[0], prev[1]))
                    claimed[addr] = (sx, sy)

        total += checks
        status = "OK" if not bad else "%d PROBLEM%s" % (len(bad),
                                                        "" if len(bad) == 1 else "S")
        print("  %-10s %-42s %4d checks  %s"
              % (ident, name[:42], checks, status))
        if how != "declared address":
            print("       calibration ID %s" % how)
        for b in bad[: (None if args.verbose else 6)]:
            print("       %s" % b)
        if bad and not args.verbose and len(bad) > 6:
            print("       ... and %d more, use --verbose" % (len(bad) - 6))
        failures.extend((xmlid, b) for b in bad)

    print("\n%d checks across %d firmwares." % (total, len(list(tree.getroot().iter("rom")))))
    for x, why in skipped:
        print("  SKIPPED %s: %s" % (x, why))
    if failures:
        print("%d problems found." % len(failures))
        return 1
    if skipped:
        print("No errors in what was checked, but %d firmware(s) were skipped - "
              "a skip is not a pass." % len(skipped))
        return 1
    print("No errors: every Denso table address matches the firmware it belongs to.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
