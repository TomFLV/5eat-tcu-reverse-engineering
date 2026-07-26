import os
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
ROM_PATH = os.path.join(_ROOT, "rom", "91D1206000_5EAT.bin")

import struct

path = ROM_PATH
data = open(path, "rb").read()
size = len(data)

def u16(off):
    return struct.unpack(">H", data[off:off+2])[0]

def is_monotonic(vals):
    if len(vals) < 3:
        return False
    incs = all(b > a for a, b in zip(vals, vals[1:]))
    decs = all(b < a for a, b in zip(vals, vals[1:]))
    return incs or decs

# ---- 1. Find [count][N monotonic u16 axis] candidate tables ----
candidates = []
for off in range(0, size - 4, 2):
    n = u16(off)
    if not (3 <= n <= 24):
        continue
    end = off + 2 + 2*n
    if end + 2*n > size:
        continue
    axis = [u16(off + 2 + 2*i) for i in range(n)]
    if not is_monotonic(axis):
        continue
    data_row = [u16(end + 2*i) for i in range(n)]
    candidates.append((off, n, axis, data_row))

print(f"Found {len(candidates)} candidate [count+axis+datarow] tables")

# ---- 2. Scan for 32-bit BE pointers referencing candidate table headers ----
header_offsets = {c[0] for c in candidates}
ptr_refs = {}
for off in range(0, size - 4):
    val = struct.unpack(">I", data[off:off+4])[0]
    if val in header_offsets:
        ptr_refs.setdefault(val, []).append(off)

print(f"\n{len(ptr_refs)} of those table headers are referenced by >=1 absolute 32-bit pointer elsewhere in the ROM")

# ---- 3. Print a catalog sorted by file offset ----
out_lines = []
out_lines.append(f"5EAT TCU ROM ({path})")
out_lines.append(f"Size: {size} (0x{size:X}) bytes\n")
out_lines.append("Candidate calibration tables: [count N][N-pt monotonic BE16 axis][N BE16 data values]")
out_lines.append("=" * 100)

for off, n, axis, row in sorted(candidates, key=lambda c: c[0]):
    refs = ptr_refs.get(off, [])
    ref_str = f"  <- referenced by {len(refs)} pointer(s) at " + ",".join(f"0x{r:06X}" for r in refs[:6]) if refs else ""
    out_lines.append(
        f"0x{off:06X}  n={n:2d}  axis[{axis[0]}..{axis[-1]}]={axis}  data={row}{ref_str}"
    )

report = "\n".join(out_lines)
outpath = os.path.join(_ROOT, "table_catalog.txt")
open(outpath, "w").write(report)
print(f"\nWrote full catalog to {outpath}")

# quick stats
referenced = sum(1 for off,_,_,_ in candidates if off in ptr_refs)
print(f"\n{referenced}/{len(candidates)} candidate tables have at least one pointer reference (higher confidence these are real tables, not coincidence)")
