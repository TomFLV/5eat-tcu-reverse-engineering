import os
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
ROM_PATH = os.path.join(_ROOT, "rom", "91D1206000_5EAT.bin")

import sys, string, math
from collections import Counter

path = ROM_PATH
data = open(path, "rb").read()
size = len(data)
print(f"File size: {size} (0x{size:X})")

# ---------- 1. Entropy map ----------
BLOCK = 256
print("\n--- Entropy map (block=256 bytes), showing low/high entropy regions ---")
def entropy(chunk):
    if not chunk:
        return 0.0
    c = Counter(chunk)
    n = len(chunk)
    return -sum((v/n) * math.log2(v/n) for v in c.values())

ent = []
for off in range(0, size, BLOCK):
    chunk = data[off:off+BLOCK]
    ent.append((off, entropy(chunk)))

# print a compact summary: runs of similar entropy bucket
def bucket(e):
    if e < 1.0: return "FLAT"      # constant/near-constant fill
    if e < 4.0: return "LOW"       # sparse tables, padding
    if e < 6.5: return "MID"       # tables/data
    return "HIGH"                  # code or dense data

prev_b = None
run_start = None
for off, e in ent:
    b = bucket(e)
    if b != prev_b:
        if prev_b is not None:
            print(f"0x{run_start:06X} - 0x{off-1:06X}  {prev_b:5s} (len 0x{off-run_start:X})")
        run_start = off
        prev_b = b
print(f"0x{run_start:06X} - 0x{size-1:06X}  {prev_b:5s} (len 0x{size-run_start:X})")
