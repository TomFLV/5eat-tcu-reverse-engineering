import os
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
ROM_PATH = os.path.join(_ROOT, "rom", "91D1206000_5EAT.bin")

import struct

path = ROM_PATH
data = open(path, "rb").read()
size = len(data)

def scan_arith(width, signed, endian, min_run=6, region=(0, size)):
    """Find runs of constant-delta arithmetic progressions."""
    fmt_char = {1: 'b' if signed else 'B', 2: 'h' if signed else 'H', 4: 'i' if signed else 'I'}[width]
    fmt = ('>' if endian == 'big' else '<') + fmt_char
    start, end = region
    n = (end - start) // width
    vals = struct.unpack(fmt + str(n)[:0] , b'') if False else None
    vals = list(struct.unpack(f"{('>' if endian=='big' else '<')}{n}{fmt_char}", data[start:start+n*width]))
    results = []
    i = 0
    while i < len(vals) - 1:
        delta = vals[i+1] - vals[i]
        if delta == 0:
            i += 1
            continue
        j = i + 1
        while j < len(vals) - 1 and vals[j+1] - vals[j] == delta:
            j += 1
        run_len = j - i + 1
        if run_len >= min_run:
            off = start + i * width
            results.append((off, run_len, delta, vals[i], vals[j]))
        i = j if j > i else i + 1
    return results

print("=== 16-bit BE unsigned arithmetic runs (min 6) ===")
for off, run_len, delta, v0, v1 in scan_arith(2, False, 'big', min_run=6):
    print(f"0x{off:06X}  len={run_len:3d}  delta={delta:6d}  {v0} -> {v1}")
