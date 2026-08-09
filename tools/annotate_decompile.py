#!/usr/bin/env python3
"""Inject per-function annotations into a Ghidra m32r decompile.

The decompiled .c files in decompiled/ are raw Ghidra output with bare
FUN_xxxxxxxx names. This tool takes a symbols JSON that records a name and a
one-line purpose for each function address and writes a copy of the decompile
with a comment block placed directly above every function header, so the
listing reads with its analysis attached.

The symbols file is a JSON object with a "functions" map keyed by address:

    {"functions": {"0x0002a380": {"name": "ssm_build_response",
                                  "comment": "Copies every SSM parameter ..."}}}

Addresses are matched loosely (case-insensitive, leading zeros ignored), so the
"0002a380" in a `// ===== FUN_0002a380 @ 0002a380 =====` header lines up with
"0x0002a380" in the map. Functions with no entry are left untouched.

    python tools/annotate_decompile.py \
        --decompile decompiled/8AF0237300_MB500NJ0.c \
        --symbols   decompiled/8AF0237300_MB500NJ0.symbols.json \
        --out       decompiled/8AF0237300_MB500NJ0.annotated.c
"""
import argparse
import json
import re


def norm(addr):
    """Normalise an address to 0x + 8 lowercase hex digits."""
    a = str(addr).lower()
    if a.startswith("0x"):
        a = a[2:]
    return "0x" + a.lstrip("0").rjust(8, "0")


def annotate(decompile_path, symbols_path, out_path):
    funcs = json.load(open(symbols_path, encoding="utf-8")).get("functions", {})
    funcs = {norm(k): v for k, v in funcs.items()}
    header = re.compile(r"//\s*=+\s*FUN_([0-9a-fA-F]+)\s*@")
    out = []
    written = 0
    for line in open(decompile_path, encoding="utf-8", errors="replace"):
        m = header.match(line)
        if m:
            entry = funcs.get(norm("0x" + m.group(1)))
            if entry:
                out.append("\n/* [%s] %s\n   %s */\n" % (
                    norm("0x" + m.group(1)),
                    entry.get("name", ""),
                    entry.get("comment", ""),
                ))
                written += 1
        out.append(line)
    open(out_path, "w", encoding="utf-8").write("".join(out))
    return written


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--decompile", required=True, help="input raw .c decompile")
    ap.add_argument("--symbols", required=True, help="symbols JSON with a 'functions' map")
    ap.add_argument("--out", required=True, help="output annotated .c path")
    args = ap.parse_args()
    n = annotate(args.decompile, args.symbols, args.out)
    print("annotated %d functions -> %s" % (n, args.out))


if __name__ == "__main__":
    main()
