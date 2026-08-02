#!/bin/bash
# Fully disassemble and decompile every Denso SH705x TCU image.
#
# Auto-analysis alone reaches only about 28% of one of these images: it follows
# control flow from the reset vector, and everything dispatched through a function
# pointer table stays undefined. Code that is never disassembled has no
# cross-references, which makes tracing a calibration table back to the routine that
# reads it impossible - that is a real dead end this project hit, not a theory.
#
# So each image gets three passes:
#   1. import as SuperH:BE:32:SH-2   (the SH7058S core is SH-2E, not SH-2A)
#   2. auto-analysis, then DensoFull.java sweeps every 2-byte-aligned address in the
#      code region below the table blocks and disassembles whatever will decode
#   3. DensoDecompAll.java writes every function to one C file
#
# The sweep stops at 0xB0000. Above that are the table headers and their data, which
# are known from the pointer index and are definitely not code; decoding them as
# instructions destroys the data and manufactures false cross-references.
#
# Coverage per image is written to decompiled-denso/coverage.log.
#
#   tools/ghidra/decompile_all_denso.sh

set -uo pipefail

GH="${GHIDRA_HOME:-$HOME/ghidra_12.1.2_PUBLIC}/support/analyzeHeadless"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="${GHIDRA_SCRIPTS:-$HOME/my_scripts}"
OUT="$REPO/decompiled-denso"
WORK="$HOME/gp_denso_batch"
LOG="$OUT/coverage.log"

CODE_START=1000        # hex; below this is the vector table
CODE_END=B0000         # hex; at and above this are the calibration tables

command -v "$GH" >/dev/null 2>&1 || [ -x "$GH" ] || { echo "analyzeHeadless not found at $GH" >&2; exit 1; }

mkdir -p "$OUT"
: > "$LOG"

for rom in "$REPO"/rom-denso/*.bin; do
    name="$(basename "$rom" .bin)"
    dest="$OUT/$name.c"
    if [ -s "$dest" ]; then
        echo "skip (already done): $name"
        continue
    fi

    echo "=== $name"
    rm -rf "$WORK"; mkdir -p "$WORK"
    cp "$rom" "$WORK/t.bin"

    "$GH" "$WORK" p -import "$WORK/t.bin" \
        -processor "SuperH:BE:32:SH-2" -loader BinaryLoader -loader-baseAddr 0x0 \
        >/dev/null 2>&1

    "$GH" "$WORK" p -process t.bin -analysisTimeoutPerFile 3000 >/dev/null 2>&1

    "$GH" "$WORK" p -process t.bin -noanalysis \
        -scriptPath "$SCRIPTS" -postScript DensoFull.java "$CODE_START" "$CODE_END" \
        2>&1 | grep -a "instruction bytes now" | sed "s|^.*DensoFull.java> |  |"

    "$GH" "$WORK" p -process t.bin -noanalysis \
        -scriptPath "$SCRIPTS" -postScript DensoDecompAll.java "$dest" \
        2>&1 | grep -a "RESULT" | sed "s|^.*DensoDecompAll.java> |  |" | tee -a "$LOG"

    if [ -s "$dest" ]; then
        printf '  %s -> %s lines\n' "$name" "$(wc -l < "$dest")"
        sed -i "s|^RESULT|$name RESULT|" "$LOG" 2>/dev/null || true
    else
        echo "  FAILED: no output for $name" | tee -a "$LOG"
    fi
done

echo
echo "=== summary"
cat "$LOG"
