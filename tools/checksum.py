"""
5EAT TCU ROM checksum: 32-bit big-endian two's-complement additive checksum.

Two 4-byte slots, at file offsets 0x008000 and 0x008004, hold an identical
checksum value C such that summing every OTHER 32-bit big-endian word in the
checksummed region and adding C once yields 0 (mod 2^32). Both slots must be
updated together (redundant storage) after any edit to the ROM.

The checksummed region is NOT always the whole file, and not always the same
length. Both conventions occur in the wild across this TCU family:

  * 0x60000 (384 KB) -- every 384 KB image, and 512 KB images that carry a
    384 KB payload with the trailing 128 KB left as blank 0xFF flash
    (e.g. 91FE216300, the 05-06 USDM Outback XT).
  * whole file -- 512 KB images that genuinely populate all 512 KB
    (e.g. ACD1A06000, AC91207000/ACD1207000, ADE0236000 -- the later
    MB558xx / MB562xx calibrations).

Assuming either one produces a confidently wrong answer on half the family,
so the region is DETECTED per image: whichever candidate reproduces the value
the ROM already stores is the convention that ROM uses. Verified against 12
real images.
"""
import struct

CHECKSUM_OFFSET_1 = 0x008000
CHECKSUM_OFFSET_2 = 0x008004

# Candidate region ends, tried in order.
CHECKSUM_REGIONS = (0x60000, None)      # None == whole file


def _sum_region(data: bytes, end: int) -> int:
    dwords = struct.unpack(f">{end // 4}I", data[:end])
    total = sum(dwords) & 0xFFFFFFFF
    c1 = dwords[CHECKSUM_OFFSET_1 // 4]
    c2 = dwords[CHECKSUM_OFFSET_2 // 4]
    return (-(total - c1 - c2)) & 0xFFFFFFFF


def _stored(data: bytes):
    a = struct.unpack(">I", data[CHECKSUM_OFFSET_1:CHECKSUM_OFFSET_1 + 4])[0]
    b = struct.unpack(">I", data[CHECKSUM_OFFSET_2:CHECKSUM_OFFSET_2 + 4])[0]
    return a, b


def _candidates(size: int):
    seen = []
    for r in CHECKSUM_REGIONS:
        end = size if r is None else min(r, size)
        if end > CHECKSUM_OFFSET_2 and end % 4 == 0 and end not in seen:
            seen.append(end)
    return seen


def detect_region(data: bytes):
    """
    Return the region end this image's stored checksum was computed over, or
    None if neither candidate reproduces it (i.e. the ROM is already modified).
    """
    stored, stored2 = _stored(data)
    if stored != stored2:
        return None
    for end in _candidates(len(data)):
        if _sum_region(data, end) == stored:
            return end
    return None


def choose_region(data: bytes) -> int:
    """
    Region to use when writing. Prefer the one the ROM already uses; if the
    checksum is already broken, fall back on whether the tail past 0x60000 is
    unprogrammed -- blank tail means the payload is 384 KB.
    """
    end = detect_region(data)
    if end is not None:
        return end
    size = len(data)
    if size > 0x60000 and set(data[0x60000:]) <= {0xFF}:
        return 0x60000
    return size


def compute_checksum(data: bytes, end: int = None) -> int:
    """Return the correct checksum value for this ROM image."""
    size = len(data)
    assert size % 4 == 0, "ROM size must be a multiple of 4 bytes"
    if end is None:
        end = choose_region(data)
    assert end > CHECKSUM_OFFSET_2, "ROM is too small to contain the checksum slots"
    return _sum_region(data, end)


def verify_checksum(data: bytes) -> bool:
    stored, stored2 = _stored(data)
    if stored != stored2:
        return False
    return detect_region(data) is not None


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

    region = choose_region(data)
    detected = detect_region(data) is not None

    if not args.fix:
        print(f"stored   0x{stored:08X}" + ("" if stored == stored2 else
              f" / 0x{stored2:08X}  (slots DISAGREE)"))
        print(f"expected 0x{expected:08X}")
        print(f"region   0x000000-0x{region:06X}"
              + ("  (detected)" if detected else "  (inferred - checksum already invalid)"))
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
