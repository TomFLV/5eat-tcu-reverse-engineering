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
                x_axis = t.find("./table[@type='X Axis']")
                if x_axis is None:
                    errors.append(f"{name}: missing X Axis")
                    continue
                x_addr = int(x_axis.get("storageaddress"), 16)
                skip = int(t.get("skipCells", "0"))

                if skip:
                    # A strided 2D table reads its axis and its data out of the
                    # same record array, so there is no count field in front of
                    # the axis and the data does not follow it. What can be checked
                    # is that the record array ends where the row count says it
                    # does: skipCells=3 is one value per 8-byte record, and the
                    # axis sits at the first field of the first record.
                    rows = int(t.get("sizey") or t.get("sizex"))
                    stride = (skip + 1) * 2
                    checked += 1
                    term = u16(x_addr + rows * stride)
                    if term != 0xFFFF:
                        errors.append(
                            f"{name}: strided 2D table, no 0xFFFF terminator after "
                            f"{rows} records at 0x{x_addr + rows * stride:06X} "
                            f"(found 0x{term:04X})")
                    checked += 1
                    if addr <= x_addr or addr - x_addr >= stride:
                        errors.append(
                            f"{name}: data 0x{addr:06X} is not a field of the same "
                            f"record as the axis at 0x{x_addr:06X} (stride {stride})")
                elif name == "ATF Blend Window":
                    # Not a count-prefixed array: two standalone bytes that all seven
                    # solenoid drivers read as a temperature window. Its geometry
                    # check is therefore meaningless; check the CONTENT instead,
                    # which is what would actually be wrong if the address slipped.
                    lo, hi = data[addr], data[addr + 1]
                    checked += 1
                    if not lo < hi:
                        errors.append(f"{name}: window not ascending "
                                      f"({lo - 40} C, {hi - 40} C)")
                    checked += 1
                    if not (-40 <= lo - 40 <= 60 and 60 <= hi - 40 <= 180):
                        errors.append(f"{name}: implausible window "
                                      f"{lo - 40} C .. {hi - 40} C")
                else:
                    sizex = int(t.get("sizex"))
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
                skip = int(t.get("skipCells", "0"))
                cell_map = t.get("cellIndices")
                if cell_map:
                    # A sparse table addresses every cell explicitly, so there is no
                    # geometry to check. What matters is that the map is well formed:
                    # the right number of entries, every real index inside the ROM,
                    # and no two cells claiming the same bytes - an alias would mean
                    # editing one cell silently changed another.
                    idx = [int(v) for v in cell_map.split(",")]
                    checked += 1
                    if len(idx) != sx * sy:
                        errors.append(f"{name}: cellIndices has {len(idx)} entries, "
                                      f"expected sizex*sizey = {sx * sy}")
                    real = [v for v in idx if v >= 0]
                    checked += 1
                    oob = [v for v in real if addr + v * 2 + 2 > len(data)]
                    if oob:
                        errors.append(f"{name}: {len(oob)} cell(s) point past the "
                                      f"end of the ROM")
                    checked += 1
                    if len(set(real)) != len(real):
                        errors.append(f"{name}: cellIndices contains duplicates - "
                                      f"{len(real) - len(set(real))} cell(s) alias "
                                      f"the same ROM bytes")
                    continue
                checked += 1
                if skip and not (sx == 1 and skip == 1):
                    # Strided 3D: cells = sx*sy values taken at (skip+1) uint16
                    # intervals. Used for the shift curves, which are sizex=rows,
                    # sizey=1, swapxy so that every cell is last-in-row and the
                    # stride therefore applies to all of them. The table may start
                    # at field 0 or field 1 of the first record, so accept either.
                    records = sx * sy
                    stride = (skip + 1) * 2
                    checked += 1
                    if not any(u16(b + records * stride) == 0xFFFF
                               for b in (addr, addr - 2)):
                        errors.append(
                            f"{name}: strided 3D table, no 0xFFFF terminator after "
                            f"{records} records at 0x{addr + records * stride:06X} "
                            f"or 0x{addr - 2 + records * stride:06X}")
                elif (sx == 1 and skip == 1
                      and (t.get("name") or "").startswith("Downshift Ramp")):
                    # The ramp parameters are a fixed array of {step, duration}
                    # structs, one per downshift - not a terminated record array,
                    # so there is no 0xFFFF to look for. Check instead that every
                    # entry is readable and that the block is not obviously the
                    # wrong address: a run of all zeros or a 0xFFFF sentinel would
                    # mean we are reading past the array rather than inside it.
                    checked += 1
                    vals = [u16(addr + i * 4) for i in range(sy)]
                    if any(v is None for v in vals):
                        errors.append(f"{name}: runs past the end of the ROM")
                    elif all(v == 0 for v in vals):
                        errors.append(f"{name}: every entry is zero, so 0x{addr:06X} "
                                      f"is probably not the ramp array")
                    elif any(v == 0xFFFF for v in vals):
                        errors.append(f"{name}: contains a 0xFFFF terminator, so it "
                                      f"reads past the end of the array")

                elif sx == 1 and skip == 1:
                    # One quantity pulled out of a record array with a stride of
                    # two uint16. Two record geometries use that same stride and
                    # cannot be told apart from sizex/skipCells alone:
                    #
                    #   8-byte records (shift schedule, hysteresis curves)
                    #     4 x uint16, two of them this quantity, so sizey counts
                    #     vertices - two per record - and the array ends with a
                    #     leading 0xFFFF.
                    #   4-byte records (line pressure curves)
                    #     2 x uint16, one of them this quantity, so sizey IS the
                    #     record count, and the array ends with a 0xFF00
                    #     breakpoint rather than 0xFFFF.
                    #
                    # The table also starts at field 0 or field 1 of the first
                    # record, and which one is not recoverable from the address
                    # because record arrays are not 8-aligned (0x00807E is a real
                    # one). So try every consistent reading and accept if any one
                    # of them lands on a real terminator.
                    ok = False
                    for start in (addr, addr - 2):
                        if u16(start + (sy // 2) * 8) == 0xFFFF:      # 8-byte
                            ok = True
                        if u16(start + (sy - 1) * 4) == 0xFF00:       # 4-byte
                            ok = True
                    if not ok:
                        errors.append(
                            f"{name}: no record-array terminator found - "
                            f"neither 0xFFFF after {sy // 2} eight-byte records "
                            f"nor 0xFF00 at record {sy} of a four-byte array")
                else:
                    term = u16(addr + sy * sx * 2)
                    if term != 0xFFFF:
                        errors.append(
                            f"{name}: no 0xFFFF terminator after {sy} rows "
                            f"(found {term})")

            else:  # 1D / Switch
                checked += 1
                if addr >= len(data):
                    errors.append(f"{name}: address 0x{addr:06X} beyond end of ROM")

                if t.get("category") == "Transmission - Diagnostic Codes":
                    # Each DTC is its own switch, so the strongest check is that the
                    # bytes it calls "Enabled" are the bytes actually in the ROM at
                    # its address, and that they decode to the P-code in its name.
                    # A switch pointing at the wrong slot would look perfectly fine
                    # and would silently blank a DIFFERENT code when set to Disabled.
                    checked += 1
                    stored = u16(addr)
                    declared = None
                    for state in t.findall("state"):
                        if state.get("name") == "Enabled":
                            declared = int(state.get("data", "0").replace(" ", ""), 16)
                    if declared is None:
                        errors.append(f"{name}: switch has no Enabled state")
                    elif declared != stored:
                        errors.append(
                            f"{name}: Enabled state is 0x{declared:04X} but the ROM "
                            f"holds 0x{stored:04X} at 0x{addr:06X}")
                    elif f"P{stored:04X}" != name:
                        errors.append(
                            f"{name}: named for a different code than it stores "
                            f"(0x{stored:04X} would be P{stored:04X})")

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
