#!/usr/bin/env python3
"""Write a checksum manifest into every tracked directory.

WHY THESE ARE WORTH HAVING. This repository distributes ROM images, decompiler
output and generated definitions - files where a silent corruption or a truncated
download produces something that still loads and is quietly wrong. A per-directory
manifest lets anyone confirm their copy is the copy that was published, without
trusting the transport or the clone.

It also means each directory carries a record of when its contents were last
checked, which is a question the repository could not previously answer.

    python tools/write-manifests.py            # write or refresh every manifest
    python tools/write-manifests.py --check     # verify, change nothing

--check is the useful one day to day: it recomputes every hash and reports
anything that does not match what was recorded, which is a real integrity test
rather than a timestamp.

ORDER MATTERS. Regenerate after the last edit, not before. Writing the manifests
and then touching two more files leaves those two reported as mismatched, which is
the check working correctly and looking like a fault. The manifests exclude
themselves, so regenerating is stable and can be repeated safely.

STAGE BEFORE GENERATING. What is hashed is the content in git's index, which does
not include edits you have not added yet. Editing this file, regenerating, and then
staging both records the OLD hash for the file you just changed - which is how the
first manifest commit failed CI on write-manifests.py itself. Run "git add -A"
first, then regenerate, then add the manifests.

WHAT IS HASHED is the content git stores, not the file on disk. Git normalises
line endings on checkout, so a CSV committed with LF appears with CRLF in a
Windows working tree and with LF on Linux - the same file, two different hashes,
and a manifest written on one platform failing on the other. Reading the blob out
of the index gives the same bytes everywhere.
"""

import argparse
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
NAME = "MANIFEST.sha256"


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True).stdout.splitlines()
    dirs = {}
    for p in out:
        if "/" not in p:
            continue
        d = p.rsplit("/", 1)[0]
        if os.path.basename(p) == NAME:
            continue
        dirs.setdefault(d, []).append(p)
    return dirs


def digest(relpath):
    """SHA-256 of the content git has stored for this path.

    Not of the working-tree file: see the note above about line endings.
    """
    blob = subprocess.run(["git", "cat-file", "blob", ":" + relpath],
                          cwd=REPO, capture_output=True)
    if blob.returncode != 0:
        return None
    return hashlib.sha256(blob.stdout).hexdigest(), len(blob.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify against the recorded hashes and change nothing")
    ap.add_argument("--date", default=None,
                    help="date to record (default: today, UTC)")
    args = ap.parse_args()

    if args.date:
        today = args.date
    else:
        import datetime
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    dirs = tracked()
    bad, checked, written = [], 0, 0
    for d, files in sorted(dirs.items()):
        mpath = os.path.join(REPO, d, NAME)
        rows = []
        for p in sorted(files):
            d2 = digest(p)
            if d2 is None:
                continue
            rows.append((d2[0], os.path.basename(p), d2[1]))

        if args.check:
            if not os.path.exists(mpath):
                print("  no manifest: %s" % d)
                continue
            recorded = {}
            for line in open(mpath, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    recorded[parts[1].strip()] = parts[0]
            for h, name, _size in rows:
                checked += 1
                if recorded.get(name) != h:
                    bad.append("%s/%s" % (d, name))
            continue

        total = sum(r[2] for r in rows)
        lines = [
            "# %s" % d,
            "#",
            "# SHA-256 of every tracked file in this directory, %d files, %.1f MB."
            % (len(rows), total / 1048576.0),
            "# Recorded %s. Verify with:  python tools/write-manifests.py --check"
            % today,
            "#",
            "# These exist because this repository ships ROM images, decompiler output",
            "# and generated definitions - files where a truncated copy still loads and",
            "# is quietly wrong.",
            "",
        ]
        lines += ["%s  %s" % (h, name) for h, name, _ in rows]
        with open(mpath, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
        written += 1
        print("  %-20s %3d files  %.1f MB" % (d, len(rows), total / 1048576.0))

    if args.check:
        print("\n%d files checked, %d mismatched" % (checked, len(bad)))
        for b in bad:
            print("  MISMATCH %s" % b)
        return 1 if bad else 0
    print("\n%d manifests written" % written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
