import os
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
ROM_PATH = os.path.join(_ROOT, "rom", "91D1206000_5EAT.bin")

import struct, zlib

path = ROM_PATH
data = open(path, "rb").read()
size = len(data)

TARGET = 0x2668221C
TARGET_SWAP = 0x1C226826  # byte-swapped, in case it's little-endian somewhere
TARGET_HALVES = (0x2668, 0x221C)  # in case it's two independent 16-bit checksums

# candidate byte ranges to sum over (start, end) -- end exclusive
candidates = [
    ("whole file",                 0x000000, size),
    ("before checksum (boot blk)", 0x000000, 0x008000),
    ("before checksum, minus vec", 0x000200, 0x008000),
    ("after checksum to end",      0x008008, size),
    ("after checksum to cal-end",  0x008008, 0x01D200),
    ("after ID block to cal-end",  0x008032, 0x01D200),
    ("cal region incl header",     0x008000, 0x01D200),
    ("cal region to code start",  0x008000, 0x020000),
    ("whole file minus checksum",  0x008008, size),  # dup, kept for clarity
    ("code region only",           0x020000, 0x05F600),
    ("vector table only",          0x000000, 0x000200),
]

def sums(chunk):
    n = len(chunk)
    byte_sum = sum(chunk) & 0xFFFFFFFF
    byte_sum16 = sum(chunk) & 0xFFFF
    byte_xor = 0
    for b in chunk:
        byte_xor ^= b

    # pad to even/multiple of 4 for word sums
    padded2 = chunk if n % 2 == 0 else chunk + b"\x00"
    words = struct.unpack(f">{len(padded2)//2}H", padded2)
    word_sum32 = sum(words) & 0xFFFFFFFF
    word_sum16 = sum(words) & 0xFFFF
    word_xor = 0
    for w in words:
        word_xor ^= w

    padded4 = chunk + b"\x00" * ((-n) % 4)
    dwords = struct.unpack(f">{len(padded4)//4}I", padded4)
    dword_sum32 = sum(dwords) & 0xFFFFFFFF

    ones_comp = 0
    for w in words:
        ones_comp += w
        ones_comp = (ones_comp & 0xFFFF) + (ones_comp >> 16)
    ones_comp_final = (~ones_comp) & 0xFFFF

    crc32 = zlib.crc32(chunk) & 0xFFFFFFFF

    return {
        "byte_sum32": byte_sum,
        "byte_sum16": byte_sum16,
        "byte_xor": byte_xor,
        "word_sum32(BE16)": word_sum32,
        "word_sum16(BE16)": word_sum16,
        "word_xor(BE16)": word_xor,
        "dword_sum32(BE32)": dword_sum32,
        "ones_comp16": ones_comp_final,
        "neg_byte_sum32": (-byte_sum) & 0xFFFFFFFF,
        "neg_word_sum32": (-word_sum32) & 0xFFFFFFFF,
        "crc32": crc32,
    }

print(f"Target value: 0x{TARGET:08X}  (halves: 0x{TARGET_HALVES[0]:04X}, 0x{TARGET_HALVES[1]:04X})\n")

found_any = False
for name, start, end in candidates:
    chunk = data[start:end]
    results = sums(chunk)
    for algo, val in results.items():
        hit = ""
        if val == TARGET:
            hit = "  <<<< MATCH (full 32-bit)"
            found_any = True
        elif val == TARGET_SWAP:
            hit = "  <<<< MATCH (byte-swapped)"
            found_any = True
        elif val == TARGET_HALVES[0] or val == TARGET_HALVES[1]:
            hit = "  <<<< MATCH (half)"
            found_any = True
        elif (val & 0xFFFF) == TARGET_HALVES[1] or (val & 0xFFFF) == TARGET_HALVES[0]:
            hit = "  <<<< MATCH (low 16 bits)"
            found_any = True
        if hit:
            print(f"[{name}] 0x{start:06X}-0x{end:06X}  {algo} = 0x{val:X}{hit}")

if not found_any:
    print("No direct matches. Printing all computed values for manual inspection:\n")
    for name, start, end in candidates:
        chunk = data[start:end]
        results = sums(chunk)
        print(f"--- [{name}] 0x{start:06X}-0x{end:06X} (len=0x{end-start:X}) ---")
        for algo, val in results.items():
            print(f"    {algo:20s} = 0x{val:X}")
        print()
