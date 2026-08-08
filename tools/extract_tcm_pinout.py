#!/usr/bin/env python3
"""Extract the TCM terminal table from the service manual.

The bench notes previously reconstructed the pinout from fault-finding procedures,
because no single terminal table had been found. There is one: section
5AT(diag)-11, "Transmission Control Module (TCM) I/O Signal", under the heading
ELECTRICAL SPECIFICATION. It gives every terminal with its signal name, the
condition to measure under, and the expected value - including the two CAN lines,
which the fault-finding pages never name because they defer to the LAN section.

    python3 tools/extract_tcm_pinout.py <TRANSMISSION_SECTION.txt>
    python3 tools/extract_tcm_pinout.py <file> --markdown

The manual is not redistributed here. Point this at your own copy.

The layout is awkward to parse: rows wrap across many lines, and the item name
often sits several lines above the connector and terminal number that belong to it.
The rule used is that a line carrying "B54" or "B55" followed by a bare number
closes a row, and the item is whatever non-numeric text accumulated since the last
row closed. Rows that come out without a plausible name are reported rather than
guessed at.
"""

import argparse
import re
import sys

ROW = re.compile(r"\b(B5[45])\s+(\d{1,2})\b")
NOISE = re.compile(
    r"^\s*$|^\s*(NOTE|Connector|Item|Terminal|Measuring|Measured|Resistance|"
    r"between|nal and|ground|Remarks|AUTOMATIC|Transmission Control|5AT|"
    r"[0-9 ]+$|A: ELECTRICAL|B: ELECTRICAL)")
VALUE = re.compile(
    r"Approx|voltage|^\s*[\d.]+\s*[-—]|Ω|kΩ|V$|Hz|°C|Ignition|Always|While|"
    r"Engine|Manual mode|driving|switch (ON|OFF)|—")


def extract(path):
    lines = open(path, encoding="utf-8", errors="replace").read().split("\n")

    # Only the ELECTRICAL SPECIFICATION sections carry the table.
    spans, start = [], None
    for i, l in enumerate(lines):
        if "ELECTRICAL SPECIFICATION" in l:
            start = i
        elif start is not None and re.match(r"^[A-Z]: [A-Z]", l) and i > start + 5:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(lines)))
    if not spans:
        return []

    rows, pending = [], []
    for a, b in spans:
        for line in lines[a:b]:
            m = ROW.search(line)
            if m:
                # Name is the text before the connector on this line, or whatever
                # accumulated above it.
                here = line[:m.start()].strip()
                name = here or " ".join(pending).strip()
                name = re.sub(r"\s{2,}", " ", name)
                rows.append((m.group(1), int(m.group(2)), name))
                pending = []
                continue
            if NOISE.match(line) or VALUE.search(line):
                continue
            t = line.strip()
            if t and not t[0].isdigit():
                pending.append(t)
                if len(pending) > 4:
                    pending = pending[-4:]
    return rows


def clean(name):
    name = re.sub(r"\s+", " ", name).strip(" .-—")
    # Join words the PDF split across lines: "sen- sor" -> "sensor".
    name = re.sub(r"(\w)- (\w)", r"\1\2", name)
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manual")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()

    rows = extract(args.manual)
    if not rows:
        sys.exit("no ELECTRICAL SPECIFICATION table found in %s" % args.manual)

    best = {}
    for conn, pin, name in rows:
        name = clean(name)
        # Keep the longest plausible name seen for a pin: the table repeats some
        # terminals across page breaks, and the fuller one is the real caption.
        if not name or len(name) > 60:
            continue
        prev = best.get((conn, pin), "")
        if len(name) > len(prev):
            best[(conn, pin)] = name

    if args.markdown:
        for conn in ("B54", "B55"):
            print("\n### %s\n" % conn)
            print("| pin | signal |")
            print("|---|---|")
            for pin in range(1, 25):
                n = best.get((conn, pin))
                if n:
                    print("| %d | %s |" % (pin, n))
                else:
                    print("| %d | *not listed* |" % pin)
    else:
        for conn in ("B54", "B55"):
            print("=== %s" % conn)
            for pin in range(1, 25):
                print("  %2d  %s" % (pin, best.get((conn, pin), "-")))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
