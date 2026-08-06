#!/bin/bash
# Fully disassemble and decompile every Denso SH705x TCU image.
#
# Auto-analysis alone reaches about 28% of one of these images: it follows control
# flow from the reset vector, and everything dispatched through a function pointer
# table stays undefined. Code that is never disassembled has no cross-references,
# which makes tracing a calibration table back to the routine that reads it
# impossible - a real dead end this project hit, not a theory.
#
# Four passes per image:
#   1. denso_data_ranges.py computes which bytes are calibration data
#   2. import as SuperH:BE:32:SH-2E. Ghidra ships no SH-2E, so this project adds
#      one: it is SH_VERSION "2" with FPU defined, two lines in a slaspec. The
#      stock SH-2 has no FPU constructors at all, so the whole 0xF000-0xFFFF
#      opcode space fails to decode - 165 halt_baddata markers in one image, and
#      5.6 points of coverage. SH-2A decodes the FPU but over-accepts about twenty
#      SH-2A-only instructions this core cannot execute. See tools/ghidra/sh-2e.slaspec.
#   3. auto-analysis, then DensoFull.java sweeps every 2-byte-aligned address
#      OUTSIDE those data ranges and disassembles whatever decodes, repeating until
#      a pass finds nothing new
#   4. DensoDecompAll.java writes every function to one C file
#
# Skipping the data ranges is not an optimisation. Decoding a calibration table as
# instructions destroys it and manufactures cross-references that look real: an
# unrestricted sweep produced 77 referrers to the shift-schedule array, every one of
# them the sweep reading its own mis-decoded pointers.
#
# Expect roughly 57% instruction coverage against 47% code-like content, which means
# essentially all the code. The rest is blank flash and constant pools; chasing 100%
# would decode padding into fake instructions.
#
# Per-image coverage is written to decompiled-denso/coverage.log.
#
#   tools/ghidra/decompile_all_denso.sh

set -uo pipefail

GH="${GHIDRA_HOME:-$HOME/ghidra_12.1.2_PUBLIC}/support/analyzeHeadless"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPTS="${GHIDRA_SCRIPTS:-$HOME/my_scripts}"
OUT="$REPO/decompiled-denso"
WORK="${DENSO_WORK:-$HOME/gp_denso_batch}"
RANGES="${DENSO_RANGES:-$HOME/denso/ranges}"
LOG="$OUT/coverage.log"

# Keep Ghidra's scratch off /tmp: it is wiped between WSL sessions, which has
# silently invalidated work here before.
export TMPDIR="${TMPDIR:-$HOME/gtmp}"
export _JAVA_OPTIONS="-Djava.io.tmpdir=$TMPDIR"
mkdir -p "$TMPDIR" "$RANGES" "$OUT"

[ -x "$GH" ] || { echo "analyzeHeadless not found at $GH" >&2; exit 1; }

touch "$LOG"

for rom in "$REPO"/rom-denso/*.bin; do
    name="$(basename "$rom" .bin)"
    dest="$OUT/$name.c"
    if [ -s "$dest" ]; then
        echo "skip (already done): $name"
        continue
    fi

    echo "=== $name"
    python3 "$REPO/tools/denso_data_ranges.py" "$rom" > "$RANGES/$name.txt" 2>/dev/null \
        || { echo "  could not compute data ranges" | tee -a "$LOG"; continue; }
    echo "  data spans: $(wc -l < "$RANGES/$name.txt")"

    rm -rf "$WORK"; mkdir -p "$WORK"
    cp "$rom" "$WORK/t.bin"

    "$GH" "$WORK" p -import "$WORK/t.bin" \
        -processor "SuperH:BE:32:SH-2E" -loader BinaryLoader -loader-baseAddr 0x0 \
        >/dev/null 2>&1

    # Give the image its on-chip RAM before analysis. Imported as a flat binary
    # there is no block at 0xFFFF0000, so Ghidra creates no symbols for RAM
    # addresses - which is why the decompiled C never mentions them, and why the
    # emulator had nowhere to keep variables. See FINDINGS sections 46 and 49.
    "$GH" "$WORK" p -process t.bin -noanalysis \
        -scriptPath "$SCRIPTS" -postScript DensoAddRam.java >/dev/null 2>&1

    "$GH" "$WORK" p -process t.bin -analysisTimeoutPerFile 3000 >/dev/null 2>&1

    "$GH" "$WORK" p -process t.bin -noanalysis \
        -scriptPath "$SCRIPTS" -postScript DensoFull.java "$RANGES/$name.txt" \
        2>&1 | grep -a "COVERAGE" | sed "s|^.*DensoFull.java> |  |" | tee -a "$LOG"

    "$GH" "$WORK" p -process t.bin -noanalysis \
        -scriptPath "$SCRIPTS" -postScript DensoDecompAll.java "$dest" \
        2>&1 | grep -a "RESULT" | sed "s|^.*DensoDecompAll.java> |  $name |" | tee -a "$LOG"

    if [ -s "$dest" ]; then
        printf '  %s lines\n' "$(wc -l < "$dest")"
    else
        echo "  FAILED: no output for $name" | tee -a "$LOG"
    fi
done

echo
echo "=== summary"
cat "$LOG"
