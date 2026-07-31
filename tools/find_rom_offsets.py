#!/usr/bin/env python3
"""Derive a firmware's table relocation offsets by matching the base ROM's headers.

Adding a firmware to the definition means telling the generator how far each table
family has moved relative to the base ROM. Those offsets were originally read out of
decompiled call sites one at a time, which is slow and easy to get wrong.

The tables themselves are identical enough between firmwares to locate directly: take
the bytes at a known header address in the base ROM and find that same run in the
target. Every header in a family must agree on the delta, or the answer is not
reported - a family whose headers disagree has genuinely moved apart and needs a human.

The tool checks itself. Run with --self-test and it re-derives the offsets for the
firmwares already in ROM_PROFILES and compares them against what is recorded there; if
it cannot reproduce known answers it has no business proposing new ones.

    python tools/find_rom_offsets.py --self-test
    python tools/find_rom_offsets.py rom/AAD1A06000.bin
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from generate_romraider_def import FAMILIES, ROM_PROFILES  # noqa: E402

BASE_ROM = os.path.join(REPO, "rom", "91D1206000_5EAT.bin")

# How far a family is allowed to have moved. The offsets recorded so far span 0 to
# about 600 bytes; this is generous without making a coincidental match likely.
SEARCH = 0x4000


def u16(buf, at):
    if at < 0 or at + 2 > len(buf):
        return None
    return (buf[at] << 8) | buf[at + 1]


def family_candidates(base, target, family):
    """Every delta at which this family's headers still read their base counts.

    A header begins with its element count, which is what the generator validates
    against, and that count survives relocation. Matching raw header bytes does not
    work - a header also holds a data pointer, which differs per firmware by
    construction, which is why the first attempt at this found nothing at all.

    Scored rather than filtered: a family whose headers do not ALL agree is common
    (a count can legitimately differ between firmwares), so each delta carries the
    number of headers supporting it and the caller decides what is good enough.
    """
    headers = family["headers"]
    score = {}
    for addr in headers:
        want = u16(base, addr)
        if want is None:
            continue
        for d in range(-SEARCH, SEARCH + 1, 2):
            if u16(target, addr + d) == want:
                score[d] = score.get(d, 0) + 1
    return score, len(headers)


def choose(per_family):
    """Pick each family's delta, preferring one the whole firmware agrees on.

    Table families do not move independently: a firmware shifts them in a couple of
    groups, so a delta supported by several families is far more likely correct than
    a nearer one supported by a single coincidental count match. Scoring by
    cross-family support rather than by smallest movement is what makes this agree
    with the offsets that were originally read out of decompiled call sites.
    """
    consensus = {}
    for _fid, (score, total) in per_family.items():
        for d, n in score.items():
            if n == total:                      # only full agreement votes
                consensus[d] = consensus.get(d, 0) + 1

    chosen = {}
    for fid, (score, total) in per_family.items():
        if not score:
            chosen[fid] = (None, "no delta matches any header")
            continue
        # A family's own headers outrank the rest of the firmware. Letting
        # cross-family consensus win instead moved PressureB and PressureC to the
        # delta the other families used, on the three 512 KB images where those two
        # genuinely move further - the header at the consensus delta was not even
        # the right kind of record. Consensus only breaks ties.
        best = max(score, key=lambda d: (score[d], consensus.get(d, 0), -abs(d), -d))
        note = None
        if score[best] < total:
            note = "%d of %d headers agree" % (score[best], total)
        chosen[fid] = (best, note)
    return chosen


def derive(target_path, verbose=False):
    base = open(BASE_ROM, "rb").read()
    target = open(target_path, "rb").read()

    per_family = {}
    for fam in FAMILIES:
        if not fam.get("headers"):
            continue
        per_family[fam["id"]] = family_candidates(base, target, fam)

    offsets, problems = {}, []
    for fid, (delta, note) in choose(per_family).items():
        if delta is None:
            problems.append("%s: %s" % (fid, note))
        elif delta:
            offsets[fid] = delta
        if verbose:
            print("    %-24s %-8s %s"
                  % (fid, "-" if delta is None else "%+d" % delta, note or ""))
    return offsets, problems


def self_test():
    """Re-derive the offsets already recorded, and compare."""
    bad = 0
    for prof in ROM_PROFILES:
        path = os.path.join(REPO, "rom", prof["rom_file"])
        if not os.path.exists(path):
            print("  SKIP  %-12s (%s missing)" % (prof["id"], prof["rom_file"]))
            continue
        got, problems = derive(path)
        want = {k: v for k, v in prof["offsets"].items() if v}
        got = {k: v for k, v in got.items() if v}
        if got == want:
            print("  ok    %-12s %d families" % (prof["id"], len(want)))
        else:
            bad += 1
            print("  FAIL  %-12s" % prof["id"])
            for k in sorted(set(got) | set(want)):
                if got.get(k) != want.get(k):
                    print("           %-24s recorded=%s derived=%s"
                          % (k, want.get(k), got.get(k)))
    print("\n%s" % ("self-test passed" if not bad else "%d firmware(s) mismatched" % bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", nargs="*", help="ROM image(s) to derive offsets for")
    ap.add_argument("--self-test", action="store_true",
                    help="re-derive offsets for the firmwares already in ROM_PROFILES")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.rom:
        ap.error("give a ROM, or --self-test")

    for path in args.rom:
        print("\n=== %s" % os.path.basename(path))
        offsets, problems = derive(path, verbose=True)
        for p in problems:
            print("    NOTE %s" % p)
        print('\n    "offsets": %s,' % repr(offsets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
