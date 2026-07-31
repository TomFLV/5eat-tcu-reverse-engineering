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

EVERY IMAGE IN THIS FAMILY CARRIES A SECOND, INDEPENDENT CHECKSUM -- a 'balance'
at 0x008020. The firmware's own routine, which is what settles the details,
decompiles to:

    for (p = 0x8000; p < end; p++)
        if (p < 0x8000 || p > 0x801f)       // skip 0x8000..0x801F
            sum += *p;

so it sums 32-bit big-endian words from 0x008020 to the end of the same region
the additive checksum covers, and a balance inside that range absorbs the
difference. TWO VARIANTS EXIST, and the firmware picks one:

  32-bit   the full sum must equal 0x5AA5A55A. The balance is the whole 32-bit
           word at 0x008020. Three of the eleven images here use this.
  16-bit   only the low half of the sum is tested, against 0x5AA5. The balance
           is the HALFWORD at 0x008022, and 0x008020 stays zero. The other
           eight use this.

The 16-bit variant is easy to miss, and missing it is expensive: from outside,
an image whose region does not sum to 0x5AA5A55A looks like an image with no
balance at all, and leaving it alone leaves eight of eleven ROMs failing their
own integrity check after any edit. The variant is decided structurally -- the
16-bit images hold zero in the halfword at 0x008020, the 32-bit images hold the
top half of a balance there -- which stays true after the ROM has been edited.

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

# Second checksum: the balance, and the constants the two variants test against.
BALANCE_OFFSET = 0x008020
BALANCE_TARGET_32 = 0x5AA5A55A
BALANCE_TARGET_16 = 0x5AA5


def _sum_balance_region(data: bytes, end: int) -> int:
    """The firmware's loop: 32-bit words from 0x008020 to the end of the region."""
    n = (end - BALANCE_OFFSET) // 4
    return sum(struct.unpack(
        f">{n}I", data[BALANCE_OFFSET:BALANCE_OFFSET + n * 4])) & 0xFFFFFFFF


def is_balance_16(data: bytes) -> bool:
    """True when this image uses the 16-bit variant."""
    return struct.unpack(">H", data[BALANCE_OFFSET:BALANCE_OFFSET + 2])[0] == 0


def balance_holds(data: bytes, end: int = None) -> bool:
    """Does the balance region already meet this image's constant?"""
    if end is None:
        end = choose_region(data)
    total = _sum_balance_region(data, end)
    if is_balance_16(data):
        return total & 0xFFFF == BALANCE_TARGET_16
    return total == BALANCE_TARGET_32


def compute_balance(data: bytes, end: int = None) -> int:
    """The balance value this image needs: a full word, or a halfword."""
    if end is None:
        end = choose_region(data)
    total = _sum_balance_region(data, end)
    if is_balance_16(data):
        stored = struct.unpack(">H", data[BALANCE_OFFSET + 2:BALANCE_OFFSET + 4])[0]
        without = (total - stored) & 0xFFFF
        return (BALANCE_TARGET_16 - without) & 0xFFFF
    stored = struct.unpack(">I", data[BALANCE_OFFSET:BALANCE_OFFSET + 4])[0]
    without = (total - stored) & 0xFFFFFFFF
    return (BALANCE_TARGET_32 - without) & 0xFFFFFFFF


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
    return balance_holds(data)


def fix_checksum(data: bytes) -> bytes:
    """Return a copy of data with both of this image's checksums corrected."""
    data = bytearray(data)
    end = choose_region(bytes(data))

    # Balance first: it lives inside the region the additive checksum covers, so
    # writing it afterwards would invalidate the value just computed.
    if not balance_holds(bytes(data), end):
        b = compute_balance(bytes(data), end)
        if is_balance_16(bytes(data)):
            data[BALANCE_OFFSET + 2:BALANCE_OFFSET + 4] = struct.pack(">H", b)
        else:
            data[BALANCE_OFFSET:BALANCE_OFFSET + 4] = struct.pack(">I", b)

    c = compute_checksum(bytes(data), end)
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
        if is_balance_16(data):
            bal = struct.unpack(">H", data[BALANCE_OFFSET + 2:BALANCE_OFFSET + 4])[0]
            print(f"balance  0x{bal:04X} at 0x{BALANCE_OFFSET + 2:06X} (16-bit "
                  f"variant, target 0x{BALANCE_TARGET_16:04X}), expected "
                  f"0x{compute_balance(data, region):04X}"
                  + ("  OK" if balance_holds(data, region) else "  BAD"))
        else:
            bal = struct.unpack(">I", data[BALANCE_OFFSET:BALANCE_OFFSET + 4])[0]
            print(f"balance  0x{bal:08X} at 0x{BALANCE_OFFSET:06X} (32-bit "
                  f"variant, target 0x{BALANCE_TARGET_32:08X}), expected "
                  f"0x{compute_balance(data, region):08X}"
                  + ("  OK" if balance_holds(data, region) else "  BAD"))
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
