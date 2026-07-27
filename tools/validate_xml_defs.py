"""
Cross-check every table address in the definition against the ROM it belongs to.

Each <rom> block is validated against ITS OWN image, matched by the calibration
ID in <internalidstring>. Validating everything against one ROM would compare a
firmware's addresses to another firmware's bytes and report nonsense -- which is
exactly what happened when the definition first became standalone-per-firmware.

Checks per table:
  2D  - the count field the ROM stores at (X axis address - 2) equals sizex, and
        the data address is exactly X axis + sizex*2
  3D  - the 0xFFFF terminator falls exactly after sizey rows of sizex uint16
  1D  - the address is in bounds
"""
import xml.etree.ElementTree as ET
import struct
import os
import glob

here = os.path.dirname(os.path.abspath(__file__))
rom_dir = os.path.join(here, "..", "rom")
xml_path = os.path.join(here, "..", "definitions", "5eat_tcu_romraider_defs.xml")


def cal_id(rom_bytes):
    """The calibration ID string at 0x8008, as RomRaider matches on."""
    return rom_bytes[0x8008:0x8018].decode("ascii", "replace")


def load_roms():
    roms = {}
    for path in sorted(glob.glob(os.path.join(rom_dir, "*.bin"))):
        b = open(path, "rb").read()
        if len(b) > 0x8018:
            roms[cal_id(b)] = (os.path.basename(path), b)
    return roms


def main():
    roms = load_roms()
    root = ET.parse(xml_path).getroot()

    total_checked = 0
    total_errors = []
    unmatched = []

    for rom_el in root.findall("rom"):
        romid = rom_el.find("romid")
        want = romid.findtext("internalidstring")
        ecuid = romid.findtext("ecuid")

        match = next(((n, b) for cid, (n, b) in roms.items() if cid.startswith(want)), None)
        if match is None:
            unmatched.append(f"{ecuid} (cal ID {want}): no ROM in rom/ to validate against")
            continue
        rom_name, data = match

        def u16(off):
            if off + 2 > len(data):
                return None
            return struct.unpack(">H", data[off:off + 2])[0]

        errors = []
        checked = 0

        for t in rom_el.findall("table"):
            ttype = t.get("type")
            name = t.get("name")
            addr = t.get("storageaddress")
            if addr is None:
                continue
            addr = int(addr, 16)

            if ttype == "2D":
                sizex = int(t.get("sizex"))
                x_axis = t.find("./table[@type='X Axis']")
                if x_axis is None:
                    errors.append(f"{name}: missing X Axis")
                    continue
                x_addr = int(x_axis.get("storageaddress"), 16)
                checked += 1
                stored = u16(x_addr - 2)
                if stored != sizex:
                    errors.append(f"{name}: count at 0x{x_addr - 2:06X} is {stored}, sizex={sizex}")
                checked += 1
                if addr != x_addr + sizex * 2:
                    errors.append(f"{name}: data 0x{addr:06X} != X axis + sizex*2 "
                                  f"(0x{x_addr + sizex * 2:06X})")

            elif ttype == "3D":
                sx, sy = int(t.get("sizex")), int(t.get("sizey"))
                checked += 1
                term = u16(addr + sy * sx * 2)
                if term != 0xFFFF:
                    errors.append(f"{name}: no 0xFFFF terminator after {sy} rows "
                                  f"(found {term})")

            else:  # 1D / Switch
                checked += 1
                if addr >= len(data):
                    errors.append(f"{name}: address 0x{addr:06X} beyond end of ROM")

        status = "OK" if not errors else f"{len(errors)} ERROR(S)"
        print(f"  {ecuid:12s} {rom_name[:38]:40s} {checked:4d} checks  {status}")
        for e in errors:
            print(f"       - {e}")
        total_checked += checked
        total_errors += errors

    print(f"\n{total_checked} checks across {len(root.findall('rom'))} firmwares.")
    for u in unmatched:
        print(f"  note: {u}")
    if total_errors:
        print(f"{len(total_errors)} ERROR(S) FOUND")
        return 1
    print("No errors: every table address matches the firmware it belongs to.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
