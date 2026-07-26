"""
5EAT TCU ROM checksum: 32-bit big-endian two's-complement additive checksum.

Two 4-byte slots, at file offsets 0x008000 and 0x008004, hold an identical
checksum value C such that summing every OTHER 32-bit big-endian word in the
checksummed region and adding C once yields 0 (mod 2^32). Both slots must be
updated together (redundant storage) after any edit to the ROM.

The checksummed region is the first 0x60000 bytes (384 KB), NOT the whole
file. This matters for the 512 KB variant: on a 384 KB image the two are the
same thing, but a 512 KB image (M32176F4, e.g. the 05-06 USDM TCU) carries
384 KB of content plus 128 KB of blank 0xFF flash that is excluded from the
sum. Confirmed by solving for the range on a real 512 KB image
(91FE216300) — treating the whole file as the region gives a value exactly
0x80000 too high.
"""
import struct

CHECKSUM_OFFSET_1 = 0x008000
CHECKSUM_OFFSET_2 = 0x008004
CHECKSUM_REGION_END = 0x60000


def compute_checksum(data: bytes) -> int:
    """Return the correct checksum value for this ROM image."""
    size = len(data)
    assert size % 4 == 0, "ROM size must be a multiple of 4 bytes"
    end = min(CHECKSUM_REGION_END, size)
    assert end > CHECKSUM_OFFSET_2, "ROM is too small to contain the checksum slots"
    dwords = struct.unpack(f">{end // 4}I", data[:end])
    idx1 = CHECKSUM_OFFSET_1 // 4
    idx2 = CHECKSUM_OFFSET_2 // 4
    total = sum(dwords) & 0xFFFFFFFF
    c1 = dwords[idx1]
    c2 = dwords[idx2]
    s_excl = (total - c1 - c2) & 0xFFFFFFFF
    return (-s_excl) & 0xFFFFFFFF


def verify_checksum(data: bytes) -> bool:
    stored = struct.unpack(">I", data[CHECKSUM_OFFSET_1:CHECKSUM_OFFSET_1 + 4])[0]
    stored2 = struct.unpack(">I", data[CHECKSUM_OFFSET_2:CHECKSUM_OFFSET_2 + 4])[0]
    if stored != stored2:
        return False
    return compute_checksum(data) == stored


def fix_checksum(data: bytes) -> bytes:
    """Return a copy of data with both checksum slots corrected."""
    data = bytearray(data)
    c = compute_checksum(bytes(data))
    packed = struct.pack(">I", c)
    data[CHECKSUM_OFFSET_1:CHECKSUM_OFFSET_1 + 4] = packed
    data[CHECKSUM_OFFSET_2:CHECKSUM_OFFSET_2 + 4] = packed
    return bytes(data)


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Verify or correct the checksum of a 5EAT TCU ROM image.",
        epilog="RomRaider cannot fix this ROM's checksum. Run --fix after any edit, "
               "before flashing.",
    )
    parser.add_argument("rom", help="path to the ROM image")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verify", action="store_true",
                       help="check the stored checksum (default)")
    group.add_argument("--fix", action="store_true",
                       help="correct both checksum slots, writing in place unless -o is given")
    parser.add_argument("-o", "--output",
                        help="write the corrected image here instead of in place")
    args = parser.parse_args()

    data = open(args.rom, "rb").read()
    if len(data) % 4:
        sys.exit(f"error: {args.rom} is {len(data)} bytes, not a multiple of 4 — "
                 "this does not look like a valid ROM image")

    expected = compute_checksum(data)
    stored = struct.unpack(">I", data[CHECKSUM_OFFSET_1:CHECKSUM_OFFSET_1 + 4])[0]
    stored2 = struct.unpack(">I", data[CHECKSUM_OFFSET_2:CHECKSUM_OFFSET_2 + 4])[0]

    if not args.fix:
        print(f"stored   0x{stored:08X}" + ("" if stored == stored2 else
              f" / 0x{stored2:08X}  (slots DISAGREE)"))
        print(f"expected 0x{expected:08X}")
        if verify_checksum(data):
            print("OK — checksum is correct.")
            return 0
        print("BAD — checksum does not match. Re-run with --fix before flashing.")
        return 1

    if verify_checksum(data):
        print(f"Checksum already correct (0x{expected:08X}); nothing to do.")
        return 0

    out = args.output or args.rom
    open(out, "wb").write(fix_checksum(data))
    print(f"0x{stored:08X} -> 0x{expected:08X}  written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
