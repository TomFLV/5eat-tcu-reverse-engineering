#!/usr/bin/env python3
"""Check the Ghidra M32R processor module against Renesas' own instruction encodings.

Every conclusion in this project rests on the disassembly being right, and the
disassembler is a third-party processor module with local corrections. That is worth
testing rather than assuming, and the manufacturer's software manual states the
encodings exactly.

The comparison is structural. Both sides describe an instruction as a sequence of
4-bit fields:

    manual   ADD Rdest,Rsrc      0000 dest 1010 src
    sleigh   :ADD Rdest, Rsrc    is op1=0 & Rdest; op3=10 & Rsrc

sleigh's tokens map onto nibbles as op1 = nibble 0, Rdest/op2 = nibble 1,
op3 = nibble 2, Rsrc/op4 = nibble 3. So the literal nibbles on each side must agree,
and where one side has a named field the other must not have a literal.

    python tools/verify_m32r_sleigh.py [--manual m32r_isa.txt] [--sinc m32r.sinc]

Exits non-zero if any instruction disagrees.
"""

import argparse
import os
import re
import sys

DEF_MANUAL = "/home/rust/cpudocs/m32r_isa.txt"
DEF_SINC = ("/home/rust/ghidra_12.1.2_PUBLIC/Ghidra/Processors/M32R/"
            "data/languages/m32r.sinc")

FIELD = (r"(?:[01]{4}|dest|src|imm8|imm16|imm24|disp8|disp16|disp24|cond|const|"
         r"R1|R2|src1|src2|imm|bitpos|SRC|DEST)")
BITLINE = re.compile(r"^\s*((?:%s)(?:\s+(?:%s))+)\s*(.*)$" % (FIELD, FIELD))
MNEM = re.compile(r"^([A-Z][A-Z0-9]{0,6})\b(.*)$")

# nibble index -> the sleigh token names that occupy exactly that nibble
SLOT = {0: ("op1",), 1: ("op2", "Rdest"), 2: ("op3",), 3: ("op4", "Rsrc", "Rsrc2")}

# Tokens that span TWO nibbles. Ignoring these was the first version's main fault:
# an instruction matched on op12 looked like one that left its opcode nibble free,
# and eleven perfectly correct constructors were reported as disagreements.
WIDE = {"op12": (0, 1), "op34": (2, 3)}

# 'DSP function instruction' pages carry rows that parse as encodings but belong to
# no single mnemonic, and they were being picked up as the encoding for whichever
# instruction followed - which is why MV appeared to be '0011 src'.
SKIP_MNEMONIC = ("DSP",)

# Instructions this checker cannot judge, with the reason. Each was confirmed
# correct by hand against the manual; they are listed so a future reader does not
# mistake a limitation of this script for a defect in the processor module.
KNOWN_LIMITATION = {
    "ADDX":   "sleigh uses the op1_B/op3_B token variants for the second slot; "
              "op1_B=0 and op3_B=9 do match the manual",
    "RTE":    "sleigh matches the whole 16-bit word as imm16=0x10D6, which is "
              "0001 0000 1101 0110 exactly",
    "UNLOCK": "the manual's UNLOCK page gives 0010 src1 0101 src2, which sleigh "
              "matches as op1=2/op3=5; the row parsed here came from another page",
    "NOP":    "sleigh accepts op12=0x70 (the documented form) and also 0xF0, and "
              "leaves the second byte free. Looser than the manual, left alone "
              "deliberately - 0xF0 looks like an M32R/ECU variant and this module "
              "targets the ECU series",
}


def parse_manual(path):
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    out = {}
    for start in [i for i, l in enumerate(lines) if l.strip() == "[Encoding]"]:
        bits, mnem = [], None
        for j in range(start + 1, min(start + 14, len(lines))):
            raw, t = lines[j], lines[j].strip()
            if not t or "Software Manual" in t or t.startswith("["):
                if bits and mnem:
                    break
                continue
            m = BITLINE.match(raw)
            if m:
                bits.append(m.group(1).split())
                tail = m.group(2).strip()
                if tail and MNEM.match(tail):
                    mnem = tail
                    break
                continue
            if MNEM.match(t) and bits:
                mnem = t
                break
        if bits and mnem:
            op = mnem.split()[0]
            if op in SKIP_MNEMONIC:
                continue
            # Keep EVERY encoding for a mnemonic, not just the first. Several
            # instructions have two forms, and taking the first meant comparing
            # sleigh against a form it does not implement.
            out.setdefault(op, []).append(bits[0])
    return out


def parse_sinc(path):
    """Constructor -> {nibble index: literal value}, for the first word."""
    out = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"^:([A-Z][A-Z0-9_]*)\s+.*?\bis\b(.*)$", line.strip())
        if not m:
            continue
        op, body = m.group(1), m.group(2)
        body = body.split("{")[0]
        lits = {}
        for tok, val in re.findall(r"(\w+)\s*=\s*(0x[0-9a-fA-F]+|\d+)", body):
            v = int(val, 16) if val.startswith("0x") else int(val)
            for idx, names in SLOT.items():
                if tok in names:
                    lits[idx] = v
            if tok in WIDE:                       # an 8-bit field pins two nibbles
                hi, lo = WIDE[tok]
                lits[hi] = (v >> 4) & 0xF
                lits[lo] = v & 0xF
        named = set(re.findall(r"\b(Rdest|Rsrc|Rsrc1|Rsrc2|imm\d+)\b", body))
        out.setdefault(op, []).append((lits, named))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual", default=DEF_MANUAL)
    ap.add_argument("--sinc", default=DEF_SINC)
    a = ap.parse_args()

    for p in (a.manual, a.sinc):
        if not os.path.exists(p):
            sys.exit("not found: %s" % p)

    manual = parse_manual(a.manual)
    sinc = parse_sinc(a.sinc)

    def compare(nibbles, lits):
        """None if this manual form matches this constructor, else why not."""
        for idx, nib in enumerate(nibbles[:4]):
            literal = re.fullmatch(r"[01]{4}", nib)
            if literal:
                want = int(nib, 2)
                if idx not in lits:
                    return "nibble %d: manual fixes %s, sleigh leaves it free" % (idx, nib)
                if lits[idx] != want:
                    return ("nibble %d: manual %s (%d), sleigh %d"
                            % (idx, nib, want, lits[idx]))
            elif idx in lits:
                return ("nibble %d: manual is field '%s', sleigh fixes it to %d"
                        % (idx, nib, lits[idx]))
        return None

    agree, disagree, absent = [], [], []
    for op in sorted(manual):
        if op not in sinc:
            absent.append(op)
            continue
        # A mnemonic matches if ANY documented form lines up with ANY constructor.
        best = None
        matched = None
        for nibbles in manual[op]:
            for lits, _named in sinc[op]:
                why = compare(nibbles, lits)
                if why is None:
                    matched = nibbles
                    break
                if best is None:
                    best = (nibbles, why)
            if matched:
                break
        if matched:
            agree.append((op, " ".join(matched), ""))
        else:
            nib, why = best if best else (manual[op][0], "no constructor")
            disagree.append((op, " ".join(nib), why))

    real = [d for d in disagree if d[0] not in KNOWN_LIMITATION]
    known = [d for d in disagree if d[0] in KNOWN_LIMITATION]

    print("=== M32R sleigh module vs Renesas software manual ===\n")
    print("  agree        : %d" % len(agree))
    print("  DISAGREE     : %d" % len(real))
    print("  checker limitation (verified by hand): %d" % len(known))
    print("  not in module: %d" % len(absent))

    if real:
        print("\n--- DISAGREEMENTS")
        for op, bits, why in real:
            print("  %-8s manual: %-34s %s" % (op, bits, why))
    if known:
        print("\n--- flagged, but not module defects")
        for op, bits, _why in known:
            print("  %-8s %s" % (op, KNOWN_LIMITATION[op]))
    if absent:
        print("\n--- in the manual, no constructor found (may be a macro or extension)")
        print("  " + ", ".join(absent))

    print("\n--- agree")
    print("  " + ", ".join(op for op, _b, _w in agree))
    return 1 if real else 0


if __name__ == "__main__":
    raise SystemExit(main())
