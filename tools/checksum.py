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

SOME IMAGES CARRY A SECOND, INDEPENDENT CHECKSUM -- a 'balance' word at
0x008020, chosen so that every 32-bit big-endian word from 0x008020 to the end
of the image sums to the constant 0x5AA5A55A. This is the same scheme FastECU
applies in its Hitachi M32R TCU module, and the same constant Denso TCU images
use for their block integrity table.

It is NOT universal, and applying it unconditionally does damage. Of the eleven
images in this repository only three carry it -- ADE0236000, ACD1207000 and
ACD1A06000. On the other eight, no region anywhere in the file sums to that
constant (two have no candidate region at all), and 0x008020 instead holds a
small unrelated value that a balance write would destroy.

So the balance is maintained only for images that demonstrably use it. The test
is exact on an unmodified image -- the region already sums to the constant --
and is backed by a structural one for images edited since loading: a real
balance is a full-width word, whereas the images that do not use the checksum
hold well under 0x10000 there.

Order matters when writing. The balance sits inside the region the additive
checksum covers, but the additive slots at 0x008000 and 0x008004 sit below
0x008020 and so fall outside the balance region. Fixing the balance first and
the additive checksum second therefore converges in a single pass.
"""
import struct

CHECKSUM_OFFSET_1 = 0x008000
CHECKSUM_OFFSET_2 = 0x008004

# Candidate region ends, tried in order.
CHECKSUM_REGIONS = (0x60000, None)      # None == whole file

# Second checksum: the balance word, and the constant its region must sum to.
BALANCE_OFFSET = 0x008020
BALANCE_TARGET = 0x5AA5A55A


def _sum_from(data: bytes, start: int) -> int:
    """Sum of every whole big-endian word from `start` to the end of the image."""
    n = (len(data) - start) // 4
    return sum(struct.unpack(f">{n}I", data[start:start + n * 4])) & 0xFFFFFFFF


def balance_holds(data: bytes) -> bool:
    """Does the balance region already sum to the constant?"""
    return _sum_from(data, BALANCE_OFFSET) == BALANCE_TARGET


def uses_balance(data: bytes) -> bool:
    """Whether this image carries the balance checksum at all."""
    if len(data) <= BALANCE_OFFSET + 4:
        return False
    stored = struct.unpack(">I", data[BALANCE_OFFSET:BALANCE_OFFSET + 4])[0]
    return balance_holds(data) or stored > 0xFFFF


def compute_balance(data: bytes) -> int:
    """The value 0x008020 must hold for its region to reach the constant."""
    stored = struct.unpack(">I", data[BALANCE_OFFSET:BALANCE_OFFSET + 4])[0]
    without = (_sum_from(data, BALANCE_OFFSET) - stored) & 0xFFFFFFFF
    return (BALANCE_TARGET - without) & 0xFFFFFFFF


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
    if detect_region(data) is None:
        return False
    if uses_balance(data) and not balance_holds(data):
        return False
    return True


def fix_checksum(data: bytes) -> bytes:
    """Return a copy of data with every checksum this image carries corrected."""
    data = bytearray(data)

    # Balance first: it lives inside the region the additive checksum covers, so
    # writing it afterwards would invalidate the value just computed.
    if uses_balance(bytes(data)):
        b = compute_balance(bytes(data))
        data[BALANCE_OFFSET:BALANCE_OFFSET + 4] = struct.pack(">I", b)

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
        if uses_balance(data):
            bal = struct.unpack(">I", data[BALANCE_OFFSET:BALANCE_OFFSET + 4])[0]
            print(f"balance  0x{bal:08X} at 0x{BALANCE_OFFSET:06X}, expected "
                  f"0x{compute_balance(data):08X}"
                  + ("  OK" if balance_holds(data) else "  BAD"))
        else:
            print(f"balance  not used by this image "
                  f"(0x{BALANCE_OFFSET:06X} is not a checksum balance here)")
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
