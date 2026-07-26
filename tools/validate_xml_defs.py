import xml.etree.ElementTree as ET
import struct
import os

here = os.path.dirname(os.path.abspath(__file__))
rom_path = os.path.join(here, "..", "rom", "91D1206000_5EAT.bin")
xml_path = os.path.join(here, "..", "definitions", "5eat_tcu_romraider_defs.xml")

data = open(rom_path, "rb").read()

def u16(off):
    return struct.unpack(">H", data[off:off+2])[0]

tree = ET.parse(xml_path)
root = tree.getroot()

errors = []
checked = 0

for table in root.findall(".//table[@type='2D']"):
    name = table.get("name")
    sizex = int(table.get("sizex"))
    data_addr = int(table.get("storageaddress"), 16)  # data lives on the OUTER table now
    x_axis = table.find("./table[@type='X Axis']")
    if x_axis is None:
        errors.append(f"{name}: missing X Axis sub-table")
        continue
    x_addr = int(x_axis.get("storageaddress"), 16)

    # the header (count field) should sit exactly 2 bytes before the X axis address
    header_addr = x_addr - 2
    stored_count = u16(header_addr)
    checked += 1
    if stored_count != sizex:
        errors.append(f"{name}: header at 0x{header_addr:06X} says count={stored_count}, but sizex={sizex}")

    # the data address should be exactly x_addr + sizex*2
    expected_data = x_addr + sizex * 2
    checked += 1
    if data_addr != expected_data:
        errors.append(f"{name}: data address 0x{data_addr:06X} != expected 0x{expected_data:06X} (X axis + sizex*2)")

    axis_vals = [u16(x_addr + 2*i) for i in range(sizex)]
    data_vals = [u16(data_addr + 2*i) for i in range(sizex)]
    print(f"{name:35s} header=0x{header_addr:06X} X=0x{x_addr:06X} data=0x{data_addr:06X}  axis={axis_vals}  values={data_vals}")

n_tables = len(root.findall(".//table[@type=\"2D\"]"))
print(f"\nChecked {checked} address relationships across {n_tables} 2D tables.")

print()
for table in root.findall(".//table[@type='1D']"):
    name = table.get("name")
    addr = int(table.get("storageaddress"), 16)
    storagetype = table.get("storagetype")
    width = 1 if storagetype == "uint8" else 2
    if addr + width > len(data):
        errors.append(f"{name}: address 0x{addr:06X} out of ROM bounds")
        continue
    val = data[addr] if width == 1 else u16(addr)
    checked += 1
    print(f"{name:50s} addr=0x{addr:06X}  storagetype={storagetype}  value={val}")
if errors:
    print(f"\n{len(errors)} ERRORS FOUND:")
    for e in errors:
        print(" -", e)
else:
    print("\nNo errors found — every table's header count matches sizex, and every data address is exactly where it should be relative to the X-axis address.")
