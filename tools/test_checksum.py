"""
Round-trip tests for checksum.py.

    python tools/test_checksum.py                 # tests the bundled 384KB ROM
    python tools/test_checksum.py other.bin ...   # also tests further ROMs

Verification is deliberately INDEPENDENT of compute_checksum(); otherwise the
test would only assert that the function agrees with itself. The invariant used
instead falls out of the algorithm's own structure — because the value is stored
twice:

    total over region = S_excl + 2C = -C + 2C = C

so summing every big-endian 32-bit word in the checksummed region, INCLUDING
both checksum slots, must equal the stored value. That is what is checked here.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")
TOOL = os.path.join(_HERE, "checksum.py")
DEFAULT_ROM = os.path.join(_ROOT, "rom", "91D1206000_5EAT.bin")

REGION_END = 0x60000
SLOT1, SLOT2 = 0x8000, 0x8004
EDIT_AT = 0x010424  # a real calibration table data byte, inside the region

failures = []


def check(label, cond):
    print(f"    {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        failures.append(label)


def invariant_holds(path):
    """Independent check: sum of the region must equal the stored value."""
    d = open(path, "rb").read()
    end = min(REGION_END, len(d))
    words = struct.unpack(f">{end // 4}I", d[:end])
    total = sum(words) & 0xFFFFFFFF
    return total == words[SLOT1 // 4] == words[SLOT2 // 4], total


def run(path, *args):
    r = subprocess.run([sys.executable, TOOL, path, *args],
                       capture_output=True, text=True)
    return r.returncode


def test_rom(src, scratch):
    name = os.path.basename(src)
    size_kb = os.path.getsize(src) // 1024
    print(f"\n=== {name}  ({size_kb} KB) ===")

    work = os.path.join(scratch, "work.bin")
    shutil.copy(src, work)
    orig = open(work, "rb").read()

    check("stock ROM verifies OK", run(work, "--verify") == 0)
    ok, total = invariant_holds(work)
    check(f"stock ROM: independent invariant holds (0x{total:08X})", ok)

    d = bytearray(orig)
    d[EDIT_AT] ^= 0xFF
    open(work, "wb").write(bytes(d))
    check("edited ROM reports BAD", run(work, "--verify") == 1)
    check("edited ROM: invariant genuinely broken", not invariant_holds(work)[0])

    check("--fix exits 0", run(work, "--fix") == 0)
    check("fixed ROM verifies OK", run(work, "--verify") == 0)
    ok, total = invariant_holds(work)
    check(f"fixed ROM: independent invariant holds (0x{total:08X})", ok)

    fixed = open(work, "rb").read()
    changed = {i for i in range(len(orig)) if orig[i] != fixed[i]}
    allowed = set(range(SLOT1, SLOT1 + 8)) | {EDIT_AT}
    check(f"--fix touched only the slots and the edit ({len(changed)} bytes)",
          changed <= allowed)
    check("file size unchanged", len(fixed) == len(orig))

    before = open(work, "rb").read()
    run(work, "--fix")
    check("--fix is idempotent", open(work, "rb").read() == before)

    d = bytearray(fixed)
    d[EDIT_AT] ^= 0xFF
    open(work, "wb").write(bytes(d))
    run(work, "--fix")
    check("undo edit + re-fix reproduces the byte-exact original",
          open(work, "rb").read() == orig)

    # Only meaningful on images larger than the checksummed region.
    if len(orig) > REGION_END:
        print("  -- region boundary --")
        shutil.copy(src, work)
        d = bytearray(open(work, "rb").read())
        d[REGION_END + 0x10000] = 0x00
        open(work, "wb").write(bytes(d))
        check("edit outside the region leaves the checksum valid",
              run(work, "--verify") == 0)

        shutil.copy(src, work)
        d = bytearray(open(work, "rb").read())
        d[REGION_END - 4] ^= 0xFF
        open(work, "wb").write(bytes(d))
        check("edit at the last word inside the region invalidates it",
              run(work, "--verify") == 1)


def main():
    roms = sys.argv[1:] or [DEFAULT_ROM]
    missing = [r for r in roms if not os.path.exists(r)]
    if missing:
        sys.exit("ROM not found: " + ", ".join(missing))

    with tempfile.TemporaryDirectory() as scratch:
        for rom in roms:
            test_rom(rom, scratch)

    print("\n" + "=" * 58)
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print("  -", f)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
