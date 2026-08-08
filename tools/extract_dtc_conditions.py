#!/usr/bin/env python3
"""Extract what condition sets each DTC, from the manual's diagnostics section.

WHAT THIS CLOSES. The firmware work established the whole DTC machinery: the code
table, the five-byte record per code, the live and confirmed flag arrays, the
routine that ORs a bit in, and the thousand-count debounce (FINDINGS 81, 83). What
it could not establish was which CONDITION sets any given code - no simulated fault
would latch one, because the monitors gate on hardware feedback the emulator does
not provide.

The manual states it outright. Every code has a section carrying a "DTC DETECTING
CONDITION" and usually a "TROUBLE SYMPTOM".

    python3 tools/extract_dtc_conditions.py <TRANSMISSION_SECTION.pdf>
    python3 tools/extract_dtc_conditions.py <pdf> --json tools/dtc_conditions.json

The manual is not redistributed here. Point this at your own copy.

TWO WAYS THIS WENT WRONG FIRST, both worth recording because both produced output
that looked like data.

Scanning linearly and switching state on headings let text from any section the
pattern missed accumulate into whichever code matched last. The result was not
merely incomplete: several codes' symptoms arrived concatenated under one entry.
Splitting on the headings first and parsing each slice in isolation cannot do that.

The section letters run A: through Z: and then AA:, AB:. A single-letter pattern
stops at Z and loses twenty of the forty-six codes.

The other obvious source, the "List of Diagnostic Trouble Code" summary table, was
tried and abandoned: its columns shift from page to page, so splitting on positions
taken from the header scrambles rows into each other.

WHICH TCU THIS MANUAL IS FOR: M32R, and its own contents establish that rather than
any outside claim. All 46 codes it documents exist in the M32R firmware's code
table, and it names none the firmware does not carry. The firmware carries seven it
does not cover - P0880, P0883, P0955, P1760 to P1762, P1841 - so a scan tool can
report codes with nothing in the book to look up. See FINDINGS 86b.

It still names no vehicle across 269 pages - no Tribeca, no Legacy, no Outback, only
the engine family H6DO - so treat anything connector- or pin-specific in it as
belonging to whichever car it is for, which remains unestablished. See FINDINGS 18e.
"""

import argparse
import json
import re
import subprocess
import sys

# "A: DTC P0705 ..." early on, "AP:DTC P1817 ..." later - the space after the colon
# is not always there, and requiring it lost nineteen of the forty-six codes while
# the ones it did find looked perfectly good.
SECTION = re.compile(r"^[A-Z]{1,3}:\s*DTC\s+(P[0-9]{4})\s+(.+?)\s*$", re.M)
HEADING = re.compile(r"^(DTC DETECTING CONDITION|TROUBLE SYMPTOM|CAUTION|NOTE|"
                     r"WIRING DIAGRAM|Step):", re.M)
NOISE = re.compile(r"5AT\(diag\)-\d+|AUTOMATIC TRANSMISSION|"
                   r"Diagnostic Procedure with|^\s*$")


def pdf_text(path, first=1):
    """Text of the PDF from the given page on, read from stdout.

    Writing to a temporary file meant guessing which side's temp directory the
    converter would use, which differs between a Windows and a WSL invocation.
    """
    r = subprocess.run(["pdftotext", "-layout", "-f", str(first), path, "-"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        sys.exit("pdftotext produced nothing - is poppler installed?\n"
                 + r.stderr.decode("utf-8", "replace")[:200])
    return r.stdout.decode("utf-8", "replace")


def field(body, name):
    """The lines under one heading, up to the next heading."""
    m = re.search(r"^%s:\s*$" % re.escape(name), body, re.M)
    if not m:
        return ""
    rest = body[m.end():]
    nxt = HEADING.search(rest)
    if nxt:
        rest = rest[:nxt.start()]
    out = []
    for line in rest.split("\n"):
        t = line.strip().lstrip("\u2022 ").strip()
        if t and not NOISE.search(t):
            out.append(t)
    return re.sub(r"\s{2,}", " ", " ".join(out)).strip()


def extract(text):
    """One entry per section, parsed from that section's own slice."""
    marks = [(m.start(), m.group(1), m.group(2)) for m in SECTION.finditer(text)]
    out = {}
    for i, (pos, code, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end]
        e = out.setdefault(code, {"item": title.strip(), "cause": "",
                                  "symptom": ""})
        for key, name in (("cause", "DTC DETECTING CONDITION"),
                          ("symptom", "TROUBLE SYMPTOM")):
            v = field(body, name)
            if v and not e[key]:
                e[key] = v
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Extract each DTC's stated detecting condition from the manual.")
    ap.add_argument("manual")
    ap.add_argument("--json")
    ap.add_argument("--first-page", type=int, default=104,
                    help="the diagnostics section starts around here")
    args = ap.parse_args()

    data = extract(pdf_text(args.manual, args.first_page))
    with_cause = {k: v for k, v in data.items() if v["cause"]}

    print("%d trouble codes, %d with a stated detecting condition\n"
          % (len(data), len(with_cause)))
    for code in sorted(data):
        v = data[code]
        print("%s  %s" % (code, v["item"][:60]))
        if v["cause"]:
            print("        sets when: %s" % v["cause"][:104])
        if v["symptom"]:
            print("        symptom:   %s" % v["symptom"][:104])

    missing = sorted(k for k in data if not data[k]["cause"])
    if missing:
        print("\nno condition stated (the manual refers these elsewhere): %s"
              % ", ".join(missing))

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
