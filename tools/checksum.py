"""
5EAT TCU ROM checksum: 32-bit big-endian two's-complement additive checksum.

Two 4-byte slots, at file offsets 0x008000 and 0x008004, hold an identical
checksum value C such that summing every OTHER 32-bit big-endian word in the
ROM and adding C once yields 0 (mod 2^32). Both slots must be updated
together (redundant storage) after any edit to the ROM.
"""
import struct

CHECKSUM_OFFSET_1 = 0x008000
CHECKSUM_OFFSET_2 = 0x008004


def compute_checksum(data: bytes) -> int:
    """Return the correct checksum value for this ROM image."""
    size = len(data)
    assert size % 4 == 0, "ROM size must be a multiple of 4 bytes"
    dwords = struct.unpack(f">{size // 4}I", data)
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
